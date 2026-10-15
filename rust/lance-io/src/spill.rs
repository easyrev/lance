// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: Copyright The Lance Authors

//! Reclaimable scratch storage.
//!
//! A [`SpillStore`] hands out scratch space for temporary state that is too
//! large to keep in memory and is read back later in the same process (for
//! example, posting lists or shuffle runs accumulated while building an index).
//! The backing storage is reclaimed automatically when its writer and handle
//! are dropped.
//!
//! [`SpillStore::new_spill`] returns a [`Writer`] paired with a [`Spill`]
//! handle: the writer is the byte sink (feed it to `FileWriter::try_new`, or
//! write to it directly); the [`Spill`] reads the bytes back (via
//! [`crate::scheduler::ScanScheduler::open_reader`] for a v2 `FileReader`) and
//! shares ownership of the file with the writer.
//!
//! # Lifecycle
//!
//! - **Write-once.** The only way to obtain a writer is `new_spill`, and each
//!   call allocates a fresh unit of storage, so a single spill cannot be
//!   written twice — there is no second-writer path to guard against.
//! - **Write-before-read.** [`Spill::reader`] fails until the writer has been
//!   shut down, so partially written bytes are never read back.
//! - **RAII.** Dropping both the writer and [`Spill`] deletes the file and
//!   releases its bytes back to the store's disk budget. A started shutdown
//!   retains ownership until it finishes, even if its caller is cancelled.
//!   The store's temp directory is created on first use and provides backstop
//!   cleanup.
//!
//! # Disk cap
//!
//! [`LocalSpillStore::with_cap`] enforces a byte budget shared across all live
//! handles, returning a typed [`lance_core::Error::DiskCapExceeded`] rather than
//! silently filling the disk. Writes reserve space before polling the underlying
//! writer and retain only the bytes it accepts. The reservation is released
//! when the final owner drops, including writes aborted before shutdown.

use std::io;
use std::path::PathBuf;
use std::pin::Pin;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::task::{Context, Poll};
use std::time::Duration;

use async_trait::async_trait;
use object_store::path::Path;
use tokio::io::AsyncWrite;
use tokio::task::JoinHandle;

use lance_core::{Error, Result};

use crate::object_store::ObjectStore;
use crate::object_writer::WriteResult;
use crate::traits::{Reader, Writer};

/// A factory for scratch storage.
///
/// The trait is object-safe and `Send + Sync` so it can be held behind an
/// `Arc<dyn SpillStore>` (e.g. inside a `Session`). Implementations need not be
/// backed by local files (e.g. in-memory buffers, remote object stores).
#[async_trait]
pub trait SpillStore: Send + Sync + 'static {
    /// Allocate a unit of scratch storage.
    ///
    /// Returns the byte sink to write it with and a [`Spill`] handle to read it
    /// back. For a capped store, writes that would exceed the cap fail with
    /// [`lance_core::Error::DiskCapExceeded`]. The storage is reclaimed when the
    /// writer and [`Spill`] are dropped and any started shutdown has completed.
    async fn new_spill(&self) -> Result<(Box<dyn Writer>, Box<dyn Spill>)>;
}

/// The readable half of a spill, and the owner of its backing storage.
///
/// Dropping it reclaims the storage once the paired writer and any started
/// shutdown have also finished. The trait is object-safe so it can be
/// returned as `Box<dyn Spill>` from [`SpillStore::new_spill`].
#[async_trait]
pub trait Spill: Send + Sync {
    /// Open a reader over the spilled bytes.
    ///
    /// Fails until the paired writer has been shut down, since the bytes are not
    /// complete before then.
    async fn reader(&self) -> Result<Box<dyn Reader>>;
}

/// A shared, cloneable byte budget.
///
/// Cloning produces another handle to the *same* underlying counter, so a quota
/// shared across many writers enforces a single combined cap.
#[derive(Debug, Clone)]
struct DiskQuota {
    cap_bytes: u64,
    used: Arc<Mutex<u64>>,
}

impl DiskQuota {
    fn new(cap_bytes: u64) -> Self {
        Self {
            cap_bytes,
            used: Arc::new(Mutex::new(0)),
        }
    }

    /// Try to reserve `n` bytes, failing with [`Error::DiskCapExceeded`] if the
    /// reservation would push total usage past the cap.
    fn try_reserve(&self, n: u64) -> Result<()> {
        // The lock is held only for a couple of arithmetic ops and never across
        // an `.await`, so a std `Mutex` is the simplest correct choice.
        let mut used = self.used.lock().unwrap();
        let Some(next) = used.checked_add(n).filter(|next| *next <= self.cap_bytes) else {
            return Err(Error::disk_cap_exceeded(self.cap_bytes, *used));
        };
        *used = next;
        Ok(())
    }

    /// Release `n` previously reserved bytes back to the budget.
    fn release(&self, n: u64) {
        // Saturating sub keeps a stray double-release from underflowing.
        let mut used = self.used.lock().unwrap();
        *used = used.saturating_sub(n);
    }
}

/// The byte sink handed out by [`SpillStore::new_spill`].
///
/// It optionally reserves a [`DiskQuota`] as bytes are written (keeping cap
/// enforcement inside the spill store rather than in [`ObjectStore`], and
/// working for any backend the store opens), and flips a shared `finished` flag
/// on shutdown so the paired [`Spill`] knows the bytes are complete.
struct SpillWriter {
    state: SpillWriterState,
    file: Arc<SpillFile>,
}

enum SpillWriterState {
    Writing(Box<dyn Writer>),
    Finishing(JoinHandle<Result<WriteResult>>),
    Done(WriteResult),
    Closed,
}

impl AsyncWrite for SpillWriter {
    fn poll_write(
        self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buf: &[u8],
    ) -> Poll<io::Result<usize>> {
        let this = self.get_mut();
        let SpillWriterState::Writing(inner) = &mut this.state else {
            return Poll::Ready(Err(io::Error::other(
                "cannot write to a spill after shutdown has started",
            )));
        };
        let accepted_before = this.file.accepted_bytes.load(Ordering::Relaxed);
        if accepted_before.checked_add(buf.len() as u64).is_none() {
            return Poll::Ready(Err(io::Error::other(Error::invalid_input(
                "spill write would exceed the maximum supported file size",
            ))));
        }
        // Reserve up-front for the bytes we intend to write, then release the
        // remainder the inner writer did not accept so the reservation tracks
        // bytes actually buffered (and, for a write-once file, the file size).
        if let Some(quota) = &this.file.quota
            && let Err(e) = quota.try_reserve(buf.len() as u64)
        {
            return Poll::Ready(Err(io::Error::other(e)));
        }
        let poll = Pin::new(inner.as_mut()).poll_write(cx, buf);
        let accepted = match &poll {
            Poll::Ready(Ok(n)) => *n as u64,
            _ => 0,
        };
        // There is one writer per spill. For capped stores, the reservation
        // above also bounds this total by the shared cap.
        this.file
            .accepted_bytes
            .store(accepted_before + accepted, Ordering::Relaxed);
        if let Some(quota) = &this.file.quota {
            quota.release(buf.len() as u64 - accepted);
        }
        poll
    }

    fn poll_flush(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        let this = self.get_mut();
        if let SpillWriterState::Writing(inner) = &mut this.state {
            Pin::new(inner.as_mut()).poll_flush(cx)
        } else {
            Pin::new(this).poll_shutdown(cx)
        }
    }

    fn poll_shutdown(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        let this = self.get_mut();
        loop {
            match &mut this.state {
                SpillWriterState::Writing(_) => {
                    let SpillWriterState::Writing(mut inner) =
                        std::mem::replace(&mut this.state, SpillWriterState::Closed)
                    else {
                        return Poll::Ready(Err(io::Error::other(
                            "spill writer is not available for shutdown",
                        )));
                    };
                    let file = this.file.clone();
                    // LocalWriter may persist its temporary file on a blocking
                    // task. Keep ownership until that operation completes so
                    // cancellation cannot recreate an already-cleaned-up file.
                    this.state = SpillWriterState::Finishing(tokio::spawn(async move {
                        let result = inner.shutdown().await;
                        if result.is_ok() {
                            file.finished.store(true, Ordering::Relaxed);
                        }
                        drop(inner);
                        drop(file);
                        result
                    }));
                }
                SpillWriterState::Finishing(handle) => match Pin::new(handle).poll(cx) {
                    Poll::Pending => return Poll::Pending,
                    Poll::Ready(Ok(Ok(result))) => {
                        this.state = SpillWriterState::Done(result);
                    }
                    Poll::Ready(Ok(Err(error))) => {
                        this.state = SpillWriterState::Closed;
                        return Poll::Ready(Err(io::Error::other(error)));
                    }
                    Poll::Ready(Err(error)) => {
                        this.state = SpillWriterState::Closed;
                        return Poll::Ready(Err(io::Error::other(error)));
                    }
                },
                SpillWriterState::Done(_) => return Poll::Ready(Ok(())),
                SpillWriterState::Closed => {
                    return Poll::Ready(Err(io::Error::other("spill writer shutdown failed")));
                }
            }
        }
    }
}

#[async_trait]
impl Writer for SpillWriter {
    async fn tell(&mut self) -> Result<usize> {
        usize::try_from(self.file.accepted_bytes.load(Ordering::Relaxed)).map_err(|_| {
            Error::invalid_input("spill position exceeds the maximum supported file size")
        })
    }

    async fn shutdown(&mut self) -> Result<WriteResult> {
        tokio::io::AsyncWriteExt::shutdown(self).await?;
        match &self.state {
            SpillWriterState::Done(result) => Ok(result.clone()),
            _ => Err(Error::invalid_input(
                "spill writer shutdown did not complete",
            )),
        }
    }
}

/// A [`SpillStore`] that writes temporary files to a local temp directory.
///
/// By default there is no disk cap. Use [`LocalSpillStore::with_cap`] to
/// configure one shared across every handle this store produces.
///
/// The scratch directory is created on the first [`SpillStore::new_spill`]
/// call, not at construction, so opening a dataset does not require a writable
/// temp directory. It is deleted when the store is dropped, cleaning up any
/// files whose handles have already been dropped.
pub struct LocalSpillStore {
    store: Arc<ObjectStore>,
    /// Created on first spill. Backstop cleanup removes the directory on drop.
    temp_dir: Mutex<Option<Arc<tempfile::TempDir>>>,
    file_counter: Arc<AtomicU64>,
    /// Byte budget shared across every handle, enforced while writing.
    quota: Option<DiskQuota>,
}

/// Create a unique scratch directory, retrying `PermissionDenied`.
///
/// Windows GitHub runners (and machines with antivirus) can reject a newly
/// created `%TEMP%` subdirectory with `ERROR_ACCESS_DENIED`. Each attempt uses
/// a fresh random name, so a short retry loop is the usual workaround.
fn create_temp_dir() -> Result<tempfile::TempDir> {
    const ATTEMPTS: u32 = 5;
    let mut attempt = 0;
    loop {
        match tempfile::tempdir() {
            Ok(dir) => return Ok(dir),
            Err(err) if err.kind() == io::ErrorKind::PermissionDenied && attempt + 1 < ATTEMPTS => {
                attempt += 1;
                std::thread::sleep(Duration::from_millis(10 * attempt as u64));
            }
            Err(err) => return Err(err.into()),
        }
    }
}

impl LocalSpillStore {
    /// Create a store with no disk cap.
    ///
    /// Construction does not touch the filesystem; the scratch directory is
    /// created on the first [`SpillStore::new_spill`] call.
    pub fn new() -> Result<Self> {
        Ok(Self::default())
    }

    /// Create a store that returns [`lance_core::Error::DiskCapExceeded`] once
    /// total bytes written across all live handles would exceed `cap_bytes`.
    pub fn with_cap(cap_bytes: u64) -> Result<Self> {
        Ok(Self {
            quota: Some(DiskQuota::new(cap_bytes)),
            ..Self::default()
        })
    }

    fn ensure_temp_dir(&self) -> Result<Arc<tempfile::TempDir>> {
        // The lock is held only for init (and the rare PermissionDenied retry)
        // and never across an `.await`.
        let mut slot = self.temp_dir.lock().unwrap();
        if let Some(dir) = slot.as_ref() {
            return Ok(dir.clone());
        }
        let dir = Arc::new(create_temp_dir()?);
        *slot = Some(dir.clone());
        Ok(dir)
    }
}

impl Default for LocalSpillStore {
    fn default() -> Self {
        Self {
            store: Arc::new(ObjectStore::local()),
            temp_dir: Mutex::new(None),
            file_counter: Arc::new(AtomicU64::new(0)),
            quota: None,
        }
    }
}

#[async_trait]
impl SpillStore for LocalSpillStore {
    async fn new_spill(&self) -> Result<(Box<dyn Writer>, Box<dyn Spill>)> {
        let temp_dir = self.ensure_temp_dir()?;
        let idx = self.file_counter.fetch_add(1, Ordering::Relaxed);
        let fs_path = temp_dir.path().join(format!("spill_{idx:06}.bin"));
        let os_path = Path::from_absolute_path(&fs_path)?;
        let file = Arc::new(SpillFile {
            fs_path,
            quota: self.quota.clone(),
            accepted_bytes: AtomicU64::new(0),
            finished: AtomicBool::new(false),
            _temp_dir: temp_dir,
        });
        let writer = Box::new(SpillWriter {
            state: SpillWriterState::Writing(self.store.create(&os_path).await?),
            file: file.clone(),
        });
        let spill = Box::new(LocalSpill {
            store: self.store.clone(),
            os_path,
            file,
        });
        Ok((writer, spill))
    }
}

/// The readable half of a [`LocalSpillStore`] spill; reclaims the file on drop.
struct LocalSpill {
    store: Arc<ObjectStore>,
    os_path: Path,
    file: Arc<SpillFile>,
}

/// Shared by the writer, its shutdown task, and the readable handle.
struct SpillFile {
    fs_path: PathBuf,
    quota: Option<DiskQuota>,
    accepted_bytes: AtomicU64,
    /// Set by the paired [`SpillWriter`] once it has been shut down.
    finished: AtomicBool,
    /// Keep the store's temp directory alive for at least this file's lifetime.
    _temp_dir: Arc<tempfile::TempDir>,
}

#[async_trait]
impl Spill for LocalSpill {
    async fn reader(&self) -> Result<Box<dyn Reader>> {
        // `Relaxed` is sufficient: the flag only gates "has the writer shut
        // down"; the bytes themselves are synchronized through the filesystem,
        // not this load.
        if !self.file.finished.load(Ordering::Relaxed) {
            return Err(Error::invalid_input(
                "spill reader requested before the writer was shut down",
            ));
        }
        self.store.open(&self.os_path).await
    }
}

impl Drop for SpillFile {
    fn drop(&mut self) {
        // An unfinished LocalWriter has already removed its temporary path.
        // A completed writer published the file at fs_path instead.
        if let Err(error) = std::fs::remove_file(&self.fs_path)
            && error.kind() != io::ErrorKind::NotFound
        {
            tracing::warn!(path = %self.fs_path.display(), %error, "failed to remove spill file");
        }
        if let Some(quota) = &self.quota {
            quota.release(self.accepted_bytes.load(Ordering::Relaxed));
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use futures::poll;
    use rstest::rstest;
    use tokio::io::AsyncWriteExt;
    use tokio::sync::oneshot;

    /// Write `data` to a fresh writer and shut it down.
    async fn finish_writer(mut writer: Box<dyn Writer>, data: &[u8]) -> Result<()> {
        writer.write_all(data).await?;
        Writer::shutdown(writer.as_mut()).await?;
        Ok(())
    }

    #[test]
    fn test_disk_quota_reserve_release() {
        let quota = DiskQuota::new(100);
        quota.try_reserve(60).unwrap();
        assert!(quota.try_reserve(60).is_err());
        quota.release(60);
        quota.try_reserve(60).unwrap();
        // Reserving exactly up to the cap succeeds; one byte past it fails.
        quota.try_reserve(40).unwrap();
        assert!(quota.try_reserve(1).is_err());

        let quota = DiskQuota::new(u64::MAX);
        quota.try_reserve(u64::MAX).unwrap();
        assert!(matches!(
            quota.try_reserve(1).unwrap_err(),
            Error::DiskCapExceeded { .. }
        ));
        assert_eq!(*quota.used.lock().unwrap(), u64::MAX);
    }

    #[tokio::test]
    async fn test_write_then_read() {
        let store = LocalSpillStore::new().unwrap();
        let (writer, spill) = store.new_spill().await.unwrap();

        let data = b"hello spill world";
        finish_writer(writer, data).await.unwrap();

        let reader = spill.reader().await.unwrap();
        let read_back = reader.get_all().await.unwrap();
        assert_eq!(read_back.as_ref(), data);
    }

    #[tokio::test]
    async fn test_reader_requires_finished_writer() {
        let store = LocalSpillStore::new().unwrap();
        let (mut writer, spill) = store.new_spill().await.unwrap();
        writer.write_all(b"partial").await.unwrap();

        // Reading before the writer is shut down is rejected.
        let Err(err) = spill.reader().await else {
            panic!("reader before shutdown should be rejected");
        };
        assert!(
            matches!(err, Error::InvalidInput { .. }),
            "expected InvalidInput, got {err:?}"
        );

        // After shutdown the reader sees the bytes.
        Writer::shutdown(writer.as_mut()).await.unwrap();
        let reader = spill.reader().await.unwrap();
        assert_eq!(reader.get_all().await.unwrap().as_ref(), b"partial");
    }

    #[tokio::test]
    async fn test_reader_ready_after_async_shutdown() {
        // Shutting down through the `AsyncWrite` surface (not the `Writer`
        // trait) must also mark the spill readable — covers poll_shutdown's
        // flag set, the path the `Writer::shutdown` tests don't reach.
        let store = LocalSpillStore::new().unwrap();
        let (mut writer, spill) = store.new_spill().await.unwrap();
        writer.write_all(b"async").await.unwrap();
        AsyncWriteExt::shutdown(&mut writer).await.unwrap();

        let reader = spill.reader().await.unwrap();
        assert_eq!(reader.get_all().await.unwrap().as_ref(), b"async");
    }

    #[tokio::test]
    async fn test_empty_spill() {
        // A spill written with no bytes round-trips empty, and the capped path
        // handles the zero-byte reserve/stat without error.
        let store = LocalSpillStore::with_cap(100).unwrap();
        let (writer, spill) = store.new_spill().await.unwrap();
        finish_writer(writer, b"").await.unwrap();

        let reader = spill.reader().await.unwrap();
        assert!(reader.get_all().await.unwrap().is_empty());
    }

    #[test]
    fn test_new_does_not_create_temp_dir() {
        // Session construction must not touch the filesystem; Windows CI panics
        // when thousands of tests each eagerly create a `%TEMP%` subdirectory.
        let store = LocalSpillStore::new().unwrap();
        assert!(
            store.temp_dir.lock().unwrap().is_none(),
            "temp directory should be created lazily on first spill"
        );
        assert!(
            LocalSpillStore::default()
                .temp_dir
                .lock()
                .unwrap()
                .is_none(),
            "Default should also defer temp directory creation"
        );
    }

    #[tokio::test]
    async fn test_raii_cleanup() {
        let store = LocalSpillStore::new().unwrap();
        let (writer, spill) = store.new_spill().await.unwrap();
        finish_writer(writer, b"some bytes").await.unwrap();

        // The first spill gets a deterministic name under the store's temp dir.
        let path = store
            .temp_dir
            .lock()
            .unwrap()
            .as_ref()
            .expect("new_spill creates the temp dir")
            .path()
            .join("spill_000000.bin");
        assert!(path.exists());
        drop(spill);
        assert!(!path.exists(), "spill file should be deleted on drop");
    }

    #[tokio::test]
    async fn test_cap_exceeded() {
        let store = LocalSpillStore::with_cap(100).unwrap();
        let (writer, _spill) = store.new_spill().await.unwrap();
        let err = finish_writer(writer, &[0u8; 101]).await.unwrap_err();
        assert!(
            matches!(err, Error::DiskCapExceeded { cap_bytes: 100, .. }),
            "expected DiskCapExceeded, got {err:?}"
        );
    }

    #[tokio::test]
    async fn test_cap_shared_across_files() {
        let store = LocalSpillStore::with_cap(100).unwrap();
        let (writer_a, _spill_a) = store.new_spill().await.unwrap();
        let (writer_b, _spill_b) = store.new_spill().await.unwrap();

        finish_writer(writer_a, &[0u8; 60]).await.unwrap();
        // 60 already reserved by `a`; writing 60 more would reach 120 > 100.
        let err = finish_writer(writer_b, &[0u8; 60]).await.unwrap_err();
        assert!(
            matches!(err, Error::DiskCapExceeded { cap_bytes: 100, .. }),
            "expected DiskCapExceeded, got {err:?}"
        );
    }

    #[tokio::test]
    async fn test_cap_freed_on_drop() {
        let store = LocalSpillStore::with_cap(100).unwrap();

        {
            let (writer, spill) = store.new_spill().await.unwrap();
            finish_writer(writer, &[0u8; 80]).await.unwrap();
            // `spill` drops at the end of this block, releasing its 80 bytes.
            drop(spill);
        }

        let (writer, _spill) = store.new_spill().await.unwrap();
        // Succeeds because the cap is no longer under pressure.
        finish_writer(writer, &[0u8; 80]).await.unwrap();
    }

    #[rstest]
    #[case::writer_first(true)]
    #[case::handle_first(false)]
    #[tokio::test]
    async fn test_cap_reused_after_aborted_write(#[case] drop_writer_first: bool) {
        let store = LocalSpillStore::with_cap(100).unwrap();
        let quota = store.quota.as_ref().unwrap();
        let (mut writer, spill) = store.new_spill().await.unwrap();
        writer.write_all(&[0u8; 80]).await.unwrap();
        let error = Error::from(writer.write_all(&[0u8; 40]).await.unwrap_err());
        assert!(matches!(
            error,
            Error::DiskCapExceeded {
                cap_bytes: 100,
                used_bytes: 80,
                ..
            }
        ));
        assert!(error.to_string().contains("currently using 80 bytes"));

        // The local writer has accepted bytes but has not published its final
        // path. Releasing a reservation by stat would leak all 80 bytes here.
        if drop_writer_first {
            drop(writer);
            assert_eq!(*quota.used.lock().unwrap(), 80);
            drop(spill);
        } else {
            drop(spill);
            assert_eq!(*quota.used.lock().unwrap(), 80);
            drop(writer);
        }
        assert_eq!(*quota.used.lock().unwrap(), 0);
        let temp_dir = store.ensure_temp_dir().unwrap();
        assert_eq!(std::fs::read_dir(temp_dir.path()).unwrap().count(), 0);

        let (writer, spill) = store.new_spill().await.unwrap();
        finish_writer(writer, &[1u8; 100]).await.unwrap();
        assert_eq!(
            spill.reader().await.unwrap().get_all().await.unwrap().len(),
            100
        );
        drop(spill);
        assert_eq!(*quota.used.lock().unwrap(), 0);
    }

    #[rstest]
    #[case::before_shutdown(false)]
    #[case::after_shutdown(true)]
    #[tokio::test]
    async fn test_handle_drop_keeps_live_writer_owned(#[case] finish_first: bool) {
        let store = LocalSpillStore::with_cap(100).unwrap();
        let quota = store.quota.as_ref().unwrap();
        let (mut writer, spill) = store.new_spill().await.unwrap();
        writer.write_all(&[0u8; 80]).await.unwrap();
        if finish_first {
            Writer::shutdown(writer.as_mut()).await.unwrap();
        }
        drop(spill);
        assert_eq!(*quota.used.lock().unwrap(), 80);

        if !finish_first {
            writer.write_all(&[0u8; 20]).await.unwrap();
            Writer::shutdown(writer.as_mut()).await.unwrap();
            assert_eq!(*quota.used.lock().unwrap(), 100);
        }
        let temp_dir = store.ensure_temp_dir().unwrap();
        let path = temp_dir.path().join("spill_000000.bin");
        assert!(path.exists());
        drop(writer);
        assert!(!path.exists());
        assert_eq!(*quota.used.lock().unwrap(), 0);
    }

    #[tokio::test]
    async fn test_custom_implementation() {
        // A custom store can satisfy the traits without a local file.
        struct MemStore;
        struct MemSpill;

        #[async_trait]
        impl Spill for MemSpill {
            async fn reader(&self) -> Result<Box<dyn Reader>> {
                ObjectStore::memory().open(&Path::from("/mem")).await
            }
        }

        #[async_trait]
        impl SpillStore for MemStore {
            async fn new_spill(&self) -> Result<(Box<dyn Writer>, Box<dyn Spill>)> {
                let writer = ObjectStore::memory().create(&Path::from("/mem")).await?;
                Ok((writer, Box::new(MemSpill)))
            }
        }

        let store = MemStore;
        // Exercise the factory + trait objects; the in-memory store is a fresh
        // instance per call so we don't round-trip data here.
        let (_writer, _spill) = store.new_spill().await.unwrap();
    }

    /// A [`Writer`] whose `poll_write` accepts a fixed number of bytes per call,
    /// or fails, so we can drive the [`SpillWriter`] release arms that the local
    /// backend (which accepts every write in full) never hits.
    struct ControlledWriter {
        outcome: Poll<io::Result<usize>>,
    }

    impl AsyncWrite for ControlledWriter {
        fn poll_write(
            self: Pin<&mut Self>,
            _cx: &mut Context<'_>,
            buf: &[u8],
        ) -> Poll<io::Result<usize>> {
            match &self.outcome {
                Poll::Ready(Ok(n)) => Poll::Ready(Ok((*n).min(buf.len()))),
                Poll::Ready(Err(e)) => Poll::Ready(Err(io::Error::new(e.kind(), e.to_string()))),
                Poll::Pending => Poll::Pending,
            }
        }
        fn poll_flush(self: Pin<&mut Self>, _cx: &mut Context<'_>) -> Poll<io::Result<()>> {
            Poll::Ready(Ok(()))
        }
        fn poll_shutdown(self: Pin<&mut Self>, _cx: &mut Context<'_>) -> Poll<io::Result<()>> {
            Poll::Ready(Ok(()))
        }
    }

    #[async_trait]
    impl Writer for ControlledWriter {
        async fn tell(&mut self) -> Result<usize> {
            Ok(0)
        }
        async fn shutdown(&mut self) -> Result<WriteResult> {
            Ok(WriteResult::default())
        }
    }

    #[rstest]
    #[case::short_write(Poll::Ready(Ok(10)), 10)]
    #[case::failed_write(Poll::Ready(Err(io::Error::other("boom"))), 0)]
    #[case::pending_write(Poll::Pending, 0)]
    fn test_spill_writer_releases_unaccepted_bytes(
        #[case] outcome: Poll<io::Result<usize>>,
        #[case] accepted: u64,
    ) {
        let quota = DiskQuota::new(100);
        let temp_dir = Arc::new(tempfile::tempdir().unwrap());
        let is_pending = outcome.is_pending();
        let is_error = matches!(&outcome, Poll::Ready(Err(_)));
        let mut writer = SpillWriter {
            state: SpillWriterState::Writing(Box::new(ControlledWriter { outcome })),
            file: Arc::new(SpillFile {
                fs_path: temp_dir.path().join("spill.bin"),
                quota: Some(quota.clone()),
                accepted_bytes: AtomicU64::new(0),
                finished: AtomicBool::new(false),
                _temp_dir: temp_dir,
            }),
        };
        let mut context = Context::from_waker(std::task::Waker::noop());
        let result = Pin::new(&mut writer).poll_write(&mut context, &[0u8; 40]);
        if is_pending {
            assert!(result.is_pending());
        } else if is_error {
            assert!(matches!(result, Poll::Ready(Err(error)) if error.to_string() == "boom"));
        } else {
            assert!(matches!(result, Poll::Ready(Ok(n)) if n as u64 == accepted));
        }
        assert_eq!(writer.file.accepted_bytes.load(Ordering::Relaxed), accepted);
        assert_eq!(
            *quota.used.lock().unwrap(),
            accepted,
            "only the accepted bytes should remain reserved"
        );
        drop(writer);
        assert_eq!(
            *quota.used.lock().unwrap(),
            0,
            "dropping an aborted writer must release accepted bytes too"
        );
    }

    struct GatedShutdownWriter {
        inner: Box<dyn Writer>,
        started: Option<oneshot::Sender<()>>,
        finish: Option<oneshot::Receiver<()>>,
    }

    impl AsyncWrite for GatedShutdownWriter {
        fn poll_write(
            self: Pin<&mut Self>,
            cx: &mut Context<'_>,
            buf: &[u8],
        ) -> Poll<io::Result<usize>> {
            Pin::new(self.get_mut().inner.as_mut()).poll_write(cx, buf)
        }

        fn poll_flush(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
            Pin::new(self.get_mut().inner.as_mut()).poll_flush(cx)
        }

        fn poll_shutdown(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
            Pin::new(self.get_mut().inner.as_mut()).poll_shutdown(cx)
        }
    }

    #[async_trait]
    impl Writer for GatedShutdownWriter {
        async fn tell(&mut self) -> Result<usize> {
            self.inner.tell().await
        }

        async fn shutdown(&mut self) -> Result<WriteResult> {
            self.started.take().unwrap().send(()).unwrap();
            self.finish.take().unwrap().await.unwrap();
            Writer::shutdown(&mut self.inner).await
        }
    }

    #[tokio::test]
    async fn test_cancelled_shutdown_retains_file_and_quota_until_completion() {
        let store = LocalSpillStore::with_cap(100).unwrap();
        let temp_dir = store.ensure_temp_dir().unwrap();
        let fs_path = temp_dir.path().join("cancelled.bin");
        let os_path = Path::from_absolute_path(&fs_path).unwrap();
        let file = Arc::new(SpillFile {
            fs_path: fs_path.clone(),
            quota: store.quota.clone(),
            accepted_bytes: AtomicU64::new(0),
            finished: AtomicBool::new(false),
            _temp_dir: temp_dir,
        });
        let (started_tx, started_rx) = oneshot::channel();
        let (finish_tx, finish_rx) = oneshot::channel();
        let mut writer = SpillWriter {
            state: SpillWriterState::Writing(Box::new(GatedShutdownWriter {
                inner: store.store.create(&os_path).await.unwrap(),
                started: Some(started_tx),
                finish: Some(finish_rx),
            })),
            file: file.clone(),
        };
        let spill = LocalSpill {
            store: store.store.clone(),
            os_path,
            file,
        };
        writer.write_all(&[0u8; 80]).await.unwrap();
        let mut shutdown = Box::pin(Writer::shutdown(&mut writer));
        assert!(poll!(shutdown.as_mut()).is_pending());
        started_rx.await.unwrap();
        drop(shutdown);

        // Keep the join handle only to wait for cleanup deterministically.
        // Dropping it, as cancellation does, would also leave the task running.
        let SpillWriterState::Finishing(shutdown_task) =
            std::mem::replace(&mut writer.state, SpillWriterState::Closed)
        else {
            panic!("shutdown task should be waiting for the gate");
        };
        drop(writer);
        drop(spill);
        let quota = store.quota.as_ref().unwrap();
        assert_eq!(*quota.used.lock().unwrap(), 80);

        finish_tx.send(()).unwrap();
        shutdown_task.await.unwrap().unwrap();
        assert!(!fs_path.exists());
        assert_eq!(*quota.used.lock().unwrap(), 0);
        let (writer, _spill) = store.new_spill().await.unwrap();
        finish_writer(writer, &[0u8; 100]).await.unwrap();
    }
}
