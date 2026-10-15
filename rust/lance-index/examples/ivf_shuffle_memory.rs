// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: Copyright The Lance Authors

//! Deterministic resource diagnostic for IVF shuffle writing and reading.
//!
//! Each process streams 262,144 Float32 vectors with 64 dimensions in batches
//! of 4,096 rows. Data generation is included in write time; exact verification
//! is included in read time. This does not train or search an IVF index.
//!
//! Run one budget and distribution per fresh process so RSS high-water marks
//! are independent:
//!
//! ```text
//! cargo run --profile release-with-debug -p lance-index \
//!   --example ivf_shuffle_memory -- 8388608 uniform
//! cargo run --profile release-with-debug -p lance-index \
//!   --example ivf_shuffle_memory -- 33554432 hotspot
//! cargo run --profile release-with-debug -p lance-index \
//!   --example ivf_shuffle_memory -- 0 uniform
//! ```
//!
//! A budget of zero uses an unbounded tracking pool with the default shuffle
//! batch target. It is a control for this implementation, not a historical
//! before-change baseline. Both modes use the same tracked local spill store.
//! The reported pool reservations cover the shuffler's documented buffers;
//! they do not cap process RSS. Unoptimized runs are correctness/resource
//! diagnostics and must not be reported as optimized performance results.

#![allow(clippy::print_stdout)]

use std::fmt::{Display, Formatter};
use std::io;
use std::pin::Pin;
use std::sync::atomic::{AtomicU64, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::task::{Context, Poll};
use std::time::Instant;

use arrow_array::{
    Array, ArrayRef, FixedSizeListArray, Float32Array, RecordBatch, UInt32Array, UInt64Array,
    cast::AsArray, types::Float32Type,
};
use arrow_schema::{DataType, Field, Schema, SchemaRef};
use async_trait::async_trait;
use datafusion::execution::memory_pool::{
    GreedyMemoryPool, MemoryConsumer, MemoryLimit, MemoryPool, MemoryReservation,
    UnboundedMemoryPool,
};
use futures::{TryStreamExt, stream};
use lance_arrow::FixedSizeListArrayExt;
use lance_core::{Error, ROW_ID, Result};
use lance_index::progress::IndexBuildProgress;
use lance_index::vector::PART_ID_COLUMN;
use lance_index::vector::v3::shuffler::{Shuffler, TwoFileShuffler};
use lance_io::object_writer::WriteResult;
use lance_io::spill::{LocalSpillStore, Spill, SpillStore};
use lance_io::stream::RecordBatchStreamAdapter;
use lance_io::traits::{Reader, Writer};
use object_store::path::Path;
use roaring::RoaringBitmap;
use serde_json::json;
use tokio::io::AsyncWrite;

const ROWS: usize = 262_144;
const DIMENSIONS: usize = 64;
const BATCH_ROWS: usize = 4_096;
const PARTITIONS: usize = 64;

#[derive(Clone, Copy)]
enum Distribution {
    Uniform,
    Hotspot,
}

impl Distribution {
    fn partition(self, row: usize) -> usize {
        match self {
            Self::Uniform => row % PARTITIONS,
            // Half the rows belong to partition zero; the rest span 63 others.
            Self::Hotspot if row.is_multiple_of(2) => 0,
            Self::Hotspot => 1 + (row / 2) % (PARTITIONS - 1),
        }
    }

    fn name(self) -> &'static str {
        match self {
            Self::Uniform => "uniform",
            Self::Hotspot => "hotspot",
        }
    }
}

// Integer mixing supplies reproducible, nonconstant values without an RNG or
// a retained input fixture. Overflow is intentional in the mixing function.
fn vector_value(row: usize, dimension: usize) -> f32 {
    let mut bits = (row * DIMENSIONS + dimension) as u32;
    bits = (bits ^ (bits >> 16)).wrapping_mul(0x7feb_352d);
    bits = (bits ^ (bits >> 15)).wrapping_mul(0x846c_a68b);
    bits ^= bits >> 16;
    f32::from_bits(0x3f80_0000 | (bits & 0x007f_ffff)) - 1.0
}

fn input_batch(schema: SchemaRef, start: usize, distribution: Distribution) -> Result<RecordBatch> {
    let end = (start + BATCH_ROWS).min(ROWS);
    let mut row_ids = Vec::with_capacity(end - start);
    let mut partitions = Vec::with_capacity(end - start);
    let mut values = Vec::with_capacity((end - start) * DIMENSIONS);
    for row in start..end {
        row_ids.push(row as u64);
        partitions.push(distribution.partition(row) as u32);
        values.extend((0..DIMENSIONS).map(|dimension| vector_value(row, dimension)));
    }
    let vectors =
        FixedSizeListArray::try_new_from_values(Float32Array::from(values), DIMENSIONS as i32)?;
    Ok(RecordBatch::try_new(
        schema,
        vec![
            Arc::new(UInt64Array::from(row_ids)) as ArrayRef,
            Arc::new(UInt32Array::from(partitions)),
            Arc::new(vectors),
        ],
    )?)
}

#[derive(Debug, Default)]
struct PoolMetrics {
    current: usize,
    peak: usize,
}

#[derive(Debug)]
struct TrackingMemoryPool {
    inner: Arc<dyn MemoryPool>,
    metrics: Mutex<PoolMetrics>,
}

impl Display for TrackingMemoryPool {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "shuffle diagnostic: {}", self.inner)
    }
}

impl MemoryPool for TrackingMemoryPool {
    fn name(&self) -> &str {
        "shuffle_diagnostic"
    }

    fn register(&self, consumer: &MemoryConsumer) {
        self.inner.register(consumer);
    }

    fn unregister(&self, consumer: &MemoryConsumer) {
        self.inner.unregister(consumer);
    }

    fn grow(&self, reservation: &MemoryReservation, additional: usize) {
        let mut metrics = self.metrics.lock().unwrap();
        self.inner.grow(reservation, additional);
        metrics.current += additional;
        metrics.peak = metrics.peak.max(metrics.current);
    }

    fn try_grow(
        &self,
        reservation: &MemoryReservation,
        additional: usize,
    ) -> datafusion_common::Result<()> {
        let mut metrics = self.metrics.lock().unwrap();
        self.inner.try_grow(reservation, additional)?;
        metrics.current += additional;
        metrics.peak = metrics.peak.max(metrics.current);
        Ok(())
    }

    fn shrink(&self, reservation: &MemoryReservation, bytes: usize) {
        let mut metrics = self.metrics.lock().unwrap();
        self.inner.shrink(reservation, bytes);
        metrics.current -= bytes;
    }

    fn reserved(&self) -> usize {
        self.inner.reserved()
    }

    fn memory_limit(&self) -> MemoryLimit {
        self.inner.memory_limit()
    }
}

#[derive(Default)]
struct SpillMetrics {
    files_created: AtomicUsize,
    live_files: AtomicUsize,
    accepted_bytes: AtomicU64,
    live_bytes: AtomicU64,
    peak_bytes: AtomicU64,
}

struct SpillAccounting {
    metrics: Arc<SpillMetrics>,
    accepted_bytes: AtomicU64,
}

impl Drop for SpillAccounting {
    fn drop(&mut self) {
        self.metrics.live_bytes.fetch_sub(
            self.accepted_bytes.load(Ordering::Relaxed),
            Ordering::Relaxed,
        );
        self.metrics.live_files.fetch_sub(1, Ordering::Relaxed);
    }
}

struct CountingSpillStore {
    inner: LocalSpillStore,
    metrics: Arc<SpillMetrics>,
}

#[async_trait]
impl SpillStore for CountingSpillStore {
    async fn new_spill(&self) -> Result<(Box<dyn Writer>, Box<dyn Spill>)> {
        let (writer, spill) = self.inner.new_spill().await?;
        self.metrics.files_created.fetch_add(1, Ordering::Relaxed);
        self.metrics.live_files.fetch_add(1, Ordering::Relaxed);
        let accounting = Arc::new(SpillAccounting {
            metrics: self.metrics.clone(),
            accepted_bytes: AtomicU64::new(0),
        });
        Ok((
            Box::new(CountingWriter {
                inner: writer,
                accounting: accounting.clone(),
            }),
            Box::new(CountingSpill {
                inner: spill,
                _accounting: accounting,
            }),
        ))
    }
}

struct CountingSpill {
    inner: Box<dyn Spill>,
    _accounting: Arc<SpillAccounting>,
}

#[async_trait]
impl Spill for CountingSpill {
    async fn reader(&self) -> Result<Box<dyn Reader>> {
        self.inner.reader().await
    }
}

struct CountingWriter {
    inner: Box<dyn Writer>,
    accounting: Arc<SpillAccounting>,
}

impl AsyncWrite for CountingWriter {
    fn poll_write(
        self: Pin<&mut Self>,
        context: &mut Context<'_>,
        bytes: &[u8],
    ) -> Poll<io::Result<usize>> {
        let this = self.get_mut();
        let result = Pin::new(this.inner.as_mut()).poll_write(context, bytes);
        if let Poll::Ready(Ok(accepted)) = result {
            let accepted = accepted as u64;
            let metrics = &this.accounting.metrics;
            this.accounting
                .accepted_bytes
                .fetch_add(accepted, Ordering::Relaxed);
            metrics
                .accepted_bytes
                .fetch_add(accepted, Ordering::Relaxed);
            let live = metrics.live_bytes.fetch_add(accepted, Ordering::Relaxed) + accepted;
            metrics.peak_bytes.fetch_max(live, Ordering::Relaxed);
        }
        result
    }

    fn poll_flush(self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<io::Result<()>> {
        Pin::new(self.get_mut().inner.as_mut()).poll_flush(context)
    }

    fn poll_shutdown(self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<io::Result<()>> {
        Pin::new(self.get_mut().inner.as_mut()).poll_shutdown(context)
    }
}

#[async_trait]
impl Writer for CountingWriter {
    async fn tell(&mut self) -> Result<usize> {
        self.inner.tell().await
    }

    async fn shutdown(&mut self) -> Result<WriteResult> {
        self.inner.shutdown().await
    }
}

#[derive(Debug, Default)]
struct FlushProgress {
    flushes: AtomicUsize,
    rows: AtomicU64,
}

#[async_trait]
impl IndexBuildProgress for FlushProgress {
    async fn stage_start(&self, _: &str, _: Option<u64>, _: &str) -> Result<()> {
        Ok(())
    }

    async fn stage_progress(&self, stage: &str, completed: u64) -> Result<()> {
        if stage == "shuffle" {
            self.flushes.fetch_add(1, Ordering::Relaxed);
            self.rows.store(completed, Ordering::Relaxed);
        }
        Ok(())
    }

    async fn stage_complete(&self, _: &str) -> Result<()> {
        Ok(())
    }
}

fn peak_rss_bytes() -> Option<u64> {
    let status = std::fs::read_to_string("/proc/self/status").ok()?;
    status.lines().find_map(|line| {
        line.strip_prefix("VmHWM:")?
            .split_whitespace()
            .next()?
            .parse::<u64>()
            .ok()?
            .checked_mul(1024)
    })
}

#[tokio::main]
async fn main() -> Result<()> {
    let mut arguments = std::env::args().skip(1);
    let budget: usize = arguments
        .next()
        .unwrap_or_else(|| "0".to_owned())
        .parse()
        .map_err(|error| Error::invalid_input(format!("invalid budget bytes: {error}")))?;
    let distribution = match arguments.next().as_deref().unwrap_or("uniform") {
        "uniform" => Distribution::Uniform,
        "hotspot" => Distribution::Hotspot,
        value => {
            return Err(Error::invalid_input(format!(
                "distribution must be uniform or hotspot, got {value:?}"
            )));
        }
    };
    if let Some(argument) = arguments.next() {
        return Err(Error::invalid_input(format!(
            "unexpected argument {argument:?}; usage: ivf_shuffle_memory [budget_bytes] [uniform|hotspot]"
        )));
    }

    let inner: Arc<dyn MemoryPool> = if budget == 0 {
        Arc::new(UnboundedMemoryPool::default())
    } else {
        Arc::new(GreedyMemoryPool::new(budget))
    };
    let pool = Arc::new(TrackingMemoryPool {
        inner,
        metrics: Mutex::new(PoolMetrics::default()),
    });
    let spill_metrics = Arc::<SpillMetrics>::default();
    let spill_store = Arc::new(CountingSpillStore {
        inner: LocalSpillStore::default(),
        metrics: spill_metrics.clone(),
    });
    let progress = Arc::<FlushProgress>::default();
    let shuffler = TwoFileShuffler::new(Path::from("unused"), PARTITIONS)
        .with_memory_pool(pool.clone())
        .with_spill_store(spill_store)
        .with_progress(progress.clone());
    let schema = Arc::new(Schema::new(vec![
        Field::new(ROW_ID, DataType::UInt64, false),
        Field::new(PART_ID_COLUMN, DataType::UInt32, false),
        Field::new(
            "vector",
            DataType::FixedSizeList(
                Arc::new(Field::new("item", DataType::Float32, true)),
                DIMENSIONS as i32,
            ),
            false,
        ),
    ]));
    let input = stream::iter((0..ROWS).step_by(BATCH_ROWS).map({
        let schema = schema.clone();
        move |start| input_batch(schema.clone(), start, distribution)
    }));
    let start = Instant::now();
    let reader = shuffler
        .shuffle(Box::new(RecordBatchStreamAdapter::new(schema, input)))
        .await?;
    let write_seconds = start.elapsed().as_secs_f64();
    let pool_after_shuffle = pool.reserved();
    let read_start = Instant::now();
    let mut seen = RoaringBitmap::new();
    let mut row_id_checksum = 0u64;
    let mut vector_bits_checksum = 0u64;
    for partition in 0..PARTITIONS {
        let expected_rows = (0..ROWS)
            .filter(|row| distribution.partition(*row) == partition)
            .count();
        assert_eq!(reader.partition_size(partition)?, expected_rows);
        let Some(mut batches) = reader.read_partition(partition).await? else {
            assert_eq!(expected_rows, 0);
            continue;
        };
        let mut partition_rows = 0;
        while let Some(batch) = batches.try_next().await? {
            let row_ids: &UInt64Array = batch[ROW_ID].as_primitive();
            let vectors = batch["vector"].as_fixed_size_list();
            let values = vectors.values().as_primitive::<Float32Type>();
            assert_eq!(row_ids.null_count(), 0);
            assert_eq!(vectors.null_count(), 0);
            assert_eq!(values.null_count(), 0);
            for (position, row_id) in row_ids.values().iter().copied().enumerate() {
                assert!(row_id < ROWS as u64);
                assert!(seen.insert(row_id as u32), "duplicate row ID {row_id}");
                assert_eq!(distribution.partition(row_id as usize), partition);
                row_id_checksum += row_id;
                for dimension in 0..DIMENSIONS {
                    let actual = values.value(position * DIMENSIONS + dimension).to_bits();
                    let expected = vector_value(row_id as usize, dimension).to_bits();
                    assert_eq!(actual, expected, "row {row_id}, dimension {dimension}");
                    vector_bits_checksum += u64::from(actual);
                }
            }
            partition_rows += batch.num_rows();
        }
        assert_eq!(partition_rows, expected_rows);
    }
    let read_verify_seconds = read_start.elapsed().as_secs_f64();
    assert_eq!(seen.len(), ROWS as u64);
    assert_eq!(row_id_checksum, ROWS as u64 * (ROWS as u64 - 1) / 2);
    assert_eq!(progress.rows.load(Ordering::Relaxed), ROWS as u64);
    drop(reader);
    drop(shuffler);
    let total_seconds = start.elapsed().as_secs_f64();
    let pool_peak = pool.metrics.lock().unwrap().peak;
    assert!(pool_peak > 0, "the pool was not used");
    if budget > 0 {
        assert!(pool_peak <= budget);
    }
    assert_eq!(pool.reserved(), 0);
    assert_eq!(spill_metrics.live_bytes.load(Ordering::Relaxed), 0);
    assert_eq!(spill_metrics.live_files.load(Ordering::Relaxed), 0);
    println!(
        "{}",
        json!({
            "diagnostic": "ivf_shuffle_memory",
            "debug_assertions": cfg!(debug_assertions),
            "budget_bytes": budget,
            "distribution": distribution.name(),
            "rows": ROWS,
            "dimensions": DIMENSIONS,
            "batch_rows": BATCH_ROWS,
            "partitions": PARTITIONS,
            "flushes": progress.flushes.load(Ordering::Relaxed),
            "write_including_generation_seconds": write_seconds,
            "read_including_verification_seconds": read_verify_seconds,
            "total_seconds": total_seconds,
            "pool_peak_bytes": pool_peak,
            "pool_after_shuffle_bytes": pool_after_shuffle,
            "pool_final_bytes": pool.reserved(),
            "process_peak_rss_bytes": peak_rss_bytes(),
            "spill_files_created": spill_metrics.files_created.load(Ordering::Relaxed),
            "spill_bytes_written": spill_metrics.accepted_bytes.load(Ordering::Relaxed),
            "spill_peak_live_bytes": spill_metrics.peak_bytes.load(Ordering::Relaxed),
            "spill_final_live_bytes": spill_metrics.live_bytes.load(Ordering::Relaxed),
            "spill_final_live_files": spill_metrics.live_files.load(Ordering::Relaxed),
            "row_id_checksum": row_id_checksum,
            "vector_bits_checksum": vector_bits_checksum,
        })
    );
    Ok(())
}
