// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: Copyright The Lance Authors

use std::collections::HashSet;
use std::sync::Arc;

use arrow_array::{
    Array, RecordBatch, RecordBatchOptions, UInt8Array, UInt32Array,
    cast::AsArray,
    types::{UInt8Type, UInt64Type},
};
use arrow_schema::{DataType, Schema, SchemaRef};
use arrow_select::take::take;
use datafusion::common::{
    Column, DFSchema, DataFusionError, Result as DFResult, TableReference,
    tree_node::{Transformed, TransformedResult, TreeNode},
};
use datafusion::execution::{
    SendableRecordBatchStream, SessionState, TaskContext, memory_pool::MemoryLimit,
};
use datafusion::physical_expr::EquivalenceProperties;
use datafusion::physical_plan::{
    DisplayAs, DisplayFormatType, ExecutionPlan, PhysicalExpr, PlanProperties,
    metrics::{BaselineMetrics, Count, ExecutionPlanMetricsSet, MetricBuilder, MetricsSet},
    stream::RecordBatchStreamAdapter,
};
use datafusion_expr::Expr;
use futures::{StreamExt, stream};
use lance_arrow::DataTypeExt;
use lance_core::ROW_ADDR;
use lance_datafusion::projection::ProjectionPlan;

use crate::Dataset;
use crate::dataset::TakeBuilder;
use crate::dataset::write::merge_insert::assign_action::Action;
use crate::dataset::write::merge_insert::{
    MERGE_ACTION_COLUMN, MERGE_SOURCE_SENTINEL, target_blob_handling,
};

/// Evaluates merge conditions over target columns on the rows they gate.
///
/// The join marks every matched row `Action::UpdateAll` and every target-only
/// row `Action::Delete`; this node takes the conditions' target columns by row
/// address for those rows alone and demotes the rejected ones to
/// `Action::Nothing`, so the target scan never reads them.
#[derive(Debug)]
pub struct MergeConditionExec {
    input: Arc<dyn ExecutionPlan>,
    evaluator: Arc<Evaluator>,
    properties: Arc<PlanProperties>,
    metrics: ExecutionPlanMetricsSet,
}

#[derive(Debug, Clone)]
struct Evaluator {
    dataset: Arc<Dataset>,
    /// Gates `UpdateAll` on the matched rows.
    update_if: Option<Arc<dyn PhysicalExpr>>,
    /// Gates `Delete` on the target-only rows.
    delete_if: Option<Arc<dyn PhysicalExpr>>,
    /// The input columns the conditions read, followed by the taken ones.
    eval_schema: SchemaRef,
    eval_inputs: Vec<usize>,
    take: Option<Arc<ProjectionPlan>>,
    action_idx: usize,
    payload: Option<Payload>,
    output_schema: SchemaRef,
}

#[derive(Debug, Clone)]
struct Payload {
    columns: Vec<String>,
    /// Columns absent from the condition's cached target values.
    take: Option<Arc<ProjectionPlan>>,
}

#[derive(Clone)]
struct TakeMetrics {
    condition_rows: Count,
    condition_bytes: Count,
    payload_rows: Count,
    payload_bytes: Count,
    reused_values: Count,
}

impl MergeConditionExec {
    /// `input_schema` is the logical schema of `input`, which carries the
    /// `source` / `target` qualifiers the conditions are resolved against.
    pub fn try_new(
        input: Arc<dyn ExecutionPlan>,
        input_schema: &DFSchema,
        dataset: Arc<Dataset>,
        update_if: Option<Expr>,
        delete_if: Option<Expr>,
        session: &SessionState,
    ) -> DFResult<Self> {
        let physical_schema = input.schema();
        let physical_names = physical_schema.fields().iter().map(|f| f.name());
        if !physical_names.eq(input_schema.fields().iter().map(|f| f.name())) {
            return Err(DataFusionError::Internal(format!(
                "merge insert input {:?} does not match its logical schema {:?}",
                physical_schema.fields(),
                input_schema.fields()
            )));
        }
        let index_of = |name: &str| {
            physical_schema
                .column_with_name(name)
                .map(|(i, _)| i)
                .ok_or_else(|| {
                    DataFusionError::Internal(format!(
                        "Expected {name} column in merge insert input"
                    ))
                })
        };
        let action_idx = index_of(MERGE_ACTION_COLUMN)?;
        index_of(ROW_ADDR)?;
        index_of(MERGE_SOURCE_SENTINEL)?;

        let mut to_take = HashSet::new();
        let update_if = update_if
            .map(|condition| {
                resolve_target_columns(condition, input_schema, &dataset, &mut to_take)
            })
            .transpose()?;
        let delete_if = delete_if
            .map(|condition| {
                resolve_target_columns(condition, input_schema, &dataset, &mut to_take)
            })
            .transpose()?;
        let columns = dataset
            .schema()
            .fields
            .iter()
            .map(|field| field.name.as_str())
            .filter(|name| to_take.contains(*name))
            .collect::<Vec<_>>();
        // Every column may already be in the input, in which case the node
        // only gates; see `resolve_target_columns`.
        let take = match columns.is_empty() {
            true => None,
            false => {
                let mut take = ProjectionPlan::from_schema(
                    dataset.clone(),
                    &dataset.schema().project(&columns)?,
                )?;
                take.physical_projection = take
                    .physical_projection
                    .clone()
                    .with_blob_handling(target_blob_handling(&dataset));
                Some(Arc::new(take))
            }
        };
        // Only the input columns the conditions read are copied for evaluation.
        let mut eval_inputs = [&update_if, &delete_if]
            .into_iter()
            .flatten()
            .flat_map(|condition| condition.column_refs())
            .filter_map(|column| input_schema.index_of_column(column).ok())
            .collect::<Vec<_>>();
        eval_inputs.sort_unstable();
        eval_inputs.dedup();
        let read = DFSchema::new_with_metadata(
            eval_inputs
                .iter()
                .map(|&i| {
                    let (qualifier, field) = input_schema.qualified_field(i);
                    (qualifier.cloned(), field.clone())
                })
                .collect(),
            Default::default(),
        )?;
        let eval_df_schema = match &take {
            Some(take) => read.join(&DFSchema::try_from_qualified_schema(
                "target",
                &take.output_schema()?,
            )?)?,
            None => read,
        };
        let eval_schema: SchemaRef = Arc::new(eval_df_schema.as_arrow().clone());
        let physical = |condition: Expr, clause: &str| -> DFResult<Arc<dyn PhysicalExpr>> {
            let condition = session.create_physical_expr(condition, &eval_df_schema)?;
            let data_type = condition.data_type(eval_schema.as_ref())?;
            if data_type != DataType::Boolean {
                return Err(DataFusionError::Plan(format!(
                    "Merge insert conditions must be expressions that return a boolean value, \
                     received a '{clause}' expression ({condition}) which has data type {data_type}"
                )));
            }
            Ok(condition)
        };
        let update_if = update_if
            .map(|condition| physical(condition, "when matched update if"))
            .transpose()?;
        let delete_if = delete_if
            .map(|condition| physical(condition, "when not matched by source delete if"))
            .transpose()?;

        Ok(Self {
            properties: input.properties().clone(),
            evaluator: Arc::new(Evaluator {
                dataset,
                update_if,
                delete_if,
                eval_schema,
                eval_inputs,
                take,
                action_idx,
                payload: None,
                output_schema: physical_schema,
            }),
            input,
            metrics: ExecutionPlanMetricsSet::new(),
        })
    }

    /// Appends omitted target columns only for rows whose final action updates.
    ///
    /// The input must omit these columns, including typed NULL placeholders, so
    /// conditions resolve against the stored values. Values already taken for
    /// an update condition are reused instead of being read a second time.
    pub(crate) fn with_payload_columns(mut self, columns: Vec<String>) -> DFResult<Self> {
        if columns.is_empty() {
            return Ok(self);
        }
        let evaluator = Arc::make_mut(&mut self.evaluator);
        let mut names = HashSet::new();
        for name in &columns {
            if !names.insert(name) || self.input.schema().column_with_name(name).is_some() {
                return Err(DataFusionError::Internal(format!(
                    "Deferred merge payload column {name:?} occurs more than once or is already in the input"
                )));
            }
        }
        let projection = evaluator.dataset.schema().project(&columns)?;
        let full_take = ProjectionPlan::from_schema(evaluator.dataset.clone(), &projection)?;
        let payload_schema = full_take.output_schema()?;
        let missing = columns
            .iter()
            .filter(|name| {
                evaluator.update_if.is_none()
                    || !evaluator
                        .taken_columns()
                        .any(|taken| taken == name.as_str())
            })
            .collect::<Vec<_>>();
        let take = if missing.is_empty() {
            None
        } else {
            Some(Arc::new(ProjectionPlan::from_schema(
                evaluator.dataset.clone(),
                &evaluator.dataset.schema().project(&missing)?,
            )?))
        };
        evaluator.output_schema = Arc::new(Schema::new_with_metadata(
            self.input
                .schema()
                .fields()
                .iter()
                .cloned()
                .chain(
                    payload_schema
                        .fields()
                        .iter()
                        .map(|field| Arc::new(field.as_ref().clone().with_nullable(true))),
                )
                .collect::<Vec<_>>(),
            self.input.schema().metadata().clone(),
        ));
        evaluator.payload = Some(Payload { columns, take });
        self.properties =
            Arc::new(
                self.input.properties().as_ref().clone().with_eq_properties(
                    EquivalenceProperties::new(evaluator.output_schema.clone()),
                ),
            );
        Ok(self)
    }
}

/// Binds each target column the condition reads to the input when the input
/// already carries it, and otherwise adds it to `to_take`.
///
/// A whole-row rewrite fills the columns the source omits from the target
/// side of the join as unqualified columns; a `target.`-qualified reference
/// to one is rewritten to that column, since a taken `target.x` next to a
/// filled `x` would be an ambiguous schema.
fn resolve_target_columns(
    condition: Expr,
    input_schema: &DFSchema,
    dataset: &Dataset,
    to_take: &mut HashSet<String>,
) -> DFResult<Expr> {
    let target = TableReference::bare("target");
    let dataset_schema = dataset.schema();
    condition
        .transform(|expr| {
            let Expr::Column(column) = &expr else {
                return Ok(Transformed::no(expr));
            };
            if dataset_schema.field(&column.name).is_none()
                || column
                    .relation
                    .as_ref()
                    .is_some_and(|relation| relation != &target)
            {
                return Ok(Transformed::no(expr));
            }
            let input_has = |qualifier: Option<&TableReference>| {
                input_schema
                    .iter()
                    .any(|(q, field)| q == qualifier && field.name() == &column.name)
            };
            if input_has(Some(&target)) {
                return Ok(Transformed::no(expr));
            }
            if input_has(None) {
                return Ok(Transformed::yes(Expr::Column(Column::new_unqualified(
                    &column.name,
                ))));
            }
            to_take.insert(column.name.clone());
            Ok(Transformed::no(expr))
        })
        .data()
}

impl Evaluator {
    fn taken_columns(&self) -> impl Iterator<Item = &str> {
        self.eval_schema.fields()[self.eval_inputs.len()..]
            .iter()
            .map(|field| field.name().as_str())
    }

    /// Returns the observed taken bytes per row for the next chunk's soft sizing.
    async fn apply(
        &self,
        batch: RecordBatch,
        metrics: &TakeMetrics,
    ) -> DFResult<(RecordBatch, usize)> {
        let actions = batch
            .column_by_name(MERGE_ACTION_COLUMN)
            .and_then(|column| column.as_primitive_opt::<UInt8Type>())
            .ok_or_else(|| {
                DataFusionError::Internal(format!(
                    "Expected UInt8Array for {MERGE_ACTION_COLUMN} column"
                ))
            })?;
        let sentinel = batch.column_by_name(MERGE_SOURCE_SENTINEL).ok_or_else(|| {
            DataFusionError::Internal(format!("Expected {MERGE_SOURCE_SENTINEL} column"))
        })?;
        let rows_with = |action: Action, target_only: bool| -> Vec<u32> {
            (0..batch.num_rows())
                .filter(|&row| {
                    actions.value(row) == action as u8 && (!target_only || sentinel.is_null(row))
                })
                .map(|row| row as u32)
                .collect()
        };
        // DeleteIf gates only target-only rows, never unconditional matched deletes.
        let update_rows = match self.update_if {
            Some(_) => rows_with(Action::UpdateAll, false),
            None => Vec::new(),
        };
        let delete_rows = match self.delete_if {
            Some(_) => rows_with(Action::Delete, true),
            None => Vec::new(),
        };
        let candidates = [update_rows.as_slice(), delete_rows.as_slice()].concat();
        let row_addrs = batch
            .column_by_name(ROW_ADDR)
            .and_then(|column| column.as_primitive_opt::<UInt64Type>())
            .ok_or_else(|| {
                DataFusionError::Internal(format!("Expected UInt64Array for {ROW_ADDR} column"))
            })?;
        let addresses = |rows: &[u32]| -> DFResult<Vec<u64>> {
            rows.iter()
                .map(|&row| {
                    if row_addrs.is_null(row as usize) {
                        Err(DataFusionError::Internal(format!(
                            "Merge insert action at row {row} has no target address"
                        )))
                    } else {
                        Ok(row_addrs.value(row as usize))
                    }
                })
                .collect()
        };
        let mut new_actions = actions.values().to_vec();
        let mut condition_values = None;
        let mut observed_width = 0;
        if !candidates.is_empty() {
            let indices = UInt32Array::from(candidates.clone());
            let mut columns = self
                .eval_inputs
                .iter()
                .map(|&i| take(batch.column(i), &indices, None))
                .collect::<Result<Vec<_>, _>>()?;
            if let Some(projection) = &self.take {
                let taken = TakeBuilder::try_new_from_addresses(
                    self.dataset.clone(),
                    addresses(&candidates)?,
                    projection.clone(),
                )?
                .execute()
                .await?;
                if taken.num_rows() != candidates.len() {
                    return Err(DataFusionError::Internal(format!(
                        "Took {} of {} rows for the merge insert conditions",
                        taken.num_rows(),
                        candidates.len()
                    )));
                }
                let bytes = taken.get_array_memory_size();
                metrics.condition_rows.add(candidates.len());
                metrics.condition_bytes.add(bytes);
                observed_width = bytes.div_ceil(candidates.len());
                for name in self.taken_columns() {
                    let column = taken.column_by_name(name).ok_or_else(|| {
                        DataFusionError::Internal(format!("Take did not return column {name}"))
                    })?;
                    columns.push(column.clone());
                }
                condition_values = Some(taken);
            }
            let eval_batch = RecordBatch::try_new_with_options(
                self.eval_schema.clone(),
                columns,
                &RecordBatchOptions::new().with_row_count(Some(candidates.len())),
            )?;
            let mut reject_failing =
                |condition: &Arc<dyn PhysicalExpr>, offset: usize, rows: &[u32]| -> DFResult<()> {
                    let eval_batch = eval_batch.slice(offset, rows.len());
                    let verdict = condition
                        .evaluate(&eval_batch)?
                        .into_array(eval_batch.num_rows())?;
                    let verdict = verdict.as_boolean();
                    for (verdict_row, &row) in rows.iter().enumerate() {
                        if !verdict.is_valid(verdict_row) || !verdict.value(verdict_row) {
                            new_actions[row as usize] = Action::Nothing as u8;
                        }
                    }
                    Ok(())
                };
            if let Some(condition) = &self.update_if {
                reject_failing(condition, 0, &update_rows)?;
            }
            if let Some(condition) = &self.delete_if {
                reject_failing(condition, update_rows.len(), &delete_rows)?;
            }
        }

        let mut columns = batch.columns().to_vec();
        if let Some(payload) = &self.payload {
            let updates = new_actions
                .iter()
                .enumerate()
                .filter(|(_, action)| **action == Action::UpdateAll as u8)
                .map(|(row, _)| row as u32)
                .collect::<Vec<_>>();
            if updates.is_empty() {
                columns.extend(
                    self.output_schema.fields()[columns.len()..]
                        .iter()
                        .map(|field| {
                            arrow_array::new_null_array(field.data_type(), batch.num_rows())
                        }),
                );
            } else {
                let mut update_positions = vec![None; batch.num_rows()];
                for (index, &row) in updates.iter().enumerate() {
                    update_positions[row as usize] = Some(index as u32);
                }
                let update_indices = UInt32Array::from(update_positions);
                let mut condition_positions = vec![None; batch.num_rows()];
                for (index, &row) in candidates.iter().enumerate() {
                    if new_actions[row as usize] == Action::UpdateAll as u8 {
                        condition_positions[row as usize] = Some(index as u32);
                    }
                }
                let condition_indices = UInt32Array::from(condition_positions);
                let payload_values = if let Some(projection) = &payload.take {
                    let taken = TakeBuilder::try_new_from_addresses(
                        self.dataset.clone(),
                        addresses(&updates)?,
                        projection.clone(),
                    )?
                    .execute()
                    .await?;
                    if taken.num_rows() != updates.len() {
                        return Err(DataFusionError::Internal(format!(
                            "Took {} of {} rows for the merge insert payload",
                            taken.num_rows(),
                            updates.len()
                        )));
                    }
                    let bytes = taken.get_array_memory_size();
                    metrics.payload_rows.add(updates.len());
                    metrics.payload_bytes.add(bytes);
                    observed_width = observed_width
                        .checked_add(bytes.div_ceil(updates.len()))
                        .ok_or_else(|| {
                            DataFusionError::ResourcesExhausted(
                                "Merge materialization bytes per row overflowed usize".into(),
                            )
                        })?;
                    Some(taken)
                } else {
                    None
                };
                for name in &payload.columns {
                    let cached = condition_values
                        .as_ref()
                        .filter(|_| self.update_if.is_some())
                        .and_then(|values| values.column_by_name(name));
                    let value = if let Some(value) = cached {
                        metrics.reused_values.add(updates.len());
                        take(value, &condition_indices, None)?
                    } else {
                        let value = payload_values
                            .as_ref()
                            .and_then(|values| values.column_by_name(name))
                            .ok_or_else(|| {
                                DataFusionError::Internal(format!(
                                    "Merge materialization did not retrieve payload column {name}"
                                ))
                            })?;
                        take(value, &update_indices, None)?
                    };
                    columns.push(value);
                }
            }
        }
        columns[self.action_idx] = Arc::new(UInt8Array::from(new_actions));
        Ok((
            RecordBatch::try_new(self.output_schema.clone(), columns)?,
            observed_width,
        ))
    }
}

impl DisplayAs for MergeConditionExec {
    fn fmt_as(&self, _t: DisplayFormatType, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        write!(f, "MergeCondition:")?;
        if let Some(condition) = &self.evaluator.update_if {
            write!(f, " update_if={condition},")?;
        }
        if let Some(condition) = &self.evaluator.delete_if {
            write!(f, " delete_if={condition},")?;
        }
        write!(
            f,
            " take=[{}]",
            self.evaluator
                .taken_columns()
                .collect::<Vec<_>>()
                .join(", ")
        )?;
        if let Some(payload) = &self.evaluator.payload {
            write!(f, " payload=[{}]", payload.columns.join(", "))?;
        }
        Ok(())
    }
}

impl ExecutionPlan for MergeConditionExec {
    fn name(&self) -> &str {
        "MergeConditionExec"
    }

    fn schema(&self) -> SchemaRef {
        self.evaluator.output_schema.clone()
    }

    fn properties(&self) -> &Arc<PlanProperties> {
        &self.properties
    }

    fn children(&self) -> Vec<&Arc<dyn ExecutionPlan>> {
        vec![&self.input]
    }

    fn maintains_input_order(&self) -> Vec<bool> {
        vec![true]
    }

    fn benefits_from_input_partitioning(&self) -> Vec<bool> {
        vec![false]
    }

    fn with_new_children(
        self: Arc<Self>,
        children: Vec<Arc<dyn ExecutionPlan>>,
    ) -> DFResult<Arc<dyn ExecutionPlan>> {
        if children.len() != 1 {
            return Err(DataFusionError::Internal(
                "MergeConditionExec requires exactly one child".to_string(),
            ));
        }
        let input = children[0].clone();
        if input.schema() != self.input.schema() {
            return Err(DataFusionError::Internal(
                "MergeConditionExec cannot change its input schema".to_string(),
            ));
        }
        let properties = if self.evaluator.payload.is_some() {
            Arc::new(
                input
                    .properties()
                    .as_ref()
                    .clone()
                    .with_eq_properties(EquivalenceProperties::new(self.schema())),
            )
        } else {
            input.properties().clone()
        };
        Ok(Arc::new(Self {
            properties,
            input,
            evaluator: self.evaluator.clone(),
            metrics: ExecutionPlanMetricsSet::new(),
        }))
    }

    fn metrics(&self) -> Option<MetricsSet> {
        Some(self.metrics.clone_inner())
    }

    fn execute(
        &self,
        partition: usize,
        context: Arc<TaskContext>,
    ) -> DFResult<SendableRecordBatchStream> {
        let baseline = BaselineMetrics::new(&self.metrics, partition);
        let metrics = TakeMetrics {
            condition_rows: MetricBuilder::new(&self.metrics)
                .counter("condition_take_rows", partition),
            condition_bytes: MetricBuilder::new(&self.metrics)
                .counter("condition_take_arrow_bytes", partition),
            payload_rows: MetricBuilder::new(&self.metrics).counter("payload_take_rows", partition),
            payload_bytes: MetricBuilder::new(&self.metrics)
                .counter("payload_take_arrow_bytes", partition),
            reused_values: MetricBuilder::new(&self.metrics)
                .counter("payload_reused_condition_values", partition),
        };
        let input = self.input.execute(partition, context.clone())?;
        let evaluator = self.evaluator.clone();
        if evaluator.payload.is_none() {
            // Preserve the existing condition-only node's batch granularity.
            // Payload materialization introduces the wider transient buffers
            // that need the candidate-based sizing below.
            let stream = input.then(move |batch| {
                let evaluator = evaluator.clone();
                let baseline = baseline.clone();
                let metrics = metrics.clone();
                async move {
                    let (output, _) = evaluator.apply(batch?, &metrics).await?;
                    baseline.record_output(output.num_rows());
                    Ok(output)
                }
            });
            return Ok(Box::pin(RecordBatchStreamAdapter::new(
                self.schema(),
                stream,
            )));
        }
        let max_rows = context
            .session_config()
            .batch_size()
            .min(u32::MAX as usize)
            .max(1);
        // This is a per-partition soft target for temporary Take/gather buffers,
        // not an allocation limit. Storage pages, one large value, input backing
        // buffers and batches retained by the writer can exceed it.
        let byte_target = match context.memory_pool().memory_limit() {
            MemoryLimit::Finite(limit) => (limit
                / 8
                / self
                    .input
                    .properties()
                    .output_partitioning()
                    .partition_count()
                    .max(1))
            .clamp(1, 16 * 1024 * 1024),
            MemoryLimit::Infinite | MemoryLimit::Unknown => 16 * 1024 * 1024,
        };
        let fixed_width = self
            .evaluator
            .take
            .iter()
            .chain(
                self.evaluator
                    .payload
                    .iter()
                    .filter_map(|payload| payload.take.as_ref()),
            )
            .map(|projection| projection.output_schema())
            .collect::<crate::Result<Vec<_>>>()?
            .iter()
            .flat_map(|schema| schema.fields())
            .try_fold(0usize, |width, field| {
                width.checked_add(field.data_type().byte_width_opt()?.checked_add(1)?)
            });
        let rows_for_width = move |width: usize| {
            // Leave room for Take concatenation, remapping and output gathers.
            (byte_target / width.saturating_mul(4).max(1)).clamp(1, max_rows)
        };
        // Fixed-width NULLs still allocate a value buffer for every output row.
        // Bound those buffers separately from rows that may trigger a Take.
        let output_width = self.evaluator.output_schema.fields()
            [self.input.schema().fields().len()..]
            .iter()
            .try_fold(0usize, |width, field| {
                width.checked_add(field.data_type().byte_width_opt().unwrap_or_default())
            })
            .ok_or_else(|| {
                DataFusionError::ResourcesExhausted(
                    "Merge materialization fixed output bytes per row overflowed usize".into(),
                )
            })?;
        let max_output_rows = rows_for_width(output_width);
        let initial_rows = fixed_width.map_or(1, rows_for_width);
        let stream = stream::try_unfold(
            (input, None::<RecordBatch>, 0usize, initial_rows),
            move |(mut input, mut pending, mut offset, rows)| {
                let evaluator = evaluator.clone();
                let baseline = baseline.clone();
                let metrics = metrics.clone();
                async move {
                    while pending
                        .as_ref()
                        .is_none_or(|batch| offset == batch.num_rows())
                    {
                        pending = match input.next().await {
                            Some(batch) => Some(batch?),
                            None => return Ok(None),
                        };
                        offset = 0;
                    }
                    let batch = pending.as_ref().ok_or_else(|| {
                        DataFusionError::Internal(
                            "Merge materialization lost its input batch".into(),
                        )
                    })?;
                    let actions = batch
                        .column_by_name(MERGE_ACTION_COLUMN)
                        .and_then(|column| column.as_primitive_opt::<UInt8Type>())
                        .ok_or_else(|| {
                            DataFusionError::Internal(format!(
                                "Expected UInt8Array for {MERGE_ACTION_COLUMN} column"
                            ))
                        })?;
                    let sentinel =
                        batch.column_by_name(MERGE_SOURCE_SENTINEL).ok_or_else(|| {
                            DataFusionError::Internal(format!(
                                "Expected {MERGE_SOURCE_SENTINEL} column"
                            ))
                        })?;
                    // Limit rows that may materialize target values, not rows
                    // that only receive NULLs. An insert-only prefix must not
                    // force one-row output batches or enlarge the first Take.
                    let mut candidates = 0;
                    let mut length = 0;
                    for row in offset..batch.num_rows().min(offset.saturating_add(max_output_rows))
                    {
                        let needs_take = actions.value(row) == Action::UpdateAll as u8
                            || (evaluator.take.is_some()
                                && evaluator.delete_if.is_some()
                                && actions.value(row) == Action::Delete as u8
                                && sentinel.is_null(row));
                        if needs_take {
                            if candidates == rows {
                                break;
                            }
                            candidates += 1;
                        }
                        length += 1;
                    }
                    let (output, observed_width) = evaluator
                        .apply(batch.slice(offset, length), &metrics)
                        .await?;
                    offset += length;
                    let next_rows = if observed_width == 0 {
                        rows
                    } else {
                        rows_for_width(observed_width)
                    };
                    baseline.record_output(output.num_rows());
                    Ok(Some((output, (input, pending, offset, next_rows))))
                }
            },
        );
        Ok(Box::pin(RecordBatchStreamAdapter::new(
            self.schema(),
            stream,
        )))
    }
}
