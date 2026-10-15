// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: Copyright The Lance Authors

//! Shuffler is a component that takes a stream of record batches and shuffles them into
//! the corresponding IVF partitions.

use std::env::VarError;
use std::fmt;
use std::ops::Range;
use std::sync::{Arc, LazyLock, RwLock};

use arrow::{array::AsArray, compute::sort_to_indices};
use arrow_array::{Array, RecordBatch, UInt32Array, UInt64Array};
use arrow_schema::{DataType, Field, Schema, SchemaRef};
use bytes::Bytes;
use datafusion::execution::memory_pool::{
    MemoryConsumer, MemoryLimit, MemoryPool, MemoryReservation,
};
use futures::{
    future::{BoxFuture, try_join_all},
    prelude::*,
};
use lance_arrow::{DataTypeExt, RecordBatchExt, SchemaExt, interleave_batches};
use lance_core::{
    Error, Result,
    cache::LanceCache,
    deepsize::{Context, DeepSizeOf},
    utils::parse::str_is_truthy,
    utils::tokio::{get_num_compute_intensive_cpus, spawn_cpu},
};
use lance_encoding::decoder::{DecoderPlugins, FilterExpression};
use lance_file::reader::{FileReader, FileReaderOptions};
use lance_file::version::ConcreteFileVersion;
use lance_file::versions;
use lance_file::writer::FileWriterOptions;
use lance_io::{
    ReadBatchParams,
    object_store::ObjectStore,
    scheduler::{FileScheduler, ScanScheduler, SchedulerConfig},
    spill::{Spill, SpillStore},
    stream::{RecordBatchStream, RecordBatchStreamAdapter},
    traits::Reader,
    utils::CachedFileSize,
};
use object_store::path::Path;
use tokio::sync::OnceCell;

use crate::vector::{LOSS_METADATA_KEY, PART_ID_COLUMN};

/// Target decoded size for a contiguous shuffle partition window.
pub const DEFAULT_PARTITION_WINDOW_BYTES: usize = 128 * 1024 * 1024;

/// One partition returned by [`ShuffleReader::read_partition_window`].
pub struct ShufflePartition {
    /// Zero-based IVF partition identifier.
    pub partition_id: usize,
    /// Partition rows, or `None` when the partition is empty.
    pub data: Option<Box<dyn RecordBatchStream + Unpin + 'static>>,
}

/// A contiguous range of shuffled partitions read as one I/O window.
pub struct ShufflePartitionWindow {
    /// Half-open range covered by `partitions`.
    pub partition_range: Range<usize>,
    /// One entry per partition in `partition_range`, including empty ones.
    pub partitions: Vec<ShufflePartition>,
    /// Decoded bytes already materialized by the reader, counted once per
    /// backing Arrow allocation. `None` means the returned streams are lazy.
    pub materialized_decoded_bytes: Option<usize>,
}

/// Metadata-only plan for a contiguous shuffle partition window.
pub struct ShufflePartitionWindowPlan {
    /// Half-open partition range that the subsequent read will return.
    pub partition_range: Range<usize>,
    /// Conservative decoded-memory admission charge for the read.
    pub estimated_decoded_bytes: usize,
}

#[async_trait::async_trait]
/// A reader that can read the shuffled partitions.
pub trait ShuffleReader: Send + Sync {
    /// Read a partition by partition_id
    /// will return Ok(None) if partition_size is 0
    /// check reader.partition_size(partition_id) before calling this function
    async fn read_partition(
        &self,
        partition_id: usize,
    ) -> Result<Option<Box<dyn RecordBatchStream + Unpin + 'static>>>;

    /// Plan a partition window without reading or decoding partition data.
    ///
    /// Readers without a decoded-size estimate use an oversized admission
    /// charge for non-empty partitions so the read runs exclusively.
    fn plan_partition_window(
        &self,
        start_partition_id: usize,
        max_decoded_bytes: usize,
    ) -> Result<ShufflePartitionWindowPlan> {
        if max_decoded_bytes == 0 {
            return Err(Error::invalid_input(
                "max_decoded_bytes must be greater than 0",
            ));
        }
        let end = start_partition_id.checked_add(1).ok_or_else(|| {
            Error::invalid_input(format!(
                "start_partition_id={} cannot be advanced",
                start_partition_id
            ))
        })?;
        let partition_rows = self.partition_size(start_partition_id)?;
        Ok(ShufflePartitionWindowPlan {
            partition_range: start_partition_id..end,
            estimated_decoded_bytes: if partition_rows == 0 { 0 } else { usize::MAX },
        })
    }

    /// Read a contiguous partition window starting at `start_partition_id`.
    ///
    /// The default implementation returns a singleton window. Other readers
    /// can coalesce I/O or return separate streams for the planned partitions.
    /// The byte budget is a decoded-memory target, not an encoded I/O size.
    /// A partition larger than the budget is returned as a singleton.
    async fn read_partition_window(
        &self,
        start_partition_id: usize,
        max_decoded_bytes: usize,
    ) -> Result<ShufflePartitionWindow> {
        if max_decoded_bytes == 0 {
            return Err(Error::invalid_input(
                "max_decoded_bytes must be greater than 0",
            ));
        }
        let end = start_partition_id.checked_add(1).ok_or_else(|| {
            Error::invalid_input(format!(
                "start_partition_id={} cannot be advanced",
                start_partition_id
            ))
        })?;
        let data = if self.partition_size(start_partition_id)? == 0 {
            None
        } else {
            self.read_partition(start_partition_id).await?
        };
        Ok(ShufflePartitionWindow {
            partition_range: start_partition_id..end,
            partitions: vec![ShufflePartition {
                partition_id: start_partition_id,
                data,
            }],
            materialized_decoded_bytes: None,
        })
    }

    /// Release optional cached data before retrying a memory reservation.
    ///
    /// Implementations keep planned partition windows valid after eviction.
    /// Already-running reads may retain cache ownership until they complete.
    async fn release_optional_memory(&self) -> Result<()> {
        Ok(())
    }

    /// Get the size of the partition by partition_id
    fn partition_size(&self, partition_id: usize) -> Result<usize>;

    /// Get the total loss,
    /// if the loss is not available, return None,
    /// in such case, the caller should sum up the losses from each batch's metadata.
    /// Must be called after all partitions are read.
    fn total_loss(&self) -> Option<f64>;
}

#[async_trait::async_trait]
/// A shuffler that can shuffle the incoming stream of record batches into IVF partitions.
/// Returns a IvfShuffleReader that can be used to read the shuffled partitions.
pub trait Shuffler: Send + Sync {
    /// Shuffle the incoming stream of record batches into IVF partitions.
    /// Returns a IvfShuffleReader that can be used to read the shuffled partitions.
    async fn shuffle(
        &self,
        data: Box<dyn RecordBatchStream + Unpin + 'static>,
    ) -> Result<Box<dyn ShuffleReader>>;
}

pub struct IvfShuffler {
    object_store: Arc<ObjectStore>,
    output_dir: Path,
    num_partitions: usize,
    format_version: ConcreteFileVersion,

    progress: Arc<dyn crate::progress::IndexBuildProgress>,
}

impl IvfShuffler {
    pub fn new(output_dir: Path, num_partitions: usize) -> Self {
        Self {
            object_store: Arc::new(ObjectStore::local()),
            output_dir,
            num_partitions,
            format_version: ConcreteFileVersion::V2_0,
            progress: crate::progress::noop_progress(),
        }
    }

    pub fn with_format_version(mut self, format_version: ConcreteFileVersion) -> Self {
        self.format_version = format_version;
        self
    }

    pub fn with_progress(mut self, progress: Arc<dyn crate::progress::IndexBuildProgress>) -> Self {
        self.progress = progress;
        self
    }
}

#[async_trait::async_trait]
impl Shuffler for IvfShuffler {
    async fn shuffle(
        &self,
        data: Box<dyn RecordBatchStream + Unpin + 'static>,
    ) -> Result<Box<dyn ShuffleReader>> {
        let num_partitions = self.num_partitions;
        let mut partition_sizes = vec![0; num_partitions];
        let schema = data.schema().without_column(PART_ID_COLUMN);
        let estimated_row_bytes = estimate_decoded_row_bytes(&schema)?;
        let mut writers = stream::iter(0..num_partitions)
            .map(|partition_id| {
                let part_path = self
                    .output_dir
                    .clone()
                    .join(format!("ivf_{}.lance", partition_id));
                let spill_path = self
                    .output_dir
                    .clone()
                    .join(format!("ivf_{}.spill", partition_id));
                let object_store = self.object_store.clone();
                let schema = schema.clone();
                let format_version = self.format_version;
                async move {
                    let writer = object_store.create(&part_path).await?;
                    let file_writer = versions::create_writer(
                        format_version,
                        writer,
                        lance_core::datatypes::Schema::try_from(&schema)?,
                        FileWriterOptions::default(),
                    )?
                    .with_page_metadata_spill(object_store.clone(), spill_path);
                    Result::Ok(file_writer)
                }
            })
            .buffered(self.object_store.io_parallelism())
            .try_collect::<Vec<_>>()
            .await?;
        let mut parallel_sort_stream = data
            .map(|batch| {
                spawn_cpu(move || {
                    let batch = batch?;

                    let loss = batch
                        .metadata()
                        .get(LOSS_METADATA_KEY)
                        .map(|s| s.parse::<f64>().unwrap_or_default())
                        .unwrap_or_default();

                    let part_ids: &UInt32Array = batch[PART_ID_COLUMN].as_primitive();

                    let indices = sort_to_indices(&part_ids, None, None)?;
                    let batch = batch.take(&indices)?;

                    let part_ids: &UInt32Array = batch[PART_ID_COLUMN].as_primitive();
                    let batch = batch.drop_column(PART_ID_COLUMN)?;

                    let mut partition_buffers = vec![Vec::new(); num_partitions];

                    let mut start = 0;
                    while start < batch.num_rows() {
                        let part_id: u32 = part_ids.value(start);
                        let mut end = start + 1;
                        while end < batch.num_rows() && part_ids.value(end) == part_id {
                            end += 1;
                        }

                        let part_batches = &mut partition_buffers[part_id as usize];
                        part_batches.push(batch.slice(start, end - start));
                        start = end;
                    }

                    Ok::<(Vec<Vec<RecordBatch>>, f64), Error>((partition_buffers, loss))
                })
            })
            .buffered(get_num_compute_intensive_cpus());

        let mut total_loss = 0.0;
        let mut num_rows = 0u64;
        while let Some(shuffled) = parallel_sort_stream.next().await {
            let (shuffled, loss) = shuffled?;
            total_loss += loss;

            let mut futs = Vec::new();
            for (part_id, (writer, batches)) in writers.iter_mut().zip(shuffled.iter()).enumerate()
            {
                if !batches.is_empty() {
                    let rows = batches.iter().map(|b| b.num_rows()).sum::<usize>();
                    partition_sizes[part_id] += rows;
                    num_rows += rows as u64;
                    futs.push(writer.write_batches(batches.iter()));
                }
            }
            try_join_all(futs).await?;

            self.progress.stage_progress("shuffle", num_rows).await?;
        }

        // finish all writers
        for writer in writers.iter_mut() {
            writer.finish().await?;
        }

        Ok(Box::new(
            IvfShufflerReader::new(
                self.object_store.clone(),
                self.output_dir.clone(),
                partition_sizes,
                total_loss,
            )
            .with_estimated_row_bytes(estimated_row_bytes),
        ))
    }
}

pub struct IvfShufflerReader {
    scheduler: Arc<ScanScheduler>,
    output_dir: Path,
    partition_sizes: Vec<usize>,
    estimated_row_bytes: Option<usize>,
    loss: f64,
}

impl IvfShufflerReader {
    pub fn new(
        object_store: Arc<ObjectStore>,
        output_dir: Path,
        partition_sizes: Vec<usize>,
        loss: f64,
    ) -> Self {
        let scheduler_config = SchedulerConfig::max_bandwidth(&object_store);
        let scheduler = ScanScheduler::new(object_store, scheduler_config);
        Self {
            scheduler,
            output_dir,
            partition_sizes,
            estimated_row_bytes: None,
            loss,
        }
    }

    fn with_estimated_row_bytes(mut self, estimated_row_bytes: usize) -> Self {
        self.estimated_row_bytes = Some(estimated_row_bytes);
        self
    }
}

#[async_trait::async_trait]
impl ShuffleReader for IvfShufflerReader {
    async fn read_partition(
        &self,
        partition_id: usize,
    ) -> Result<Option<Box<dyn RecordBatchStream + Unpin + 'static>>> {
        if partition_id >= self.partition_sizes.len() {
            return Ok(None);
        }

        let partition_path = self
            .output_dir
            .clone()
            .join(format!("ivf_{}.lance", partition_id));

        let reader = FileReader::try_open(
            self.scheduler
                .open_file(&partition_path, &CachedFileSize::unknown())
                .await?,
            None,
            Arc::<DecoderPlugins>::default(),
            &LanceCache::no_cache(),
            FileReaderOptions::default(),
        )
        .await?;
        let schema: Schema = reader.schema().as_ref().into();
        let stream = reader
            .read_stream(
                lance_io::ReadBatchParams::RangeFull,
                u32::MAX,
                16,
                FilterExpression::no_filter(),
            )
            .await?;
        Ok(Some(Box::new(RecordBatchStreamAdapter::new(
            Arc::new(schema),
            stream,
        ))))
    }

    fn plan_partition_window(
        &self,
        start_partition_id: usize,
        max_decoded_bytes: usize,
    ) -> Result<ShufflePartitionWindowPlan> {
        if max_decoded_bytes == 0 {
            return Err(Error::invalid_input(
                "max_decoded_bytes must be greater than 0",
            ));
        }
        let Some(&partition_rows) = self.partition_sizes.get(start_partition_id) else {
            return Err(Error::invalid_input(format!(
                "start_partition_id={} is out of range [0, {})",
                start_partition_id,
                self.partition_sizes.len()
            )));
        };
        let end_partition_id = start_partition_id.checked_add(1).ok_or_else(|| {
            Error::invalid_input(format!(
                "start_partition_id={} cannot be advanced",
                start_partition_id
            ))
        })?;
        let estimated_decoded_bytes = match (partition_rows, self.estimated_row_bytes) {
            (0, _) => 0,
            (_, Some(estimated_row_bytes)) => {
                conservative_partition_admission_bytes(partition_rows, estimated_row_bytes)?
            }
            (_, None) => usize::MAX,
        };
        Ok(ShufflePartitionWindowPlan {
            partition_range: start_partition_id..end_partition_id,
            estimated_decoded_bytes,
        })
    }

    fn partition_size(&self, partition_id: usize) -> Result<usize> {
        Ok(self.partition_sizes.get(partition_id).copied().unwrap_or(0))
    }

    fn total_loss(&self) -> Option<f64> {
        Some(self.loss)
    }
}

pub struct EmptyReader;

#[async_trait::async_trait]
impl ShuffleReader for EmptyReader {
    async fn read_partition(
        &self,
        _partition_id: usize,
    ) -> Result<Option<Box<dyn RecordBatchStream + Unpin + 'static>>> {
        Ok(None)
    }

    fn partition_size(&self, _partition_id: usize) -> Result<usize> {
        Ok(0)
    }

    fn total_loss(&self) -> Option<f64> {
        None
    }
}

/// Create an IVF shuffler. Uses [`TwoFileShuffler`] by default, which writes
/// all data to just two files (data + offsets) instead of one file per partition.
/// Set `LANCE_LEGACY_SHUFFLER=1` to fall back to [`IvfShuffler`], which opens
/// one file per partition.
///
/// An optional `progress` callback can be provided to receive shuffle progress
/// updates.
pub fn create_ivf_shuffler(
    output_dir: Path,
    num_partitions: usize,
    format_version: ConcreteFileVersion,
    progress: Option<Arc<dyn crate::progress::IndexBuildProgress>>,
) -> Box<dyn Shuffler> {
    let use_legacy = std::env::var("LANCE_LEGACY_SHUFFLER")
        .map(|v| str_is_truthy(&v))
        .unwrap_or(false);
    if use_legacy {
        let mut shuffler =
            IvfShuffler::new(output_dir, num_partitions).with_format_version(format_version);
        if let Some(progress) = progress {
            shuffler = shuffler.with_progress(progress);
        }
        Box::new(shuffler)
    } else {
        let mut shuffler = TwoFileShuffler::new(output_dir, num_partitions);
        if let Some(progress) = progress {
            shuffler = shuffler.with_progress(progress);
        }
        Box::new(shuffler)
    }
}

/// Create an IVF shuffler whose temporary files use a shared spill store.
///
/// This includes the data, partition offsets, and their page metadata. The
/// legacy shuffler does not support a spill store, so this function returns an
/// error when `LANCE_LEGACY_SHUFFLER` is enabled. `output_dir` is unused when
/// the configured store supplies backing storage. An optional memory pool
/// accounts for buffered shuffle inputs and sort/interleave workspace.
///
/// ```no_run
/// # use std::sync::Arc;
/// # use lance_index::vector::v3::shuffler::create_ivf_shuffler_with_resources;
/// # use lance_file::version::ConcreteFileVersion;
/// # use lance_io::spill::LocalSpillStore;
/// # use object_store::path::Path;
/// # fn example() -> lance_core::Result<()> {
/// let shuffler = create_ivf_shuffler_with_resources(
///     Path::from("shuffle"), 16, ConcreteFileVersion::V2_1, None,
///     Arc::new(LocalSpillStore::default()), None,
/// )?;
/// # Ok(())
/// # }
/// ```
pub fn create_ivf_shuffler_with_resources(
    output_dir: Path,
    num_partitions: usize,
    _format_version: ConcreteFileVersion,
    progress: Option<Arc<dyn crate::progress::IndexBuildProgress>>,
    spill_store: Arc<dyn SpillStore>,
    memory_pool: Option<Arc<dyn MemoryPool>>,
) -> Result<Box<dyn Shuffler>> {
    if std::env::var("LANCE_LEGACY_SHUFFLER")
        .map(|value| str_is_truthy(&value))
        .unwrap_or(false)
    {
        return Err(Error::invalid_input(
            "LANCE_LEGACY_SHUFFLER is enabled, but the legacy shuffler does not support \
             a configured memory pool or session spill store; unset LANCE_LEGACY_SHUFFLER",
        ));
    }
    let mut shuffler =
        TwoFileShuffler::new(output_dir, num_partitions).with_spill_store(spill_store);
    if let Some(progress) = progress {
        shuffler = shuffler.with_progress(progress);
    }
    if let Some(memory_pool) = memory_pool {
        shuffler = shuffler.with_memory_pool(memory_pool);
    }
    Ok(Box::new(shuffler))
}

/// Schema of the partition-offsets sidecar written alongside shuffled data.
static OFFSETS_SCHEMA: LazyLock<SchemaRef> = LazyLock::new(|| {
    Arc::new(Schema::new(vec![Field::new(
        "offset",
        DataType::UInt64,
        false,
    )]))
});

const DEFAULT_SHUFFLE_BATCH_BYTES: usize = 128 * 1024 * 1024;

/// Maximum resident size of the preloaded offsets table.
///
/// This covers tens of millions of offsets while bounding the additional memory
/// held for unusually large shuffles. Larger tables are still validated once as
/// a stream and then read on demand.
const DEFAULT_MAX_PRELOADED_OFFSETS_BYTES: usize = 256 * 1024 * 1024;
const MAX_PRELOADED_OFFSETS_BYTES_ENV: &str = "LANCE_SHUFFLE_MAX_PRELOADED_OFFSETS_BYTES";

fn parse_max_preloaded_offsets_bytes(
    value: std::result::Result<String, VarError>,
) -> Result<usize> {
    match value {
        Ok(value) => value.trim().parse::<usize>().map_err(|error| {
            Error::invalid_input(format!(
                "{MAX_PRELOADED_OFFSETS_BYTES_ENV} must be a non-negative integer number of bytes \
                 (0 disables preloading), got {value:?}: {error}"
            ))
        }),
        Err(VarError::NotPresent) => Ok(DEFAULT_MAX_PRELOADED_OFFSETS_BYTES),
        Err(VarError::NotUnicode(value)) => Err(Error::invalid_input(format!(
            "{MAX_PRELOADED_OFFSETS_BYTES_ENV} must contain a UTF-8 integer number of bytes, got {value:?}"
        ))),
    }
}

/// Number of rows per output batch when streaming sorted data via interleave.
/// Small enough to keep the output chunk's memory footprint modest relative to
/// the accumulated source data.
const SHUFFLE_WRITE_CHUNK_ROWS: usize = 8 * 1024;

/// Limit of how much transformed data we accumulate before spilling to disk.
///
/// A larger value will use more RAM but require less random access during the
/// read phase.
///
/// This default is likely to be fine for most use cases.
fn shuffle_batch_bytes() -> usize {
    let batch_size = std::env::var("LANCE_SHUFFLE_BATCH_BYTES")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(DEFAULT_SHUFFLE_BATCH_BYTES);
    if batch_size == 0 {
        log::warn!(
            "LANCE_SHUFFLE_BATCH_BYTES is 0, using default of {}",
            DEFAULT_SHUFFLE_BATCH_BYTES
        );
        DEFAULT_SHUFFLE_BATCH_BYTES
    } else {
        batch_size
    }
}

/// A shuffler that writes all data to just two files (data + offsets) instead
/// of one file per partition. This avoids hitting OS file descriptor limits
/// when there are many partitions.
///
/// First we accumulate data in memory until we reach the batch size limit.
/// Then we sort the data by partition ID and compute an offset per partition.
/// Then we write the data to a data file and the offsets to an offsets file.
///
/// To read the data back, we read every Nth value from the offsets file to get
/// the start and end of each partition.
///
/// Then we read those ranges from the data file.
pub struct TwoFileShuffler {
    object_store: Arc<ObjectStore>,
    spill_store: Option<Arc<dyn SpillStore>>,
    memory_pool: Option<Arc<dyn MemoryPool>>,
    output_dir: Path,
    num_partitions: usize,
    batch_size_bytes: usize,

    progress: Arc<dyn crate::progress::IndexBuildProgress>,
}

impl TwoFileShuffler {
    pub fn new(output_dir: Path, num_partitions: usize) -> Self {
        Self {
            object_store: Arc::new(ObjectStore::local()),
            spill_store: None,
            memory_pool: None,
            output_dir,
            num_partitions,
            batch_size_bytes: shuffle_batch_bytes(),
            progress: crate::progress::noop_progress(),
        }
    }

    pub fn with_progress(mut self, progress: Arc<dyn crate::progress::IndexBuildProgress>) -> Self {
        self.progress = progress;
        self
    }

    /// Use reclaimable scratch storage for data, offsets, and page metadata.
    ///
    /// No files are written to the constructor's `output_dir` in this mode.
    /// The returned shuffle reader and its streams keep the scratch files alive.
    ///
    /// ```no_run
    /// # use std::sync::Arc;
    /// # use lance_index::vector::v3::shuffler::TwoFileShuffler;
    /// # use lance_io::spill::LocalSpillStore;
    /// # use object_store::path::Path;
    /// let shuffler = TwoFileShuffler::new(Path::from("shuffle"), 16)
    ///     .with_spill_store(Arc::new(LocalSpillStore::default()));
    /// ```
    pub fn with_spill_store(mut self, store: Arc<dyn SpillStore>) -> Self {
        self.spill_store = Some(store);
        self
    }

    /// Account for shuffle input buffers and sort/interleave workspace.
    ///
    /// A finite pool sets the target flush size to half its limit, overriding
    /// `LANCE_SHUFFLE_BATCH_BYTES`. Failed reservations flush
    /// buffered rows and retry; an input batch that still cannot fit returns an
    /// error. Input arrays retain their full backing allocation when sliced.
    /// The upstream stream owns each current or lookahead input before it is
    /// admitted. A rejected lookahead batch can remain alive while earlier rows
    /// flush; that allocation is outside this reservation. Upstream transforms,
    /// encoder internals, and operating-system I/O buffers are also excluded.
    /// This is not a process RSS limit.
    ///
    /// ```no_run
    /// # use std::sync::Arc;
    /// # use datafusion::execution::memory_pool::GreedyMemoryPool;
    /// # use lance_index::vector::v3::shuffler::TwoFileShuffler;
    /// # use object_store::path::Path;
    /// let shuffler = TwoFileShuffler::new(Path::from("shuffle"), 16)
    ///     .with_memory_pool(Arc::new(GreedyMemoryPool::new(64 * 1024 * 1024)));
    /// ```
    pub fn with_memory_pool(mut self, pool: Arc<dyn MemoryPool>) -> Self {
        self.memory_pool = Some(pool);
        self
    }

    fn batch_target_bytes(&self) -> usize {
        self.memory_pool
            .as_ref()
            .map_or(self.batch_size_bytes, |pool| match pool.memory_limit() {
                MemoryLimit::Finite(limit) => limit / 2,
                MemoryLimit::Infinite | MemoryLimit::Unknown => self.batch_size_bytes,
            })
    }

    async fn create_writer(&self, name: &str, schema: &Schema) -> Result<ShuffleWriter> {
        let (writer, file) = if let Some(store) = &self.spill_store {
            let (writer, spill) = store.new_spill().await?;
            (writer, ShuffleFile::Spill(spill.into()))
        } else {
            let path = self.output_dir.clone().join(format!("{name}.lance"));
            (
                self.object_store.create(&path).await?,
                ShuffleFile::Path(path),
            )
        };
        let writer = versions::v2_1::create_writer(
            writer,
            lance_core::datatypes::Schema::try_from(schema)?,
            FileWriterOptions {
                // Returning from write_batch must release its input arrays
                // before the shuffle reservation can be returned to the pool.
                data_cache_bytes: self.memory_pool.as_ref().map(|_| 0),
                ..Default::default()
            },
        )?;
        let writer = if let Some(store) = &self.spill_store {
            writer.with_page_metadata_spill_store(store.clone())
        } else {
            writer.with_page_metadata_spill(
                self.object_store.clone(),
                self.output_dir.clone().join(format!("{name}.spill")),
            )
        };
        Ok(ShuffleWriter { writer, file })
    }

    #[cfg(test)]
    fn with_batch_size_bytes(mut self, batch_size_bytes: usize) -> Self {
        self.batch_size_bytes = batch_size_bytes;
        self
    }
}

/// `(batch_idx, row_idx)` pairs produced by [`sort_to_interleave_indices`], paired with
/// per-partition row counts.
type InterleaveResult = (Vec<(usize, usize)>, Vec<u64>);

/// Sorts rows from multiple batches by partition ID and returns interleave indices.
///
/// Builds a sort key of `(part_id, batch_idx, row_idx)` for every row across all
/// batches, sorts by `part_id`, then emits `(batch_idx, row_idx)` pairs in that
/// order. This avoids concatenating the full data: only the `UInt32` partition-ID
/// columns are touched here.
///
/// Also returns per-partition row counts (derived from the same sorted keys at no
/// extra cost).
///
/// Returns an error if any partition ID is null or out of range `[0, num_partitions)`.
///
/// `PrimitiveArray::values()` stores a 0 in null slots. Treating those as
/// partition 0 would silently move filtered/invalid rows into the first IVF
/// partition.
fn sort_to_interleave_indices(
    part_id_columns: &[&UInt32Array],
    num_partitions: usize,
) -> Result<InterleaveResult> {
    let total_rows: usize = part_id_columns.iter().map(|a| a.len()).sum();

    // Partition ids are bounded by `num_partitions`, so counting sort orders the
    // rows in O(n + num_partitions) passes instead of sorting n key tuples.
    let mut partition_counts = vec![0u64; num_partitions];
    for (batch_idx, col) in part_id_columns.iter().enumerate() {
        for row_idx in 0..col.len() {
            if col.is_null(row_idx) {
                return Err(Error::invalid_input(format!(
                    "null partition ID at batch {} row {}",
                    batch_idx, row_idx
                )));
            }
            let part_id = col.value(row_idx) as usize;
            if part_id >= num_partitions {
                return Err(Error::invalid_input(format!(
                    "partition ID {} is out of range [0, {})",
                    part_id, num_partitions
                )));
            }
            partition_counts[part_id] += 1;
        }
    }

    // Prefix sums turn the counts into the first slot of each partition's run,
    // then the scatter pass below consumes them as a write cursor per partition.
    let mut cursors = Vec::with_capacity(num_partitions);
    let mut running = 0usize;
    for &count in partition_counts.iter() {
        cursors.push(running);
        running += count as usize;
    }

    let mut interleave_indices = vec![(0usize, 0usize); total_rows];
    for (batch_idx, col) in part_id_columns.iter().enumerate() {
        for (row_idx, &part_id) in col.values().iter().enumerate() {
            let cursor = &mut cursors[part_id as usize];
            interleave_indices[*cursor] = (batch_idx, row_idx);
            *cursor += 1;
        }
    }

    Ok((interleave_indices, partition_counts))
}

#[async_trait::async_trait]
impl Shuffler for TwoFileShuffler {
    async fn shuffle(
        &self,
        data: Box<dyn RecordBatchStream + Unpin + 'static>,
    ) -> Result<Box<dyn ShuffleReader>> {
        let max_preloaded_offsets_bytes =
            parse_max_preloaded_offsets_bytes(std::env::var(MAX_PRELOADED_OFFSETS_BYTES_ENV))?;
        self.shuffle_with_preload_limit(data, max_preloaded_offsets_bytes)
            .await
    }
}

impl TwoFileShuffler {
    async fn shuffle_with_preload_limit(
        &self,
        data: Box<dyn RecordBatchStream + Unpin + 'static>,
        max_preloaded_offsets_bytes: usize,
    ) -> Result<Box<dyn ShuffleReader>> {
        let num_partitions = self.num_partitions;
        let schema = data.schema().without_column(PART_ID_COLUMN);
        let offsets_schema = OFFSETS_SCHEMA.clone();
        let batch_size_bytes = self.batch_target_bytes();
        let reservation = self.memory_pool.as_ref().map(|pool| {
            Arc::new(
                MemoryConsumer::new("IVFShuffle")
                    .with_can_spill(true)
                    .register(pool),
            )
        });
        // Keep cached offsets a small part of a finite pool so they cannot
        // strand most of the budget while the next build stage reads partitions.
        let max_preloaded_offsets_bytes =
            self.memory_pool
                .as_ref()
                .map_or(max_preloaded_offsets_bytes, |pool| {
                    max_preloaded_offsets_bytes.min(match pool.memory_limit() {
                        MemoryLimit::Finite(limit) => limit / 16,
                        MemoryLimit::Unknown => 256 * 1024,
                        MemoryLimit::Infinite => max_preloaded_offsets_bytes,
                    })
                });
        let mut written_offsets = BoundedWrittenOffsets::new(max_preloaded_offsets_bytes);
        if let Some(pool) = &self.memory_pool {
            written_offsets.reservation =
                Some(MemoryConsumer::new("IVFShuffleOffsets").register(pool));
        }
        let mut data_file = self.create_writer("shuffle_data", &schema).await?;
        let mut offsets_file = self
            .create_writer("shuffle_offsets", &offsets_schema)
            .await?;
        let mut num_batches: u64 = 0;
        let mut partition_counts: Vec<u64> = vec![0; num_partitions];
        let mut global_row_count: u64 = 0;
        let mut rows_processed: u64 = 0;
        let mut total_loss = 0.0f64;
        let mut accumulated: Vec<RecordBatch> = Vec::new();
        let mut acc_bytes: usize = 0;
        let mut pending_batch = None;
        let mut data = std::pin::pin!(data);
        loop {
            let next = match pending_batch.take() {
                Some(batch) => Some(Ok(batch)),
                None => data.next().await,
            };
            let input_finished = next.is_none();
            if let Some(batch) = next {
                let batch = batch?;
                let mut must_flush = false;
                if let Some(reservation) = &reservation {
                    let charge = shuffle_batch_memory_charge(
                        &batch,
                        num_partitions,
                        accumulated.is_empty(),
                    )?;
                    if let Err(error) = reservation.try_grow(charge) {
                        if accumulated.is_empty() {
                            // The cache is optional; discard it before rejecting
                            // an otherwise valid minimum input batch.
                            written_offsets.discard();
                            reservation.try_grow(charge).map_err(|retry_error| Error::execution(format!(
                                "IVF shuffle memory cannot admit an input batch with {} rows: \
                                 {} bytes required for its Arrow buffers and sort/interleave workspace; \
                                 increase the memory budget or reduce the upstream input batch size: {} \
                                 (initial reservation: {})",
                                batch.num_rows(), charge, retry_error, error,
                            )))?;
                        } else {
                            must_flush = true;
                        }
                    }
                }
                if must_flush {
                    pending_batch = Some(batch);
                } else {
                    total_loss += batch
                        .metadata()
                        .get(LOSS_METADATA_KEY)
                        .and_then(|value| value.parse::<f64>().ok())
                        .unwrap_or(0.0);
                    acc_bytes = acc_bytes
                        .checked_add(batch.get_array_memory_size())
                        .ok_or_else(|| {
                            Error::invalid_input(
                                "IVF shuffle accumulated input size overflows usize",
                            )
                        })?;
                    accumulated.push(batch);
                    // Flush on the charged workspace as well as input size so
                    // a near-limit batch leaves before polling another input.
                    // Arbitrary upstream streams can still return a larger
                    // lookahead allocation before we can reserve it.
                    let workspace_below_target = reservation
                        .as_ref()
                        .is_none_or(|reservation| reservation.size() < batch_size_bytes);
                    if acc_bytes < batch_size_bytes && workspace_below_target {
                        continue;
                    }
                }
            }
            if accumulated.is_empty() {
                break;
            }
            let (total_rows, counts) = flush_shuffle_batch(
                std::mem::take(&mut accumulated),
                &mut data_file.writer,
                &mut offsets_file.writer,
                offsets_schema.clone(),
                num_partitions,
                global_row_count,
                &mut written_offsets,
                reservation.clone(),
            )
            .await?;
            if let Some(reservation) = &reservation {
                reservation.free();
            }
            acc_bytes = 0;
            for (partition, count) in counts.iter().enumerate() {
                partition_counts[partition] += count;
            }
            global_row_count += total_rows;
            rows_processed += total_rows;
            num_batches += 1;
            self.progress
                .stage_progress("shuffle", rows_processed)
                .await?;
            if input_finished {
                break;
            }
        }
        // Unregister the spilling consumer before reader construction and
        // partition building, so FairSpillPool does not count an idle spiller.
        drop(reservation);
        data_file.writer.finish().await?;
        offsets_file.writer.finish().await?;
        TwoFileShuffleReader::try_new_with_files(
            self.object_store.clone(),
            data_file.file.clone(),
            offsets_file.file.clone(),
            num_partitions,
            num_batches,
            partition_counts,
            total_loss,
            max_preloaded_offsets_bytes,
            written_offsets.into_offsets(),
        )
        .await
    }
}

/// Reserve source allocations plus a full-size interleave output, per-row
/// sort indices, and per-batch/partition bookkeeping. Counting a full output
/// rather than just its 8192-row chunk also covers variable-width inputs.
fn shuffle_batch_memory_charge(
    batch: &RecordBatch,
    num_partitions: usize,
    first: bool,
) -> Result<usize> {
    let arrays_and_output = batch.get_array_memory_size().checked_mul(2);
    let row_indices = batch
        .num_rows()
        .checked_mul(std::mem::size_of::<(usize, usize)>());
    let partition_workspace = if first {
        num_partitions.checked_mul(3 * std::mem::size_of::<u64>())
    } else {
        Some(0)
    };
    arrays_and_output
        .and_then(|bytes| bytes.checked_add(row_indices?))
        .and_then(|bytes| bytes.checked_add(partition_workspace?))
        .and_then(|bytes| {
            bytes.checked_add(
                2 * std::mem::size_of::<RecordBatch>() + std::mem::size_of::<UInt32Array>(),
            )
        })
        .ok_or_else(|| {
            Error::invalid_input(format!(
                "IVF shuffle memory estimate overflows for {} rows and {} partitions",
                batch.num_rows(),
                num_partitions,
            ))
        })
}

/// Sorts `accumulated` batches by partition ID and writes the result to the data
/// and offsets files.
///
/// Returns `(total_rows_written, per_partition_row_counts)`.
#[allow(clippy::too_many_arguments)]
async fn flush_shuffle_batch(
    accumulated: Vec<RecordBatch>,
    file_writer: &mut versions::v2_1::Writer,
    offsets_writer: &mut versions::v2_1::Writer,
    offsets_schema: Arc<Schema>,
    num_partitions: usize,
    global_row_count: u64,
    written_offsets: &mut BoundedWrittenOffsets,
    memory_reservation: Option<Arc<MemoryReservation>>,
) -> Result<(u64, Vec<u64>)> {
    // Clone part-id columns into the CPU task (cheap: Arc ref bump, not data copy).
    let part_id_cols: Vec<UInt32Array> = accumulated
        .iter()
        .map(|b| {
            let col: &UInt32Array = b[PART_ID_COLUMN].as_primitive();
            col.clone()
        })
        .collect();

    let np = num_partitions;
    let (interleave_indices, batch_partition_counts) = spawn_cpu(move || {
        // CPU work can finish after its awaiting future is cancelled.
        let _memory_reservation = memory_reservation;
        sort_to_interleave_indices(&part_id_cols.iter().collect::<Vec<_>>(), np)
    })
    .await?;

    let total_rows = u64::try_from(interleave_indices.len()).map_err(|_| {
        Error::invalid_input(format!(
            "shuffle flush has {} rows, which cannot be represented as u64",
            interleave_indices.len()
        ))
    })?;
    let counted_rows: u64 = batch_partition_counts.iter().sum();
    if counted_rows != total_rows {
        return Err(Error::invalid_input(format!(
            "partition counts sum to {} rows but the flush is interleaving {} rows",
            counted_rows, total_rows
        )));
    }

    // Drop part-id column from source batches before interleaving.
    let source_batches: Vec<RecordBatch> = accumulated
        .into_iter()
        .map(|b| b.drop_column(PART_ID_COLUMN).map_err(Error::from))
        .collect::<Result<_>>()?;

    // Stream sorted output to the data file in fixed-size chunks so the peak
    // memory for the interleave output stays small relative to the source data.
    for chunk in interleave_indices.chunks(SHUFFLE_WRITE_CHUNK_ROWS) {
        let out = interleave_batches(&source_batches, chunk)?;
        file_writer.write_batch(&out).await?;
    }

    // Compute cumulative end-row offsets (adjusted by global position) and write
    // one offsets batch for this flush group.
    let mut adjusted_offsets = Vec::with_capacity(num_partitions);
    let mut running = 0u64;
    for count in &batch_partition_counts {
        running += count;
        adjusted_offsets.push(global_row_count + running);
    }
    if adjusted_offsets.last().copied() != Some(global_row_count + total_rows) {
        return Err(Error::invalid_input(format!(
            "flush end offset {:?} does not equal global_row_count {} + total_rows {}",
            adjusted_offsets.last(),
            global_row_count,
            total_rows
        )));
    }
    written_offsets.retain(&adjusted_offsets)?;
    let offsets_batch = RecordBatch::try_new(
        offsets_schema,
        vec![Arc::new(UInt64Array::from(adjusted_offsets))],
    )?;
    offsets_writer.write_batch(&offsets_batch).await?;

    Ok((total_rows, batch_partition_counts))
}

// Drop the writer before releasing its scratch file, including on cancellation.
struct ShuffleWriter {
    writer: versions::v2_1::Writer,
    file: ShuffleFile,
}

#[derive(Clone)]
enum ShuffleFile {
    Path(Path),
    Spill(Arc<dyn Spill>),
}

impl ShuffleFile {
    async fn open(&self, scheduler: &Arc<ScanScheduler>) -> Result<FileScheduler> {
        match self {
            Self::Path(path) => scheduler.open_file(path, &CachedFileSize::unknown()).await,
            Self::Spill(spill) => {
                let reader = spill.reader().await?;
                Ok(scheduler.open_reader(Arc::new(ShuffleSpillReader {
                    reader,
                    spill: spill.clone(),
                })))
            }
        }
    }

    fn diagnostic_path(&self, name: &str) -> Path {
        match self {
            Self::Path(path) => path.clone(),
            Self::Spill(_) => Path::from(name),
        }
    }
}

// A FileReader and its returned streams can outlive the shuffler. Retain the
// scratch owner at the I/O boundary, including for already-submitted requests.
struct ShuffleSpillReader {
    reader: Box<dyn Reader>,
    spill: Arc<dyn Spill>,
}

impl fmt::Debug for ShuffleSpillReader {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_tuple("ShuffleSpillReader")
            .field(&self.reader)
            .finish()
    }
}

impl DeepSizeOf for ShuffleSpillReader {
    fn deep_size_of_children(&self, context: &mut Context) -> usize {
        self.reader.deep_size_of_children(context)
    }
}

impl Reader for ShuffleSpillReader {
    fn path(&self) -> &Path {
        self.reader.path()
    }

    fn block_size(&self) -> usize {
        self.reader.block_size()
    }

    fn io_parallelism(&self) -> usize {
        self.reader.io_parallelism()
    }

    fn size(&self) -> BoxFuture<'_, object_store::Result<usize>> {
        self.reader.size()
    }

    fn get_range(&self, range: Range<usize>) -> BoxFuture<'static, object_store::Result<Bytes>> {
        let read = self.reader.get_range(range);
        let spill = self.spill.clone();
        async move {
            let _spill = spill;
            read.await
        }
        .boxed()
    }

    fn get_all(&self) -> BoxFuture<'_, object_store::Result<Bytes>> {
        self.reader.get_all()
    }
}

pub struct TwoFileShuffleReader {
    scheduler: Arc<ScanScheduler>,
    file_reader: FileReader,
    num_partitions: usize,
    num_batches: usize,
    offsets: RwLock<Option<Arc<CachedShuffleOffsets>>>,
    offsets_reader: OnceCell<FileReader>,
    offsets_file: ShuffleFile,
    partition_counts: Vec<u64>,
    estimated_row_bytes: usize,
    total_loss: f64,
}

struct CachedShuffleOffsets {
    values: Vec<u64>,
    _reservation: Option<MemoryReservation>,
}

enum ShuffleOffsets {
    Preloaded(Vec<u64>),
    OnDemand(FileReader),
}

/// How the shuffle reader should obtain partition offsets.
///
/// A writer-side capacity/allocation fallback must stay on-demand through
/// reader construction. Recomputing preload eligibility from logical length
/// would retry `Vec` allocation after the writer already dropped its copy.
enum OffsetPreloadSource {
    /// Writer-side prefix sums. Allocated capacity is already bounded.
    Writer(Vec<u64>),
    ReservedWriter(Vec<u64>, MemoryReservation),
    /// Writer dropped its copy after a capacity or reservation fallback.
    ForcedOnDemand,
    /// Reopening files without a writer copy. Decide from the byte cap, but
    /// sidecar preload itself must still be fallible and capacity-checked.
    Sidecar,
}

/// Ranges of `partition_id`'s rows in the shuffle data file, one per flush
/// group that holds any.
///
/// A partition is usually absent from most groups, and a zero-length range
/// still costs the reader a range entry, so the empty ones are dropped.
fn preloaded_partition_ranges(
    offsets: &[u64],
    num_batches: usize,
    num_partitions: usize,
    partition_id: usize,
) -> Vec<Range<u64>> {
    let mut ranges = Vec::with_capacity(num_batches);
    for batch_idx in 0..num_batches {
        let end_index = batch_idx * num_partitions + partition_id;
        let start = if end_index == 0 {
            0
        } else {
            offsets[end_index - 1]
        };
        let end = offsets[end_index];
        if start < end {
            ranges.push(start..end);
        }
    }
    ranges
}

impl TwoFileShuffleReader {
    pub(super) async fn try_new(
        object_store: Arc<ObjectStore>,
        output_dir: Path,
        num_partitions: usize,
        num_batches: u64,
        partition_counts: Vec<u64>,
        total_loss: f64,
    ) -> Result<Box<dyn ShuffleReader>> {
        Self::try_new_with_preload_limit(
            object_store,
            output_dir,
            num_partitions,
            num_batches,
            partition_counts,
            total_loss,
            parse_max_preloaded_offsets_bytes(std::env::var(MAX_PRELOADED_OFFSETS_BYTES_ENV))?,
            OffsetPreloadSource::Sidecar,
        )
        .await
    }

    #[allow(clippy::too_many_arguments)]
    async fn try_new_with_preload_limit(
        object_store: Arc<ObjectStore>,
        output_dir: Path,
        num_partitions: usize,
        num_batches: u64,
        partition_counts: Vec<u64>,
        total_loss: f64,
        max_preloaded_offsets_bytes: usize,
        offset_source: OffsetPreloadSource,
    ) -> Result<Box<dyn ShuffleReader>> {
        Self::try_new_with_files(
            object_store,
            ShuffleFile::Path(output_dir.clone().join("shuffle_data.lance")),
            ShuffleFile::Path(output_dir.join("shuffle_offsets.lance")),
            num_partitions,
            num_batches,
            partition_counts,
            total_loss,
            max_preloaded_offsets_bytes,
            offset_source,
        )
        .await
    }

    #[allow(clippy::too_many_arguments)]
    async fn try_new_with_files(
        object_store: Arc<ObjectStore>,
        data_file: ShuffleFile,
        offsets_file: ShuffleFile,
        num_partitions: usize,
        num_batches: u64,
        partition_counts: Vec<u64>,
        total_loss: f64,
        max_preloaded_offsets_bytes: usize,
        offset_source: OffsetPreloadSource,
    ) -> Result<Box<dyn ShuffleReader>> {
        if num_batches == 0 {
            return Ok(Box::new(EmptyReader));
        }

        let scheduler_config = SchedulerConfig::max_bandwidth(&object_store);
        let scheduler = ScanScheduler::new(object_store, scheduler_config);

        let file_reader = FileReader::try_open(
            data_file.open(&scheduler).await?,
            None,
            Arc::<DecoderPlugins>::default(),
            &LanceCache::no_cache(),
            FileReaderOptions::default(),
        )
        .await?;

        if partition_counts.len() != num_partitions {
            return Err(Error::invalid_input(format!(
                "partition_counts has {} entries, expected num_partitions={}",
                partition_counts.len(),
                num_partitions
            )));
        }

        let num_batches = usize::try_from(num_batches).map_err(|_| {
            Error::invalid_input(format!(
                "num_batches={} cannot be represented as usize",
                num_batches
            ))
        })?;
        let expected_offsets = num_batches.checked_mul(num_partitions).ok_or_else(|| {
            Error::invalid_input(format!(
                "num_batches={} * num_partitions={} overflows usize",
                num_batches, num_partitions
            ))
        })?;
        let offsets_path = offsets_file.diagnostic_path("shuffle_offsets.lance");
        let (offset_source, mut offset_reservation) = match offset_source {
            OffsetPreloadSource::ReservedWriter(offsets, reservation) => {
                (OffsetPreloadSource::Writer(offsets), Some(reservation))
            }
            source => (source, None),
        };
        let offsets = match offset_source {
            OffsetPreloadSource::Writer(written_offsets) => {
                if written_offsets.len() != expected_offsets {
                    return Err(Error::invalid_input(format!(
                        "writer produced {} offsets, expected num_batches={} * num_partitions={} = {}",
                        written_offsets.len(),
                        num_batches,
                        num_partitions,
                        expected_offsets
                    )));
                }
                let mut validator = ShuffleOffsetsValidator::new(
                    expected_offsets,
                    num_partitions,
                    file_reader.num_rows(),
                    &partition_counts,
                    &offsets_path,
                );
                validator.push(&written_offsets)?;
                validator.finish()?;
                if should_preload_offsets(written_offsets.len(), max_preloaded_offsets_bytes)?
                    && should_preload_offsets(
                        written_offsets.capacity(),
                        max_preloaded_offsets_bytes,
                    )?
                {
                    // Prefer the prefix sums computed at flush time over a decode
                    // of the ephemeral sidecar.
                    ShuffleOffsets::Preloaded(written_offsets)
                } else {
                    // Writer-side copy exceeded the resident-memory bound. The
                    // sidecar is still on disk; validate-and-stream it on demand.
                    drop(written_offsets);
                    load_shuffle_offsets_from_file(
                        &scheduler,
                        &offsets_file,
                        expected_offsets,
                        num_batches,
                        num_partitions,
                        file_reader.num_rows(),
                        &partition_counts,
                        false,
                        max_preloaded_offsets_bytes,
                    )
                    .await?
                }
            }
            OffsetPreloadSource::ForcedOnDemand => {
                // The writer already fell back; do not recompute eligibility
                // from logical length and retry a full preload.
                load_shuffle_offsets_from_file(
                    &scheduler,
                    &offsets_file,
                    expected_offsets,
                    num_batches,
                    num_partitions,
                    file_reader.num_rows(),
                    &partition_counts,
                    false,
                    max_preloaded_offsets_bytes,
                )
                .await?
            }
            OffsetPreloadSource::ReservedWriter(..) => {
                return Err(Error::internal(
                    "reserved shuffle offsets were not normalized",
                ));
            }
            OffsetPreloadSource::Sidecar => {
                let should_preload_offsets =
                    should_preload_offsets(expected_offsets, max_preloaded_offsets_bytes)?;
                load_shuffle_offsets_from_file(
                    &scheduler,
                    &offsets_file,
                    expected_offsets,
                    num_batches,
                    num_partitions,
                    file_reader.num_rows(),
                    &partition_counts,
                    should_preload_offsets,
                    max_preloaded_offsets_bytes,
                )
                .await?
            }
        };
        let (offsets, offsets_reader) = match offsets {
            ShuffleOffsets::Preloaded(values) => (
                RwLock::new(Some(Arc::new(CachedShuffleOffsets {
                    values,
                    _reservation: offset_reservation.take(),
                }))),
                OnceCell::new(),
            ),
            ShuffleOffsets::OnDemand(reader) => {
                (RwLock::new(None), OnceCell::new_with(Some(reader)))
            }
        };
        let decoded_schema: Schema = file_reader.schema().as_ref().into();
        let estimated_row_bytes = estimate_decoded_row_bytes(&decoded_schema)?;

        Ok(Box::new(Self {
            scheduler,
            file_reader,
            num_partitions,
            num_batches,
            offsets,
            offsets_reader,
            offsets_file,
            partition_counts,
            estimated_row_bytes,
            total_loss,
        }))
    }

    fn cached_offsets(&self) -> Result<Option<Arc<CachedShuffleOffsets>>> {
        self.offsets
            .read()
            .map(|offsets| offsets.clone())
            .map_err(|_| Error::internal("IVF shuffle offsets cache lock was poisoned"))
    }

    async fn offsets_reader(&self) -> Result<&FileReader> {
        self.offsets_reader
            .get_or_try_init(|| async {
                let expected_offsets = self
                    .num_batches
                    .checked_mul(self.num_partitions)
                    .ok_or_else(|| Error::internal("IVF shuffle offset count overflows usize"))?;
                // Writer-side prefix sums bypassed sidecar decoding. Validate
                // the sidecar once before using it after cache eviction.
                match load_shuffle_offsets_from_file(
                    &self.scheduler,
                    &self.offsets_file,
                    expected_offsets,
                    self.num_batches,
                    self.num_partitions,
                    self.file_reader.num_rows(),
                    &self.partition_counts,
                    false,
                    0,
                )
                .await?
                {
                    ShuffleOffsets::OnDemand(reader) => Ok(reader),
                    ShuffleOffsets::Preloaded(_) => Err(Error::internal(
                        "IVF shuffle offsets were preloaded after cache eviction",
                    )),
                }
            })
            .await
    }

    async fn partition_ranges(&self, partition_id: usize) -> Result<Vec<Range<u64>>> {
        if partition_id >= self.num_partitions {
            return Err(Error::invalid_input(format!(
                "partition_id={} is out of range [0, {})",
                partition_id, self.num_partitions,
            )));
        }
        if let Some(offsets) = self.cached_offsets()? {
            Ok(preloaded_partition_ranges(
                &offsets.values,
                self.num_batches,
                self.num_partitions,
                partition_id,
            ))
        } else {
            self.read_partition_ranges(self.offsets_reader().await?, partition_id)
                .await
        }
    }

    async fn read_partition_ranges(
        &self,
        offsets_reader: &FileReader,
        partition_id: usize,
    ) -> Result<Vec<Range<u64>>> {
        let max_offset_values = self.num_batches.checked_mul(2).ok_or_else(|| {
            Error::invalid_input(format!(
                "num_batches={} overflows on-demand offset count",
                self.num_batches
            ))
        })?;
        let mut offset_ranges = Vec::with_capacity(max_offset_values);
        for batch_idx in 0..self.num_batches {
            let end_index = batch_idx * self.num_partitions + partition_id;
            if end_index != 0 {
                let start_index = u64::try_from(end_index - 1).map_err(|_| {
                    Error::invalid_input(format!(
                        "offset index {} cannot be represented as u64",
                        end_index - 1
                    ))
                })?;
                offset_ranges.push(start_index..start_index + 1);
            }
            let end_index = u64::try_from(end_index).map_err(|_| {
                Error::invalid_input(format!(
                    "offset index {} cannot be represented as u64",
                    end_index
                ))
            })?;
            offset_ranges.push(end_index..end_index + 1);
        }

        let mut offsets_stream = offsets_reader
            .read_stream(
                ReadBatchParams::Ranges(offset_ranges.into()),
                u32::MAX,
                1,
                FilterExpression::no_filter(),
            )
            .await?;
        let expected_values = max_offset_values - usize::from(partition_id == 0);
        let mut offsets = Vec::with_capacity(expected_values);
        while let Some(batch) = offsets_stream.try_next().await? {
            let offset_column = batch
                .column_by_name("offset")
                .and_then(|column| column.as_any().downcast_ref::<UInt64Array>())
                .ok_or_else(|| {
                    Error::corrupt_file_named(
                        "shuffle_offsets.lance",
                        "required UInt64 column 'offset' is missing from decoded batch",
                    )
                })?;
            offsets.extend_from_slice(offset_column.values());
        }
        if offsets.len() != expected_values {
            return Err(Error::corrupt_file_named(
                "shuffle_offsets.lance",
                format!(
                    "decoded {} on-demand offsets for partition {}, expected {}",
                    offsets.len(),
                    partition_id,
                    expected_values
                ),
            ));
        }

        let mut offsets = offsets.into_iter();
        let mut ranges = Vec::with_capacity(self.num_batches);
        for batch_idx in 0..self.num_batches {
            let start = if batch_idx == 0 && partition_id == 0 {
                0
            } else {
                offsets.next().ok_or_else(|| {
                    Error::corrupt_file_named(
                        "shuffle_offsets.lance",
                        format!("missing start offset for partition {}", partition_id),
                    )
                })?
            };
            let end = offsets.next().ok_or_else(|| {
                Error::corrupt_file_named(
                    "shuffle_offsets.lance",
                    format!("missing end offset for partition {}", partition_id),
                )
            })?;
            // Same as the preloaded path: skip the groups this partition has no
            // rows in rather than passing empty ranges to the reader.
            if start < end {
                ranges.push(start..end);
            }
        }
        Ok(ranges)
    }
}

#[cfg(test)]
fn validate_shuffle_offsets(
    offsets: &[u64],
    num_batches: usize,
    num_partitions: usize,
    data_rows: u64,
    partition_counts: &[u64],
    offsets_path: &Path,
) -> Result<()> {
    let expected_offsets = num_batches.checked_mul(num_partitions).ok_or_else(|| {
        Error::invalid_input(format!(
            "num_batches={} * num_partitions={} overflows usize",
            num_batches, num_partitions
        ))
    })?;
    let mut validator = ShuffleOffsetsValidator::new(
        expected_offsets,
        num_partitions,
        data_rows,
        partition_counts,
        offsets_path,
    );
    validator.push(offsets)?;
    validator.finish()
}

fn should_preload_offsets(expected_offsets: usize, max_bytes: usize) -> Result<bool> {
    let offsets_bytes = expected_offsets
        .checked_mul(std::mem::size_of::<u64>())
        .ok_or_else(|| {
            Error::invalid_input(format!(
                "expected offset count {} overflows byte-size calculation",
                expected_offsets
            ))
        })?;
    Ok(offsets_bytes <= max_bytes)
}

/// Allocate a Vec for `len` u64 offsets if both the logical size and the
/// allocated capacity fit in `max_bytes`.
///
/// Returns `None` on reservation failure or allocator rounding past the
/// ceiling so the caller can stay on-demand instead of panicking.
fn try_allocate_preloaded_offsets(len: usize, max_bytes: usize) -> Result<Option<Vec<u64>>> {
    if !should_preload_offsets(len, max_bytes)? {
        return Ok(None);
    }
    let mut offsets = Vec::new();
    if offsets.try_reserve_exact(len).is_err()
        || !should_preload_offsets(offsets.capacity(), max_bytes)?
    {
        return Ok(None);
    }
    Ok(Some(offsets))
}

/// Writer-side prefix sums kept only while their allocated `Vec` capacity
/// fits in `max_bytes`.
///
/// Once a flush would exceed the bound the in-memory copy is dropped; the
/// offsets sidecar remains the on-demand fallback. Growth uses
/// [`Vec::try_reserve_exact`] rather than amortized doubling, and the copy
/// is dropped if the allocator still rounds capacity above `max_bytes`.
struct BoundedWrittenOffsets {
    offsets: Option<Vec<u64>>,
    max_bytes: usize,
    reservation: Option<MemoryReservation>,
}

impl BoundedWrittenOffsets {
    fn new(max_bytes: usize) -> Self {
        Self {
            offsets: Some(Vec::new()),
            max_bytes,
            reservation: None,
        }
    }

    fn discard(&mut self) {
        self.offsets = None;
        self.reservation = None;
    }

    fn retain(&mut self, new_offsets: &[u64]) -> Result<()> {
        let Some(offsets) = self.offsets.as_mut() else {
            return Ok(());
        };
        let new_len = offsets
            .len()
            .checked_add(new_offsets.len())
            .ok_or_else(|| {
                Error::invalid_input(format!(
                    "written offset count {} + {} overflows usize",
                    offsets.len(),
                    new_offsets.len(),
                ))
            })?;
        if !should_preload_offsets(new_len, self.max_bytes)? {
            self.discard();
            return Ok(());
        }
        if new_len > offsets.capacity() {
            let bytes = new_len * std::mem::size_of::<u64>();
            if self
                .reservation
                .as_ref()
                .is_some_and(|reservation| reservation.try_resize(bytes).is_err())
            {
                self.discard();
                return Ok(());
            }
            if offsets.try_reserve_exact(new_offsets.len()).is_err()
                || !should_preload_offsets(offsets.capacity(), self.max_bytes)?
                || self.reservation.as_ref().is_some_and(|reservation| {
                    reservation
                        .try_resize(offsets.capacity() * std::mem::size_of::<u64>())
                        .is_err()
                })
            {
                self.discard();
                return Ok(());
            }
        }
        offsets.extend_from_slice(new_offsets);
        Ok(())
    }

    fn into_offsets(self) -> OffsetPreloadSource {
        match (self.offsets, self.reservation) {
            (Some(offsets), Some(reservation)) => {
                OffsetPreloadSource::ReservedWriter(offsets, reservation)
            }
            (Some(offsets), None) => OffsetPreloadSource::Writer(offsets),
            (None, _) => OffsetPreloadSource::ForcedOnDemand,
        }
    }
}

async fn open_shuffle_offsets_reader(
    scheduler: &Arc<ScanScheduler>,
    offsets_file: &ShuffleFile,
    expected_offsets: usize,
    num_batches: usize,
    num_partitions: usize,
) -> Result<FileReader> {
    let offsets_path = offsets_file.diagnostic_path("shuffle_offsets.lance");
    let offsets_reader = FileReader::try_open(
        offsets_file.open(scheduler).await?,
        None,
        Arc::<DecoderPlugins>::default(),
        &LanceCache::no_cache(),
        FileReaderOptions::default(),
    )
    .await?;
    let expected_offsets_u64 = u64::try_from(expected_offsets).map_err(|_| {
        Error::invalid_input(format!(
            "expected offset count {} cannot be represented as u64",
            expected_offsets
        ))
    })?;
    if offsets_reader.num_rows() != expected_offsets_u64 {
        return Err(Error::corrupt_file(
            offsets_path.clone(),
            format!(
                "offset count is {}, expected num_batches={} * num_partitions={} = {}",
                offsets_reader.num_rows(),
                num_batches,
                num_partitions,
                expected_offsets
            ),
        ));
    }
    let offsets_schema = offsets_reader.schema();
    let offset_field = offsets_schema.field("offset").ok_or_else(|| {
        Error::corrupt_file(
            offsets_path.clone(),
            "required non-null UInt64 column 'offset' is missing",
        )
    })?;
    if offset_field.data_type() != DataType::UInt64 || offset_field.nullable {
        return Err(Error::corrupt_file(
            offsets_path.clone(),
            format!(
                "column 'offset' must be non-null UInt64, found {:?} (nullable={})",
                offset_field.data_type(),
                offset_field.nullable
            ),
        ));
    }
    Ok(offsets_reader)
}

#[allow(clippy::too_many_arguments)]
async fn load_shuffle_offsets_from_file(
    scheduler: &Arc<ScanScheduler>,
    offsets_file: &ShuffleFile,
    expected_offsets: usize,
    num_batches: usize,
    num_partitions: usize,
    data_rows: u64,
    partition_counts: &[u64],
    preload: bool,
    max_preloaded_offsets_bytes: usize,
) -> Result<ShuffleOffsets> {
    let offsets_path = offsets_file.diagnostic_path("shuffle_offsets.lance");
    let offsets_reader = open_shuffle_offsets_reader(
        scheduler,
        offsets_file,
        expected_offsets,
        num_batches,
        num_partitions,
    )
    .await?;
    let mut offsets = if preload {
        try_allocate_preloaded_offsets(expected_offsets, max_preloaded_offsets_bytes)?
    } else {
        None
    };
    let mut validator = ShuffleOffsetsValidator::new(
        expected_offsets,
        num_partitions,
        data_rows,
        partition_counts,
        &offsets_path,
    );
    let mut offsets_stream = offsets_reader
        .read_stream(
            ReadBatchParams::RangeFull,
            1024 * 1024,
            16,
            FilterExpression::no_filter(),
        )
        .await?;
    while let Some(batch) = offsets_stream.try_next().await? {
        let offset_column = batch
            .column_by_name("offset")
            .and_then(|column| column.as_any().downcast_ref::<UInt64Array>())
            .ok_or_else(|| {
                Error::corrupt_file(
                    offsets_path.clone(),
                    "required UInt64 column 'offset' is missing from decoded batch",
                )
            })?;
        if offset_column.null_count() != 0 {
            return Err(Error::corrupt_file(
                offsets_path.clone(),
                format!(
                    "column 'offset' contains {} null values",
                    offset_column.null_count()
                ),
            ));
        }
        if offset_column.values().len() != offset_column.len() {
            return Err(Error::corrupt_file(
                offsets_path.clone(),
                format!(
                    "offset values buffer length {} does not match array length {}",
                    offset_column.values().len(),
                    offset_column.len()
                ),
            ));
        }
        let decoded = offset_column.values().as_ref();
        validator.push(decoded)?;
        if let Some(offsets) = offsets.as_mut() {
            offsets.extend_from_slice(decoded);
        }
    }
    validator.finish()?;
    Ok(match offsets {
        Some(offsets)
            if should_preload_offsets(offsets.capacity(), max_preloaded_offsets_bytes)? =>
        {
            ShuffleOffsets::Preloaded(offsets)
        }
        _ => ShuffleOffsets::OnDemand(offsets_reader),
    })
}

struct ShuffleOffsetsValidator<'a> {
    expected_offsets: usize,
    num_partitions: usize,
    data_rows: u64,
    partition_counts: &'a [u64],
    offsets_path: &'a Path,
    decoded_offsets: usize,
    previous_offset: u64,
    decoded_partition_counts: Vec<u64>,
}

impl<'a> ShuffleOffsetsValidator<'a> {
    fn new(
        expected_offsets: usize,
        num_partitions: usize,
        data_rows: u64,
        partition_counts: &'a [u64],
        offsets_path: &'a Path,
    ) -> Self {
        Self {
            expected_offsets,
            num_partitions,
            data_rows,
            partition_counts,
            offsets_path,
            decoded_offsets: 0,
            previous_offset: 0,
            decoded_partition_counts: vec![0; num_partitions],
        }
    }

    fn push(&mut self, offsets: &[u64]) -> Result<()> {
        for &offset in offsets {
            if self.decoded_offsets >= self.expected_offsets {
                return Err(Error::corrupt_file(
                    self.offsets_path.clone(),
                    format!(
                        "decoded more than the expected {} offsets",
                        self.expected_offsets
                    ),
                ));
            }
            if self.previous_offset > offset {
                return Err(Error::corrupt_file(
                    self.offsets_path.clone(),
                    format!(
                        "offsets are not monotonic at indices {} and {}: {} > {}",
                        self.decoded_offsets - 1,
                        self.decoded_offsets,
                        self.previous_offset,
                        offset
                    ),
                ));
            }

            let partition_id = self.decoded_offsets % self.num_partitions;
            self.decoded_partition_counts[partition_id] = self.decoded_partition_counts
                [partition_id]
                .checked_add(offset - self.previous_offset)
                .ok_or_else(|| {
                    Error::corrupt_file(
                        self.offsets_path.clone(),
                        format!("row count for partition {} overflows u64", partition_id),
                    )
                })?;
            self.previous_offset = offset;
            self.decoded_offsets += 1;
        }
        Ok(())
    }

    fn finish(self) -> Result<()> {
        if self.decoded_offsets != self.expected_offsets {
            return Err(Error::corrupt_file(
                self.offsets_path.clone(),
                format!(
                    "decoded {} offsets, expected {}",
                    self.decoded_offsets, self.expected_offsets
                ),
            ));
        }
        if self.previous_offset != self.data_rows {
            return Err(Error::corrupt_file(
                self.offsets_path.clone(),
                format!(
                    "final offset {} does not match shuffle data row count {}",
                    self.previous_offset, self.data_rows
                ),
            ));
        }
        if let Some((partition_id, (&decoded, &expected))) = self
            .decoded_partition_counts
            .iter()
            .zip(self.partition_counts)
            .enumerate()
            .find(|(_, (decoded, expected))| decoded != expected)
        {
            return Err(Error::corrupt_file(
                self.offsets_path.clone(),
                format!(
                    "offset-derived count {} for partition {} does not match expected count {}; offset-derived counts={:?} expected counts={:?}",
                    decoded,
                    partition_id,
                    expected,
                    self.decoded_partition_counts,
                    self.partition_counts
                ),
            ));
        }
        Ok(())
    }
}

/// Variable-width columns are uncommon in vector shuffle data. This fallback
/// keeps window planning bounded when one is present without claiming an exact
/// decoded size for values that have no fixed Arrow stride.
const VARIABLE_WIDTH_ROW_ESTIMATE_BYTES: usize = 64;
const WINDOW_ADMISSION_FIXED_HEADROOM_BYTES: usize = 1024 * 1024;

fn estimate_decoded_row_bytes(schema: &Schema) -> Result<usize> {
    let mut row_bytes = 0usize;
    for field in schema.fields() {
        let value_bytes = match field.data_type() {
            DataType::Boolean => 1,
            data_type => data_type
                .byte_width_opt()
                .unwrap_or(VARIABLE_WIDTH_ROW_ESTIMATE_BYTES),
        };
        row_bytes = row_bytes.checked_add(value_bytes).ok_or_else(|| {
            Error::invalid_input(format!(
                "decoded row-size estimate overflows usize at field '{}'",
                field.name()
            ))
        })?;
        if field.is_nullable() {
            // Arrow validity is bit-packed. One byte per row is deliberately
            // conservative and also covers small-buffer alignment overhead.
            row_bytes = row_bytes.checked_add(1).ok_or_else(|| {
                Error::invalid_input(format!(
                    "decoded row-size estimate overflows usize at nullable field '{}'",
                    field.name()
                ))
            })?;
        }
    }
    Ok(row_bytes.max(1))
}

fn plan_partition_window_end(
    partition_counts: &[u64],
    start_partition_id: usize,
    estimated_row_bytes: usize,
    max_decoded_bytes: usize,
) -> Result<usize> {
    if max_decoded_bytes == 0 {
        return Err(Error::invalid_input(
            "max_decoded_bytes must be greater than 0",
        ));
    }
    if start_partition_id >= partition_counts.len() {
        return Err(Error::invalid_input(format!(
            "start_partition_id={} is out of range [0, {})",
            start_partition_id,
            partition_counts.len()
        )));
    }

    let mut decoded_bytes = 0usize;
    let mut end_partition_id = start_partition_id;
    while end_partition_id < partition_counts.len() {
        let partition_rows = usize::try_from(partition_counts[end_partition_id]).map_err(|_| {
            Error::invalid_input(format!(
                "partition {} row count {} cannot be represented as usize",
                end_partition_id, partition_counts[end_partition_id]
            ))
        })?;
        let partition_bytes = partition_rows
            .checked_mul(estimated_row_bytes)
            .ok_or_else(|| {
                Error::invalid_input(format!(
                    "decoded byte estimate overflows for partition {} with {} rows at {} bytes per row",
                    end_partition_id, partition_rows, estimated_row_bytes
                ))
            })?;

        if end_partition_id > start_partition_id
            && partition_bytes > max_decoded_bytes.saturating_sub(decoded_bytes)
        {
            break;
        }
        decoded_bytes = decoded_bytes.checked_add(partition_bytes).ok_or_else(|| {
            Error::invalid_input(format!(
                "decoded window byte estimate overflows at partition {}",
                end_partition_id
            ))
        })?;
        end_partition_id += 1;

        // A partition that exceeds the budget must make progress as a
        // singleton. Otherwise stop as soon as the target has been filled.
        if decoded_bytes >= max_decoded_bytes {
            break;
        }
    }
    Ok(end_partition_id)
}

fn conservative_window_admission_bytes(
    partition_counts: &[u64],
    partition_range: Range<usize>,
    estimated_row_bytes: usize,
) -> Result<usize> {
    let rows = partition_counts[partition_range]
        .iter()
        .try_fold(0usize, |total, count| {
            let count = usize::try_from(*count).map_err(|_| {
                Error::invalid_input(format!(
                    "partition row count {} cannot be represented as usize",
                    count
                ))
            })?;
            total
                .checked_add(count)
                .ok_or_else(|| Error::invalid_input("partition window row count overflows usize"))
        })?;
    if rows == 0 {
        return Ok(0);
    }
    conservative_partition_admission_bytes(rows, estimated_row_bytes)
}

fn conservative_partition_admission_bytes(
    rows: usize,
    estimated_row_bytes: usize,
) -> Result<usize> {
    let value_bytes = rows.checked_mul(estimated_row_bytes).ok_or_else(|| {
        Error::invalid_input(format!(
            "decoded byte estimate overflows for {} rows at {} bytes per row",
            rows, estimated_row_bytes
        ))
    })?;
    // Arrow buffers and batch/array allocations add a small amount beyond the
    // fixed-width values. Reserve 25% plus fixed headroom before decoding; the
    // charge is reconciled to the allocation-backed size immediately after.
    value_bytes
        .checked_add(value_bytes / 4)
        .and_then(|bytes| bytes.checked_add(WINDOW_ADMISSION_FIXED_HEADROOM_BYTES))
        .ok_or_else(|| Error::invalid_input("partition window admission estimate overflows usize"))
}

type PartitionWindowReadPlan = (Vec<Range<u64>>, Vec<Vec<usize>>);

fn preloaded_window_ranges(
    offsets: &[u64],
    num_batches: usize,
    num_partitions: usize,
    partition_range: Range<usize>,
) -> Result<PartitionWindowReadPlan> {
    let window_len = partition_range.end - partition_range.start;
    let mut ranges = Vec::with_capacity(num_batches);
    let mut group_partition_counts = Vec::with_capacity(num_batches);

    for batch_idx in 0..num_batches {
        let group_base = batch_idx * num_partitions;
        let range_start_index = group_base + partition_range.start;
        let range_start = if range_start_index == 0 {
            0
        } else {
            offsets[range_start_index - 1]
        };
        let range_end = offsets[group_base + partition_range.end - 1];
        if range_start == range_end {
            continue;
        }

        let mut counts = Vec::with_capacity(window_len);
        let mut previous = range_start;
        for partition_id in partition_range.clone() {
            let end = offsets[group_base + partition_id];
            let count = usize::try_from(end - previous).map_err(|_| {
                Error::corrupt_file_named(
                    "shuffle_offsets.lance",
                    format!(
                        "row count {} for flush group {} partition {} cannot be represented as usize",
                        end - previous,
                        batch_idx,
                        partition_id
                    ),
                )
            })?;
            counts.push(count);
            previous = end;
        }
        ranges.push(range_start..range_end);
        group_partition_counts.push(counts);
    }
    Ok((ranges, group_partition_counts))
}

async fn split_partition_window_stream<S>(
    mut stream: S,
    window_len: usize,
    group_partition_counts: &[Vec<usize>],
) -> Result<(Vec<Vec<RecordBatch>>, usize)>
where
    S: Stream<Item = Result<RecordBatch>> + Unpin,
{
    let expected_rows = group_partition_counts
        .iter()
        .flatten()
        .try_fold(0usize, |total, count| total.checked_add(*count))
        .ok_or_else(|| {
            Error::corrupt_file_named("shuffle_data.lance", "window row count overflows usize")
        })?;
    let mut segments = group_partition_counts
        .iter()
        .flat_map(|counts| counts.iter().copied().enumerate())
        .filter(|(_, count)| *count != 0);
    let mut current_segment = segments.next();
    let mut segment_rows_read = 0usize;
    let mut actual_rows = 0usize;
    let mut materialized_decoded_bytes = 0usize;
    let mut partition_batches = vec![Vec::new(); window_len];

    while let Some(batch) = stream.try_next().await? {
        materialized_decoded_bytes =
            batch
                .columns()
                .iter()
                .try_fold(materialized_decoded_bytes, |total, array| {
                    total
                        .checked_add(array.get_array_memory_size())
                        .ok_or_else(|| {
                            Error::internal("decoded partition window byte count overflows usize")
                        })
                })?;
        let mut batch_offset = 0usize;
        while batch_offset < batch.num_rows() {
            let Some((partition_offset, segment_rows)) = current_segment else {
                return Err(Error::corrupt_file_named(
                    "shuffle_data.lance",
                    format!(
                        "decoded more than the expected {} rows for partition window",
                        expected_rows
                    ),
                ));
            };
            let remaining_in_segment = segment_rows - segment_rows_read;
            let rows_to_take = remaining_in_segment.min(batch.num_rows() - batch_offset);
            partition_batches[partition_offset].push(batch.slice(batch_offset, rows_to_take));
            batch_offset += rows_to_take;
            actual_rows = actual_rows.checked_add(rows_to_take).ok_or_else(|| {
                Error::corrupt_file_named(
                    "shuffle_data.lance",
                    "decoded window row count overflows usize",
                )
            })?;
            segment_rows_read += rows_to_take;
            if segment_rows_read == segment_rows {
                current_segment = segments.next();
                segment_rows_read = 0;
            }
        }
    }

    if current_segment.is_some() {
        return Err(Error::corrupt_file_named(
            "shuffle_data.lance",
            format!(
                "decoded {} rows for partition window, expected {}",
                actual_rows, expected_rows
            ),
        ));
    }
    Ok((partition_batches, materialized_decoded_bytes))
}

#[async_trait::async_trait]
impl ShuffleReader for TwoFileShuffleReader {
    async fn read_partition(
        &self,
        partition_id: usize,
    ) -> Result<Option<Box<dyn RecordBatchStream + Unpin + 'static>>> {
        if partition_id >= self.num_partitions {
            return Ok(None);
        }
        if self.partition_counts[partition_id] == 0 {
            return Ok(None);
        }

        let ranges = self.partition_ranges(partition_id).await?;
        if ranges.is_empty() {
            return Ok(None);
        }

        let schema: Schema = self.file_reader.schema().as_ref().into();
        let stream = self
            .file_reader
            .read_stream(
                ReadBatchParams::Ranges(ranges.into()),
                u32::MAX,
                16,
                FilterExpression::no_filter(),
            )
            .await?;
        Ok(Some(Box::new(RecordBatchStreamAdapter::new(
            Arc::new(schema),
            stream,
        ))))
    }

    fn plan_partition_window(
        &self,
        start_partition_id: usize,
        max_decoded_bytes: usize,
    ) -> Result<ShufflePartitionWindowPlan> {
        if start_partition_id >= self.num_partitions {
            return Err(Error::invalid_input(format!(
                "start_partition_id={} is out of range [0, {})",
                start_partition_id, self.num_partitions
            )));
        }
        let end_partition_id = plan_partition_window_end(
            &self.partition_counts,
            start_partition_id,
            self.estimated_row_bytes,
            max_decoded_bytes,
        )?;
        let partition_range = start_partition_id..end_partition_id;
        let estimated_decoded_bytes = conservative_window_admission_bytes(
            &self.partition_counts,
            partition_range.clone(),
            self.estimated_row_bytes,
        )?;
        Ok(ShufflePartitionWindowPlan {
            partition_range,
            estimated_decoded_bytes,
        })
    }

    async fn read_partition_window(
        &self,
        start_partition_id: usize,
        max_decoded_bytes: usize,
    ) -> Result<ShufflePartitionWindow> {
        if max_decoded_bytes == 0 {
            return Err(Error::invalid_input(
                "max_decoded_bytes must be greater than 0",
            ));
        }

        // Planning uses only partition counts, so eviction between planning
        // and reading cannot change the admitted range.
        let partition_range = self
            .plan_partition_window(start_partition_id, max_decoded_bytes)?
            .partition_range;
        let Some(offsets) = self.cached_offsets()? else {
            let mut partitions = Vec::with_capacity(partition_range.len());
            for partition_id in partition_range.clone() {
                partitions.push(ShufflePartition {
                    partition_id,
                    data: self.read_partition(partition_id).await?,
                });
            }
            return Ok(ShufflePartitionWindow {
                partition_range,
                partitions,
                materialized_decoded_bytes: None,
            });
        };
        let (ranges, group_partition_counts) = preloaded_window_ranges(
            &offsets.values,
            self.num_batches,
            self.num_partitions,
            partition_range.clone(),
        )?;
        let schema: Schema = self.file_reader.schema().as_ref().into();
        let schema = Arc::new(schema);

        let (partition_batches, materialized_decoded_bytes) = if ranges.is_empty() {
            (vec![Vec::new(); partition_range.len()], 0)
        } else {
            let stream = self
                .file_reader
                .read_stream(
                    ReadBatchParams::Ranges(ranges.into()),
                    u32::MAX,
                    16,
                    FilterExpression::no_filter(),
                )
                .await?;
            split_partition_window_stream(stream, partition_range.len(), &group_partition_counts)
                .await?
        };

        let partitions = partition_range
            .clone()
            .zip(partition_batches)
            .map(|(partition_id, batches)| {
                let data = if batches.is_empty() {
                    None
                } else {
                    let stream = futures::stream::iter(batches.into_iter().map(Ok));
                    Some(
                        Box::new(RecordBatchStreamAdapter::new(schema.clone(), stream))
                            as Box<dyn RecordBatchStream + Unpin + 'static>,
                    )
                };
                ShufflePartition { partition_id, data }
            })
            .collect();

        Ok(ShufflePartitionWindow {
            partition_range,
            partitions,
            materialized_decoded_bytes: Some(materialized_decoded_bytes),
        })
    }

    async fn release_optional_memory(&self) -> Result<()> {
        let cached = self
            .offsets
            .write()
            .map_err(|_| Error::internal("IVF shuffle offsets cache lock was poisoned"))?
            .take();
        drop(cached);
        Ok(())
    }

    fn partition_size(&self, partition_id: usize) -> Result<usize> {
        Ok(self
            .partition_counts
            .get(partition_id)
            .copied()
            .unwrap_or(0) as usize)
    }

    fn total_loss(&self) -> Option<f64> {
        Some(self.total_loss)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    use arrow_array::{FixedSizeListArray, Float32Array, Int32Array, RecordBatch, UInt32Array};
    use arrow_schema::{DataType, Field, Schema as ArrowSchema};
    use datafusion::execution::memory_pool::{
        FairSpillPool, GreedyMemoryPool, UnboundedMemoryPool,
    };
    use futures::stream;
    use lance_arrow::{FixedSizeListArrayExt, RecordBatchExt};
    use lance_core::utils::tempfile::TempStrDir;
    use lance_io::{
        spill::LocalSpillStore, stream::RecordBatchStreamAdapter, traits::Writer as ObjectWriter,
    };
    use std::sync::atomic::{AtomicUsize, Ordering};
    use tokio::io::AsyncWriteExt;

    use crate::vector::{LOSS_METADATA_KEY, PART_ID_COLUMN};

    /// Create a test batch with partition IDs, an int column, and optional loss metadata.
    fn make_batch(part_ids: &[u32], values: &[i32], loss: Option<f64>) -> RecordBatch {
        let schema = Arc::new(ArrowSchema::new(vec![
            Field::new(PART_ID_COLUMN, DataType::UInt32, false),
            Field::new("val", DataType::Int32, false),
        ]));
        let batch = RecordBatch::try_new(
            schema,
            vec![
                Arc::new(UInt32Array::from(part_ids.to_vec())),
                Arc::new(Int32Array::from(values.to_vec())),
            ],
        )
        .unwrap();
        if let Some(loss_val) = loss {
            batch
                .add_metadata(LOSS_METADATA_KEY.to_owned(), loss_val.to_string())
                .unwrap()
        } else {
            batch
        }
    }

    fn batches_to_stream(
        batches: Vec<RecordBatch>,
    ) -> Box<dyn RecordBatchStream + Unpin + 'static> {
        let schema = batches[0].schema();
        let stream = stream::iter(batches.into_iter().map(Ok));
        Box::new(RecordBatchStreamAdapter::new(schema, stream))
    }

    /// Collect all rows from a partition into a single RecordBatch.
    async fn collect_partition(
        reader: &dyn ShuffleReader,
        partition_id: usize,
    ) -> Option<RecordBatch> {
        let stream = reader.read_partition(partition_id).await.unwrap()?;
        let batches: Vec<RecordBatch> = stream.try_collect().await.unwrap();
        if batches.is_empty() {
            return None;
        }
        Some(arrow::compute::concat_batches(&batches[0].schema(), &batches).unwrap())
    }

    async fn collect_values(mut stream: Box<dyn RecordBatchStream + Unpin + 'static>) -> Vec<i32> {
        let mut values = Vec::new();
        while let Some(batch) = stream.try_next().await.unwrap() {
            let batch_values: &Int32Array = batch["val"].as_primitive();
            values.extend_from_slice(batch_values.values());
        }
        values
    }

    struct TrackingSpillStore {
        store: Arc<ObjectStore>,
        created: AtomicUsize,
        live: Arc<AtomicUsize>,
    }

    impl TrackingSpillStore {
        fn new() -> Self {
            Self {
                store: Arc::new(ObjectStore::memory()),
                created: AtomicUsize::new(0),
                live: Arc::new(AtomicUsize::new(0)),
            }
        }
    }

    struct TrackingSpill {
        store: Arc<ObjectStore>,
        path: Path,
        live: Arc<AtomicUsize>,
    }

    #[async_trait::async_trait]
    impl Spill for TrackingSpill {
        async fn reader(&self) -> Result<Box<dyn Reader>> {
            self.store.open(&self.path).await
        }
    }

    impl Drop for TrackingSpill {
        fn drop(&mut self) {
            self.live.fetch_sub(1, Ordering::SeqCst);
        }
    }

    #[async_trait::async_trait]
    impl SpillStore for TrackingSpillStore {
        async fn new_spill(&self) -> Result<(Box<dyn ObjectWriter>, Box<dyn Spill>)> {
            let id = self.created.fetch_add(1, Ordering::SeqCst);
            let path = Path::from(format!("spill_{id}"));
            let writer = self.store.create(&path).await?;
            self.live.fetch_add(1, Ordering::SeqCst);
            Ok((
                writer,
                Box::new(TrackingSpill {
                    store: self.store.clone(),
                    path,
                    live: self.live.clone(),
                }),
            ))
        }
    }

    #[derive(Debug)]
    struct PeakMemoryPool {
        inner: Arc<dyn MemoryPool>,
        peak: AtomicUsize,
        report_unknown_limit: bool,
    }

    impl fmt::Display for PeakMemoryPool {
        fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
            fmt::Display::fmt(self.inner.as_ref(), formatter)
        }
    }

    impl MemoryPool for PeakMemoryPool {
        fn name(&self) -> &str {
            "shuffle-test"
        }
        fn register(&self, consumer: &MemoryConsumer) {
            self.inner.register(consumer);
        }
        fn unregister(&self, consumer: &MemoryConsumer) {
            self.inner.unregister(consumer);
        }
        fn grow(&self, _: &MemoryReservation, _: usize) {
            panic!("shuffle must not bypass the pool through infallible grow");
        }
        fn shrink(&self, reservation: &MemoryReservation, size: usize) {
            self.inner.shrink(reservation, size);
        }
        fn try_grow(
            &self,
            reservation: &MemoryReservation,
            size: usize,
        ) -> datafusion::common::Result<()> {
            self.inner.try_grow(reservation, size)?;
            self.peak.fetch_max(self.inner.reserved(), Ordering::SeqCst);
            Ok(())
        }
        fn reserved(&self) -> usize {
            self.inner.reserved()
        }
        fn memory_limit(&self) -> MemoryLimit {
            if self.report_unknown_limit {
                MemoryLimit::Unknown
            } else {
                self.inner.memory_limit()
            }
        }
    }

    #[derive(Debug, Default)]
    struct ShuffleFlushCount(AtomicUsize);

    #[async_trait::async_trait]
    impl crate::progress::IndexBuildProgress for ShuffleFlushCount {
        async fn stage_start(&self, _: &str, _: Option<u64>, _: &str) -> Result<()> {
            Ok(())
        }
        async fn stage_progress(&self, stage: &str, _: u64) -> Result<()> {
            assert_eq!(stage, "shuffle");
            self.0.fetch_add(1, Ordering::SeqCst);
            Ok(())
        }
        async fn stage_complete(&self, _: &str) -> Result<()> {
            Ok(())
        }
    }

    fn memory_test_batch() -> RecordBatch {
        make_batch(
            &(0..32).map(|row| row % 2).collect::<Vec<_>>(),
            &(0..32).collect::<Vec<_>>(),
            None,
        )
    }

    #[test]
    fn test_shuffle_memory_large_pool_sets_larger_batch_target() {
        let shuffler = TwoFileShuffler::new(Path::from("unused"), 2)
            .with_batch_size_bytes(DEFAULT_SHUFFLE_BATCH_BYTES)
            .with_memory_pool(Arc::new(GreedyMemoryPool::new(1024 * 1024 * 1024)));
        assert_eq!(shuffler.batch_target_bytes(), 512 * 1024 * 1024);
    }

    #[rstest::rstest]
    #[case::greedy(false, false)]
    #[case::unknown(false, true)]
    #[case::fair(true, false)]
    #[tokio::test]
    async fn test_shuffle_memory_budget_controls_flushes(
        #[case] fair: bool,
        #[case] unknown: bool,
    ) {
        let minimum = shuffle_batch_memory_charge(&memory_test_batch(), 2, true).unwrap();
        let mut flush_counts = Vec::new();
        for limit in [minimum + 64, minimum * 16] {
            let inner: Arc<dyn MemoryPool> = if fair {
                Arc::new(FairSpillPool::new(limit))
            } else {
                Arc::new(GreedyMemoryPool::new(limit))
            };
            let pool = Arc::new(PeakMemoryPool {
                inner,
                peak: AtomicUsize::new(0),
                report_unknown_limit: unknown,
            });
            let progress = Arc::new(ShuffleFlushCount::default());
            let shuffler = TwoFileShuffler::new(Path::from("unused"), 2)
                .with_spill_store(Arc::new(TrackingSpillStore::new()))
                .with_memory_pool(pool.clone())
                .with_progress(progress.clone());
            let reader = shuffler
                .shuffle(batches_to_stream(
                    (0..4).map(|_| memory_test_batch()).collect(),
                ))
                .await
                .unwrap();
            assert_eq!(reader.partition_size(0).unwrap(), 64);
            assert_eq!(reader.partition_size(1).unwrap(), 64);
            let values = collect_values(reader.read_partition(1).await.unwrap().unwrap()).await;
            assert_eq!(
                values,
                (0..4).flat_map(|_| (1..32).step_by(2)).collect::<Vec<_>>()
            );
            assert!(pool.peak.load(Ordering::SeqCst) >= minimum);
            assert!(pool.peak.load(Ordering::SeqCst) <= limit);
            // Only the bounded optional offset cache can remain after writing.
            assert!(pool.reserved() <= if unknown { 256 * 1024 } else { limit / 16 });
            drop(reader);
            assert_eq!(pool.reserved(), 0);
            flush_counts.push(progress.0.load(Ordering::SeqCst));
        }
        assert!(
            flush_counts[0] > flush_counts[1],
            "small and large budgets: {flush_counts:?}"
        );
    }

    #[tokio::test]
    async fn test_shuffle_offset_eviction_releases_pool_and_preserves_window() {
        let limit = 1024 * 1024;
        let pool: Arc<dyn MemoryPool> = Arc::new(GreedyMemoryPool::new(limit));
        let shuffler = TwoFileShuffler::new(Path::from("unused"), 2)
            .with_spill_store(Arc::new(TrackingSpillStore::new()))
            .with_memory_pool(pool.clone());
        let reader = shuffler
            .shuffle(batches_to_stream(vec![memory_test_batch()]))
            .await
            .unwrap();
        let plan = reader
            .plan_partition_window(0, DEFAULT_PARTITION_WINDOW_BYTES)
            .unwrap();
        assert_eq!(plan.partition_range, 0..2);
        assert!(pool.reserved() > 0);
        let partition_memory = MemoryConsumer::new("next partition").register(&pool);
        assert!(partition_memory.try_grow(limit).is_err());
        reader.release_optional_memory().await.unwrap();
        assert_eq!(pool.reserved(), 0);
        partition_memory.try_grow(limit).unwrap();
        let window = reader
            .read_partition_window(0, DEFAULT_PARTITION_WINDOW_BYTES)
            .await
            .unwrap();
        assert_eq!(window.partition_range, plan.partition_range);
        assert!(window.materialized_decoded_bytes.is_none());
        for partition in window.partitions {
            let expected = (partition.partition_id as i32..32)
                .step_by(2)
                .collect::<Vec<_>>();
            assert_eq!(collect_values(partition.data.unwrap()).await, expected);
        }
        reader.release_optional_memory().await.unwrap();
        assert_eq!(pool.reserved(), limit);
        drop(partition_memory);
        drop(reader);
        assert_eq!(pool.reserved(), 0);
    }

    #[tokio::test]
    async fn test_shuffle_flushes_near_limit_batch_before_polling_lookahead() {
        let vectors =
            FixedSizeListArray::try_new_from_values(Float32Array::from(vec![1.0; 8 * 256]), 256)
                .unwrap();
        let batch = make_batch(&[0, 1, 0, 1, 0, 1, 0, 1], &[0, 1, 2, 3, 4, 5, 6, 7], None)
            .try_with_column(
                Field::new("vector", vectors.data_type().clone(), false),
                Arc::new(vectors),
            )
            .unwrap();
        let minimum = shuffle_batch_memory_charge(&batch, 2, true).unwrap();
        let pool: Arc<dyn MemoryPool> = Arc::new(GreedyMemoryPool::new(minimum + 64));
        let check_pool = pool.clone();
        let schema = batch.schema();
        let input = stream::iter([Ok(batch.clone()), Ok(batch)])
            .enumerate()
            .map(move |(index, batch)| {
                if index == 1 {
                    // Only one flush group's cached offsets remain when the next
                    // caller-owned input is requested. No input-memory peak is
                    // inferred from the reservation counter.
                    assert!(check_pool.reserved() <= 2 * std::mem::size_of::<u64>());
                }
                batch
            });
        let shuffler = TwoFileShuffler::new(Path::from("unused"), 2)
            .with_spill_store(Arc::new(TrackingSpillStore::new()))
            .with_memory_pool(pool.clone());
        let reader = shuffler
            .shuffle(Box::new(RecordBatchStreamAdapter::new(schema, input)))
            .await
            .unwrap();
        assert_eq!(reader.partition_size(0).unwrap(), 8);
        assert_eq!(reader.partition_size(1).unwrap(), 8);
        drop(reader);
        assert_eq!(pool.reserved(), 0);
    }

    #[tokio::test]
    async fn test_shuffle_memory_respects_external_pressure() {
        let minimum = shuffle_batch_memory_charge(&memory_test_batch(), 2, true).unwrap();
        let limit = minimum * 4;
        let pool: Arc<dyn MemoryPool> = Arc::new(GreedyMemoryPool::new(limit));
        let external = MemoryConsumer::new("another operation").register(&pool);
        let external_bytes = limit - minimum - 64;
        external.try_grow(external_bytes).unwrap();
        let shuffler = TwoFileShuffler::new(Path::from("unused"), 2)
            .with_spill_store(Arc::new(TrackingSpillStore::new()))
            .with_memory_pool(pool.clone());
        let reader = shuffler
            .shuffle(batches_to_stream(
                (0..3).map(|_| memory_test_batch()).collect(),
            ))
            .await
            .unwrap();
        assert_eq!(reader.partition_size(0).unwrap(), 48);
        assert_eq!(reader.partition_size(1).unwrap(), 48);
        drop(reader);
        assert_eq!(pool.reserved(), external_bytes);
        drop(external);
        assert_eq!(pool.reserved(), 0);
    }

    #[tokio::test]
    async fn test_shuffle_memory_rejects_oversized_backing_allocation() {
        let batch = memory_test_batch().slice(0, 1);
        let minimum = shuffle_batch_memory_charge(&batch, 2, true).unwrap();
        let pool: Arc<dyn MemoryPool> = Arc::new(GreedyMemoryPool::new(minimum - 1));
        let spill_store = Arc::new(TrackingSpillStore::new());
        let shuffler = TwoFileShuffler::new(Path::from("unused"), 2)
            .with_spill_store(spill_store.clone())
            .with_memory_pool(pool.clone());
        let error = shuffler
            .shuffle(batches_to_stream(vec![batch]))
            .await
            .err()
            .unwrap();
        assert!(matches!(error, Error::Execution { .. }));
        assert!(error.to_string().contains("IVF shuffle memory"));
        assert!(error.to_string().contains("1 rows"));
        assert_eq!(pool.reserved(), 0);
        assert_eq!(spill_store.live.load(Ordering::SeqCst), 0);
    }

    #[tokio::test]
    async fn test_shuffle_memory_unbounded_pool_is_tracked() {
        let pool = Arc::new(PeakMemoryPool {
            inner: Arc::new(UnboundedMemoryPool::default()),
            peak: AtomicUsize::new(0),
            report_unknown_limit: false,
        });
        let shuffler = TwoFileShuffler::new(Path::from("unused"), 2)
            .with_spill_store(Arc::new(TrackingSpillStore::new()))
            .with_memory_pool(pool.clone());
        let reader = shuffler
            .shuffle(batches_to_stream(vec![memory_test_batch()]))
            .await
            .unwrap();
        assert!(pool.peak.load(Ordering::SeqCst) > 0);
        drop(reader);
        assert_eq!(pool.reserved(), 0);
    }

    #[tokio::test]
    async fn test_shuffle_memory_released_on_cancellation() {
        let pool: Arc<dyn MemoryPool> = Arc::new(GreedyMemoryPool::new(1024 * 1024));
        let spill_store = Arc::new(TrackingSpillStore::new());
        let shuffler = TwoFileShuffler::new(Path::from("unused"), 2)
            .with_spill_store(spill_store.clone())
            .with_memory_pool(pool.clone());
        let batch = memory_test_batch();
        let schema = batch.schema();
        let (polled, reached_input) = tokio::sync::oneshot::channel();
        let input = stream::iter([Ok(batch)])
            .chain(stream::once(async move {
                polled.send(()).unwrap();
                futures::future::pending::<Result<RecordBatch>>().await
            }))
            .boxed();
        let mut shuffle =
            Box::pin(shuffler.shuffle(Box::new(RecordBatchStreamAdapter::new(schema, input))));
        tokio::select! {
            _ = reached_input => {},
            _ = &mut shuffle => panic!("shuffle should wait for more input"),
        }
        assert!(pool.reserved() > 0);
        drop(shuffle);
        assert_eq!(pool.reserved(), 0);
        assert_eq!(spill_store.live.load(Ordering::SeqCst), 0);
    }

    #[rstest::rstest]
    #[case::preloaded(DEFAULT_MAX_PRELOADED_OFFSETS_BYTES, 2)]
    #[case::on_demand(0, 2)]
    #[tokio::test]
    async fn test_two_file_spill_round_trip_and_stream_lifetime(
        #[case] preload_limit: usize,
        #[case] retained_files: usize,
    ) {
        let spill_store = Arc::new(TrackingSpillStore::new());
        let dir = TempStrDir::default();
        let shuffler = TwoFileShuffler::new(Path::from(dir.as_ref()), 3)
            .with_spill_store(spill_store.clone())
            .with_batch_size_bytes(1);
        let reader = shuffler
            .shuffle_with_preload_limit(
                batches_to_stream(vec![
                    make_batch(&[0, 1, 2], &[10, 20, 30], Some(1.5)),
                    make_batch(&[1, 0], &[40, 50], Some(2.5)),
                ]),
                preload_limit,
            )
            .await
            .unwrap();
        assert_eq!(spill_store.created.load(Ordering::SeqCst), 4);
        // Metadata sidecars have already been replayed and reclaimed.
        assert_eq!(spill_store.live.load(Ordering::SeqCst), retained_files);
        assert_eq!(std::fs::read_dir(dir.as_ref()).unwrap().count(), 0);
        assert_eq!(reader.total_loss(), Some(4.0));
        assert_eq!(reader.partition_size(0).unwrap(), 2);
        assert_eq!(reader.partition_size(1).unwrap(), 2);
        assert_eq!(reader.partition_size(2).unwrap(), 1);
        assert_eq!(
            collect_values(reader.read_partition(0).await.unwrap().unwrap()).await,
            vec![10, 50]
        );
        assert_eq!(
            collect_values(reader.read_partition(2).await.unwrap().unwrap()).await,
            vec![30]
        );
        let partition = reader.read_partition(1).await.unwrap().unwrap();
        drop(reader);
        drop(shuffler);
        // Only data is needed after partition ranges have been resolved.
        assert_eq!(spill_store.live.load(Ordering::SeqCst), 1);
        assert_eq!(collect_values(partition).await, vec![20, 40]);
        assert_eq!(spill_store.live.load(Ordering::SeqCst), 0);
    }

    #[tokio::test]
    async fn test_two_file_spill_reclaims_files_on_input_error() {
        let spill_store = Arc::new(TrackingSpillStore::new());
        let shuffler =
            TwoFileShuffler::new(Path::from("unused"), 2).with_spill_store(spill_store.clone());
        let batch = make_batch(&[0, 1], &[10, 20], None);
        let input = RecordBatchStreamAdapter::new(
            batch.schema(),
            stream::iter([
                Ok(batch),
                Err(Error::invalid_input("injected shuffle source failure")),
            ]),
        );
        let error = shuffler.shuffle(Box::new(input)).await.err().unwrap();
        assert!(matches!(error, Error::InvalidInput { .. }));
        assert!(
            error
                .to_string()
                .contains("injected shuffle source failure")
        );
        assert_eq!(spill_store.created.load(Ordering::SeqCst), 2);
        assert_eq!(spill_store.live.load(Ordering::SeqCst), 0);
    }

    #[tokio::test]
    async fn test_two_file_spill_reclaims_files_on_cancellation() {
        let spill_store = Arc::new(TrackingSpillStore::new());
        let shuffler =
            TwoFileShuffler::new(Path::from("unused"), 2).with_spill_store(spill_store.clone());
        let batch = make_batch(&[0, 1], &[10, 20], None);
        let (polled, reached_input) = tokio::sync::oneshot::channel();
        let schema = batch.schema();
        let input = stream::once(async move {
            polled.send(()).unwrap();
            futures::future::pending::<Result<RecordBatch>>().await
        })
        .boxed();
        let mut shuffle =
            Box::pin(shuffler.shuffle(Box::new(RecordBatchStreamAdapter::new(schema, input))));
        tokio::select! {
            _ = reached_input => {},
            _ = &mut shuffle => panic!("shuffle should wait for input"),
        }
        assert_eq!(spill_store.live.load(Ordering::SeqCst), 2);
        drop(shuffle);
        assert_eq!(spill_store.live.load(Ordering::SeqCst), 0);
    }

    #[tokio::test]
    async fn test_two_file_spill_disk_cap_is_typed_and_reusable() {
        let spill_store = Arc::new(LocalSpillStore::with_cap(16).unwrap());
        let shuffler =
            TwoFileShuffler::new(Path::from("unused"), 1).with_spill_store(spill_store.clone());
        for _ in 0..2 {
            let error = shuffler
                .shuffle(batches_to_stream(vec![make_batch(&[0], &[10], None)]))
                .await
                .err()
                .unwrap();
            assert!(matches!(
                error,
                Error::DiskCapExceeded { cap_bytes: 16, .. }
            ));
            assert!(error.to_string().contains("16"));
            // A failed build must return every byte to the shared session cap.
            let (mut writer, spill) = spill_store.new_spill().await.unwrap();
            writer.write_all(&[0; 16]).await.unwrap();
            ObjectWriter::shutdown(writer.as_mut()).await.unwrap();
            drop(writer);
            drop(spill);
        }
    }

    #[tokio::test]
    async fn test_two_file_shuffler_round_trip() {
        let dir = TempStrDir::default();
        let output_dir = Path::from(dir.as_ref());
        let num_partitions = 3;

        // Partition 0: rows with values 10, 40
        // Partition 1: rows with values 20, 50
        // Partition 2: rows with values 30
        let batch = make_batch(&[0, 1, 2, 0, 1], &[10, 20, 30, 40, 50], None);

        let shuffler = TwoFileShuffler::new(output_dir.clone(), num_partitions);
        let stream = batches_to_stream(vec![batch]);
        let reader = shuffler.shuffle(stream).await.unwrap();

        let object_store = Arc::new(ObjectStore::local());
        let scheduler = ScanScheduler::new(
            object_store.clone(),
            SchedulerConfig::max_bandwidth(&object_store),
        );
        for filename in ["shuffle_data.lance", "shuffle_offsets.lance"] {
            let file_reader = FileReader::try_open(
                scheduler
                    .open_file(
                        &output_dir.clone().join(filename),
                        &CachedFileSize::unknown(),
                    )
                    .await
                    .unwrap(),
                None,
                Arc::<DecoderPlugins>::default(),
                &LanceCache::no_cache(),
                FileReaderOptions::default(),
            )
            .await
            .unwrap();
            assert_eq!(file_reader.version(), ConcreteFileVersion::V2_1);
        }

        // Verify partition sizes
        assert_eq!(reader.partition_size(0).unwrap(), 2);
        assert_eq!(reader.partition_size(1).unwrap(), 2);
        assert_eq!(reader.partition_size(2).unwrap(), 1);

        // Verify partition 0 data
        let p0 = collect_partition(reader.as_ref(), 0).await.unwrap();
        let vals: &Int32Array = p0.column_by_name("val").unwrap().as_primitive();
        let mut v: Vec<i32> = vals.iter().map(|x| x.unwrap()).collect();
        v.sort();
        assert_eq!(v, vec![10, 40]);

        // Verify partition 1 data
        let p1 = collect_partition(reader.as_ref(), 1).await.unwrap();
        let vals: &Int32Array = p1.column_by_name("val").unwrap().as_primitive();
        let mut v: Vec<i32> = vals.iter().map(|x| x.unwrap()).collect();
        v.sort();
        assert_eq!(v, vec![20, 50]);

        // Verify partition 2 data
        let p2 = collect_partition(reader.as_ref(), 2).await.unwrap();
        let vals: &Int32Array = p2.column_by_name("val").unwrap().as_primitive();
        let v: Vec<i32> = vals.iter().map(|x| x.unwrap()).collect();
        assert_eq!(v, vec![30]);

        // Out of range partition returns None
        assert!(reader.read_partition(3).await.unwrap().is_none());
    }

    #[tokio::test]
    async fn test_two_file_shuffler_empty_first_batch() {
        let dir = TempStrDir::default();
        let output_dir = Path::from(dir.as_ref());
        let empty_batch = make_batch(&[], &[], None);
        let data_batch = make_batch(&[1, 0, 1], &[10, 20, 30], None);

        let shuffler = TwoFileShuffler::new(output_dir, 2);
        let stream = batches_to_stream(vec![empty_batch, data_batch]);
        let reader = shuffler.shuffle(stream).await.unwrap();

        assert_eq!(reader.partition_size(0).unwrap(), 1);
        assert_eq!(reader.partition_size(1).unwrap(), 2);

        let expected_schema = ArrowSchema::new(vec![Field::new("val", DataType::Int32, false)]);
        let p0 = collect_partition(reader.as_ref(), 0).await.unwrap();
        assert_eq!(p0.schema().as_ref(), &expected_schema);
        let p0_values: &Int32Array = p0["val"].as_primitive();
        assert_eq!(p0_values.values(), &[20]);

        let p1 = collect_partition(reader.as_ref(), 1).await.unwrap();
        assert_eq!(p1.schema().as_ref(), &expected_schema);
        let p1_values: &Int32Array = p1["val"].as_primitive();
        assert_eq!(p1_values.values(), &[10, 30]);
    }

    #[tokio::test]
    async fn test_two_file_shuffler_empty_partitions() {
        let dir = TempStrDir::default();
        let output_dir = Path::from(dir.as_ref());
        let num_partitions = 5;

        // Only use partitions 0 and 3, leaving 1, 2, 4 empty
        let batch = make_batch(&[0, 3, 0, 3], &[10, 20, 30, 40], None);

        let shuffler = TwoFileShuffler::new(output_dir, num_partitions);
        let stream = batches_to_stream(vec![batch]);
        let reader = shuffler.shuffle(stream).await.unwrap();

        assert_eq!(reader.partition_size(0).unwrap(), 2);
        assert_eq!(reader.partition_size(1).unwrap(), 0);
        assert_eq!(reader.partition_size(2).unwrap(), 0);
        assert_eq!(reader.partition_size(3).unwrap(), 2);
        assert_eq!(reader.partition_size(4).unwrap(), 0);

        assert!(reader.read_partition(1).await.unwrap().is_none());
        assert!(reader.read_partition(2).await.unwrap().is_none());
        assert!(reader.read_partition(4).await.unwrap().is_none());

        let p0 = collect_partition(reader.as_ref(), 0).await.unwrap();
        assert_eq!(p0.num_rows(), 2);
        let p3 = collect_partition(reader.as_ref(), 3).await.unwrap();
        assert_eq!(p3.num_rows(), 2);
    }

    #[tokio::test]
    async fn test_two_file_shuffler_loss_tracking() {
        let dir = TempStrDir::default();
        let output_dir = Path::from(dir.as_ref());
        let num_partitions = 2;

        let batch1 = make_batch(&[0, 1], &[10, 20], Some(1.5));
        let batch2 = make_batch(&[0, 1], &[30, 40], Some(2.5));
        let batch3 = make_batch(&[0], &[50], Some(0.25));

        let shuffler = TwoFileShuffler::new(output_dir, num_partitions);
        let stream = batches_to_stream(vec![batch1, batch2, batch3]);
        let reader = shuffler.shuffle(stream).await.unwrap();

        let loss = reader.total_loss().unwrap();
        assert!((loss - 4.25).abs() < 1e-10, "expected 4.25, got {}", loss);
    }

    #[tokio::test]
    async fn test_two_file_shuffler_single_batch() {
        let dir = TempStrDir::default();
        let output_dir = Path::from(dir.as_ref());
        let num_partitions = 2;

        let batch = make_batch(&[1, 0], &[100, 200], Some(3.0));

        let shuffler = TwoFileShuffler::new(output_dir, num_partitions);
        let stream = batches_to_stream(vec![batch]);
        let reader = shuffler.shuffle(stream).await.unwrap();

        assert_eq!(reader.partition_size(0).unwrap(), 1);
        assert_eq!(reader.partition_size(1).unwrap(), 1);

        let p0 = collect_partition(reader.as_ref(), 0).await.unwrap();
        let vals: &Int32Array = p0.column_by_name("val").unwrap().as_primitive();
        assert_eq!(vals.value(0), 200);

        let p1 = collect_partition(reader.as_ref(), 1).await.unwrap();
        let vals: &Int32Array = p1.column_by_name("val").unwrap().as_primitive();
        assert_eq!(vals.value(0), 100);

        assert!((reader.total_loss().unwrap() - 3.0).abs() < 1e-10);
    }

    #[tokio::test]
    async fn test_two_file_shuffler_multiple_batches() {
        let dir = TempStrDir::default();
        let output_dir = Path::from(dir.as_ref());
        let num_partitions = 3;

        // Use a very small batch size to force multiple write batches
        // Each i32 is 4 bytes, each u32 is 4 bytes, so ~8 bytes/row.
        // With a small batch_size_bytes, we get multiple rechunked batches.
        let batch1 = make_batch(&[0, 1, 2], &[10, 20, 30], Some(1.0));
        let batch2 = make_batch(&[2, 0, 1], &[40, 50, 60], Some(2.0));
        let batch3 = make_batch(&[1, 2, 0], &[70, 80, 90], Some(3.0));

        let shuffler = TwoFileShuffler::new(output_dir, num_partitions)
            // Set very small batch size to force multiple batches
            .with_batch_size_bytes(16);
        let stream = batches_to_stream(vec![batch1, batch2, batch3]);
        let reader = shuffler.shuffle(stream).await.unwrap();

        // Partition 0 should have values: 10, 50, 90
        assert_eq!(reader.partition_size(0).unwrap(), 3);
        let p0 = collect_partition(reader.as_ref(), 0).await.unwrap();
        let vals: &Int32Array = p0.column_by_name("val").unwrap().as_primitive();
        let mut v: Vec<i32> = vals.iter().map(|x| x.unwrap()).collect();
        v.sort();
        assert_eq!(v, vec![10, 50, 90]);

        // Partition 1 should have values: 20, 60, 70
        assert_eq!(reader.partition_size(1).unwrap(), 3);
        let p1 = collect_partition(reader.as_ref(), 1).await.unwrap();
        let vals: &Int32Array = p1.column_by_name("val").unwrap().as_primitive();
        let mut v: Vec<i32> = vals.iter().map(|x| x.unwrap()).collect();
        v.sort();
        assert_eq!(v, vec![20, 60, 70]);

        // Partition 2 should have values: 30, 40, 80
        assert_eq!(reader.partition_size(2).unwrap(), 3);
        let p2 = collect_partition(reader.as_ref(), 2).await.unwrap();
        let vals: &Int32Array = p2.column_by_name("val").unwrap().as_primitive();
        let mut v: Vec<i32> = vals.iter().map(|x| x.unwrap()).collect();
        v.sort();
        assert_eq!(v, vec![30, 40, 80]);

        assert!((reader.total_loss().unwrap() - 6.0).abs() < 1e-10);
    }

    #[tokio::test]
    async fn test_two_file_shuffler_four_flush_groups_with_empty_partitions() {
        let dir = TempStrDir::default();
        let output_dir = Path::from(dir.as_ref());
        let num_partitions = 5;

        // Each input batch is flushed independently. Partition 4 is empty in
        // every group, while the other partitions exercise empty ranges at the
        // beginning, middle, and end of individual groups.
        let batch1 = make_batch(&[0, 2], &[10, 20], None);
        let batch2 = make_batch(&[1, 3], &[30, 40], None);
        let batch3 = make_batch(&[0, 3], &[50, 60], None);
        let batch4 = make_batch(&[3], &[70], None);

        let shuffler =
            TwoFileShuffler::new(output_dir.clone(), num_partitions).with_batch_size_bytes(1);
        let reader = shuffler
            .shuffle(batches_to_stream(vec![batch1, batch2, batch3, batch4]))
            .await
            .unwrap();

        let expected = [vec![10, 50], vec![30], vec![20], vec![40, 60, 70]];
        for (partition_id, expected_values) in expected.iter().enumerate() {
            assert_eq!(
                reader.partition_size(partition_id).unwrap(),
                expected_values.len()
            );
            let partition = collect_partition(reader.as_ref(), partition_id)
                .await
                .unwrap();
            let values: &Int32Array = partition["val"].as_primitive();
            assert_eq!(values.values(), expected_values);
        }
        assert_eq!(reader.partition_size(4).unwrap(), 0);
        assert!(reader.read_partition(4).await.unwrap().is_none());

        // Force the bounded-memory fallback and verify its u64 range reads
        // produce the same partition order and empty-partition behavior.
        let fallback_reader = TwoFileShuffleReader::try_new_with_preload_limit(
            Arc::new(ObjectStore::local()),
            output_dir,
            num_partitions,
            4,
            vec![2, 1, 1, 3, 0],
            0.0,
            0,
            OffsetPreloadSource::Sidecar,
        )
        .await
        .unwrap();
        for (partition_id, expected_values) in expected.iter().enumerate() {
            let partition = collect_partition(fallback_reader.as_ref(), partition_id)
                .await
                .unwrap();
            let values: &Int32Array = partition["val"].as_primitive();
            assert_eq!(values.values(), expected_values);
        }
        assert!(fallback_reader.read_partition(4).await.unwrap().is_none());
    }

    #[tokio::test]
    async fn test_partition_windows_match_singletons_with_hotspot_and_empty_boundaries() {
        let dir = TempStrDir::default();
        let output_dir = Path::from(dir.as_ref());
        let num_partitions = 6;

        // Four flush groups, with empty partitions at the beginning, middle,
        // and end. Partition 2 is deliberately much larger than its neighbors.
        let batch1 = make_batch(&[1, 2, 2, 2], &[10, 20, 21, 22], None);
        let batch2 = make_batch(&[2, 2, 4], &[23, 24, 40], None);
        let batch3 = make_batch(&[1, 2, 2], &[11, 25, 26], None);
        let batch4 = make_batch(&[2, 2, 2], &[27, 28, 29], None);
        let reader = TwoFileShuffler::new(output_dir, num_partitions)
            .with_batch_size_bytes(1)
            .shuffle(batches_to_stream(vec![batch1, batch2, batch3, batch4]))
            .await
            .unwrap();

        let mut singleton_values = Vec::with_capacity(num_partitions);
        for partition_id in 0..num_partitions {
            let values = match reader.read_partition(partition_id).await.unwrap() {
                Some(stream) => collect_values(stream).await,
                None => Vec::new(),
            };
            singleton_values.push(values);
        }

        // The decoded schema is one Int32 (4 bytes). A 12-byte target fits the
        // first empty + two-row partition, while the ten-row hotspot is forced
        // into a singleton window.
        let mut next_partition_id = 0;
        let mut ranges = Vec::new();
        let mut admission_bytes = Vec::new();
        let mut window_values = vec![Vec::new(); num_partitions];
        while next_partition_id < num_partitions {
            let plan = reader.plan_partition_window(next_partition_id, 12).unwrap();
            let window = reader
                .read_partition_window(next_partition_id, 12)
                .await
                .unwrap();
            assert_eq!(window.partition_range, plan.partition_range);
            assert!(window.materialized_decoded_bytes.is_some());
            assert_eq!(window.partitions.len(), window.partition_range.len());
            ranges.push(window.partition_range.clone());
            admission_bytes.push(plan.estimated_decoded_bytes);
            next_partition_id = window.partition_range.end;
            for partition in window.partitions {
                if let Some(stream) = partition.data {
                    window_values[partition.partition_id] = collect_values(stream).await;
                }
            }
        }

        assert_eq!(ranges, vec![0..2, 2..3, 3..6]);
        assert!(admission_bytes[1] > admission_bytes[0]);
        assert!(admission_bytes[1] > admission_bytes[2]);
        assert_eq!(window_values, singleton_values);
        assert_eq!(window_values[0], Vec::<i32>::new());
        assert_eq!(window_values[2].len(), 10);
        assert_eq!(window_values[5], Vec::<i32>::new());
    }

    #[tokio::test]
    async fn test_on_demand_offsets_preserve_planned_window() {
        let dir = TempStrDir::default();
        let output_dir = Path::from(dir.as_ref());
        let reader = TwoFileShuffler::new(output_dir.clone(), 3)
            .with_batch_size_bytes(1)
            .shuffle(batches_to_stream(vec![
                make_batch(&[0, 1], &[10, 20], None),
                make_batch(&[1, 2], &[30, 40], None),
            ]))
            .await
            .unwrap();
        drop(reader);

        let fallback_reader = TwoFileShuffleReader::try_new_with_preload_limit(
            Arc::new(ObjectStore::local()),
            output_dir.clone(),
            3,
            2,
            vec![1, 2, 1],
            0.0,
            0,
            OffsetPreloadSource::Sidecar,
        )
        .await
        .unwrap();
        let window = fallback_reader
            .read_partition_window(1, DEFAULT_PARTITION_WINDOW_BYTES)
            .await
            .unwrap();
        assert_eq!(window.partition_range, 1..3);
        assert_eq!(window.partitions.len(), 2);
        assert!(window.materialized_decoded_bytes.is_none());
        assert_eq!(window.partitions[0].partition_id, 1);

        // Writer-side offsets that exceed the byte cap must take the same
        // sidecar on-demand path rather than staying Preloaded.
        let over_limit_reader = TwoFileShuffleReader::try_new_with_preload_limit(
            Arc::new(ObjectStore::local()),
            output_dir,
            3,
            2,
            vec![1, 2, 1],
            0.0,
            0,
            OffsetPreloadSource::Writer(vec![1, 2, 2, 2, 3, 4]),
        )
        .await
        .unwrap();
        let window = over_limit_reader
            .read_partition_window(1, DEFAULT_PARTITION_WINDOW_BYTES)
            .await
            .unwrap();
        assert_eq!(window.partition_range, 1..3);
        let partition = collect_partition(over_limit_reader.as_ref(), 1)
            .await
            .unwrap();
        let values: &Int32Array = partition["val"].as_primitive();
        assert_eq!(values.values(), &[20, 30]);
    }

    #[rstest::rstest]
    #[case::disabled(0, false)]
    #[case::too_small(47, false)]
    #[case::exact_fit(48, true)]
    #[case::raised(536_870_912, true)]
    #[tokio::test]
    async fn test_shuffle_offset_preload_environment(
        #[case] limit: usize,
        #[case] is_preloaded: bool,
    ) {
        const CHILD_ENV: &str = "LANCE_TEST_SHUFFLE_OFFSET_PRELOAD_CHILD";
        if std::env::var_os(CHILD_ENV).is_none() {
            let output = std::process::Command::new(std::env::current_exe().unwrap())
                .args([
                    "--exact",
                    std::thread::current().name().unwrap(),
                    "--nocapture",
                ])
                .env(CHILD_ENV, "1")
                .env(MAX_PRELOADED_OFFSETS_BYTES_ENV, limit.to_string())
                .output()
                .unwrap();
            assert!(
                output.status.success(),
                "child test failed: {}\n{}",
                String::from_utf8_lossy(&output.stdout),
                String::from_utf8_lossy(&output.stderr)
            );
            assert!(String::from_utf8_lossy(&output.stdout).contains("1 passed"));
            return;
        }
        let dir = TempStrDir::default();
        let output_dir = Path::from(dir.as_ref());
        let reader = TwoFileShuffler::new(output_dir.clone(), 3)
            .with_batch_size_bytes(1)
            .shuffle(batches_to_stream(vec![
                make_batch(&[0, 1], &[10, 20], None),
                make_batch(&[1, 2], &[30, 40], None),
            ]))
            .await
            .unwrap();

        assert_eq!(reader.partition_size(0).unwrap(), 1);
        assert_eq!(reader.partition_size(1).unwrap(), 2);
        assert_eq!(reader.partition_size(2).unwrap(), 1);
        let p1 = collect_partition(reader.as_ref(), 1).await.unwrap();
        let values: &Int32Array = p1["val"].as_primitive();
        assert_eq!(values.values(), &[20, 30]);
        let window = reader
            .read_partition_window(0, DEFAULT_PARTITION_WINDOW_BYTES)
            .await
            .unwrap();
        assert_eq!(window.partition_range, 0..3);
        assert_eq!(window.materialized_decoded_bytes.is_some(), is_preloaded);

        let reopened = TwoFileShuffleReader::try_new(
            Arc::new(ObjectStore::local()),
            output_dir,
            3,
            2,
            vec![1, 2, 1],
            0.0,
        )
        .await
        .unwrap();
        let window = reopened
            .read_partition_window(0, DEFAULT_PARTITION_WINDOW_BYTES)
            .await
            .unwrap();
        assert_eq!(window.partition_range, 0..3);
        assert_eq!(window.materialized_decoded_bytes.is_some(), is_preloaded);
        let p1 = collect_partition(reopened.as_ref(), 1).await.unwrap();
        let values: &Int32Array = p1["val"].as_primitive();
        assert_eq!(values.values(), &[20, 30]);
    }

    #[rstest::rstest]
    #[case::unset(None, 256 * 1024 * 1024)]
    #[case::disabled(Some("0"), 0)]
    #[case::raised(Some("536870912"), 512 * 1024 * 1024)]
    #[case::whitespace(Some(" 48 "), 48)]
    fn test_parse_max_preloaded_offsets_bytes(
        #[case] value: Option<&str>,
        #[case] expected: usize,
    ) {
        assert_eq!(
            parse_max_preloaded_offsets_bytes(value.map(str::to_owned).ok_or(VarError::NotPresent))
                .unwrap(),
            expected
        );
    }

    #[rstest::rstest]
    #[case::empty("")]
    #[case::negative("-1")]
    #[case::suffix("512MiB")]
    #[case::overflow("18446744073709551616")]
    fn test_parse_max_preloaded_offsets_bytes_rejects_invalid(#[case] value: &str) {
        let error = parse_max_preloaded_offsets_bytes(Ok(value.to_owned())).unwrap_err();
        assert!(matches!(error, Error::InvalidInput { .. }));
        let message = error.to_string();
        assert!(message.contains(MAX_PRELOADED_OFFSETS_BYTES_ENV));
        assert!(message.contains(&format!("{value:?}")));
    }

    #[tokio::test]
    async fn test_forced_on_demand_does_not_repreload_when_logical_size_fits() {
        let dir = TempStrDir::default();
        let output_dir = Path::from(dir.as_ref());
        let reader = TwoFileShuffler::new(output_dir.clone(), 3)
            .with_batch_size_bytes(1)
            .shuffle(batches_to_stream(vec![
                make_batch(&[0, 1], &[10, 20], None),
                make_batch(&[1, 2], &[30, 40], None),
            ]))
            .await
            .unwrap();
        drop(reader);

        // Logical table is 2 batches * 3 partitions * 8 bytes = 48 bytes, well
        // under the default 256 MiB cap. ForcedOnDemand must still stay
        // on-demand instead of retrying a full sidecar preload.
        let forced = TwoFileShuffleReader::try_new_with_preload_limit(
            Arc::new(ObjectStore::local()),
            output_dir.clone(),
            3,
            2,
            vec![1, 2, 1],
            0.0,
            DEFAULT_MAX_PRELOADED_OFFSETS_BYTES,
            OffsetPreloadSource::ForcedOnDemand,
        )
        .await
        .unwrap();
        let forced_plan = forced
            .plan_partition_window(0, DEFAULT_PARTITION_WINDOW_BYTES)
            .unwrap();
        assert_eq!(forced_plan.partition_range, 0..3);
        let forced_window = forced
            .read_partition_window(0, DEFAULT_PARTITION_WINDOW_BYTES)
            .await
            .unwrap();
        assert!(
            forced_window.materialized_decoded_bytes.is_none(),
            "ForcedOnDemand must not re-preload from the sidecar"
        );

        let sidecar = TwoFileShuffleReader::try_new_with_preload_limit(
            Arc::new(ObjectStore::local()),
            output_dir,
            3,
            2,
            vec![1, 2, 1],
            0.0,
            DEFAULT_MAX_PRELOADED_OFFSETS_BYTES,
            OffsetPreloadSource::Sidecar,
        )
        .await
        .unwrap();
        let sidecar_plan = sidecar
            .plan_partition_window(0, DEFAULT_PARTITION_WINDOW_BYTES)
            .unwrap();
        assert_eq!(sidecar_plan.partition_range, forced_plan.partition_range);
        let sidecar_window = sidecar
            .read_partition_window(0, DEFAULT_PARTITION_WINDOW_BYTES)
            .await
            .unwrap();
        assert!(
            sidecar_window.materialized_decoded_bytes.is_some(),
            "sidecar reopen with room under the cap should preload and coalesce"
        );
    }

    #[test]
    fn test_window_planning_uses_decoded_bytes_and_isolates_hotspot() {
        let partition_counts = [0, 2, 10, 0, 1, 0];
        assert_eq!(
            plan_partition_window_end(&partition_counts, 0, 4, 12).unwrap(),
            2
        );
        assert_eq!(
            plan_partition_window_end(&partition_counts, 2, 4, 12).unwrap(),
            3
        );
        assert_eq!(
            plan_partition_window_end(&partition_counts, 3, 4, 12).unwrap(),
            6
        );

        let error = plan_partition_window_end(&partition_counts, 0, 4, 0).unwrap_err();
        assert!(matches!(error, Error::InvalidInput { .. }));
        assert!(error.to_string().contains("must be greater than 0"));
    }

    #[tokio::test]
    async fn legacy_shuffler_uses_schema_estimate_for_parallel_admission() {
        let dir = TempStrDir::default();
        let output_dir = Path::from(dir.as_ref());
        let part_ids = vec![0; 32];
        let values = (0..32).collect::<Vec<_>>();
        let reader = IvfShuffler::new(output_dir, 2)
            .shuffle(batches_to_stream(vec![make_batch(
                &part_ids, &values, None,
            )]))
            .await
            .unwrap();

        let non_empty = reader.plan_partition_window(0, 128 * 1024 * 1024).unwrap();
        assert_eq!(non_empty.partition_range, 0..1);
        assert_eq!(
            non_empty.estimated_decoded_bytes,
            32 * 4 + 32 * 4 / 4 + WINDOW_ADMISSION_FIXED_HEADROOM_BYTES
        );
        assert_ne!(non_empty.estimated_decoded_bytes, usize::MAX);

        let empty = reader.plan_partition_window(1, 128 * 1024 * 1024).unwrap();
        assert_eq!(empty.partition_range, 1..2);
        assert_eq!(empty.estimated_decoded_bytes, 0);
    }

    #[test]
    fn test_preloaded_window_ranges_coalesce_each_nonempty_flush_group() {
        // Three groups x five partitions. Window [1, 4) is empty in the last
        // group, so only two ranges are submitted.
        let offsets = [1, 3, 3, 4, 4, 4, 4, 6, 7, 8, 9, 9, 9, 9, 10];
        let (ranges, counts) = preloaded_window_ranges(&offsets, 3, 5, 1..4).unwrap();
        assert_eq!(ranges, vec![1..4, 4..7]);
        assert_eq!(counts, vec![vec![2, 0, 1], vec![0, 2, 1]]);
    }

    #[tokio::test]
    async fn test_partition_window_split_rejects_short_and_extra_rows() {
        let data = make_batch(&[0, 0, 0, 0, 0], &[10, 20, 30, 40, 50], None)
            .drop_column(PART_ID_COLUMN)
            .unwrap();
        let group_counts = vec![vec![1, 2], vec![0, 1]];

        let short_stream = stream::iter(vec![Ok(data.slice(0, 3))]);
        let error = split_partition_window_stream(short_stream, 2, &group_counts)
            .await
            .unwrap_err();
        assert!(matches!(error, Error::CorruptFile { .. }));
        assert!(
            error
                .to_string()
                .contains("decoded 3 rows for partition window, expected 4"),
            "unexpected error: {error}"
        );

        let extra_stream = stream::iter(vec![Ok(data)]);
        let error = split_partition_window_stream(extra_stream, 2, &group_counts)
            .await
            .unwrap_err();
        assert!(matches!(error, Error::CorruptFile { .. }));
        assert!(
            error
                .to_string()
                .contains("decoded more than the expected 4 rows"),
            "unexpected error: {error}"
        );
    }

    #[tokio::test]
    async fn test_partition_window_split_propagates_stream_error() {
        let injected = Error::io("injected window read failure");
        let error = split_partition_window_stream(stream::iter(vec![Err(injected)]), 1, &[vec![1]])
            .await
            .unwrap_err();
        assert!(matches!(error, Error::IO { .. }));
        assert!(error.to_string().contains("injected window read failure"));
    }

    #[test]
    fn test_validate_shuffle_offsets_rejects_truncated_offsets() {
        let offsets_path = Path::from("shuffle_offsets.lance");
        let offsets = [2, 2, 3, 3, 3, 6, 6, 7, 8, 8, 8];
        let error =
            validate_shuffle_offsets(&offsets, 3, 4, 10, &[3, 3, 1, 3], &offsets_path).unwrap_err();

        assert!(matches!(error, Error::CorruptFile { .. }));
        assert!(
            error
                .to_string()
                .contains("decoded 11 offsets, expected 12"),
            "unexpected error: {error}"
        );
    }

    #[test]
    fn test_validate_shuffle_offsets_rejects_non_monotonic_offsets() {
        let offsets_path = Path::from("shuffle_offsets.lance");
        let offsets = [2, 2, 3, 3, 3, 2, 6, 7, 8, 8, 8, 10];
        let error =
            validate_shuffle_offsets(&offsets, 3, 4, 10, &[3, 3, 1, 3], &offsets_path).unwrap_err();

        assert!(matches!(error, Error::CorruptFile { .. }));
        assert!(
            error
                .to_string()
                .contains("offsets are not monotonic at indices 4 and 5: 3 > 2"),
            "unexpected error: {error}"
        );
    }

    #[test]
    fn test_validate_shuffle_offsets_rejects_data_boundary_mismatch() {
        let offsets_path = Path::from("shuffle_offsets.lance");
        let offsets = [2, 2, 3, 3, 3, 6, 6, 7, 8, 8, 8, 11];
        let error =
            validate_shuffle_offsets(&offsets, 3, 4, 10, &[3, 3, 1, 4], &offsets_path).unwrap_err();

        assert!(matches!(error, Error::CorruptFile { .. }));
        assert!(
            error
                .to_string()
                .contains("final offset 11 does not match shuffle data row count 10"),
            "unexpected error: {error}"
        );
    }

    #[test]
    fn test_validate_shuffle_offsets_checks_partition_counts() {
        let offsets_path = Path::from("shuffle_offsets.lance");
        let offsets = [2, 2, 3, 3, 3, 6, 6, 7, 8, 8, 8, 10];
        let error =
            validate_shuffle_offsets(&offsets, 3, 4, 10, &[3, 2, 1, 4], &offsets_path).unwrap_err();

        assert!(matches!(error, Error::CorruptFile { .. }));
        assert!(
            error
                .to_string()
                .contains("offset-derived count 3 for partition 1 does not match expected count 2"),
            "unexpected error: {error}"
        );
    }

    #[test]
    fn test_should_preload_offsets_enforces_byte_limit_and_checks_overflow() {
        assert!(should_preload_offsets(4, 4 * std::mem::size_of::<u64>()).unwrap());
        assert!(!should_preload_offsets(5, 4 * std::mem::size_of::<u64>()).unwrap());

        let error = should_preload_offsets(usize::MAX, usize::MAX).unwrap_err();
        assert!(matches!(error, Error::InvalidInput { .. }));
        assert!(
            error
                .to_string()
                .contains("overflows byte-size calculation"),
            "unexpected error: {error}"
        );
    }

    #[test]
    fn test_try_allocate_preloaded_offsets_is_fallible_and_capacity_checked() {
        let elem = std::mem::size_of::<u64>();
        let allocated = try_allocate_preloaded_offsets(4, 4 * elem)
            .unwrap()
            .expect("logical size fits");
        assert!(allocated.capacity() * elem <= 4 * elem);

        assert!(
            try_allocate_preloaded_offsets(5, 4 * elem)
                .unwrap()
                .is_none(),
            "logical size above the cap must stay on-demand"
        );
    }

    fn assert_allocated_bytes_within_limit(written: &BoundedWrittenOffsets, max_bytes: usize) {
        let Some(offsets) = written.offsets.as_ref() else {
            return;
        };
        let allocated = offsets
            .capacity()
            .checked_mul(std::mem::size_of::<u64>())
            .expect("capacity * size_of::<u64> overflows");
        assert!(
            allocated <= max_bytes,
            "allocated {allocated} bytes exceeds cap {max_bytes} (len={}, capacity={})",
            offsets.len(),
            offsets.capacity()
        );
    }

    #[test]
    fn test_bounded_written_offsets_drops_copy_at_byte_limit() {
        let max_bytes = 2 * std::mem::size_of::<u64>();
        let mut written = BoundedWrittenOffsets::new(max_bytes);
        written.retain(&[1, 2]).unwrap();
        assert_eq!(written.offsets.as_deref(), Some(&[1, 2][..]));
        assert_allocated_bytes_within_limit(&written, max_bytes);

        written.retain(&[3]).unwrap();
        assert!(
            written.offsets.is_none(),
            "exceeding the preload cap must drop the in-memory copy"
        );

        written.retain(&[4]).unwrap();
        assert!(
            written.offsets.is_none(),
            "a dropped copy must stay dropped"
        );
        assert!(matches!(
            written.into_offsets(),
            OffsetPreloadSource::ForcedOnDemand
        ));
    }

    #[test]
    fn test_bounded_written_offsets_allocated_capacity_stays_within_limit() {
        // 3 u64s = 24 bytes. A first retain of 2 typically allocates capacity 2.
        // A second retain of 1 still fits by length (24 bytes) but amortized
        // doubling would grow capacity to 4 = 32 bytes, past the ceiling.
        let max_bytes = 3 * std::mem::size_of::<u64>();
        let mut written = BoundedWrittenOffsets::new(max_bytes);
        written.retain(&[1, 2]).unwrap();
        assert_eq!(written.offsets.as_deref(), Some(&[1, 2][..]));
        assert_allocated_bytes_within_limit(&written, max_bytes);

        written.retain(&[3]).unwrap();
        if let Some(offsets) = written.offsets.as_ref() {
            assert_eq!(offsets.as_slice(), &[1, 2, 3]);
        }
        assert_allocated_bytes_within_limit(&written, max_bytes);

        // Filling the cap in a single retain must also keep allocated bytes
        // at or below the ceiling.
        let mut written = BoundedWrittenOffsets::new(max_bytes);
        written.retain(&[1, 2, 3]).unwrap();
        assert_eq!(written.offsets.as_deref(), Some(&[1, 2, 3][..]));
        assert_allocated_bytes_within_limit(&written, max_bytes);
    }

    #[tokio::test]
    async fn test_two_file_shuffler_multi_batch_single_flush() {
        // All three batches fit within the default batch_size_bytes, so they
        // accumulate and are interleaved in a single flush group. This exercises
        // the cross-batch interleave path.
        let dir = TempStrDir::default();
        let output_dir = Path::from(dir.as_ref());
        let num_partitions = 3;

        let batch1 = make_batch(&[0, 1, 2], &[10, 20, 30], None);
        let batch2 = make_batch(&[2, 0, 1], &[40, 50, 60], None);
        let batch3 = make_batch(&[1, 2, 0], &[70, 80, 90], None);

        // Large batch_size_bytes so all three batches flush together.
        let shuffler =
            TwoFileShuffler::new(output_dir, num_partitions).with_batch_size_bytes(1024 * 1024);
        let stream = batches_to_stream(vec![batch1, batch2, batch3]);
        let reader = shuffler.shuffle(stream).await.unwrap();

        assert_eq!(reader.partition_size(0).unwrap(), 3);
        assert_eq!(reader.partition_size(1).unwrap(), 3);
        assert_eq!(reader.partition_size(2).unwrap(), 3);

        let p0 = collect_partition(reader.as_ref(), 0).await.unwrap();
        let vals: &Int32Array = p0.column_by_name("val").unwrap().as_primitive();
        let mut v: Vec<i32> = vals.iter().map(|x| x.unwrap()).collect();
        v.sort();
        assert_eq!(v, vec![10, 50, 90]);

        let p1 = collect_partition(reader.as_ref(), 1).await.unwrap();
        let vals: &Int32Array = p1.column_by_name("val").unwrap().as_primitive();
        let mut v: Vec<i32> = vals.iter().map(|x| x.unwrap()).collect();
        v.sort();
        assert_eq!(v, vec![20, 60, 70]);

        let p2 = collect_partition(reader.as_ref(), 2).await.unwrap();
        let vals: &Int32Array = p2.column_by_name("val").unwrap().as_primitive();
        let mut v: Vec<i32> = vals.iter().map(|x| x.unwrap()).collect();
        v.sort();
        assert_eq!(v, vec![30, 40, 80]);
    }

    #[tokio::test]
    async fn test_two_file_shuffler_out_of_range_partition_id() {
        let dir = TempStrDir::default();
        let output_dir = Path::from(dir.as_ref());

        // Row with partition ID 5 is out of range for num_partitions=3.
        let batch = make_batch(&[0, 5, 1], &[10, 20, 30], None);

        let shuffler = TwoFileShuffler::new(output_dir, 3);
        let stream = batches_to_stream(vec![batch]);
        let Err(err) = shuffler.shuffle(stream).await else {
            panic!("expected an error for out-of-range partition ID");
        };
        assert!(
            err.to_string().contains("partition ID 5 is out of range"),
            "unexpected error: {err}"
        );
    }

    /// CI failed `test_ann_with_deletion` with:
    /// `offset-derived count 127 for partition 0 does not match expected count 126`
    /// on a 512-row IVF shuffle into 4 partitions. This is that exact histogram.
    #[tokio::test]
    async fn test_two_file_shuffler_uneven_512_rows_four_partitions() {
        let dir = TempStrDir::default();
        let output_dir = Path::from(dir.as_ref());
        let num_partitions = 4;

        let mut part_ids = Vec::with_capacity(512);
        part_ids.extend(std::iter::repeat_n(0u32, 126));
        part_ids.extend(std::iter::repeat_n(1u32, 130));
        part_ids.extend(std::iter::repeat_n(2u32, 128));
        part_ids.extend(std::iter::repeat_n(3u32, 128));
        let values: Vec<i32> = (0..512).collect();
        let batch = make_batch(&part_ids, &values, None);

        let shuffler = TwoFileShuffler::new(output_dir, num_partitions);
        let reader = shuffler
            .shuffle(batches_to_stream(vec![batch]))
            .await
            .unwrap();

        assert_eq!(reader.partition_size(0).unwrap(), 126);
        assert_eq!(reader.partition_size(1).unwrap(), 130);
        assert_eq!(reader.partition_size(2).unwrap(), 128);
        assert_eq!(reader.partition_size(3).unwrap(), 128);

        let p0 = collect_partition(reader.as_ref(), 0).await.unwrap();
        assert_eq!(p0.num_rows(), 126);
        let p1 = collect_partition(reader.as_ref(), 1).await.unwrap();
        assert_eq!(p1.num_rows(), 130);
    }

    /// A partition that only appears in some flush groups used to get one
    /// zero-length range per group it is absent from, and those reach the file
    /// reader as real range entries.
    #[test]
    fn test_preloaded_partition_ranges_skip_empty_groups() {
        // Three partitions, four flush groups. Offsets are cumulative row
        // counts per (group, partition): partition 1 holds rows in group 1 only.
        let offsets = vec![
            1u64, 1, 2, // group 0: p0 one row, p1 none, p2 one row
            2, 4, 4, // group 1: p0 none, p1 two rows, p2 none
            5, 5, 5, // group 2: p0 one row, nothing else
            5, 5, 6, // group 3: p2 one row
        ];

        let p1 = preloaded_partition_ranges(&offsets, 4, 3, 1);
        assert_eq!(p1, vec![2..4], "partition 1 spans group 1 only");

        let p0 = preloaded_partition_ranges(&offsets, 4, 3, 0);
        assert_eq!(p0, vec![0..1, 4..5], "partition 0 spans groups 0 and 2");
        assert!(
            p0.iter()
                .chain(p1.iter())
                .all(|range| range.start < range.end),
            "no zero-length range should survive: {p0:?} {p1:?}"
        );
    }

    /// Two non-empty batches in one flush group: the bucketing has to keep each
    /// row with its own batch, so a partition's rows come out batch by batch and
    /// in row order within a batch. A wrong bucket offset would move values into
    /// the neighbouring partition while leaving every partition size intact.
    #[tokio::test]
    async fn test_two_file_shuffler_groups_two_batches_by_partition() {
        let dir = TempStrDir::default();
        let output_dir = Path::from(dir.as_ref());

        let batch1 = make_batch(&[1, 0, 2], &[10, 20, 30], None);
        let batch2 = make_batch(&[2, 1, 0], &[40, 50, 60], None);

        let shuffler = TwoFileShuffler::new(output_dir, 3);
        let reader = shuffler
            .shuffle(batches_to_stream(vec![batch1, batch2]))
            .await
            .unwrap();

        let expected = [vec![20, 60], vec![10, 50], vec![30, 40]];
        for (partition_id, expected_values) in expected.iter().enumerate() {
            assert_eq!(reader.partition_size(partition_id).unwrap(), 2);
            let partition = collect_partition(reader.as_ref(), partition_id)
                .await
                .unwrap();
            let values: &Int32Array = partition["val"].as_primitive();
            assert_eq!(
                values.values(),
                expected_values,
                "partition {partition_id} holds the wrong rows"
            );
        }
    }

    /// Nullable `__ivf_part_id` must not be treated as partition 0 via `values()`.
    #[tokio::test]
    async fn test_two_file_shuffler_rejects_null_partition_ids() {
        let dir = TempStrDir::default();
        let output_dir = Path::from(dir.as_ref());

        let schema = Arc::new(ArrowSchema::new(vec![
            Field::new(PART_ID_COLUMN, DataType::UInt32, true),
            Field::new("val", DataType::Int32, false),
        ]));
        let batch = RecordBatch::try_new(
            schema,
            vec![
                Arc::new(UInt32Array::from(vec![Some(0), None, Some(1)])),
                Arc::new(Int32Array::from(vec![10, 20, 30])),
            ],
        )
        .unwrap();

        let shuffler = TwoFileShuffler::new(output_dir, 2);
        let Err(err) = shuffler.shuffle(batches_to_stream(vec![batch])).await else {
            panic!("expected an error for null partition IDs");
        };
        assert!(
            err.to_string().contains("null partition ID"),
            "unexpected error: {err}"
        );
    }
}
