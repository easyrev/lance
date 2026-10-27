// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: Copyright The Lance Authors

use super::*;
use std::collections::{BTreeSet, VecDeque};
use std::sync::Mutex;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};

use arrow_array::record_batch;
use lance_core::utils::deletion::DeletionVector;
use lance_table::feature_flags::FLAG_FRAGMENT_REUSE_INDEX;
use lance_table::format::IndexMetadata;
use lance_table::format::Transaction as TableTransaction;
use lance_table::io::deletion::write_deletion_file;

use crate::dataset::builder::DatasetBuilder;
use crate::index::frag_reuse::{
    FRAG_REUSE_INLINE_DETAILS_LIMIT, build_tagged_frag_reuse_entry, load_raw_frag_reuse_content,
};
use crate::index::frag_reuse_reader::tests::persist_fixture;
use crate::utils::test::{
    FailingProxyStore, commit_padding_reuse_history, inline_padding_capacity,
};
use lance_io::object_store::ObjectStoreParams;

fn index_directories(uri: &str) -> BTreeSet<String> {
    std::fs::read_dir(std::path::Path::new(uri).join("_indices"))
        .unwrap()
        .map(|entry| {
            let entry = entry.unwrap();
            assert!(entry.file_type().unwrap().is_dir());
            entry.file_name().into_string().unwrap()
        })
        .collect()
}

#[derive(Debug, Clone, Copy)]
enum CommitFault {
    Fail,
    LandAndError,
    AppendAndConflict,
    PublishIndicesAndFail,
    DropIndexAndFail,
    FailLatestRead,
}

/// Captures actual directories at the manifest boundary, including artifacts
/// that a rebase replaced before the commit handler sees the next attempt.
#[derive(Debug)]
struct IndexCleanupHandler {
    uri: String,
    faults: Mutex<VecDeque<CommitFault>>,
    snapshots: Mutex<Vec<BTreeSet<String>>>,
    kept_ids: Mutex<Vec<String>>,
    rewrite_calls: AtomicUsize,
    fail_latest_read: AtomicBool,
}

impl IndexCleanupHandler {
    fn new(uri: &str) -> Self {
        Self {
            uri: uri.to_owned(),
            faults: Mutex::default(),
            snapshots: Mutex::default(),
            kept_ids: Mutex::default(),
            rewrite_calls: AtomicUsize::new(0),
            fail_latest_read: AtomicBool::new(false),
        }
    }

    fn arm(&self, faults: impl IntoIterator<Item = CommitFault>) {
        *self.faults.lock().unwrap() = faults.into_iter().collect();
    }
}

#[async_trait]
impl CommitHandler for IndexCleanupHandler {
    fn is_version_not_found_definitive(&self) -> bool {
        true
    }

    async fn resolve_latest_location(
        &self,
        base_path: &object_store::path::Path,
        object_store: &ObjectStore,
    ) -> Result<ManifestLocation> {
        if self.fail_latest_read.load(Ordering::SeqCst) {
            return Err(Error::io("injected latest manifest read failure"));
        }
        ConditionalPutCommitHandler
            .resolve_latest_location(base_path, object_store)
            .await
    }

    // Keep the trait default for propagate_commit_error_after_success: a landed
    // commit still returns the injected error, which must never trigger cleanup.
    async fn commit(
        &self,
        manifest: &mut Manifest,
        indices: Option<Vec<IndexMetadata>>,
        base_path: &object_store::path::Path,
        object_store: &ObjectStore,
        manifest_writer: ManifestWriter,
        naming_scheme: ManifestNamingScheme,
        transaction: Option<TableTransaction>,
    ) -> std::result::Result<ManifestLocation, CommitError> {
        let rewrite = transaction
            .as_ref()
            .and_then(|transaction| transaction.as_pb().operation.as_ref())
            .and_then(|operation| match operation {
                PbOperation::Rewrite(rewrite) => Some(rewrite),
                _ => None,
            });
        let fault = if let Some(rewrite) = rewrite {
            self.rewrite_calls.fetch_add(1, Ordering::SeqCst);
            self.kept_ids.lock().unwrap().extend(
                rewrite
                    .rewritten_indices
                    .iter()
                    .filter(|index| index.old_id == index.new_id)
                    .map(|index| {
                        Uuid::try_from(index.new_id.as_ref().unwrap())
                            .unwrap()
                            .to_string()
                    }),
            );
            let fault = self.faults.lock().unwrap().pop_front();
            if fault.is_some() {
                self.snapshots
                    .lock()
                    .unwrap()
                    .push(index_directories(&self.uri));
            }
            fault
        } else {
            None
        };

        match fault {
            Some(CommitFault::AppendAndConflict) => {
                let batch = record_batch!(("id", Int32, vec![100])).unwrap();
                Dataset::write(
                    RecordBatchIterator::new([Ok(batch.clone())], batch.schema()),
                    &self.uri,
                    Some(WriteParams {
                        mode: WriteMode::Append,
                        ..Default::default()
                    }),
                )
                .await
                .unwrap();
                return Err(CommitError::CommitConflict);
            }
            Some(CommitFault::PublishIndicesAndFail) => {
                let mut latest = Dataset::open(&self.uri).await.unwrap();
                let mut new_indices = indices.clone().unwrap();
                for index in &mut new_indices {
                    index.fragment_bitmap = Some(latest.fragment_bitmap().as_ref().clone());
                    index.dataset_version = latest.version_id();
                }
                let transaction = Transaction::new(
                    latest.version_id(),
                    Operation::CreateIndex {
                        new_indices,
                        removed_indices: vec![],
                    },
                    None,
                );
                latest
                    .apply_commit(transaction, &Default::default(), &Default::default())
                    .await
                    .unwrap();
            }
            Some(CommitFault::DropIndexAndFail) => {
                let mut latest = Dataset::open(&self.uri).await.unwrap();
                latest.drop_index("id_idx").await.unwrap();
            }
            Some(CommitFault::FailLatestRead) => {
                self.fail_latest_read.store(true, Ordering::SeqCst);
            }
            _ => {}
        }

        if let Some(fault) = fault
            && !matches!(fault, CommitFault::LandAndError)
        {
            return Err(CommitError::OtherError(Error::io(
                "injected index cleanup commit failure",
            )));
        }

        let location = ConditionalPutCommitHandler
            .commit(
                manifest,
                indices,
                base_path,
                object_store,
                manifest_writer,
                naming_scheme,
                transaction,
            )
            .await?;
        if matches!(fault, Some(CommitFault::LandAndError)) {
            Err(CommitError::OtherError(Error::io(
                "injected index cleanup commit failure",
            )))
        } else {
            Ok(location)
        }
    }
}

async fn indexed_fixture(uri: &str, handler: Arc<IndexCleanupHandler>) -> Dataset {
    let batch = record_batch!(("id", Int32, (0..8).collect::<Vec<_>>())).unwrap();
    let mut dataset = Dataset::write(
        RecordBatchIterator::new([Ok(batch.clone())], batch.schema()),
        uri,
        Some(WriteParams {
            max_rows_per_file: 2,
            commit_handler: Some(handler),
            ..Default::default()
        }),
    )
    .await
    .unwrap();
    dataset
        .create_index(
            &["id"],
            IndexType::BTree,
            Some("id_idx".into()),
            &ScalarIndexParams::default(),
            false,
        )
        .await
        .unwrap();
    dataset
}

fn compaction_options(defer_index_remap: bool) -> CompactionOptions {
    CompactionOptions {
        target_rows_per_fragment: 100,
        defer_index_remap,
        ..Default::default()
    }
}

fn assert_injected_failure(error: &Error) {
    assert!(matches!(error, Error::IO { .. }), "{error:?}");
    assert!(
        error
            .to_string()
            .contains("injected index cleanup commit failure"),
        "{error}"
    );
}

async fn install_external_fri(dataset: &mut Dataset, tagged: bool) {
    let mut metadata = commit_padding_reuse_history(dataset, inline_padding_capacity() + 1).await;
    if tagged {
        let content = load_raw_frag_reuse_content(dataset, &metadata)
            .await
            .unwrap();
        metadata = build_tagged_frag_reuse_entry(
            dataset,
            content,
            metadata.fragment_bitmap.clone().unwrap(),
        )
        .await
        .unwrap();
        let mut indices = load_all_indices(dataset).await.unwrap().as_ref().clone();
        *indices
            .iter_mut()
            .find(|index| index.name == FRAG_REUSE_INDEX_NAME)
            .unwrap() = metadata.clone();
        let manifest = Arc::make_mut(&mut dataset.manifest);
        manifest.reader_feature_flags |= FLAG_FRAGMENT_REUSE_INDEX;
        manifest.writer_feature_flags |= FLAG_FRAGMENT_REUSE_INDEX;
        // Use the existing persisted-fixture helper. CreateIndex deliberately
        // rejects hand-built tagged histories in the public commit path.
        persist_fixture(dataset, indices).await;
    }
    let path = std::path::Path::new(&dataset.uri)
        .join("_indices")
        .join(metadata.uuid.to_string())
        .join("details.binpb");
    assert!(std::fs::metadata(path).unwrap().len() > FRAG_REUSE_INLINE_DETAILS_LIMIT as u64);
}

#[rstest]
#[case::verified_absent(false)]
#[case::latest_manifest_references_output(true)]
#[tokio::test]
async fn test_owned_indices_after_verified_loss(#[case] publish_output: bool) {
    let dir = TempStrDir::default();
    let handler = Arc::new(IndexCleanupHandler::new(dir.as_str()));
    let mut dataset = indexed_fixture(dir.as_str(), handler.clone()).await;
    let before = index_directories(dir.as_str());
    handler.arm([if publish_output {
        CommitFault::PublishIndicesAndFail
    } else {
        CommitFault::Fail
    }]);
    let error = compact_files(&mut dataset, compaction_options(false), None)
        .await
        .unwrap_err();
    assert_injected_failure(&error);
    assert_eq!(handler.rewrite_calls.load(Ordering::SeqCst), 1);
    let attempted = handler.snapshots.lock().unwrap()[0].clone();
    assert_eq!(attempted.difference(&before).count(), 1);
    let expected = if publish_output { &attempted } else { &before };
    assert_eq!(&index_directories(dir.as_str()), expected);
}

#[rstest]
#[case::v0(false)]
#[case::tagged(true)]
#[tokio::test]
async fn test_owned_external_fri_after_verified_loss(#[case] tagged: bool) {
    let dir = TempStrDir::default();
    let handler = Arc::new(IndexCleanupHandler::new(dir.as_str()));
    let mut dataset = indexed_fixture(dir.as_str(), handler.clone()).await;
    install_external_fri(&mut dataset, tagged).await;
    let before = index_directories(dir.as_str());
    handler.arm([CommitFault::Fail]);
    let error = compact_files(&mut dataset, compaction_options(true), None)
        .await
        .unwrap_err();
    assert_injected_failure(&error);
    assert_eq!(handler.rewrite_calls.load(Ordering::SeqCst), 1);
    assert!(!handler.snapshots.lock().unwrap()[0].is_subset(&before));
    assert_eq!(index_directories(dir.as_str()), before);
}

#[rstest]
#[case::v0(false)]
#[case::tagged(true)]
#[tokio::test]
async fn test_owned_fri_rebase_then_terminal_loss(#[case] tagged: bool) {
    let dir = TempStrDir::default();
    let handler = Arc::new(IndexCleanupHandler::new(dir.as_str()));
    let mut dataset = indexed_fixture(dir.as_str(), handler.clone()).await;
    install_external_fri(&mut dataset, tagged).await;
    let before = index_directories(dir.as_str());
    handler.arm([CommitFault::AppendAndConflict, CommitFault::Fail]);
    let error = compact_files(&mut dataset, compaction_options(true), None)
        .await
        .unwrap_err();
    assert_injected_failure(&error);
    assert_eq!(handler.rewrite_calls.load(Ordering::SeqCst), 2);
    {
        let snapshots = handler.snapshots.lock().unwrap();
        assert!(!snapshots[0].is_subset(&before));
        assert!(snapshots[0].is_subset(&snapshots[1]));
        assert_eq!(snapshots[1].difference(&snapshots[0]).count(), 1);
    }
    assert_eq!(index_directories(dir.as_str()), before);
    assert_eq!(
        Dataset::open(dir.as_str())
            .await
            .unwrap()
            .count_rows(None)
            .await
            .unwrap(),
        9
    );
}

#[tokio::test]
async fn test_owned_indices_landed_error_keeps_directories() {
    let dir = TempStrDir::default();
    let handler = Arc::new(IndexCleanupHandler::new(dir.as_str()));
    let mut dataset = indexed_fixture(dir.as_str(), handler.clone()).await;
    let before = index_directories(dir.as_str());
    handler.arm([CommitFault::LandAndError]);
    let error = compact_files(&mut dataset, compaction_options(false), None)
        .await
        .unwrap_err();
    assert_injected_failure(&error);
    assert_eq!(handler.rewrite_calls.load(Ordering::SeqCst), 1);
    let attempted = handler.snapshots.lock().unwrap()[0].clone();
    assert_eq!(attempted.difference(&before).count(), 1);
    assert_eq!(index_directories(dir.as_str()), attempted);
    let latest = Dataset::open(dir.as_str()).await.unwrap();
    assert_eq!(latest.fragments().len(), 1);
    assert_eq!(latest.count_rows(None).await.unwrap(), 8);
    assert_eq!(
        latest
            .scan()
            .filter("id = 3")
            .unwrap()
            .try_into_batch()
            .await
            .unwrap()
            .num_rows(),
        1
    );
}

struct DeleteAfterPlanning;

#[async_trait]
impl CompactionPlanner for DeleteAfterPlanning {
    async fn plan(&self, dataset: &Dataset) -> Result<CompactionPlan> {
        let plan = plan_compaction(dataset, &compaction_options(false)).await?;
        assert_eq!(plan.tasks().len(), 1);
        let mut concurrent = Dataset::open(&dataset.uri).await?;
        concurrent.delete("id = 0").await?;
        Ok(plan)
    }
}

struct AllFragmentsPlanner;

#[async_trait]
impl CompactionPlanner for AllFragmentsPlanner {
    async fn plan(&self, dataset: &Dataset) -> Result<CompactionPlan> {
        Ok(CompactionPlan {
            tasks: vec![TaskData {
                fragments: dataset.fragments().as_ref().clone(),
            }],
            read_version: dataset.version_id(),
            options: compaction_options(false),
        })
    }
}

#[tokio::test]
async fn test_owned_indices_preempted_by_delete_before_manifest_write() {
    let dir = TempStrDir::default();
    let handler = Arc::new(IndexCleanupHandler::new(dir.as_str()));
    let mut dataset = indexed_fixture(dir.as_str(), handler.clone()).await;
    let before = index_directories(dir.as_str());
    let error = compact_files_with_planner(&mut dataset, None, &DeleteAfterPlanning)
        .await
        .unwrap_err();
    assert!(
        matches!(error, Error::RetryableCommitConflict { .. }),
        "{error:?}"
    );
    assert!(
        error
            .to_string()
            .contains("This Rewrite transaction was preempted by concurrent transaction Delete"),
        "{error}"
    );
    assert_eq!(handler.rewrite_calls.load(Ordering::SeqCst), 0);
    assert_eq!(
        Dataset::open(dir.as_str())
            .await
            .unwrap()
            .count_rows(None)
            .await
            .unwrap(),
        7
    );
    assert_eq!(index_directories(dir.as_str()), before);
}

#[tokio::test]
async fn test_owned_indices_keep_id_after_concurrent_drop() {
    let dir = TempStrDir::default();
    let handler = Arc::new(IndexCleanupHandler::new(dir.as_str()));
    let mut dataset = indexed_fixture(dir.as_str(), handler.clone()).await;
    let before = index_directories(dir.as_str());
    let batch = record_batch!(("id", Int32, vec![100, 101])).unwrap();
    dataset = Dataset::write(
        RecordBatchIterator::new([Ok(batch.clone())], batch.schema()),
        dir.as_str(),
        Some(WriteParams {
            mode: WriteMode::Append,
            commit_handler: Some(handler.clone()),
            ..Default::default()
        }),
    )
    .await
    .unwrap();
    let indices = load_all_indices(&dataset).await.unwrap().as_ref().clone();
    let mut fragments = dataset.fragments().as_ref().clone();
    for fragment in &mut fragments[..4] {
        let deleted: DeletionVector = (0..2u32).collect();
        fragment.deletion_file = write_deletion_file(
            &dataset.base,
            fragment.id,
            dataset.version_id(),
            &deleted,
            &dataset.object_store,
        )
        .await
        .unwrap();
    }
    // Retain fully deleted indexed fragments beside live, unindexed data.
    // The custom planner includes them so the built-in remapper returns Keep.
    Arc::make_mut(&mut dataset.manifest).fragments = fragments.into();
    persist_fixture(&mut dataset, indices).await;
    handler.arm([CommitFault::DropIndexAndFail]);
    let error = compact_files_with_planner(&mut dataset, None, &AllFragmentsPlanner)
        .await
        .unwrap_err();
    assert_injected_failure(&error);
    assert_eq!(handler.rewrite_calls.load(Ordering::SeqCst), 1);
    assert_eq!(
        handler
            .kept_ids
            .lock()
            .unwrap()
            .iter()
            .cloned()
            .collect::<BTreeSet<_>>(),
        before
    );
    assert!(
        Dataset::open(dir.as_str())
            .await
            .unwrap()
            .load_indices()
            .await
            .unwrap()
            .is_empty()
    );
    assert_eq!(index_directories(dir.as_str()), before);
}

#[rstest]
#[case::custom_remapper(true)]
#[case::public_commit_compaction(false)]
#[tokio::test]
async fn test_borrowed_remap_outputs_survive_verified_loss(#[case] custom_remapper: bool) {
    let dir = TempStrDir::default();
    let handler = Arc::new(IndexCleanupHandler::new(dir.as_str()));
    let mut dataset = indexed_fixture(dir.as_str(), handler.clone()).await;
    let before = index_directories(dir.as_str());
    handler.arm([CommitFault::Fail]);
    let options = compaction_options(false);
    let error = if custom_remapper {
        compact_files(
            &mut dataset,
            options,
            Some(Arc::new(DatasetIndexRemapperOptions::default())),
        )
        .await
    } else {
        let completed = execute_compaction_plan(&dataset, &options).await;
        commit_compaction(
            &mut dataset,
            completed,
            Arc::new(DatasetIndexRemapperOptions::default()),
            &options,
        )
        .await
    }
    .unwrap_err();
    assert_injected_failure(&error);
    assert_eq!(handler.rewrite_calls.load(Ordering::SeqCst), 1);
    let attempted = handler.snapshots.lock().unwrap()[0].clone();
    assert_eq!(attempted.difference(&before).count(), 1);
    assert_eq!(index_directories(dir.as_str()), attempted);
}

#[rstest]
#[case::create_index(false)]
#[case::rewrite(true)]
#[tokio::test]
async fn test_borrowed_transaction_can_replay_after_verified_loss(#[case] rewrite: bool) {
    let dir = TempStrDir::default();
    let handler = Arc::new(IndexCleanupHandler::new(dir.as_str()));
    let mut dataset = indexed_fixture(dir.as_str(), handler).await;
    let old_id = dataset.load_indices().await.unwrap()[0].uuid;
    let metadata = dataset
        .create_index_builder(&["id"], IndexType::BTree, &ScalarIndexParams::default())
        .name("staged_idx".into())
        .execute_uncommitted()
        .await
        .unwrap();
    let operation = if rewrite {
        Operation::Rewrite {
            groups: vec![],
            rewritten_indices: vec![RewrittenIndex {
                old_id,
                new_id: metadata.uuid,
                new_index_details: metadata.index_details.as_ref().unwrap().as_ref().clone(),
                new_index_version: metadata.index_version.try_into().unwrap(),
                new_index_files: metadata.files,
            }],
            frag_reuse_index: None,
        }
    } else {
        Operation::CreateIndex {
            new_indices: vec![metadata],
            removed_indices: vec![],
        }
    };
    let transaction = Transaction::new(dataset.version_id(), operation, None);
    let before = index_directories(dir.as_str());
    let handler = Arc::new(AmbiguousCommitHandler::default());
    dataset.commit_handler = handler.clone();
    handler.fail_next(AmbiguousFailure::FailOutright);
    let error = dataset
        .apply_commit(
            transaction.clone(),
            &Default::default(),
            &Default::default(),
        )
        .await
        .unwrap_err();
    assert!(matches!(error, Error::IO { .. }), "{error:?}");
    assert!(
        error
            .to_string()
            .contains("simulated outright commit failure"),
        "{error}"
    );
    assert_eq!(index_directories(dir.as_str()), before);
    dataset
        .apply_commit(transaction, &Default::default(), &Default::default())
        .await
        .unwrap();
    assert_eq!(index_directories(dir.as_str()), before);
    assert_eq!(
        dataset
            .scan()
            .filter("id = 3")
            .unwrap()
            .try_into_batch()
            .await
            .unwrap()
            .num_rows(),
        1
    );
}

#[tokio::test]
async fn test_index_cleanup_latest_read_failure_preserves_commit_error() {
    let dir = TempStrDir::default();
    let handler = Arc::new(IndexCleanupHandler::new(dir.as_str()));
    let mut dataset = indexed_fixture(dir.as_str(), handler.clone()).await;
    let before = index_directories(dir.as_str());
    handler.arm([CommitFault::FailLatestRead]);
    let error = compact_files(&mut dataset, compaction_options(false), None)
        .await
        .unwrap_err();
    assert_injected_failure(&error);
    assert_eq!(handler.rewrite_calls.load(Ordering::SeqCst), 1);
    let attempted = handler.snapshots.lock().unwrap()[0].clone();
    assert_eq!(attempted.difference(&before).count(), 1);
    assert_eq!(index_directories(dir.as_str()), attempted);
}

#[tokio::test]
async fn test_index_cleanup_delete_failure_preserves_commit_error() {
    let dir = TempStrDir::default();
    let handler = Arc::new(IndexCleanupHandler::new(dir.as_str()));
    let routed_uri = format!(
        "file-object-store://{}{}",
        if dir.as_str().starts_with('/') {
            ""
        } else {
            "/"
        },
        dir.as_str()
    );
    indexed_fixture(&routed_uri, handler.clone()).await;
    let failing = Arc::new(FailingProxyStore::new());
    failing.fail_when("delete", "_indices", "injected index delete failure");
    let mut dataset = DatasetBuilder::from_uri(&routed_uri)
        .with_read_params(crate::dataset::ReadParams {
            commit_handler: Some(handler.clone()),
            store_options: Some(ObjectStoreParams {
                object_store_wrapper: Some(failing),
                ..Default::default()
            }),
            ..Default::default()
        })
        .load()
        .await
        .unwrap();
    let before = index_directories(dir.as_str());
    handler.arm([CommitFault::Fail]);
    let error = compact_files(&mut dataset, compaction_options(false), None)
        .await
        .unwrap_err();
    assert_injected_failure(&error);
    assert_eq!(handler.rewrite_calls.load(Ordering::SeqCst), 1);
    let attempted = handler.snapshots.lock().unwrap()[0].clone();
    assert_eq!(attempted.difference(&before).count(), 1);
    assert_eq!(index_directories(dir.as_str()), attempted);
}
