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

#[cfg(test)]
mod tests {
    use super::*;
    use arrow::compute::concat_batches;
    use arrow_array::{ArrayRef, RecordBatchIterator, record_batch, types::Int32Type};
    use datafusion::execution::{memory_pool::GreedyMemoryPool, runtime_env::RuntimeEnvBuilder};
    use datafusion::physical_plan::collect;
    use datafusion::prelude::{SessionConfig, SessionContext};
    use datafusion_expr::{col, lit};
    use datafusion_physical_plan::test::TestMemoryExec;
    use lance_core::utils::address::RowAddress;
    use lance_datagen::{ArrayGeneratorExt, ByteCount, RowCount, Seed, array, gen_batch};
    use lance_io::object_store::WrappingObjectStore;
    use object_store::throttle::ThrottleConfig;

    use std::collections::HashMap;
    use std::time::Duration;

    use datafusion::catalog::TableProvider;
    use lance_file::version::LanceFileVersion;

    use crate::datafusion::dataframe::LanceTableProvider;
    use crate::dataset::WriteParams;
    use crate::utils::test::ThrottledStoreWrapper;
    use crate::{BlobArrayBuilder, blob_field};

    #[rstest::rstest]
    #[case::single_row_chunks(1)]
    #[case::mixed_chunks(1024)]
    #[tokio::test]
    async fn payload_reuses_condition_values_and_preserves_row_mapping(#[case] batch_size: usize) {
        let stored = record_batch!(
            ("key", Int32, [0, 1, 2, 3, 4, 5]),
            (
                "payload",
                Utf8,
                [
                    Some("drop"),
                    None,
                    Some("keep"),
                    Some("drop"),
                    Some("keep"),
                    None
                ]
            ),
            ("extra", Int32, [10, 11, 12, 13, 14, 15])
        )
        .unwrap();
        let fields = stored
            .schema()
            .fields()
            .iter()
            .map(|field| match field.name().as_str() {
                "payload" => Arc::new(field.as_ref().clone().with_metadata(HashMap::from([(
                    "purpose".to_string(),
                    "preserved".to_string(),
                )]))),
                "extra" => Arc::new(field.as_ref().clone().with_nullable(false)),
                _ => field.clone(),
            })
            .collect::<Vec<_>>();
        let stored =
            RecordBatch::try_new(Arc::new(Schema::new(fields)), stored.columns().to_vec()).unwrap();
        let ds = Arc::new(
            Dataset::write(
                RecordBatchIterator::new([Ok(stored.clone())], stored.schema()),
                "memory://",
                Some(WriteParams {
                    max_rows_per_file: 3,
                    ..Default::default()
                }),
            )
            .await
            .unwrap(),
        );
        let address = |fragment, row| u64::from(RowAddress::new_from_parts(fragment, row));
        let input = record_batch!(
            (
                "_rowid",
                UInt64,
                [Some(4), Some(2), Some(1), Some(4), None, Some(0), Some(3)]
            ),
            (
                "_rowaddr",
                UInt64,
                [
                    Some(address(1, 1)),
                    Some(address(0, 2)),
                    Some(address(0, 1)),
                    Some(address(1, 1)),
                    None,
                    Some(address(0, 0)),
                    Some(address(1, 0))
                ]
            ),
            ("key", Int32, [4, 2, 1, 4, 100, 0, 3]),
            (
                "__merge_source_sentinel",
                Boolean,
                [
                    Some(true),
                    Some(true),
                    Some(true),
                    Some(true),
                    Some(true),
                    Some(true),
                    Some(true)
                ]
            ),
            ("__action", UInt8, [1, 1, 1, 1, 2, 0, 3])
        )
        .unwrap();
        let input = input
            .clone()
            .with_schema(Arc::new(input.schema().as_ref().clone().with_metadata(
                HashMap::from([("input".to_string(), "metadata".to_string())]),
            )))
            .unwrap();
        let input_schema = DFSchema::from_field_specific_qualified_schema(
            ["target", "target", "source", "source"]
                .map(|relation| Some(TableReference::bare(relation)))
                .into_iter()
                .chain([None])
                .collect(),
            &input.schema(),
        )
        .unwrap();
        let session =
            SessionContext::new_with_config(SessionConfig::new().with_batch_size(batch_size));
        let exec = Arc::new(
            MergeConditionExec::try_new(
                TestMemoryExec::try_new_exec(&[vec![input.clone()]], input.schema(), None).unwrap(),
                &input_schema,
                ds,
                Some(
                    col("target.payload")
                        .eq(lit("keep"))
                        .or(col("source.key").eq(lit(999))),
                ),
                None,
                &session.state(),
            )
            .unwrap()
            .with_payload_columns(vec!["payload".into(), "extra".into()])
            .unwrap(),
        );
        let batches = collect(exec.clone(), session.task_ctx()).await.unwrap();
        assert!(batches.iter().all(|batch| batch.num_rows() <= batch_size));
        let output = concat_batches(&exec.schema(), &batches).unwrap();
        assert_eq!(output["key"].to_data(), input["key"].to_data());
        assert_eq!(output["_rowaddr"].to_data(), input["_rowaddr"].to_data());
        assert_eq!(
            output["__action"].as_primitive::<UInt8Type>().values(),
            &[1, 1, 0, 1, 2, 0, 3]
        );
        assert_eq!(
            output["payload"]
                .as_string::<i32>()
                .iter()
                .collect::<Vec<_>>(),
            vec![
                Some("keep"),
                Some("keep"),
                None,
                Some("keep"),
                None,
                None,
                None
            ]
        );
        assert_eq!(
            output["extra"]
                .as_primitive::<Int32Type>()
                .iter()
                .collect::<Vec<_>>(),
            vec![Some(14), Some(12), None, Some(14), None, None, None]
        );
        assert_eq!(output.schema().metadata(), input.schema().metadata());
        assert_eq!(
            output
                .schema()
                .field_with_name("payload")
                .unwrap()
                .metadata()
                .get("purpose"),
            Some(&"preserved".to_string())
        );
        // The physical outer-join output must allow NULL for inserts and rejected rows;
        // the dataset's non-nullable extra values are retained on every update.
        assert!(
            output
                .schema()
                .field_with_name("extra")
                .unwrap()
                .is_nullable()
        );
        let metrics = exec.metrics().unwrap();
        assert_eq!(
            metrics
                .sum_by_name("condition_take_rows")
                .unwrap()
                .as_usize(),
            4
        );
        assert_eq!(
            metrics.sum_by_name("payload_take_rows").unwrap().as_usize(),
            3
        );
        assert_eq!(
            metrics
                .sum_by_name("payload_reused_condition_values")
                .unwrap()
                .as_usize(),
            3
        );
        let payload_take_schema = exec
            .evaluator
            .payload
            .as_ref()
            .unwrap()
            .take
            .as_ref()
            .unwrap()
            .output_schema()
            .unwrap();
        assert_eq!(
            payload_take_schema
                .fields()
                .iter()
                .map(|field| field.name().as_str())
                .collect::<Vec<_>>(),
            vec!["extra"]
        );
        assert_eq!(
            exec.properties().equivalence_properties().schema(),
            &exec.schema()
        );
        let rebuilt = exec
            .clone()
            .with_new_children(vec![exec.input.clone()])
            .unwrap();
        assert_eq!(rebuilt.schema(), exec.schema());
        assert_eq!(
            rebuilt.properties().equivalence_properties().schema(),
            &rebuilt.schema()
        );
        let replayed = collect(rebuilt, session.task_ctx()).await.unwrap();
        assert_eq!(concat_batches(&exec.schema(), &replayed).unwrap(), output);
    }

    #[tokio::test]
    async fn payload_does_not_reuse_values_taken_for_target_only_deletes() {
        let stored = record_batch!(
            ("key", Int32, [0, 1]),
            ("payload", Utf8, ["keep", "delete"])
        )
        .unwrap();
        let ds = Arc::new(
            Dataset::write(
                RecordBatchIterator::new([Ok(stored.clone())], stored.schema()),
                "memory://",
                None,
            )
            .await
            .unwrap(),
        );
        let input = record_batch!(
            ("_rowid", UInt64, [0, 1]),
            ("_rowaddr", UInt64, [0, 1]),
            ("key", Int32, [0, 1]),
            ("__merge_source_sentinel", Boolean, [Some(true), None]),
            ("__action", UInt8, [1, 3])
        )
        .unwrap();
        let input_schema = DFSchema::from_field_specific_qualified_schema(
            ["target", "target", "source", "source"]
                .map(|relation| Some(TableReference::bare(relation)))
                .into_iter()
                .chain([None])
                .collect(),
            &input.schema(),
        )
        .unwrap();
        let session = SessionContext::new();
        let exec = Arc::new(
            MergeConditionExec::try_new(
                TestMemoryExec::try_new_exec(&[vec![input.clone()]], input.schema(), None).unwrap(),
                &input_schema,
                ds,
                None,
                Some(col("target.payload").eq(lit("delete"))),
                &session.state(),
            )
            .unwrap()
            .with_payload_columns(vec!["payload".into()])
            .unwrap(),
        );
        let batches = collect(exec.clone(), session.task_ctx()).await.unwrap();
        let output = concat_batches(&exec.schema(), &batches).unwrap();
        assert_eq!(
            output["__action"].as_primitive::<UInt8Type>().values(),
            &[1, 3]
        );
        assert_eq!(
            output["payload"]
                .as_string::<i32>()
                .iter()
                .collect::<Vec<_>>(),
            vec![Some("keep"), None]
        );
        let metrics = exec.metrics().unwrap();
        assert_eq!(
            metrics
                .sum_by_name("condition_take_rows")
                .unwrap()
                .as_usize(),
            1
        );
        assert_eq!(
            metrics.sum_by_name("payload_take_rows").unwrap().as_usize(),
            1
        );
        assert_eq!(
            metrics
                .sum_by_name("payload_reused_condition_values")
                .unwrap()
                .as_usize(),
            0
        );
    }

    #[rstest::rstest]
    #[case::finite_pool(false)]
    #[case::cancel_pending_take(true)]
    #[tokio::test(start_paused = true)]
    async fn payload_chunks_obey_soft_budget_and_release_pending_reads(#[case] cancel: bool) {
        let stored = record_batch!(
            ("key", Int32, [0, 1, 2, 3]),
            ("payload", Int64, [10, 11, 12, 13])
        )
        .unwrap();
        let original = Arc::new(
            Dataset::write(
                RecordBatchIterator::new([Ok(stored.clone())], stored.schema()),
                "memory://",
                None,
            )
            .await
            .unwrap(),
        );
        let dataset = if cancel {
            let wrapper: Arc<dyn WrappingObjectStore> = Arc::new(ThrottledStoreWrapper {
                config: ThrottleConfig {
                    wait_get_per_call: Duration::from_secs(60),
                    ..Default::default()
                },
            });
            Arc::new(original.with_object_store_wrappers([wrapper]))
        } else {
            original.clone()
        };
        let snapshot = Arc::downgrade(&dataset);
        let input = record_batch!(
            ("_rowid", UInt64, [0, 1, 2, 3]),
            ("_rowaddr", UInt64, [0, 1, 2, 3]),
            ("key", Int32, [0, 1, 2, 3]),
            ("__merge_source_sentinel", Boolean, [true, true, true, true]),
            ("__action", UInt8, [1, 1, 1, 1])
        )
        .unwrap();
        let input_schema = DFSchema::from_field_specific_qualified_schema(
            ["target", "target", "source", "source"]
                .map(|relation| Some(TableReference::bare(relation)))
                .into_iter()
                .chain([None])
                .collect(),
            &input.schema(),
        )
        .unwrap();
        // A 256-byte nominal pool gives this partition a 32-byte soft target:
        // an Int64 payload plus remapping headroom must use one row per Take.
        let runtime = RuntimeEnvBuilder::new()
            .with_memory_pool(Arc::new(GreedyMemoryPool::new(256)))
            .build_arc()
            .unwrap();
        let session =
            SessionContext::new_with_config_rt(SessionConfig::new().with_batch_size(1024), runtime);
        let exec = Arc::new(
            MergeConditionExec::try_new(
                TestMemoryExec::try_new_exec(&[vec![input.clone()]], input.schema(), None).unwrap(),
                &input_schema,
                dataset,
                None,
                None,
                &session.state(),
            )
            .unwrap()
            .with_payload_columns(vec!["payload".into()])
            .unwrap(),
        );
        if cancel {
            let mut stream = exec.execute(0, session.task_ctx()).unwrap();
            let mut next = Box::pin(stream.next());
            assert!(futures::poll!(&mut next).is_pending());
            drop(next);
            drop(stream);
            drop(exec);
            assert!(snapshot.upgrade().is_none());
        } else {
            let batches = collect(exec.clone(), session.task_ctx()).await.unwrap();
            assert_eq!(batches.len(), 4);
            assert!(batches.iter().all(|batch| batch.num_rows() == 1));
            let output = concat_batches(&exec.schema(), &batches).unwrap();
            assert_eq!(output["payload"].to_data(), stored["payload"].to_data());
            assert_eq!(
                exec.metrics()
                    .unwrap()
                    .sum_by_name("payload_take_rows")
                    .unwrap()
                    .as_usize(),
                4
            );
        }
        assert_eq!(original.latest_version_id().await.unwrap(), 1);
        assert_eq!(original.scan().try_into_batch().await.unwrap(), stored);
    }

    #[rstest::rstest]
    #[case::payload_no_candidates(true, false)]
    #[case::payload_after_insert_prefix(true, true)]
    #[case::condition_only(false, true)]
    #[tokio::test]
    async fn materialization_chunks_count_candidates_not_input_rows(
        #[case] with_payload: bool,
        #[case] with_updates: bool,
    ) {
        let large = "x".repeat(32 * 1024);
        let stored = record_batch!(
            ("key", Int32, [0, 1]),
            ("payload", Utf8, [large.as_str(), large.as_str()])
        )
        .unwrap();
        let dataset = Arc::new(
            Dataset::write(
                RecordBatchIterator::new([Ok(stored.clone())], stored.schema()),
                "memory://",
                Some(WriteParams {
                    max_rows_per_file: 1,
                    ..Default::default()
                }),
            )
            .await
            .unwrap(),
        );
        let mut addresses = vec![None; 12];
        let mut actions = vec![Action::Insert as u8; 12];
        if with_updates {
            addresses[10] = Some(u64::from(RowAddress::new_from_parts(0, 0)));
            addresses[11] = Some(u64::from(RowAddress::new_from_parts(1, 0)));
            actions[10..].fill(Action::UpdateAll as u8);
        }
        let input = record_batch!(
            ("_rowid", UInt64, addresses.clone()),
            ("_rowaddr", UInt64, addresses),
            ("key", Int32, (100..112).collect::<Vec<i32>>()),
            ("__merge_source_sentinel", Boolean, vec![true; 12]),
            ("__action", UInt8, actions)
        )
        .unwrap();
        let input_schema = DFSchema::from_field_specific_qualified_schema(
            ["target", "target", "source", "source"]
                .map(|relation| Some(TableReference::bare(relation)))
                .into_iter()
                .chain([None])
                .collect(),
            &input.schema(),
        )
        .unwrap();
        // The first batch has no candidates. The next starts with two more
        // inserts before a value larger than the partition's soft byte target.
        let runtime = RuntimeEnvBuilder::new()
            .with_memory_pool(Arc::new(GreedyMemoryPool::new(64 * 1024)))
            .build_arc()
            .unwrap();
        let session =
            SessionContext::new_with_config_rt(SessionConfig::new().with_batch_size(8), runtime);
        let exec = MergeConditionExec::try_new(
            TestMemoryExec::try_new_exec(
                &[vec![input.slice(0, 8), input.slice(8, 4)]],
                input.schema(),
                None,
            )
            .unwrap(),
            &input_schema,
            dataset,
            (!with_payload).then(|| col("target.payload").is_not_null()),
            None,
            &session.state(),
        )
        .unwrap();
        let exec = if with_payload {
            exec.with_payload_columns(vec!["payload".into()]).unwrap()
        } else {
            exec
        };
        let metric = if with_payload {
            "payload_take_rows"
        } else {
            "condition_take_rows"
        };
        let taken_rows = || {
            exec.metrics()
                .unwrap()
                .sum_by_name(metric)
                .unwrap()
                .as_usize()
        };
        let mut stream = exec.execute(0, session.task_ctx()).unwrap();
        let first = stream.next().await.unwrap().unwrap();
        assert_eq!(first.num_rows(), 8);
        assert_eq!(taken_rows(), 0);
        let second = stream.next().await.unwrap().unwrap();
        let mut batches = vec![first, second];
        if with_payload && with_updates {
            assert_eq!(batches[1].num_rows(), 3);
            assert_eq!(taken_rows(), 1);
            let third = stream.next().await.unwrap().unwrap();
            assert_eq!(third.num_rows(), 1);
            batches.push(third);
        } else {
            assert_eq!(batches[1].num_rows(), 4);
        }
        assert!(stream.next().await.is_none());
        assert_eq!(taken_rows(), if with_updates { 2 } else { 0 });
        let output = concat_batches(&exec.schema(), &batches).unwrap();
        for field in input.schema().fields() {
            assert_eq!(
                output[field.name().as_str()].to_data(),
                input[field.name().as_str()].to_data()
            );
        }
        if with_payload {
            let payload = output["payload"].as_string::<i32>();
            assert_eq!(payload.null_count(), if with_updates { 10 } else { 12 });
            if with_updates {
                assert_eq!(payload.value(10), large);
                assert_eq!(payload.value(11), large);
            }
        }
    }

    #[tokio::test]
    async fn fixed_width_null_payload_obeys_output_row_budget_without_taking() {
        let payload = arrow_array::FixedSizeBinaryArray::try_from_iter(
            [vec![0u8; 512], vec![1u8; 512]].into_iter(),
        )
        .unwrap();
        let stored = RecordBatch::try_from_iter([
            (
                "key",
                Arc::new(arrow_array::Int32Array::from(vec![0, 1])) as ArrayRef,
            ),
            ("payload", Arc::new(payload) as ArrayRef),
        ])
        .unwrap();
        let dataset = Arc::new(
            Dataset::write(
                RecordBatchIterator::new([Ok(stored.clone())], stored.schema()),
                "memory://",
                Some(WriteParams {
                    max_rows_per_file: 1,
                    ..Default::default()
                }),
            )
            .await
            .unwrap(),
        );
        let input = record_batch!(
            ("_rowid", UInt64, vec![None::<u64>; 8]),
            ("_rowaddr", UInt64, vec![None::<u64>; 8]),
            ("key", Int32, (100..108).collect::<Vec<i32>>()),
            ("__merge_source_sentinel", Boolean, vec![true; 8]),
            ("__action", UInt8, [2, 0, 2, 0, 2, 0, 2, 0])
        )
        .unwrap();
        let input_schema = DFSchema::from_field_specific_qualified_schema(
            ["target", "target", "source", "source"]
                .map(|relation| Some(TableReference::bare(relation)))
                .into_iter()
                .chain([None])
                .collect(),
            &input.schema(),
        )
        .unwrap();
        // The 2 KiB soft target and four-buffer headroom allow one 512-byte
        // fixed-width value per output, even when every value is NULL.
        let runtime = RuntimeEnvBuilder::new()
            .with_memory_pool(Arc::new(GreedyMemoryPool::new(16 * 1024)))
            .build_arc()
            .unwrap();
        let session =
            SessionContext::new_with_config_rt(SessionConfig::new().with_batch_size(8), runtime);
        let exec = Arc::new(
            MergeConditionExec::try_new(
                TestMemoryExec::try_new_exec(&[vec![input.clone()]], input.schema(), None).unwrap(),
                &input_schema,
                dataset,
                None,
                None,
                &session.state(),
            )
            .unwrap()
            .with_payload_columns(vec!["payload".into()])
            .unwrap(),
        );
        assert_eq!(
            exec.schema()
                .field_with_name("payload")
                .unwrap()
                .data_type(),
            &DataType::FixedSizeBinary(512)
        );
        let batches = collect(exec.clone(), session.task_ctx()).await.unwrap();
        assert_eq!(batches.len(), 8);
        for batch in &batches {
            assert_eq!(batch.num_rows(), 1);
            assert_eq!(batch["payload"].null_count(), 1);
            assert!(batch["payload"].get_array_memory_size() < 2 * 1024);
        }
        assert_eq!(
            exec.metrics()
                .unwrap()
                .sum_by_name("payload_take_rows")
                .unwrap()
                .as_usize(),
            0
        );
        let output = concat_batches(&exec.schema(), &batches).unwrap();
        assert_eq!(
            output[MERGE_ACTION_COLUMN].to_data(),
            input[MERGE_ACTION_COLUMN].to_data()
        );
    }

    /// The taken columns must carry the types the target scan presents, or a
    /// condition that resolves against the scan fails against the take.
    #[rstest::rstest]
    #[case::legacy_blob(LanceFileVersion::V2_1, legacy_blob_batch())]
    #[case::blob_v2(LanceFileVersion::V2_2, blob_v2_batch())]
    #[case::json(LanceFileVersion::V2_2, json_batch())]
    #[case::plain_binary(LanceFileVersion::V2_2, plain_binary_batch())]
    #[tokio::test]
    async fn taken_types_match_the_target_scan(
        #[case] version: LanceFileVersion,
        #[case] batch: RecordBatch,
    ) {
        let ds = Arc::new(
            Dataset::write(
                Box::new(RecordBatchIterator::new(
                    [Ok(batch.clone())],
                    batch.schema(),
                )),
                "memory://",
                Some(WriteParams {
                    data_storage_version: Some(version),
                    ..Default::default()
                }),
            )
            .await
            .unwrap(),
        );
        let scan = LanceTableProvider::new_with_ordering(ds.clone(), true, true, false)
            .with_blob_handling(target_blob_handling(&ds));
        let scanned = scan.schema().field_with_name("payload").unwrap().clone();

        let input = record_batch!(
            ("_rowid", UInt64, [0u64]),
            ("_rowaddr", UInt64, [0u64]),
            ("key", Int32, [1]),
            ("__merge_source_sentinel", Boolean, [Some(true)]),
            ("__action", UInt8, [1u8])
        )
        .unwrap();
        let input_schema = DFSchema::from_field_specific_qualified_schema(
            ["target", "target", "source", "source"]
                .map(|relation| Some(TableReference::bare(relation)))
                .into_iter()
                .chain([None])
                .collect(),
            &input.schema(),
        )
        .unwrap();
        let session = SessionContext::new();
        let exec = MergeConditionExec::try_new(
            TestMemoryExec::try_new_exec(&[vec![input.clone()]], input.schema(), None).unwrap(),
            &input_schema,
            ds,
            Some(col("target.payload").is_not_null()),
            None,
            &session.state(),
        )
        .unwrap();
        let taken = exec
            .evaluator
            .eval_schema
            .field_with_name("payload")
            .unwrap()
            .clone();
        assert_eq!(taken.data_type(), scanned.data_type());
        assert_eq!(taken.is_nullable(), scanned.is_nullable());
    }

    fn json_batch() -> RecordBatch {
        let payload = lance_arrow::json::json_field("payload", true);
        let values: ArrayRef = match payload.data_type() {
            DataType::Utf8 => Arc::new(arrow_array::StringArray::from(vec![r#"{"a":1}"#])),
            DataType::LargeUtf8 => {
                Arc::new(arrow_array::LargeStringArray::from(vec![r#"{"a":1}"#]))
            }
            _ => Arc::new(arrow_array::LargeBinaryArray::from(vec![
                lance_arrow::json::encode_json(r#"{"a":1}"#)
                    .unwrap()
                    .as_slice(),
            ])),
        };
        RecordBatch::try_new(
            Arc::new(arrow_schema::Schema::new(vec![
                arrow_schema::Field::new("key", DataType::Int32, false),
                payload,
            ])),
            vec![Arc::new(arrow_array::Int32Array::from(vec![1])), values],
        )
        .unwrap()
    }

    fn plain_binary_batch() -> RecordBatch {
        record_batch!(
            ("key", Int32, [1]),
            ("payload", LargeBinary, [b"old".as_slice()])
        )
        .unwrap()
    }

    fn legacy_blob_batch() -> RecordBatch {
        let payload =
            arrow_schema::Field::new("payload", DataType::LargeBinary, true).with_metadata(
                HashMap::from([(lance_arrow::BLOB_META_KEY.to_string(), "true".to_string())]),
            );
        RecordBatch::try_new(
            Arc::new(arrow_schema::Schema::new(vec![
                arrow_schema::Field::new("key", DataType::Int32, false),
                payload,
            ])),
            vec![
                Arc::new(arrow_array::Int32Array::from(vec![1])),
                Arc::new(arrow_array::LargeBinaryArray::from(vec![Some(
                    b"old".as_slice(),
                )])),
            ],
        )
        .unwrap()
    }

    fn blob_v2_batch() -> RecordBatch {
        let mut blobs = BlobArrayBuilder::new(1);
        blobs.push_bytes(b"old").unwrap();
        RecordBatch::try_new(
            Arc::new(arrow_schema::Schema::new(vec![
                arrow_schema::Field::new("key", DataType::Int32, false),
                blob_field("payload", true),
            ])),
            vec![
                Arc::new(arrow_array::Int32Array::from(vec![1])),
                blobs.finish().unwrap(),
            ],
        )
        .unwrap()
    }

    /// `WhenMatched::Delete` marks matched rows `Delete` unconditionally; the
    /// `DeleteIf` gate applies to the target-only rows alone, which the join
    /// left without a source sentinel.
    #[tokio::test]
    async fn delete_if_gates_target_only_rows_only() {
        // Two 50-row fragments; `payload` is null at local row 25.
        let mut nulls = vec![false; 50];
        nulls[25] = true;
        let batch = gen_batch()
            .with_seed(Seed::from(7))
            .col("key", array::step::<Int32Type>())
            .col(
                "payload",
                array::rand_fixedbin(ByteCount::from(8), true).with_nulls(&nulls),
            )
            .into_batch_rows(RowCount::from(100))
            .unwrap();
        let ds = Dataset::write(
            Box::new(RecordBatchIterator::new(
                [Ok(batch.clone())],
                batch.schema(),
            )),
            "memory://",
            Some(WriteParams {
                max_rows_per_file: 50,
                ..Default::default()
            }),
        )
        .await
        .unwrap();

        // Row 0 is matched; rows 1 and 2 are target-only and only row 1's
        // payload is null.
        let input = record_batch!(
            ("_rowid", UInt64, [25u64, (1 << 32) | 25, (1 << 32) | 30]),
            ("_rowaddr", UInt64, [25u64, (1 << 32) | 25, (1 << 32) | 30]),
            ("key", Int32, [25, 75, 80]),
            ("__merge_source_sentinel", Boolean, [Some(true), None, None]),
            ("__action", UInt8, [3u8, 3, 3])
        )
        .unwrap();
        let input_schema = DFSchema::from_field_specific_qualified_schema(
            ["target", "target", "source", "source"]
                .map(|relation| Some(TableReference::bare(relation)))
                .into_iter()
                .chain([None])
                .collect(),
            &input.schema(),
        )
        .unwrap();
        let session = SessionContext::new();
        let exec = MergeConditionExec::try_new(
            TestMemoryExec::try_new_exec(&[vec![input.clone()]], input.schema(), None).unwrap(),
            &input_schema,
            Arc::new(ds),
            None,
            Some(col("target.payload").is_null()),
            &session.state(),
        )
        .unwrap();
        let output = collect(Arc::new(exec), session.task_ctx()).await.unwrap();
        let actions = output[0][MERGE_ACTION_COLUMN].as_primitive::<UInt8Type>();
        assert_eq!(
            actions.values(),
            &[
                Action::Delete as u8,
                Action::Delete as u8,
                Action::Nothing as u8
            ]
        );
    }
}
