// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: Copyright The Lance Authors

use std::sync::Arc;

use datafusion::common::{Result, Statistics, config::ConfigOptions, stats::Precision};
use datafusion::execution::TaskContext;
use datafusion::physical_plan::{
    DisplayAs, DisplayFormatType, ExecutionPlan, PhysicalExpr, PlanProperties,
    SendableRecordBatchStream,
    filter_pushdown::{FilterDescription, FilterPushdownPhase},
};

/// Withdraws unsafe size and cardinality hints only at the merge target boundary.
/// CardinalityEffect deliberately stays Unknown: the statistics registry must call us.
#[derive(Debug)]
pub(super) struct MergeTargetStatsGuardExec {
    input: Arc<dyn ExecutionPlan>,
}

impl MergeTargetStatsGuardExec {
    pub fn new(input: Arc<dyn ExecutionPlan>) -> Self {
        Self { input }
    }
}

impl DisplayAs for MergeTargetStatsGuardExec {
    fn fmt_as(&self, _: DisplayFormatType, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        write!(f, "MergeTargetStatsGuard: rows=Absent, bytes=Absent")
    }
}

impl ExecutionPlan for MergeTargetStatsGuardExec {
    fn name(&self) -> &str {
        "MergeTargetStatsGuardExec"
    }
    fn properties(&self) -> &Arc<PlanProperties> {
        self.input.properties()
    }
    fn children(&self) -> Vec<&Arc<dyn ExecutionPlan>> {
        vec![&self.input]
    }
    fn maintains_input_order(&self) -> Vec<bool> {
        vec![true]
    }
    fn with_new_children(
        self: Arc<Self>,
        children: Vec<Arc<dyn ExecutionPlan>>,
    ) -> Result<Arc<dyn ExecutionPlan>> {
        let [input]: [Arc<dyn ExecutionPlan>; 1] =
            children.try_into().map_err(|children: Vec<_>| {
                datafusion::common::DataFusionError::Internal(format!(
                    "StatsGuard expected 1 child, got {}",
                    children.len()
                ))
            })?;
        Ok(Arc::new(Self::new(input)))
    }
    fn partition_statistics(&self, partition: Option<usize>) -> Result<Arc<Statistics>> {
        let mut stats = self.input.partition_statistics(partition)?.as_ref().clone();
        stats.num_rows = Precision::Absent;
        stats.total_byte_size = Precision::Absent;
        Ok(Arc::new(stats))
    }
    fn execute(
        &self,
        partition: usize,
        context: Arc<TaskContext>,
    ) -> Result<SendableRecordBatchStream> {
        self.input.execute(partition, context)
    }

    fn reset_state(self: Arc<Self>) -> Result<Arc<dyn ExecutionPlan>> {
        Ok(Arc::new(Self::new(self.input.clone().reset_state()?)))
    }

    fn try_swapping_with_projection(
        &self,
        projection: &datafusion::physical_plan::projection::ProjectionExec,
    ) -> Result<Option<Arc<dyn ExecutionPlan>>> {
        let projection = datafusion::physical_plan::projection::ProjectionExec::try_new(
            projection.expr().to_vec(),
            self.input.clone(),
        )?;
        let input = self
            .input
            .try_swapping_with_projection(&projection)?
            .unwrap_or_else(|| Arc::new(projection));
        // A later physical projection can narrow the schema. Retain the conservative mask.
        Ok(Some(Arc::new(Self::new(input))))
    }
    fn repartitioned(
        &self,
        partitions: usize,
        config: &ConfigOptions,
    ) -> Result<Option<Arc<dyn ExecutionPlan>>> {
        Ok(self
            .input
            .repartitioned(partitions, config)?
            .map(|input| Arc::new(Self::new(input)) as Arc<dyn ExecutionPlan>))
    }
    fn gather_filters_for_pushdown(
        &self,
        _: FilterPushdownPhase,
        filters: Vec<Arc<dyn PhysicalExpr>>,
        _: &ConfigOptions,
    ) -> Result<FilterDescription> {
        FilterDescription::from_children(filters, &self.children())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use arrow_array::record_batch;
    use datafusion::common::NullEquality;
    use datafusion::datasource::memory::MemorySourceConfig;
    use datafusion::logical_expr::JoinType;
    use datafusion::physical_expr::expressions::Column;
    use datafusion::physical_optimizer::{PhysicalOptimizerRule, join_selection::JoinSelection};
    use datafusion::physical_plan::collect;
    use datafusion::physical_plan::joins::{HashJoinExec, PartitionMode};
    use datafusion::physical_plan::operator_statistics::StatisticsRegistry;
    use lance_datafusion::exec::OneShotExec;

    #[tokio::test]
    async fn guard_survives_registry_and_preserves_rows() {
        let batch = record_batch!(
            ("key", Int64, [1, 2]),
            ("payload", Utf8, ["old-one", "old-two"])
        )
        .unwrap();
        let input =
            MemorySourceConfig::try_new_exec(&[vec![batch.clone()]], batch.schema(), None).unwrap();
        let plan: Arc<dyn ExecutionPlan> = Arc::new(MergeTargetStatsGuardExec::new(input));
        for registry in [
            StatisticsRegistry::new(),
            StatisticsRegistry::default_with_builtin_providers(),
        ] {
            let stats = registry.compute(plan.as_ref()).unwrap();
            assert_eq!(stats.base().num_rows, Precision::Absent);
            assert_eq!(stats.base().total_byte_size, Precision::Absent);
        }
        let stats = plan.partition_statistics(None).unwrap();
        assert_eq!(stats.num_rows, Precision::Absent);
        assert_eq!(stats.total_byte_size, Precision::Absent);
        let rebuilt = plan.clone().reset_state().unwrap();
        let output = collect(rebuilt, Arc::new(TaskContext::default()))
            .await
            .unwrap();
        assert_eq!(output, vec![batch]);
    }

    #[derive(Debug)]
    struct BytesOnly(Arc<dyn ExecutionPlan>);
    impl DisplayAs for BytesOnly {
        fn fmt_as(&self, _: DisplayFormatType, f: &mut std::fmt::Formatter) -> std::fmt::Result {
            write!(f, "BytesOnlyCounterfactual")
        }
    }
    impl ExecutionPlan for BytesOnly {
        fn name(&self) -> &str {
            "BytesOnlyCounterfactual"
        }
        fn properties(&self) -> &Arc<PlanProperties> {
            self.0.properties()
        }
        fn children(&self) -> Vec<&Arc<dyn ExecutionPlan>> {
            vec![&self.0]
        }
        fn with_new_children(
            self: Arc<Self>,
            children: Vec<Arc<dyn ExecutionPlan>>,
        ) -> Result<Arc<dyn ExecutionPlan>> {
            Ok(Arc::new(Self(children[0].clone())))
        }
        fn partition_statistics(&self, _: Option<usize>) -> Result<Arc<Statistics>> {
            let mut stats = self.0.partition_statistics(None)?.as_ref().clone();
            stats.num_rows = Precision::Exact(200);
            stats.total_byte_size = Precision::Absent;
            Ok(Arc::new(stats))
        }
        fn execute(
            &self,
            partition: usize,
            context: Arc<TaskContext>,
        ) -> Result<SendableRecordBatchStream> {
            self.0.execute(partition, context)
        }
    }

    fn hash_join(plan: &Arc<dyn ExecutionPlan>) -> &HashJoinExec {
        if let Some(join) = plan.downcast_ref::<HashJoinExec>() {
            return join;
        }
        hash_join(plan.children()[0])
    }

    #[rstest::rstest]
    #[case::registry_off(false)]
    #[case::registry_on(true)]
    #[test]
    fn dual_absent_prevents_auto_collect_row_fallback(#[case] registry: bool) {
        let mut config = ConfigOptions::new();
        // This is DataFusion 54.1's actual JoinSelection registry switch.
        config.optimizer.use_statistics_registry = registry;
        for guarded in [false, true] {
            let source = record_batch!(("key", Int64, [1]), ("source_marker", Int64, [7])).unwrap();
            let source: Arc<dyn ExecutionPlan> = Arc::new(OneShotExec::from_batch(source));
            let target = record_batch!(("key", Int64, [1]), ("payload", Utf8, ["old"])).unwrap();
            let target =
                MemorySourceConfig::try_new_exec(&[vec![target.clone()]], target.schema(), None)
                    .unwrap();
            let mut target: Arc<dyn ExecutionPlan> = Arc::new(BytesOnly(target));
            if guarded {
                target = Arc::new(MergeTargetStatsGuardExec::new(target));
            }
            let join: Arc<dyn ExecutionPlan> = Arc::new(
                HashJoinExec::try_new(
                    source,
                    target,
                    vec![(
                        Arc::new(Column::new("key", 0)),
                        Arc::new(Column::new("key", 0)),
                    )],
                    None,
                    &JoinType::Full,
                    None,
                    PartitionMode::Auto,
                    NullEquality::NullEqualsNothing,
                    false,
                )
                .unwrap(),
            );
            let optimized = JoinSelection::new().optimize(join, &config).unwrap();
            let join = hash_join(&optimized);
            assert_eq!(
                join.left()
                    .schema()
                    .column_with_name("source_marker")
                    .is_some(),
                guarded
            );
            assert_eq!(
                *join.partition_mode(),
                if guarded {
                    PartitionMode::Partitioned
                } else {
                    PartitionMode::CollectLeft
                }
            );
        }
    }
}
