// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: Copyright The Lance Authors

//! Internal controls for the frozen #9505 experiment. These are not public tuning APIs.

use std::io::Write;
use std::num::NonZero;
use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::Instant;

use arrow_schema::{DataType, Schema};
use datafusion::catalog::TableProvider;
use datafusion::execution::{
    context::{SessionConfig, SessionContext},
    disk_manager::DiskManagerBuilder,
    memory_pool::{
        FairSpillPool, MemoryConsumer, MemoryLimit, MemoryPool, MemoryReservation,
        TrackConsumersPool, UnboundedMemoryPool,
    },
    runtime_env::RuntimeEnvBuilder,
};
use datafusion::physical_plan::{ExecutionPlan, metrics::MetricValue};
use lance_core::utils::tokio::get_num_compute_intensive_cpus;
use lance_core::{Error, Result};
use lance_datafusion::exec::LanceExecutionOptions;
use serde_json::{Value, json};

use crate::Dataset;
use crate::dataset::scanner::{
    BATCH_SIZE_FALLBACK, get_default_batch_size, get_default_io_buffer_size_override,
};
use lance_io::scheduler::SchedulerConfig;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum ExperimentMode {
    PrepUnbounded,
    Prep,
    Budget,
    Core,
    Late,
    BudgetLate,
}

impl ExperimentMode {
    pub fn from_env() -> Result<Self> {
        match std::env::var("LANCE_MERGE_EXPERIMENT").as_deref() {
            Err(std::env::VarError::NotPresent) | Ok("Ccore") => Ok(Self::Core),
            Ok("Cprep_infinite") => Ok(Self::PrepUnbounded),
            Ok("Cprep") => Ok(Self::Prep),
            Ok("Cbudget") => Ok(Self::Budget),
            Ok("Clate") => Ok(Self::Late),
            Ok("Cbudget_late") => Ok(Self::BudgetLate),
            value => Err(Error::invalid_input(format!(
                "Invalid LANCE_MERGE_EXPERIMENT: {value:?}"
            ))),
        }
    }

    pub fn late(self) -> bool {
        matches!(self, Self::Late | Self::BudgetLate)
    }

    pub fn budget(self) -> bool {
        matches!(
            self,
            Self::Budget | Self::Core | Self::Late | Self::BudgetLate
        )
    }

    pub fn native(self) -> bool {
        matches!(self, Self::Core | Self::Late)
    }
}

#[derive(Debug, Clone, Default)]
pub(super) enum SourceEvidence {
    Complete,
    Prefix,
    #[default]
    ProviderStatsOnly,
}

pub(super) struct PreparedMergeSource {
    pub provider: Arc<dyn TableProvider>,
    pub evidence: SourceEvidence,
    pub allow_replay: bool,
}

#[derive(Debug)]
pub struct MergeScanPolicy {
    pub partitions: usize,
    pub decode_tasks: usize,
    pub io_bytes: Option<u64>,
    pub decode_bytes: u64,
    pub width: Option<u64>,
    pub use_budget: bool,
    pub use_native: bool,
}

pub(super) struct MergeResources {
    pub context: SessionContext,
    pub mode: ExperimentMode,
    pub policy_bytes: usize,
    pub prefix_bytes: usize,
    pub prefix_rows: usize,
    pub scan: Arc<MergeScanPolicy>,
}

/// Observes accepted reservation changes. Concurrent operations can make this
/// peak lower than the inner pool's instantaneous peak. It is not a process limit.
#[derive(Debug)]
pub(super) struct PeakMemoryPool {
    inner: Arc<dyn MemoryPool>,
    current: AtomicUsize,
    peak: AtomicUsize,
}

impl PeakMemoryPool {
    pub fn peak(&self) -> usize {
        self.peak.load(Ordering::Relaxed)
    }
    fn record_growth(&self, bytes: usize) {
        let current = self.current.fetch_add(bytes, Ordering::Relaxed) + bytes;
        self.peak.fetch_max(current, Ordering::Relaxed);
    }
}

impl std::fmt::Display for PeakMemoryPool {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        std::fmt::Display::fmt(self.inner.as_ref(), f)
    }
}

impl MemoryPool for PeakMemoryPool {
    fn name(&self) -> &str {
        self.inner.name()
    }
    fn register(&self, consumer: &MemoryConsumer) {
        self.inner.register(consumer);
    }
    fn unregister(&self, consumer: &MemoryConsumer) {
        self.inner.unregister(consumer);
    }
    fn grow(&self, reservation: &MemoryReservation, bytes: usize) {
        self.inner.grow(reservation, bytes);
        self.record_growth(bytes);
    }
    fn try_grow(
        &self,
        reservation: &MemoryReservation,
        bytes: usize,
    ) -> datafusion::common::Result<()> {
        self.inner.try_grow(reservation, bytes)?;
        self.record_growth(bytes);
        Ok(())
    }
    fn shrink(&self, reservation: &MemoryReservation, bytes: usize) {
        self.current.fetch_sub(bytes, Ordering::Relaxed);
        self.inner.shrink(reservation, bytes);
    }
    fn reserved(&self) -> usize {
        self.inner.reserved()
    }
    fn memory_limit(&self) -> MemoryLimit {
        self.inner.memory_limit()
    }
}

impl MergeResources {
    pub fn new(dataset: &Dataset, target_schema: &Schema) -> Result<Self> {
        let mode = ExperimentMode::from_env()?;
        if std::env::var_os("LANCE_BYPASS_SPILLING").is_some() {
            return Err(Error::invalid_input(
                "C experiments require LANCE_BYPASS_SPILLING to be unset",
            ));
        }
        let original_config = SessionConfig::new();
        let requested = original_config.target_partitions();
        let options = LanceExecutionOptions {
            use_spilling: true,
            target_partition: Some(requested),
            ..Default::default()
        };
        let policy_bytes = usize::try_from(options.mem_pool_size())
            .map_err(|_| Error::invalid_input("Merge pool size exceeds usize"))?;
        if policy_bytes == 0 {
            return Err(Error::invalid_input(
                "Merge policy pool bytes must be greater than 0",
            ));
        }
        let fixed_width = fixed_schema_width(target_schema);
        let width = fixed_width.or_else(|| {
            let (rows, bytes) =
                dataset
                    .fragments()
                    .iter()
                    .try_fold((0u64, 0u64), |(rows, bytes), fragment| {
                        let bytes_in_fragment =
                            fragment.files.iter().try_fold(0u64, |sum, file| {
                                sum.checked_add(file.file_size_bytes.get()?.get())
                            })?;
                        Some((
                            rows.checked_add(fragment.physical_rows? as u64)?,
                            bytes.checked_add(bytes_in_fragment)?,
                        ))
                    })?;
            (rows > 0).then(|| bytes.div_ceil(rows).max(1))
        });
        let decode_tasks = get_num_compute_intensive_cpus().max(1);
        let decode_bytes = policy_bytes as u64 / 4;
        let memory_partitions = width
            .map(|width| (decode_bytes / width.max(1)).max(1) as usize)
            .unwrap_or(usize::MAX);
        let partitions = requested.min(decode_tasks).min(memory_partitions).max(1);
        let configured_io = get_default_io_buffer_size_override().unwrap_or_else(|| {
            SchedulerConfig::max_bandwidth(dataset.object_store.as_ref()).io_buffer_size_bytes
        });
        let io_bytes = (configured_io != 0).then(|| {
            (policy_bytes as u64 / 4)
                .max(16 * 1024 * 1024)
                .min(configured_io)
        });
        let mut config = original_config
            .with_target_partitions(partitions)
            .with_sort_spill_reservation_bytes((policy_bytes / 3).min(40 * 1024 * 1024));
        // Keep normal JoinSelection, repartitioning and round-robin rules enabled.
        let prefix_rows = config
            .options()
            .optimizer
            .hash_join_single_partition_threshold_rows;
        let prefix_bytes = (100 * 1024 * 1024).min(policy_bytes / 8);
        config.options_mut().execution.target_partitions = partitions;
        let pool: Arc<dyn MemoryPool> = if mode == ExperimentMode::PrepUnbounded {
            Arc::new(TrackConsumersPool::new(
                UnboundedMemoryPool::default(),
                NonZero::<usize>::MIN.saturating_add(15),
            ))
        } else {
            Arc::new(TrackConsumersPool::new(
                FairSpillPool::new(policy_bytes),
                NonZero::<usize>::MIN.saturating_add(15),
            ))
        };
        let runtime = RuntimeEnvBuilder::new()
            .with_disk_manager_builder(
                DiskManagerBuilder::default()
                    .with_max_temp_directory_size(options.max_temp_directory_size()),
            )
            .with_memory_pool(Arc::new(PeakMemoryPool {
                inner: pool,
                current: AtomicUsize::new(0),
                peak: AtomicUsize::new(0),
            }))
            .build_arc()?;
        let context = SessionContext::new_with_config_rt(config, runtime);
        lance_datafusion::udf::register_functions(&context);
        let scan = Arc::new(MergeScanPolicy {
            partitions,
            decode_tasks,
            io_bytes,
            decode_bytes,
            width,
            use_budget: mode.budget(),
            use_native: mode.native() && width.is_some() && io_bytes.is_some(),
        });
        evidence(
            json!({"phase":"resources", "revision":"C-r2", "mode":format!("{mode:?}"), "policy_bytes":policy_bytes,
            "pool": if mode == ExperimentMode::PrepUnbounded {"unbounded"} else {"FairSpillPool"},
            "requested_p":requested, "effective_p":partitions, "decode_tasks":decode_tasks,
            "prefix_bytes":prefix_bytes, "prefix_rows":prefix_rows, "prefix_batches":1024,
            "small_target_bytes":(32 * 1024 * 1024).min(policy_bytes / 4), "width":width,
            "width_source":if fixed_width.is_some() {"fixed_projection"} else if width.is_some() {"file_bytes_per_physical_row"} else {"unavailable"},
            "io_bytes":io_bytes, "decode_bytes":decode_bytes,
            "row_cap":get_default_batch_size().unwrap_or_else(|| (dataset.object_store.block_size()/4).max(BATCH_SIZE_FALLBACK)),
            "context":format!("{:p}", context.runtime_env())}),
        );
        Ok(Self {
            context,
            mode,
            policy_bytes,
            prefix_bytes,
            prefix_rows,
            scan,
        })
    }
}

// Include a conservative byte per validity bitmap, including non-nullable fields.
// Nested and variable-width fields stay unmodeled until their accounting is tested.
pub(super) fn fixed_schema_width(schema: &Schema) -> Option<u64> {
    schema.fields().iter().try_fold(0u64, |width, field| {
        if field.metadata().contains_key("ARROW:extension:name") {
            return None;
        }
        let bytes = match field.data_type() {
            DataType::Null => 0,
            DataType::Boolean => 1,
            DataType::FixedSizeBinary(size) if *size >= 0 => *size as u64,
            data_type if data_type.is_primitive() => data_type.primitive_width()? as u64,
            _ => return None,
        };
        width.checked_add(bytes)?.checked_add(1)
    })
}

pub fn evidence(mut value: Value) {
    if let Some(path) = std::env::var_os("LANCE_MERGE_EVIDENCE") {
        if let Some(object) = value.as_object_mut() {
            object.insert(
                "unix_seconds".into(),
                json!(
                    std::time::SystemTime::now()
                        .duration_since(std::time::UNIX_EPOCH)
                        .ok()
                        .map(|elapsed| elapsed.as_secs_f64())
                ),
            );
        }
        let write = || -> std::io::Result<()> {
            let mut file = std::fs::OpenOptions::new()
                .append(true)
                .create(true)
                .open(path)?;
            writeln!(file, "{value}")
        };
        if let Err(error) = write() {
            log::warn!("Could not write merge experiment evidence: {error}");
        }
    }
}

pub(super) fn resource_gauges(plan: &dyn ExecutionPlan, output: &mut Vec<Value>) {
    if matches!(
        plan.name(),
        "FilteredReadExec" | "HashJoinExec" | "RepartitionExec" | "CoalescePartitionsExec"
    ) {
        output.push(json!({"kind":"topology", "operator":plan.name(), "output_p":plan.properties().output_partitioning().partition_count()}));
    }
    if let Some(join) = plan.downcast_ref::<datafusion::physical_plan::joins::HashJoinExec>() {
        output.push(json!({"kind":"join", "mode":format!("{:?}", join.partition_mode()),
            "build_fields":join.left().schema().fields().iter().map(|field| field.name()).collect::<Vec<_>>(),
            "probe_fields":join.right().schema().fields().iter().map(|field| field.name()).collect::<Vec<_>>()}));
    }
    if let Some(metrics) = plan.metrics() {
        for metric in metrics.iter() {
            if let MetricValue::Gauge { name, gauge } = metric.value()
                && matches!(
                    name.as_ref(),
                    "build_mem_used" | "active_read_tasks" | "peak_read_tasks"
                )
            {
                output.push(json!({"operator":plan.name(), "partition":metric.partition(), "name":name, "value":gauge.value()}));
            }
        }
    }
    for child in plan.children() {
        resource_gauges(child.as_ref(), output);
    }
}

pub(super) fn preparation_evidence(
    start: Instant,
    rows: usize,
    bytes: usize,
    batches: usize,
    reason: &str,
) {
    evidence(
        json!({"phase":"source_prepared", "seconds":start.elapsed().as_secs_f64(), "rows":rows, "arrow_bytes":bytes, "batches":batches, "stop":reason}),
    );
}
