// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: Copyright The Lance Authors

//! Reproduction harness for #7207: every compaction commit that is verified
//! not to have landed leaves the `_indices/{uuid}` directory its index remap
//! minted. Lives on the `review/7207-failed-commit-index-cleanup` branch only.
//!
//! Run with:
//! `cargo test -p lance --lib repro_7207 -- --nocapture`

use std::collections::HashSet;
use std::sync::Mutex;

use async_trait::async_trait;
use futures::TryStreamExt;
use lance_core::utils::tempfile::TempStrDir;
use lance_index::IndexType;
use lance_index::scalar::ScalarIndexParams;
use lance_io::object_store::ObjectStore;
use lance_table::format::pb::transaction::Operation as PbOperation;
use lance_table::format::{IndexMetadata, Manifest};
use lance_table::io::commit::{
    CommitError, CommitHandler, ConditionalPutCommitHandler, ManifestLocation,
    ManifestNamingScheme, ManifestWriter,
};
use lance_table::io::manifest::read_manifest_indexes;
use object_store::path::Path;
use uuid::Uuid;

use crate::Dataset;
use crate::dataset::WriteParams;
use crate::dataset::optimize::{CompactionOptions, compact_files};
use crate::index::DatasetIndexExt;

/// Deletes one row just before a Rewrite commit's conditional put, so the put
/// conflicts and the retry's conflict check rejects the rewrite with #7207's
/// "preempted by concurrent transaction Delete" error.
#[derive(Debug, Default)]
struct DeleteBeforeRewrite {
    handle: Mutex<Option<Dataset>>,
    rows: Mutex<std::vec::IntoIter<i32>>,
}

impl DeleteBeforeRewrite {
    fn arm(&self, handle: &Dataset, rows: impl IntoIterator<Item = i32>) {
        *self.handle.lock().unwrap() = Some(handle.clone());
        *self.rows.lock().unwrap() = rows.into_iter().collect::<Vec<_>>().into_iter();
    }
}

#[async_trait]
impl CommitHandler for DeleteBeforeRewrite {
    async fn commit(
        &self,
        manifest: &mut Manifest,
        indices: Option<Vec<IndexMetadata>>,
        base_path: &Path,
        object_store: &ObjectStore,
        manifest_writer: ManifestWriter,
        naming_scheme: ManifestNamingScheme,
        transaction: Option<lance_table::format::Transaction>,
    ) -> std::result::Result<ManifestLocation, CommitError> {
        let is_rewrite = transaction
            .as_ref()
            .and_then(|transaction| transaction.as_pb().operation.as_ref())
            .is_some_and(|operation| matches!(operation, PbOperation::Rewrite(_)));
        if is_rewrite {
            let row = self.rows.lock().unwrap().next();
            if let Some(row) = row {
                let mut handle = self.handle.lock().unwrap().clone().unwrap();
                handle.checkout_latest().await.unwrap();
                handle.delete(&format!("i = {row}")).await.unwrap();
            }
        }
        ConditionalPutCommitHandler
            .commit(
                manifest,
                indices,
                base_path,
                object_store,
                manifest_writer,
                naming_scheme,
                transaction,
            )
            .await
    }
}

#[tokio::test]
async fn repro_7207_leaked_index_dirs() {
    const ATTEMPTS: i32 = 20;

    let dir = TempStrDir::default();
    let uri = dir.as_str();
    let handler = std::sync::Arc::new(DeleteBeforeRewrite::default());

    // 200 rows, 10 per fragment: one compaction task rewrites all 20.
    let batch = lance_datagen::gen_batch()
        .col(
            "i",
            lance_datagen::array::step::<arrow_array::types::Int32Type>(),
        )
        .into_batch_rows(lance_datagen::RowCount::from(200))
        .unwrap();
    let schema = batch.schema();
    let mut dataset = Dataset::write(
        arrow_array::RecordBatchIterator::new(vec![Ok(batch)], schema),
        uri,
        Some(WriteParams {
            max_rows_per_file: 10,
            commit_handler: Some(handler.clone()),
            ..Default::default()
        }),
    )
    .await
    .unwrap();
    dataset
        .create_index(
            &["i"],
            IndexType::Scalar,
            Some("i_idx".into()),
            &ScalarIndexParams::default(),
            false,
        )
        .await
        .unwrap();

    handler.arm(&dataset, 0..ATTEMPTS);
    let options = CompactionOptions {
        target_rows_per_fragment: 1000,
        ..Default::default()
    };
    for attempt in 0..ATTEMPTS {
        let result = compact_files(&mut dataset, options.clone(), None).await;
        assert!(
            result.is_err(),
            "attempt {attempt} was expected to lose to the injected DELETE"
        );
        dataset.checkout_latest().await.unwrap();
    }

    let latest = Dataset::open(uri).await.unwrap();
    let stored = read_manifest_indexes(
        &latest.object_store,
        &latest.manifest_location,
        &latest.manifest,
    )
    .await
    .unwrap();
    let referenced = stored
        .iter()
        .map(|index| index.uuid)
        .collect::<HashSet<Uuid>>();
    let mut orphan_dirs = 0usize;
    let mut orphan_bytes = 0u64;
    for name in latest
        .object_store
        .read_dir(latest.indices_dir())
        .await
        .unwrap()
    {
        let Ok(uuid) = Uuid::parse_str(&name) else {
            continue;
        };
        if referenced.contains(&uuid) {
            continue;
        }
        orphan_dirs += 1;
        let index_dir = latest.indices_dir().join(name);
        let mut files = latest.object_store.read_dir_all(&index_dir, None);
        while let Some(meta) = files.try_next().await.unwrap() {
            orphan_bytes += meta.size;
        }
    }
    println!(
        "ORPHANS after {ATTEMPTS} failed compaction commits: dirs={orphan_dirs} bytes={orphan_bytes}"
    );
}
