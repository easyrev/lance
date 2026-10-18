// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: Copyright The Lance Authors

use std::sync::Arc;

use arrow_array::{
    Array, RecordBatch, UInt32Array,
    cast::AsArray,
    types::{UInt8Type, UInt64Type},
};
use arrow_schema::{Schema, SchemaRef};
use arrow_select::take::take;
use datafusion::common::{DataFusionError, Result};
use datafusion::execution::TaskContext;
use datafusion::physical_expr::{EquivalenceProperties, Partitioning};
use datafusion::physical_plan::{
    DisplayAs, DisplayFormatType, Distribution, ExecutionPlan, PlanProperties,
    SendableRecordBatchStream,
    execution_plan::{Boundedness, EmissionType},
    metrics::{ExecutionPlanMetricsSet, MetricBuilder, MetricsSet},
    stream::RecordBatchStreamAdapter,
};
use futures::TryStreamExt;
use lance_core::ROW_ADDR;
use lance_datafusion::projection::ProjectionPlan;

use super::super::{MERGE_ACTION_COLUMN, assign_action::Action};
use crate::{Dataset, dataset::TakeBuilder};

/// Serial, action-aware payload retrieval from the same snapshot that produced the addresses.
#[derive(Debug)]
pub(in crate::dataset::write::merge_insert) struct MergePayloadExec {
    input: Arc<dyn ExecutionPlan>,
    dataset: Arc<Dataset>,
    columns: Vec<String>,
    take: Arc<ProjectionPlan>,
    schema: SchemaRef,
    properties: Arc<PlanProperties>,
    metrics: ExecutionPlanMetricsSet,
}

impl MergePayloadExec {
    pub fn try_new(
        input: Arc<dyn ExecutionPlan>,
        dataset: Arc<Dataset>,
        columns: Vec<String>,
    ) -> Result<Self> {
        let projection = dataset.schema().project(&columns)?;
        let take = Arc::new(ProjectionPlan::from_schema(dataset.clone(), &projection)?);
        let taken_schema = take.output_schema()?;
        let fields = input
            .schema()
            .fields()
            .iter()
            .cloned()
            .chain(
                taken_schema
                    .fields()
                    .iter()
                    .map(|field| Arc::new(field.as_ref().clone().with_nullable(true))),
            )
            .collect::<Vec<_>>();
        let schema = Arc::new(Schema::new(fields));
        let properties = Arc::new(PlanProperties::new(
            EquivalenceProperties::new(schema.clone()),
            Partitioning::UnknownPartitioning(1),
            EmissionType::Incremental,
            Boundedness::Bounded,
        ));
        Ok(Self {
            input,
            dataset,
            columns,
            take,
            schema,
            properties,
            metrics: ExecutionPlanMetricsSet::new(),
        })
    }
}

impl DisplayAs for MergePayloadExec {
    fn fmt_as(&self, _: DisplayFormatType, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        write!(
            f,
            "MergePayload: columns={:?}, snapshot={}",
            self.columns,
            self.dataset.version().version
        )
    }
}

impl ExecutionPlan for MergePayloadExec {
    fn name(&self) -> &str {
        "MergePayloadExec"
    }
    fn properties(&self) -> &Arc<PlanProperties> {
        &self.properties
    }
    fn children(&self) -> Vec<&Arc<dyn ExecutionPlan>> {
        vec![&self.input]
    }
    fn required_input_distribution(&self) -> Vec<Distribution> {
        vec![Distribution::SinglePartition]
    }
    fn benefits_from_input_partitioning(&self) -> Vec<bool> {
        vec![false]
    }
    fn with_new_children(
        self: Arc<Self>,
        children: Vec<Arc<dyn ExecutionPlan>>,
    ) -> Result<Arc<dyn ExecutionPlan>> {
        let [input]: [Arc<dyn ExecutionPlan>; 1] =
            children.try_into().map_err(|children: Vec<_>| {
                DataFusionError::Internal(format!(
                    "MergePayload expected 1 child, got {}",
                    children.len()
                ))
            })?;
        Ok(Arc::new(Self::try_new(
            input,
            self.dataset.clone(),
            self.columns.clone(),
        )?))
    }
    fn metrics(&self) -> Option<MetricsSet> {
        Some(self.metrics.clone_inner())
    }
    fn execute(
        &self,
        partition: usize,
        context: Arc<TaskContext>,
    ) -> Result<SendableRecordBatchStream> {
        if partition != 0 {
            return Err(DataFusionError::Internal(format!(
                "MergePayload expected partition 0, got {partition}"
            )));
        }
        let dataset = self.dataset.clone();
        let projection = self.take.clone();
        let names = self.columns.clone();
        let schema = self.schema.clone();
        let rows_metric = MetricBuilder::new(&self.metrics).counter("payload_take_rows", partition);
        let bytes_metric =
            MetricBuilder::new(&self.metrics).counter("payload_take_arrow_bytes", partition);
        let output_schema = schema.clone();
        let stream = self
            .input
            .execute(partition, context)?
            .and_then(move |batch| {
                let dataset = dataset.clone();
                let projection = projection.clone();
                let names = names.clone();
                let schema = schema.clone();
                let rows_metric = rows_metric.clone();
                let bytes_metric = bytes_metric.clone();
                async move {
                    let actions = batch
                        .column_by_name(MERGE_ACTION_COLUMN)
                        .and_then(|a| a.as_primitive_opt::<UInt8Type>())
                        .ok_or_else(|| {
                            DataFusionError::Internal("MergePayload requires UInt8 actions".into())
                        })?;
                    let addresses = batch
                        .column_by_name(ROW_ADDR)
                        .and_then(|a| a.as_primitive_opt::<UInt64Type>())
                        .ok_or_else(|| {
                            DataFusionError::Internal(
                                "MergePayload requires UInt64 row addresses".into(),
                            )
                        })?;
                    let mut addrs = Vec::new();
                    let mut gather = vec![None; batch.num_rows()];
                    for (row, index) in gather.iter_mut().enumerate() {
                        if actions.value(row) == Action::UpdateAll as u8 {
                            if addresses.is_null(row) {
                                return Err(DataFusionError::Internal(
                                    "MergePayload update has no target address".into(),
                                ));
                            }
                            *index = Some(
                                u32::try_from(addrs.len())
                                    .map_err(|e| DataFusionError::Internal(e.to_string()))?,
                            );
                            addrs.push(addresses.value(row));
                        }
                    }
                    let mut columns = batch.columns().to_vec();
                    if addrs.is_empty() {
                        columns.extend(schema.fields()[columns.len()..].iter().map(|field| {
                            arrow_array::new_null_array(field.data_type(), batch.num_rows())
                        }));
                    } else {
                        let expected = addrs.len();
                        let taken =
                            TakeBuilder::try_new_from_addresses(dataset, addrs, projection)?
                                .execute()
                                .await?;
                        if taken.num_rows() != expected {
                            return Err(DataFusionError::Internal(format!(
                                "MergePayload took {} of {expected} rows",
                                taken.num_rows()
                            )));
                        }
                        rows_metric.add(expected);
                        bytes_metric.add(taken.get_array_memory_size());
                        let indices = UInt32Array::from(gather);
                        for name in &names {
                            let column = taken.column_by_name(name).ok_or_else(|| {
                                DataFusionError::Internal(format!(
                                    "MergePayload take omitted {name}"
                                ))
                            })?;
                            columns.push(take(column, &indices, None)?);
                        }
                    }
                    Ok(RecordBatch::try_new(schema, columns)?)
                }
            });
        Ok(Box::pin(RecordBatchStreamAdapter::new(
            output_schema,
            stream,
        )))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::utils::test::{DatagenExt, FragmentCount, FragmentRowCount};
    use arrow_array::record_batch;
    use datafusion::datasource::memory::MemorySourceConfig;
    use datafusion::physical_plan::collect;
    use lance_core::utils::address::RowAddress;
    use lance_datagen::{array, gen_batch};

    #[tokio::test(start_paused = true)]
    async fn payload_pending_take_is_released_on_cancel() {
        use crate::utils::test::ThrottledStoreWrapper;
        use futures::StreamExt;
        use lance_io::object_store::WrappingObjectStore;
        use object_store::throttle::ThrottleConfig;
        use std::time::Duration;

        let original = Arc::new(
            gen_batch()
                .col("key", array::step::<UInt64Type>())
                .col("old", array::step::<UInt64Type>())
                .into_ram_dataset(FragmentCount::from(1), FragmentRowCount::from(1))
                .await
                .unwrap(),
        );
        let wrapper: Arc<dyn WrappingObjectStore> = Arc::new(ThrottledStoreWrapper {
            config: ThrottleConfig {
                wait_get_per_call: Duration::from_secs(60),
                ..Default::default()
            },
        });
        let dataset = Arc::new(original.with_object_store_wrappers([wrapper]));
        let snapshot = Arc::downgrade(&dataset);
        let batch = record_batch!(
            ("key", UInt64, [0]),
            ("_rowaddr", UInt64, [0]),
            ("__action", UInt8, [1])
        )
        .unwrap();
        let input =
            MemorySourceConfig::try_new_exec(&[vec![batch.clone()]], batch.schema(), None).unwrap();
        let plan = MergePayloadExec::try_new(input, dataset, vec!["old".into()]).unwrap();
        let mut stream = plan.execute(0, Arc::new(TaskContext::default())).unwrap();
        let mut next = Box::pin(stream.next());
        assert!(futures::poll!(&mut next).is_pending());
        drop(next);
        drop(stream);
        drop(plan);
        assert!(snapshot.upgrade().is_none());
        assert_eq!(original.latest_version_id().await.unwrap(), 1);
        let unchanged = original.scan().try_into_batch().await.unwrap();
        assert_eq!(unchanged["old"].as_primitive::<UInt64Type>().value(0), 0);
        assert_eq!(unchanged.num_rows(), 1);
    }

    #[tokio::test]
    async fn payload_uses_physical_addresses_and_keeps_insert_rows() {
        let dataset = Arc::new(
            gen_batch()
                .col("key", array::step::<UInt64Type>())
                .col("old", array::step::<UInt64Type>())
                .into_ram_dataset(FragmentCount::from(2), FragmentRowCount::from(3))
                .await
                .unwrap(),
        );
        let addresses = [
            Some(u64::from(RowAddress::new_from_parts(1, 0))),
            Some(u64::from(RowAddress::new_from_parts(0, 1))),
            None,
            Some(0),
            Some(2),
        ];
        let batch = record_batch!(
            ("key", UInt64, [8, 8, 9, 10, 11]),
            ("_rowaddr", UInt64, addresses.to_vec()),
            ("__action", UInt8, [1, 1, 2, 3, 0])
        )
        .unwrap();
        let input =
            MemorySourceConfig::try_new_exec(&[vec![batch.clone()]], batch.schema(), None).unwrap();
        let plan: Arc<dyn ExecutionPlan> =
            Arc::new(MergePayloadExec::try_new(input, dataset, vec!["old".into()]).unwrap());
        let output = collect(plan, Arc::new(TaskContext::default()))
            .await
            .unwrap();
        assert_eq!(output.len(), 1);
        assert_eq!(output[0].num_rows(), 5);
        let old = output[0]["old"].as_primitive::<UInt64Type>();
        assert_eq!(
            old.iter().collect::<Vec<_>>(),
            vec![Some(3), Some(1), None, None, None]
        );
        assert_eq!(output[0]["__action"].to_data(), batch["__action"].to_data());
        assert!(
            output[0]
                .schema()
                .field_with_name("old")
                .unwrap()
                .is_nullable()
        );
    }

    #[tokio::test]
    async fn payload_take_error_is_not_an_empty_success() {
        let dataset = Arc::new(
            gen_batch()
                .col("key", array::step::<UInt64Type>())
                .col("old", array::step::<UInt64Type>())
                .into_ram_dataset(FragmentCount::from(1), FragmentRowCount::from(1))
                .await
                .unwrap(),
        );
        let address = u64::from(RowAddress::new_from_parts(99, 0));
        let batch = record_batch!(
            ("key", UInt64, [1]),
            ("_rowaddr", UInt64, [address]),
            ("__action", UInt8, [1])
        )
        .unwrap();
        let input =
            MemorySourceConfig::try_new_exec(&[vec![batch.clone()]], batch.schema(), None).unwrap();
        let plan: Arc<dyn ExecutionPlan> = Arc::new(
            MergePayloadExec::try_new(input, dataset.clone(), vec!["old".into()]).unwrap(),
        );
        let error = collect(plan, Arc::new(TaskContext::default()))
            .await
            .unwrap_err();
        assert!(matches!(error, DataFusionError::External(_)));
        assert!(
            error.to_string().contains("non-existent fragment: 99"),
            "{error}"
        );
        assert_eq!(dataset.version().version, 1);
    }
}
