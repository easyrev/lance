// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: Copyright The Lance Authors

use async_trait::async_trait;
use datafusion::common::Result as DFResult;
use datafusion::{
    common::DFSchema,
    execution::SessionState,
    physical_plan::ExecutionPlan,
    physical_planner::{ExtensionPlanner, PhysicalPlanner},
};
use datafusion_expr::{Expr, LogicalPlan, UserDefinedLogicalNode, UserDefinedLogicalNodeCore};
use lance_core::{ROW_ADDR, ROW_CREATED_AT_VERSION, ROW_ID};
use std::{
    cmp::Ordering,
    sync::{Arc, atomic::AtomicU64},
};

use crate::Dataset;
use crate::dataset::write::merge_insert::exec::{
    DeleteOnlyMergeInsertExec, FullSchemaMergeInsertExec, InPlaceMergeInsertExec,
    MergeConditionExec,
};
use crate::dataset::{WhenMatched, WhenNotMatchedBySource};

use super::candidate::{SourceEvidence, evidence, fixed_schema_width};
use super::stats_guard::MergeTargetStatsGuardExec;
use super::{MERGE_ACTION_COLUMN, MERGE_SOURCE_SENTINEL, MergeInsertParams};
use datafusion::common::stats::Precision;
use datafusion::physical_plan::{
    filter::FilterExec,
    joins::{HashJoinExec, PartitionMode},
    projection::ProjectionExec,
};
use serde_json::json;

/// Which write half a planned merge insert will use.
///
/// This is the *resolved* choice, so it has no `Auto`: the caller's
/// [`MergeInsertWriteMode`](super::MergeInsertWriteMode) is resolved against the
/// operation by [`MergeInsertJob::select_write_sink`](super::MergeInsertJob) before
/// the plan is built.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum WriteSink {
    /// Delete the matched rows and write whole rows into new fragments.
    RewriteRows,
    /// Attach new data files for the source columns to the fragments that
    /// already hold the matched rows and tombstone the old versions of those
    /// columns.
    RewriteColumns,
}

/// Logical plan node for merge insert write.
///
/// Expects input schema:
/// * `source.{col1, col2, ...}` - columns from the source relation
/// * `target.{col1, col2, ...}` - columns from the target relation
/// * `target._rowaddr` - special column to locate existing rows in the target
/// * `__action` - unqualified column that describes the action to perform.
///   See [`super::assign_action::merge_insert_action`]
///
/// Output is empty.
/// Conditions over target columns, evaluated by [`MergeConditionExec`] on the
/// rows they gate rather than folded into `__action`.
#[derive(Debug, Clone, Default, PartialEq, Eq, Hash, PartialOrd)]
pub struct DeferredConditions {
    /// `UpdateIf`, on the matched rows.
    pub update_if: Option<Expr>,
    /// `DeleteIf`, on the target-only rows.
    pub delete_if: Option<Expr>,
}

#[derive(Debug)]
pub struct MergeInsertWriteNode {
    input: LogicalPlan,
    pub(crate) dataset: Arc<Dataset>,
    pub(crate) params: MergeInsertParams,
    pub(crate) source_skipped_duplicates: Arc<AtomicU64>,
    pub(crate) write_sink: WriteSink,
    /// Blob columns supplied by the source, excluding target-filled columns.
    pub(crate) source_blob_columns: Vec<String>,
    pub(crate) deferred: DeferredConditions,
    deferred_target_columns: Vec<String>,
    schema: Arc<DFSchema>,
}

impl PartialEq for MergeInsertWriteNode {
    fn eq(&self, other: &Self) -> bool {
        self.params == other.params
            && self.write_sink == other.write_sink
            && self.source_blob_columns == other.source_blob_columns
            && self.deferred == other.deferred
            && self.deferred_target_columns == other.deferred_target_columns
            && self.input == other.input
            && self.dataset.base == other.dataset.base
    }
}

impl Eq for MergeInsertWriteNode {}

impl std::hash::Hash for MergeInsertWriteNode {
    fn hash<H: std::hash::Hasher>(&self, state: &mut H) {
        self.params.hash(state);
        self.write_sink.hash(state);
        self.source_blob_columns.hash(state);
        self.deferred.hash(state);
        self.deferred_target_columns.hash(state);
        self.input.hash(state);
        self.dataset.base.hash(state);
    }
}

impl PartialOrd for MergeInsertWriteNode {
    fn partial_cmp(&self, other: &Self) -> Option<std::cmp::Ordering> {
        match self.params.partial_cmp(&other.params) {
            Some(Ordering::Equal) => match self.write_sink.cmp(&other.write_sink) {
                Ordering::Equal => match self.source_blob_columns.cmp(&other.source_blob_columns) {
                    Ordering::Equal => match self.deferred.partial_cmp(&other.deferred) {
                        Some(Ordering::Equal) => match self
                            .deferred_target_columns
                            .cmp(&other.deferred_target_columns)
                        {
                            Ordering::Equal => self.input.partial_cmp(&other.input),
                            cmp => Some(cmp),
                        },
                        cmp => cmp,
                    },
                    cmp => Some(cmp),
                },
                cmp => Some(cmp),
            },
            cmp => cmp,
        }
    }
}

impl MergeInsertWriteNode {
    pub fn new(
        input: LogicalPlan,
        dataset: Arc<Dataset>,
        params: MergeInsertParams,
        source_skipped_duplicates: Arc<AtomicU64>,
        write_sink: WriteSink,
        source_blob_columns: Vec<String>,
        deferred: DeferredConditions,
    ) -> Self {
        let empty_schema = Arc::new(arrow_schema::Schema::empty());
        let schema = Arc::new(DFSchema::try_from(empty_schema).unwrap());
        Self {
            input,
            dataset,
            params,
            source_skipped_duplicates,
            write_sink,
            source_blob_columns,
            deferred,
            deferred_target_columns: Vec::new(),
            schema,
        }
    }

    pub(super) fn with_deferred_target_columns(mut self, columns: Vec<String>) -> Self {
        self.deferred_target_columns = columns;
        self
    }
}

impl UserDefinedLogicalNodeCore for MergeInsertWriteNode {
    fn name(&self) -> &str {
        "MergeInsertWrite"
    }

    fn inputs(&self) -> Vec<&LogicalPlan> {
        vec![&self.input]
    }

    fn schema(&self) -> &Arc<DFSchema> {
        &self.schema
    }

    fn expressions(&self) -> Vec<datafusion_expr::Expr> {
        vec![]
    }

    fn fmt_for_explain(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        let on_keys = self.params.on.join(", ");
        let when_matched = match &self.params.when_matched {
            crate::dataset::WhenMatched::DoNothing => "DoNothing",
            crate::dataset::WhenMatched::UpdateAll => "UpdateAll",
            crate::dataset::WhenMatched::UpdateIf(_) => "UpdateIf",
            crate::dataset::WhenMatched::UpdateIfExpr(_) => "UpdateIfExpr",
            crate::dataset::WhenMatched::Fail => "Fail",
            crate::dataset::WhenMatched::Delete => "Delete",
        };
        let when_not_matched = if self.params.insert_not_matched {
            "InsertAll"
        } else {
            "DoNothing"
        };
        let when_not_matched_by_source = match &self.params.delete_not_matched_by_source {
            crate::dataset::WhenNotMatchedBySource::Keep => "Keep",
            crate::dataset::WhenNotMatchedBySource::Delete => "Delete",
            crate::dataset::WhenNotMatchedBySource::DeleteIf(_) => "DeleteIf",
        };

        write!(
            f,
            "MergeInsertWrite: on=[{}], when_matched={}, when_not_matched={}, when_not_matched_by_source={}",
            on_keys, when_matched, when_not_matched, when_not_matched_by_source
        )?;
        if self.write_sink == WriteSink::RewriteColumns {
            write!(f, ", mode=RewriteColumns")?;
        }
        Ok(())
    }

    fn with_exprs_and_inputs(
        &self,
        exprs: Vec<datafusion_expr::Expr>,
        inputs: Vec<LogicalPlan>,
    ) -> datafusion::error::Result<Self> {
        if !exprs.is_empty() {
            return Err(datafusion::error::DataFusionError::Internal(
                "MergeInsertWriteNode does not accept expressions".to_string(),
            ));
        }
        if inputs.len() != 1 {
            return Err(datafusion::error::DataFusionError::Internal(
                "MergeInsertWriteNode requires exactly one input".to_string(),
            ));
        }
        Ok(Self::new(
            inputs[0].clone(),
            self.dataset.clone(),
            self.params.clone(),
            self.source_skipped_duplicates.clone(),
            self.write_sink,
            self.source_blob_columns.clone(),
            self.deferred.clone(),
        )
        .with_deferred_target_columns(self.deferred_target_columns.clone()))
    }

    fn necessary_children_exprs(&self, _output_columns: &[usize]) -> Option<Vec<Vec<usize>>> {
        // Going to need:
        // * all columns from the `source` relation (or just key columns for delete-only)
        // * `__action` column (unqualified)
        // * `target._rowaddr` column specifically

        let input_schema = self.input.schema();
        let mut necessary_columns = Vec::new();

        // Check if this is a delete-only operation (no writes needed)
        // In delete-only mode, we only need the key columns from source for matching
        let no_upsert = matches!(
            self.params.when_matched,
            crate::dataset::WhenMatched::Delete
        ) && !self.params.insert_not_matched;

        for (i, (qualifier, field)) in input_schema.iter().enumerate() {
            let should_include = match qualifier {
                // For delete-only: only include source KEY columns (for matching) plus the
                // sentinel column needed for action determination.
                // For other ops: include all source columns - they contain the new data to write.
                Some(qualifier) if qualifier.table() == "source" => {
                    if no_upsert {
                        self.params.on.iter().any(|k| k == field.name())
                            || field.name() == MERGE_SOURCE_SENTINEL
                    } else {
                        true
                    }
                }

                // Include target._rowaddr specifically - needed to locate existing rows for updates/deletes
                Some(qualifier) if qualifier.table() == "target" && field.name() == ROW_ADDR => {
                    true
                }

                // Include target._rowid specifically - needed to locate existing rows for updates
                Some(qualifier) if qualifier.table() == "target" && field.name() == ROW_ID => true,

                // Present only when the row rewrite can spill carried lineage.
                Some(qualifier)
                    if qualifier.table() == "target" && field.name() == ROW_CREATED_AT_VERSION =>
                {
                    true
                }

                // Include unqualified columns like "__action" - tells us what operation to perform
                None if field.name() == MERGE_ACTION_COLUMN => true,

                // Partial-schema upsert: the `create_plan` builder adds
                // unqualified columns (named after dataset fields) for every
                // column missing from the source, filled from the target
                // side of the join. Those columns carry the values that
                // should be written for non-source columns, so they must
                // flow through to the write exec alongside `source.*`.
                None if self.dataset.schema().field(field.name()).is_some() => true,

                // Skip other target columns (target.value, target.key, target._rowid) - not needed for write
                _ => false,
            };

            if should_include {
                necessary_columns.push(i);
            }
        }

        Some(vec![necessary_columns])
    }
}

/// Physical planner for MergeInsertWriteNode.
pub struct MergeInsertPlanner {
    pub(super) source_evidence: SourceEvidence,
    pub(super) policy_bytes: Option<usize>,
}

impl MergeInsertPlanner {
    fn prepare_join(
        &self,
        input: Arc<dyn ExecutionPlan>,
        params: &MergeInsertParams,
    ) -> DFResult<Arc<dyn ExecutionPlan>> {
        let Some(policy_bytes) = self.policy_bytes else {
            return Ok(input);
        };
        if let Some(join) = input.downcast_ref::<HashJoinExec>() {
            let target = join.left();
            let source = join.right();
            // This is the first join under only the merge's Projection/Filter chain.
            // Verify both identities and all keys before touching it. Do not enter a provider's join.
            let recognized = target.schema().column_with_name(ROW_ADDR).is_some()
                && source
                    .schema()
                    .column_with_name(MERGE_SOURCE_SENTINEL)
                    .is_some()
                && target
                    .schema()
                    .column_with_name(MERGE_SOURCE_SENTINEL)
                    .is_none()
                && join.on().len() == params.on.len()
                && join
                    .on()
                    .iter()
                    .zip(&params.on)
                    .all(|((left, right), name)| {
                        left.as_ref()
                            .downcast_ref::<datafusion::physical_expr::expressions::Column>()
                            .is_some_and(|c| c.name() == name)
                            && right
                                .as_ref()
                                .downcast_ref::<datafusion::physical_expr::expressions::Column>()
                                .is_some_and(|c| c.name() == name)
                    });
            if !recognized {
                evidence(json!({"phase":"join_policy", "decision":"skipped_unrecognized_join"}));
                return Ok(input);
            }
            let stats = target.partition_statistics(None)?;
            let width = fixed_schema_width(target.schema().as_ref());
            let model = match (width, stats.num_rows) {
                (Some(width), Precision::Exact(rows)) => (rows as u64)
                    .checked_mul(width)
                    .and_then(|bytes| bytes.checked_mul(2))
                    .and_then(|bytes| {
                        (rows as u64)
                            .checked_mul(64)
                            .and_then(|hash| bytes.checked_add(hash))
                    })
                    .and_then(|bytes| bytes.checked_add(1024 * 1024)),
                _ => None,
            };
            let threshold = (32 * 1024 * 1024).min(policy_bytes / 4) as u64;
            let target_left = !matches!(self.source_evidence, SourceEvidence::Complete)
                && model.is_some_and(|bytes| bytes <= threshold);
            let guarded_target: Arc<dyn ExecutionPlan> = if width.is_none() {
                Arc::new(MergeTargetStatsGuardExec::new(target.clone()))
            } else {
                target.clone()
            };
            let guarded = input
                .clone()
                .with_new_children(vec![guarded_target, source.clone()])?;
            evidence(
                json!({"phase":"join_policy", "decision":if target_left {"small_fixed_target"} else {"source_default"}, "target_width":width,
                "target_rows":format!("{:?}", stats.num_rows), "model_bytes":model, "threshold_bytes":threshold,
                "source_evidence":format!("{:?}", self.source_evidence), "target_schema":format!("{:?}",target.schema()), "stats_guard":width.is_none()}),
            );
            if target_left {
                return Ok(guarded);
            }
            let Some(join) = guarded.downcast_ref::<HashJoinExec>() else {
                return Ok(guarded);
            };
            return join.swap_inputs(PartitionMode::Auto);
        }
        if input.downcast_ref::<ProjectionExec>().is_some()
            || input.downcast_ref::<FilterExec>().is_some()
        {
            let children = input.children();
            if children.len() == 1 {
                let child = self.prepare_join(children[0].clone(), params)?;
                return input.with_new_children(vec![child]);
            }
        }
        evidence(
            json!({"phase":"join_policy", "decision":"skipped_unrecognized_chain", "node":input.name()}),
        );
        Ok(input)
    }
    /// Check if this is a delete-only operation that can use the optimized path.
    ///
    /// Delete-only operations are when:
    /// - `when_matched` is `Delete`
    /// - `insert_not_matched` is `false` (no inserts)
    /// - `delete_not_matched_by_source` is `Keep` (no additional deletes of unmatched target rows)
    fn is_delete_only(params: &MergeInsertParams) -> bool {
        matches!(params.when_matched, WhenMatched::Delete)
            && !params.insert_not_matched
            && matches!(
                params.delete_not_matched_by_source,
                WhenNotMatchedBySource::Keep
            )
    }
}

#[async_trait]
impl ExtensionPlanner for MergeInsertPlanner {
    async fn plan_extension(
        &self,
        _planner: &dyn PhysicalPlanner,
        node: &dyn UserDefinedLogicalNode,
        logical_inputs: &[&LogicalPlan],
        physical_inputs: &[Arc<dyn ExecutionPlan>],
        session_state: &SessionState,
    ) -> DFResult<Option<Arc<dyn ExecutionPlan>>> {
        Ok(
            if let Some(write_node) = node.as_any().downcast_ref::<MergeInsertWriteNode>() {
                assert_eq!(logical_inputs.len(), 1, "Inconsistent number of inputs");
                assert_eq!(physical_inputs.len(), 1, "Inconsistent number of inputs");

                let mut input =
                    self.prepare_join(physical_inputs[0].clone(), &write_node.params)?;
                let update_if_deferred = write_node.deferred.update_if.is_some();
                if write_node.deferred != DeferredConditions::default() {
                    input = Arc::new(MergeConditionExec::try_new(
                        input,
                        logical_inputs[0].schema(),
                        write_node.dataset.clone(),
                        write_node.deferred.update_if.clone(),
                        write_node.deferred.delete_if.clone(),
                        session_state,
                    )?);
                }
                if !write_node.deferred_target_columns.is_empty() {
                    input = Arc::new(super::exec::MergePayloadExec::try_new(
                        input,
                        write_node.dataset.clone(),
                        write_node.deferred_target_columns.clone(),
                    )?);
                }

                let exec: Arc<dyn ExecutionPlan> = if Self::is_delete_only(&write_node.params) {
                    Arc::new(DeleteOnlyMergeInsertExec::try_new(
                        input,
                        write_node.dataset.clone(),
                        write_node.params.clone(),
                        write_node.source_skipped_duplicates.clone(),
                    )?)
                } else if write_node.write_sink == WriteSink::RewriteColumns {
                    let exec = InPlaceMergeInsertExec::try_new(
                        input,
                        write_node.dataset.clone(),
                        write_node.params.clone(),
                        write_node.source_skipped_duplicates.clone(),
                    )?;
                    match update_if_deferred {
                        true => Arc::new(exec.with_update_if_deferred()),
                        false => Arc::new(exec),
                    }
                } else {
                    let exec = FullSchemaMergeInsertExec::try_new(
                        input,
                        write_node.dataset.clone(),
                        write_node.params.clone(),
                        write_node.source_skipped_duplicates.clone(),
                        write_node.source_blob_columns.clone(),
                    )?;
                    match update_if_deferred {
                        true => Arc::new(exec.with_update_if_deferred()),
                        false => Arc::new(exec),
                    }
                };
                Some(exec)
            } else {
                None
            },
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::utils::test::{DatagenExt, FragmentCount, FragmentRowCount};
    use arrow_array::{record_batch, types::UInt64Type};
    use datafusion::common::NullEquality;
    use datafusion::datasource::memory::MemorySourceConfig;
    use datafusion::logical_expr::JoinType;
    use datafusion::physical_expr::expressions::Column;
    use lance_datafusion::exec::OneShotExec;
    use lance_datagen::{array, gen_batch};

    fn join_in(plan: &Arc<dyn ExecutionPlan>) -> &HashJoinExec {
        if let Some(join) = plan.downcast_ref::<HashJoinExec>() {
            return join;
        }
        join_in(plan.children()[0])
    }

    #[rstest::rstest]
    #[case::below_threshold(1, SourceEvidence::Prefix, true)]
    #[case::exact_threshold(0, SourceEvidence::Prefix, true)]
    #[case::above_threshold(-1, SourceEvidence::Prefix, false)]
    #[case::complete_source(0, SourceEvidence::Complete, false)]
    #[tokio::test]
    async fn initial_direction_obeys_small_fixed_target_boundary(
        #[case] threshold_delta: i64,
        #[case] source_evidence: SourceEvidence,
        #[case] target_left: bool,
    ) {
        let dataset = Arc::new(
            gen_batch()
                .col("key", array::step::<UInt64Type>())
                .into_ram_dataset(FragmentCount::from(1), FragmentRowCount::from(1))
                .await
                .unwrap(),
        );
        let job = super::super::MergeInsertBuilder::try_new(dataset, vec!["key".into()])
            .unwrap()
            .try_build()
            .unwrap();
        let target = record_batch!(("key", UInt64, [1]), (ROW_ADDR, UInt64, [0])).unwrap();
        let model = 2 * fixed_schema_width(target.schema().as_ref()).unwrap() + 64 + 1024 * 1024;
        let threshold = model.checked_add_signed(threshold_delta).unwrap();
        let target =
            MemorySourceConfig::try_new_exec(&[vec![target.clone()]], target.schema(), None)
                .unwrap();
        let source = record_batch!(
            ("key", UInt64, [1]),
            (MERGE_SOURCE_SENTINEL, Boolean, [true])
        )
        .unwrap();
        let source: Arc<dyn ExecutionPlan> = Arc::new(OneShotExec::from_batch(source));
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
        let planner = MergeInsertPlanner {
            source_evidence,
            policy_bytes: Some(threshold as usize * 4),
        };
        let planned = planner.prepare_join(join, &job.params).unwrap();
        let join = join_in(&planned);
        assert_eq!(
            join.left().schema().column_with_name(ROW_ADDR).is_some(),
            target_left
        );
        assert_eq!(*join.partition_mode(), PartitionMode::Auto);
    }
}
