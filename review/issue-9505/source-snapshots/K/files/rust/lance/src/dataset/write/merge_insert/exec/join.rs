// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: Copyright The Lance Authors

use std::sync::Arc;

use arrow_schema::{DataType, Schema};
use datafusion::common::{
    DataFusionError, Result, Statistics, config::ConfigOptions, stats::Precision,
};
use datafusion::execution::{TaskContext, memory_pool::MemoryLimit};
use datafusion::physical_expr::expressions::{Column, Literal};
use datafusion::physical_plan::{
    DisplayAs, DisplayFormatType, ExecutionPlan, PhysicalExpr, PlanProperties,
    SendableRecordBatchStream,
    filter::FilterExec,
    filter_pushdown::{FilterDescription, FilterPushdownPhase},
    joins::{HashJoinExec, PartitionMode},
    projection::ProjectionExec,
};
use lance_core::ROW_ADDR;

use super::super::MERGE_SOURCE_SENTINEL;

/// Give an unknown source the build side when a fixed-width target projection
/// exceeds the admission budget. Keep Auto for variable-width or unknown target
/// sizes, where neither side can be proved smaller without reading the streams.
pub fn prepare_merge_join(
    input: Arc<dyn ExecutionPlan>,
    on: &[String],
    pool_limit: MemoryLimit,
) -> Result<Arc<dyn ExecutionPlan>> {
    // This is deliberately a conservative admission heuristic, not a complete
    // hash-join memory bound. Leave headroom for the probe, writer and Take.
    let target_limit = match pool_limit {
        MemoryLimit::Finite(bytes) => bytes / 4,
        MemoryLimit::Infinite | MemoryLimit::Unknown => return Ok(input),
    };
    prepare_join(input, on, target_limit)
}

fn prepare_join(
    input: Arc<dyn ExecutionPlan>,
    on: &[String],
    target_limit: usize,
) -> Result<Arc<dyn ExecutionPlan>> {
    if let Some(join) = input.downcast_ref::<HashJoinExec>() {
        let target = join.left().clone();
        let source = join.right().clone();
        // Only recognize the merge's own join. A user-supplied provider can
        // contain joins too, and their direction is not ours to choose.
        let is_merge_join = target.schema().column_with_name(ROW_ADDR).is_some()
            && target
                .schema()
                .column_with_name(MERGE_SOURCE_SENTINEL)
                .is_none()
            && source
                .schema()
                .column_with_name(MERGE_SOURCE_SENTINEL)
                .is_some()
            && join.on().len() == on.len()
            && join.on().iter().zip(on).all(|((left, right), name)| {
                left.as_ref()
                    .downcast_ref::<Column>()
                    .is_some_and(|column| column.name() == name)
                    && right
                        .as_ref()
                        .downcast_ref::<Column>()
                        .is_some_and(|column| column.name() == name)
            });
        if !is_merge_join {
            return Ok(input);
        }
        let statistics = target.partition_statistics(None)?;
        let target_bytes = match (fixed_width(target.schema().as_ref()), statistics.num_rows) {
            (Some(width), Precision::Exact(rows)) => width
                .checked_mul(2)
                .and_then(|bytes| bytes.checked_add(64))
                .and_then(|bytes| bytes.checked_mul(rows))
                .and_then(|bytes| bytes.checked_add(1024 * 1024)),
            _ => None,
        };
        let Some(target_bytes) = target_bytes else {
            return Ok(input);
        };
        let mut source_has_exact_size = matches!(
            source.partition_statistics(None)?.total_byte_size,
            Precision::Exact(_)
        );
        // The merge adds a Boolean sentinel through a projection. DataFusion
        // recomputes that projection's byte estimate and loses the child's Exact
        // precision. Recognize only column passthrough plus our sentinel so a
        // measured provider does not become an unknown stream at this boundary.
        if let Some(projection) = source.downcast_ref::<ProjectionExec>()
            && projection.expr().iter().all(|projection| {
                projection.expr.downcast_ref::<Column>().is_some()
                    || (projection.alias == MERGE_SOURCE_SENTINEL
                        && projection
                            .expr
                            .downcast_ref::<Literal>()
                            .is_some_and(|literal| {
                                matches!(
                                    literal.value(),
                                    datafusion::common::ScalarValue::Boolean(Some(true))
                                )
                            }))
            })
        {
            source_has_exact_size |= matches!(
                projection
                    .input()
                    .partition_statistics(None)?
                    .total_byte_size,
                Precision::Exact(_)
            );
        }
        // A materialized source has a measured size. For a fixed-width target,
        // leave Auto free to choose either side even beyond our small-target
        // admission limit; forcing a much larger known source would regress it.
        if target_bytes <= target_limit || source_has_exact_size {
            return Ok(input);
        }
        // DataFusion also falls back to row count when byte size is unavailable.
        // Withdraw both hints at this boundary so join selection cannot put the
        // target back on the build side after it exceeded our admission budget.
        let target = Arc::new(MergeTargetStatsGuardExec { input: target });
        let guarded = input.with_new_children(vec![target, source])?;
        let guarded = guarded.downcast_ref::<HashJoinExec>().ok_or_else(|| {
            DataFusionError::Internal("Rebuilding the merge join changed its operator type".into())
        })?;
        return guarded.swap_inputs(PartitionMode::Auto);
    }
    if input.downcast_ref::<ProjectionExec>().is_some()
        || input.downcast_ref::<FilterExec>().is_some()
    {
        let children = input.children();
        if let [child] = children.as_slice() {
            let child = prepare_join((*child).clone(), on, target_limit)?;
            return input.with_new_children(vec![child]);
        }
    }
    Ok(input)
}

fn fixed_width(schema: &Schema) -> Option<usize> {
    schema.fields().iter().try_fold(0usize, |total, field| {
        if field.metadata().contains_key("ARROW:extension:name") {
            return None;
        }
        let width = match field.data_type() {
            DataType::Null => 0,
            DataType::Boolean => 1,
            DataType::FixedSizeBinary(width) => usize::try_from(*width).ok()?,
            data_type if data_type.is_primitive() => data_type.primitive_width()?,
            _ => return None,
        };
        // One byte per validity bit is conservative, including non-null fields.
        total.checked_add(width)?.checked_add(1)
    })
}

/// Keep unsafe target cardinality/size hints out of the join-selection rule,
/// including when DataFusion's statistics registry is enabled.
#[derive(Debug)]
struct MergeTargetStatsGuardExec {
    input: Arc<dyn ExecutionPlan>,
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
                DataFusionError::Internal(format!(
                    "Merge target statistics guard expected 1 child, got {}",
                    children.len()
                ))
            })?;
        Ok(Arc::new(Self { input }))
    }

    fn partition_statistics(&self, partition: Option<usize>) -> Result<Arc<Statistics>> {
        let mut statistics = self.input.partition_statistics(partition)?.as_ref().clone();
        statistics.num_rows = Precision::Absent;
        statistics.total_byte_size = Precision::Absent;
        Ok(Arc::new(statistics))
    }

    fn execute(
        &self,
        partition: usize,
        context: Arc<TaskContext>,
    ) -> Result<SendableRecordBatchStream> {
        self.input.execute(partition, context)
    }

    fn reset_state(self: Arc<Self>) -> Result<Arc<dyn ExecutionPlan>> {
        Ok(Arc::new(Self {
            input: self.input.clone().reset_state()?,
        }))
    }

    fn try_swapping_with_projection(
        &self,
        projection: &ProjectionExec,
    ) -> Result<Option<Arc<dyn ExecutionPlan>>> {
        let projection = ProjectionExec::try_new(projection.expr().to_vec(), self.input.clone())?;
        let input = self
            .input
            .try_swapping_with_projection(&projection)?
            .unwrap_or_else(|| Arc::new(projection));
        Ok(Some(Arc::new(Self { input })))
    }

    fn repartitioned(
        &self,
        partitions: usize,
        config: &ConfigOptions,
    ) -> Result<Option<Arc<dyn ExecutionPlan>>> {
        Ok(self
            .input
            .repartitioned(partitions, config)?
            .map(|input| Arc::new(Self { input }) as Arc<dyn ExecutionPlan>))
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
    use arrow_array::{RecordBatch, record_batch};
    use datafusion::common::{NullEquality, ScalarValue};
    use datafusion::datasource::memory::MemorySourceConfig;
    use datafusion::logical_expr::{JoinType, Operator};
    use datafusion::physical_expr::expressions::BinaryExpr;
    use datafusion::physical_optimizer::{PhysicalOptimizerRule, join_selection::JoinSelection};
    use datafusion::physical_plan::collect;
    use datafusion::physical_plan::operator_statistics::StatisticsRegistry;
    use lance_datafusion::exec::OneShotExec;

    fn find_join(plan: &dyn ExecutionPlan) -> Option<&HashJoinExec> {
        plan.downcast_ref::<HashJoinExec>().or_else(|| {
            plan.children()
                .into_iter()
                .find_map(|child| find_join(child.as_ref()))
        })
    }

    /// Synthetic cardinality for planner tests, without allocating large arrays.
    #[derive(Debug)]
    struct TargetCardinality {
        input: Arc<dyn ExecutionPlan>,
        rows: usize,
    }

    impl DisplayAs for TargetCardinality {
        fn fmt_as(&self, _: DisplayFormatType, f: &mut std::fmt::Formatter) -> std::fmt::Result {
            write!(f, "TargetCardinality")
        }
    }

    impl ExecutionPlan for TargetCardinality {
        fn name(&self) -> &str {
            "TargetCardinality"
        }
        fn properties(&self) -> &Arc<PlanProperties> {
            self.input.properties()
        }
        fn children(&self) -> Vec<&Arc<dyn ExecutionPlan>> {
            vec![&self.input]
        }
        fn with_new_children(
            self: Arc<Self>,
            children: Vec<Arc<dyn ExecutionPlan>>,
        ) -> Result<Arc<dyn ExecutionPlan>> {
            Ok(Arc::new(Self {
                input: children[0].clone(),
                rows: self.rows,
            }))
        }
        fn partition_statistics(&self, _: Option<usize>) -> Result<Arc<Statistics>> {
            let mut statistics = self.input.partition_statistics(None)?.as_ref().clone();
            statistics.num_rows = Precision::Exact(self.rows);
            statistics.total_byte_size = Precision::Exact(self.rows * 12);
            Ok(Arc::new(statistics))
        }
        fn execute(&self, _: usize, _: Arc<TaskContext>) -> Result<SendableRecordBatchStream> {
            unreachable!("TargetCardinality is only used by planner tests")
        }
    }

    #[rstest::rstest]
    #[case::fixed_small(false, false, 2, 128 * 1024 * 1024, true)]
    #[case::variable_keeps_existing_auto(true, false, 2, 128 * 1024 * 1024, true)]
    #[case::fixed_budget_exceeded(false, false, 2, 1, false)]
    #[case::measured_source_preserves_auto(false, true, 2, 1, true)]
    #[case::medium_target_keeps_streaming_source(false, false, 1_000_000, 1024 * 1024 * 1024, true)]
    #[case::large_target_builds_unknown_source(false, false, 1_000_000, 128 * 1024 * 1024, false)]
    #[test]
    fn final_join_uses_projected_target_size(
        #[case] variable: bool,
        #[case] measured_source: bool,
        #[case] target_rows: usize,
        #[case] pool_bytes: usize,
        #[case] target_build: bool,
    ) {
        let target = if variable {
            record_batch!(("key", Utf8, ["one", "two"]), ("_rowaddr", UInt64, [0, 1])).unwrap()
        } else {
            record_batch!(("key", UInt32, [1, 2]), ("_rowaddr", UInt64, [0, 1])).unwrap()
        };
        let source_schema = Arc::new(Schema::new(vec![target.schema().field(0).clone()]));
        let source_batch =
            RecordBatch::try_new(source_schema.clone(), vec![target.column(0).clone()]).unwrap();
        for registry in [false, true] {
            let mut target: Arc<dyn ExecutionPlan> =
                MemorySourceConfig::try_new_exec(&[vec![target.clone()]], target.schema(), None)
                    .unwrap();
            if target_rows != 2 {
                target = Arc::new(TargetCardinality {
                    input: target,
                    rows: target_rows,
                });
            }
            let source: Arc<dyn ExecutionPlan> = if measured_source {
                MemorySourceConfig::try_new_exec(
                    &[vec![source_batch.clone(); 64]],
                    source_schema.clone(),
                    None,
                )
                .unwrap()
            } else {
                Arc::new(OneShotExec::from_batch(RecordBatch::new_empty(
                    source_schema.clone(),
                )))
            };
            // Match create_plan's actual source shape: the sentinel is added by
            // ProjectionExec, whose byte estimate is not Exact for Boolean.
            let source = Arc::new(
                ProjectionExec::try_new(
                    vec![
                        (
                            Arc::new(Column::new("key", 0)) as Arc<dyn PhysicalExpr>,
                            "key".to_string(),
                        ),
                        (
                            Arc::new(Literal::new(ScalarValue::Boolean(Some(true))))
                                as Arc<dyn PhysicalExpr>,
                            MERGE_SOURCE_SENTINEL.to_string(),
                        ),
                    ],
                    source,
                )
                .unwrap(),
            );
            let join: Arc<dyn ExecutionPlan> = Arc::new(
                HashJoinExec::try_new(
                    target,
                    source,
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
            let prepared =
                prepare_merge_join(join, &["key".to_string()], MemoryLimit::Finite(pool_bytes))
                    .unwrap();
            let mut config = ConfigOptions::new();
            config.optimizer.use_statistics_registry = registry;
            let optimized = JoinSelection::new().optimize(prepared, &config).unwrap();
            let join = find_join(optimized.as_ref()).unwrap();
            assert_eq!(
                join.left().schema().column_with_name(ROW_ADDR).is_some(),
                target_build
            );
            assert_eq!(
                *join.partition_mode(),
                if target_build && target_rows == 2 {
                    PartitionMode::CollectLeft
                } else {
                    PartitionMode::Partitioned
                }
            );
        }
    }

    #[test]
    fn guard_masks_both_statistics_for_the_registry() {
        let batch = record_batch!(("key", UInt32, [1, 2])).unwrap();
        let input =
            MemorySourceConfig::try_new_exec(&[vec![batch.clone()]], batch.schema(), None).unwrap();
        let columns = input
            .partition_statistics(None)
            .unwrap()
            .column_statistics
            .clone();
        let guarded = MergeTargetStatsGuardExec { input };
        let registry = StatisticsRegistry::default_with_builtin_providers();
        let statistics = registry.compute(&guarded).unwrap();
        assert_eq!(statistics.base().num_rows, Precision::Absent);
        assert_eq!(statistics.base().total_byte_size, Precision::Absent);
        assert_eq!(statistics.base().column_statistics, columns);
    }

    #[tokio::test]
    async fn guard_preserves_projection_and_filter_results() {
        let batch = record_batch!(("key", UInt32, [1, 2]), ("extra", UInt32, [10, 20])).unwrap();
        let input =
            MemorySourceConfig::try_new_exec(&[vec![batch.clone()]], batch.schema(), None).unwrap();
        let guard: Arc<dyn ExecutionPlan> = Arc::new(MergeTargetStatsGuardExec { input });
        let projection = ProjectionExec::try_new(
            vec![(
                Arc::new(Column::new("key", 0)) as Arc<dyn PhysicalExpr>,
                "key".to_string(),
            )],
            guard.clone(),
        )
        .unwrap();
        let projected = guard
            .try_swapping_with_projection(&projection)
            .unwrap()
            .unwrap();
        let predicate = Arc::new(BinaryExpr::new(
            Arc::new(Column::new("key", 0)),
            Operator::Gt,
            Arc::new(Literal::new(ScalarValue::UInt32(Some(1)))),
        ));
        let filtered: Arc<dyn ExecutionPlan> =
            Arc::new(FilterExec::try_new(predicate, projected).unwrap());
        let actual = collect(filtered, Arc::new(TaskContext::default()))
            .await
            .unwrap();
        assert_eq!(actual, vec![record_batch!(("key", UInt32, [2])).unwrap()]);
    }
}
