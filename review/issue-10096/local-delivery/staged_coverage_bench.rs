// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: Copyright The Lance Authors

//! Manual workload for issue #10096. See the accompanying reproduction guide.
#![allow(clippy::print_stdout)]

use std::sync::{Arc, Mutex};
use std::time::Instant;

use arrow_array::{RecordBatchIterator, cast::AsArray, record_batch, types::Int64Type};
use futures::TryStreamExt;
use lance::Dataset;
use lance::dataset::WriteParams;
use lance::dataset::builder::DatasetBuilder;
use lance::dataset::optimize::{CompactionOptions, compact_files};
use lance::index::DatasetIndexExt;
use lance_datafusion::exec::ExecutionSummaryCounts;
use lance_index::{IndexType, scalar::ScalarIndexParams};
use lance_table::format::{IndexMetadata, pb};
use prost::Message;
use serde_json::json;

fn value(id: i64) -> i64 {
    (id * 48_271) % 2_147_483_647
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args = std::env::args().collect::<Vec<_>>();
    let action = &args[1];
    let uri = &args[2];
    match action.as_str() {
        "prepare" => {
            let rows: usize = args[4].parse()?;
            let schema = record_batch!(("id", Int64, vec![0]), ("val", Int64, vec![0]))?.schema();
            let batches = (0..rows).step_by(65_536).map(move |start| {
                let ids = (start..(start + 65_536).min(rows))
                    .map(|id| id as i64)
                    .collect::<Vec<_>>();
                let vals = ids.iter().copied().map(value).collect::<Vec<_>>();
                record_batch!(("id", Int64, ids), ("val", Int64, vals))
            });
            let mut dataset = Dataset::write(
                RecordBatchIterator::new(batches, schema),
                uri,
                Some(WriteParams {
                    max_rows_per_file: 250_000,
                    enable_stable_row_ids: false,
                    ..Default::default()
                }),
            )
            .await?;
            dataset
                .create_index(
                    &["id"],
                    IndexType::BTree,
                    Some("id_idx".into()),
                    &ScalarIndexParams::default(),
                    false,
                )
                .await?;
            let segment = dataset
                .create_index_builder(&["val"], IndexType::BTree, &ScalarIndexParams::default())
                .name("val_idx".into())
                .execute_uncommitted()
                .await?;
            std::fs::write(&args[3], pb::IndexMetadata::from(&segment).encode_to_vec())?;
            compact_files(
                &mut dataset,
                CompactionOptions {
                    target_rows_per_fragment: 500_000,
                    defer_index_remap: true,
                    ..Default::default()
                },
                None,
            )
            .await?;
            println!(
                "{}",
                json!({"action": action, "rows": rows, "build_version": segment.dataset_version, "compacted_version": dataset.version().version, "fragments": dataset.get_fragments().len()})
            );
        }
        "publish" => {
            let metadata = pb::IndexMetadata::decode(std::fs::read(&args[3])?.as_slice())?;
            let segment = IndexMetadata::try_from(metadata)?;
            let build_version = segment.dataset_version;
            let mut dataset = Dataset::open(uri).await?;
            let start = Instant::now();
            dataset
                .commit_existing_index_segments("val_idx", "val", vec![segment])
                .await?;
            let elapsed = start.elapsed();
            let dataset = Dataset::open(uri).await?;
            let segments = dataset.load_indices_by_name("val_idx").await?;
            let live = dataset.fragment_bitmap();
            let covered = segments
                .iter()
                .filter_map(|s| s.fragment_bitmap.as_ref())
                .fold(roaring::RoaringBitmap::new(), |all, bitmap| all | bitmap);
            assert!(segments.iter().all(|s| s.dataset_version == build_version));
            println!(
                "{}",
                json!({"action": action, "commit_us": elapsed.as_micros(), "build_version": build_version, "live_fragments": live.len(), "covered_live_fragments": (&covered & live.as_ref()).len()})
            );
        }
        "query" => {
            let label = &args[3];
            let cache = &args[4];
            let repeats: usize = args[5].parse()?;
            let mut dataset = Dataset::open(uri).await?;
            let rows = dataset.count_rows(None).await?;
            // Warm the OS page cache with the same unindexed read for every invocation.
            let mut warm = dataset.scan();
            warm.use_scalar_index(false).project(&["id", "val"])?;
            let count = warm
                .try_into_stream()
                .await?
                .try_fold(
                    0,
                    |count, batch| async move { Ok(count + batch.num_rows()) },
                )
                .await?;
            assert_eq!(count, rows);
            for iteration in 0..(repeats + 5) {
                if cache == "fresh-session" {
                    dataset = DatasetBuilder::from_uri(uri).load().await?;
                }
                let id = ((iteration * 104_729 + 12_345) % rows) as i64;
                let expected = value(id);
                let stats = Arc::new(Mutex::new(None::<ExecutionSummaryCounts>));
                let observed = stats.clone();
                let store = dataset.object_store(None).await?;
                store.io_stats_incremental();
                let start = Instant::now();
                let mut scan = dataset.scan();
                scan.project(&["id", "val"])?
                    .filter(&format!("val = {expected}"))?;
                scan.scan_stats_callback(Arc::new(move |counts| {
                    *observed.lock().unwrap() = Some(counts.clone());
                }));
                let batch = scan.try_into_batch().await?;
                let elapsed = start.elapsed();
                assert_eq!(batch.num_rows(), 1);
                assert_eq!(batch["id"].as_primitive::<Int64Type>().value(0), id);
                assert_eq!(batch["val"].as_primitive::<Int64Type>().value(0), expected);
                let io = store.io_stats_incremental();
                let counts = stats.lock().unwrap().take().unwrap_or_default();
                println!(
                    "{}",
                    json!({"label": label, "cache": cache, "iteration": iteration, "warmup": iteration < 5, "id": id, "latency_us": elapsed.as_micros(), "store_read_bytes": io.read_bytes, "plan_bytes_read": counts.bytes_read, "all_counts": counts.all_counts})
                );
            }
            let mut scan = dataset.scan();
            scan.project(&["id", "val"])?
                .filter(&format!("val = {}", value(12_345)))?;
            eprintln!("{}", scan.analyze_plan().await?);
        }
        _ => return Err(format!("Unknown action: {action}").into()),
    }
    Ok(())
}
