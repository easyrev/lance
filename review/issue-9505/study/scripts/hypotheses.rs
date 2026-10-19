// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: Copyright The Lance Authors

//! Isolated research driver. Not enabled in production builds.

use super::*;
use std::collections::BTreeMap;
use std::fmt::{Display, Formatter};
use std::fs::{File, OpenOptions};
use std::io::Write;
use std::path::PathBuf;
use std::sync::Mutex;
use std::time::Instant;

use arrow_array::{Array, Int64Array, UInt8Array, cast::AsArray};
use arrow_ipc::{reader::FileReader, writer::FileWriter};
use arrow_schema::SchemaRef;
use datafusion::common::{DFSchema, Statistics, config::ConfigOptions, stats::Precision};
use datafusion::execution::{SessionStateBuilder, TaskContext};
use datafusion::execution::memory_pool::{FairSpillPool, MemoryLimit, MemoryPool, MemoryReservation};
use datafusion::execution::runtime_env::RuntimeEnvBuilder;
use datafusion::physical_expr::{EquivalenceProperties, Partitioning};
use datafusion::physical_optimizer::PhysicalOptimizerRule;
use datafusion::physical_plan::{DisplayAs, DisplayFormatType, PlanProperties, displayable};
use datafusion::physical_plan::joins::{HashJoinExec, PartitionMode};
use datafusion::physical_plan::repartition::RepartitionExec;
use datafusion::physical_plan::stream::RecordBatchStreamAdapter;
use datafusion::physical_plan::streaming::PartitionStream;
use futures::{TryStreamExt, stream};
use serde_json::{Value, json};

mod deferred_reference;

type ProbeResult<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;

#[derive(Debug, Default)]
struct PoolCounters {
    peak: usize,
    per_consumer: BTreeMap<String, (usize, usize)>,
    failed_reservations: usize,
    infallible_grows: usize,
}

#[derive(Debug)]
struct ObservedPool {
    inner: FairSpillPool,
    counters: Mutex<PoolCounters>,
}

impl ObservedPool {
    fn new(bytes: usize) -> Self {
        Self { inner: FairSpillPool::new(bytes), counters: Mutex::new(PoolCounters::default()) }
    }
    fn record(&self, counters: &mut PoolCounters, reservation: &MemoryReservation, add: usize, remove: usize) {
        counters.peak = counters.peak.max(self.inner.reserved());
        let usage = counters.per_consumer.entry(reservation.consumer().name().to_string()).or_default();
        usage.0 = usage.0 + add - remove;
        usage.1 = usage.1.max(usage.0);
    }
    fn snapshot(&self) -> Value {
        let c = self.counters.lock().unwrap();
        json!({"reserved": self.inner.reserved(), "peak_reserved": c.peak,
            "per_consumer_current_peak": c.per_consumer,
            "failed_reservations": c.failed_reservations, "infallible_grows": c.infallible_grows,
            "interpretation": "Reservation mutations are serialized for exact tracked high-water accounting; unregistered arrays are not included."})
    }
}
impl Display for ObservedPool {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result { write!(f, "Observed({})", self.inner) }
}
impl MemoryPool for ObservedPool {
    fn name(&self) -> &str { "ObservedFairSpillPool" }
    fn register(&self, consumer: &MemoryConsumer) {
        let _lock = self.counters.lock().unwrap(); self.inner.register(consumer);
    }
    fn unregister(&self, consumer: &MemoryConsumer) {
        let _lock = self.counters.lock().unwrap(); self.inner.unregister(consumer);
    }
    fn grow(&self, r: &MemoryReservation, n: usize) {
        let mut c = self.counters.lock().unwrap(); self.inner.grow(r,n); c.infallible_grows += 1; self.record(&mut c,r,n,0);
    }
    fn shrink(&self, r: &MemoryReservation, n: usize) {
        let mut c = self.counters.lock().unwrap(); self.inner.shrink(r,n); self.record(&mut c,r,0,n);
    }
    fn try_grow(&self, r: &MemoryReservation, n: usize) -> datafusion::error::Result<()> {
        let mut c = self.counters.lock().unwrap();
        match self.inner.try_grow(r,n) {
            Ok(()) => { self.record(&mut c,r,n,0); Ok(()) }
            Err(e) => { c.failed_reservations += 1; Err(e) }
        }
    }
    fn reserved(&self) -> usize { self.inner.reserved() }
    fn memory_limit(&self) -> MemoryLimit { self.inner.memory_limit() }
}

fn save(path: impl AsRef<std::path::Path>, v: &Value) -> ProbeResult<()> {
    std::fs::write(path, serde_json::to_vec_pretty(v)?)?; Ok(())
}
fn flag(spec: &Value, name: &str, default: bool) -> bool { spec[name].as_bool().unwrap_or(default) }
fn number(spec: &Value, name: &str, default: usize) -> usize { spec[name].as_u64().map(|x|x as usize).unwrap_or(default) }
fn stats_json(plan: &Arc<dyn ExecutionPlan>) -> Value {
    match plan.partition_statistics(None) {
        Ok(s) => json!({"rows": format!("{:?}", s.num_rows), "bytes": format!("{:?}", s.total_byte_size),
            "rows_value": s.num_rows.get_value(), "bytes_value": s.total_byte_size.get_value()}),
        Err(e) => json!({"error": e.to_string()}),
    }
}
fn has_scan(plan: &Arc<dyn ExecutionPlan>) -> bool {
    matches!(plan.name(), "FilteredReadExec" | "LanceScanExec" | "LancePushdownScanExec")
        || plan.children().iter().any(|p| has_scan(p))
}
fn variable_schema(schema: &arrow_schema::Schema) -> bool {
    schema.fields().iter().any(|f| matches!(f.data_type(), DataType::Binary | DataType::LargeBinary | DataType::Utf8 | DataType::LargeUtf8 | DataType::BinaryView | DataType::Utf8View))
}

#[derive(Debug)]
struct TargetStatistics {
    input: Arc<dyn ExecutionPlan>,
    bytes: Option<usize>,
    mask_rows: bool,
}
impl DisplayAs for TargetStatistics {
    fn fmt_as(&self, _: DisplayFormatType, f: &mut Formatter<'_>) -> std::fmt::Result {
        write!(f, "ProbeTargetStatistics: bytes={:?}, mask_rows={}", self.bytes, self.mask_rows)
    }
}
impl ExecutionPlan for TargetStatistics {
    fn name(&self) -> &str { "ProbeTargetStatistics" }
    fn properties(&self) -> &Arc<PlanProperties> { self.input.properties() }
    fn children(&self) -> Vec<&Arc<dyn ExecutionPlan>> { vec![&self.input] }
    fn maintains_input_order(&self) -> Vec<bool> { vec![true] }
    fn with_new_children(self: Arc<Self>, mut c: Vec<Arc<dyn ExecutionPlan>>) -> datafusion::error::Result<Arc<dyn ExecutionPlan>> {
        assert_eq!(c.len(),1); Ok(Arc::new(Self { input:c.remove(0),bytes:self.bytes,mask_rows:self.mask_rows }))
    }
    fn partition_statistics(&self, partition: Option<usize>) -> datafusion::error::Result<Arc<Statistics>> {
        let mut stats = self.input.partition_statistics(partition)?.as_ref().clone();
        stats.total_byte_size = self.bytes.map(Precision::Inexact).unwrap_or(Precision::Absent);
        if self.mask_rows { stats.num_rows = Precision::Absent; }
        Ok(Arc::new(stats))
    }
    fn execute(&self, p:usize, c:Arc<TaskContext>) -> datafusion::error::Result<SendableRecordBatchStream> { self.input.execute(p,c) }
}

#[derive(Debug)]
struct HypothesisPolicy {
    policy: String,
    manifest_bytes: usize,
    observations: Arc<Mutex<Vec<Value>>>,
}
impl PhysicalOptimizerRule for HypothesisPolicy {
    fn name(&self) -> &str { "source_hypothesis_policy" }
    fn schema_check(&self) -> bool { true }
    fn optimize(&self, plan: Arc<dyn ExecutionPlan>, _: &ConfigOptions) -> datafusion::error::Result<Arc<dyn ExecutionPlan>> {
        Ok(plan.transform_up(|p| {
            let Some(join) = p.downcast_ref::<HashJoinExec>() else { return Ok(Transformed::no(p)); };
            let left_target = has_scan(join.left());
            if left_target == has_scan(join.right()) { return Ok(Transformed::no(p)); }
            let target = if left_target { join.left().clone() } else { join.right().clone() };
            let source = if left_target { join.right().clone() } else { join.left().clone() };
            self.observations.lock().unwrap().push(json!({"policy":self.policy,"target_before":stats_json(&target),"source_before":stats_json(&source),
                "target_schema":format!("{:?}",target.schema()),"target_variable":variable_schema(target.schema().as_ref()),"manifest_file_bytes":self.manifest_bytes}));
            if self.policy == "p" { return Ok(Transformed::no(p)); }
            let guarded = self.policy == "guard" && variable_schema(target.schema().as_ref());
            let new_target: Arc<dyn ExecutionPlan> = match self.policy.as_str() {
                "manifest" => {
                    let rows = target.partition_statistics(None)?.num_rows.get_value().copied().unwrap_or(0);
                    Arc::new(TargetStatistics { input:target,bytes:Some(self.manifest_bytes.saturating_add(16*rows)),mask_rows:false })
                },
                "guard" | "mask_only" if variable_schema(target.schema().as_ref()) => Arc::new(TargetStatistics { input:target,bytes:None,mask_rows:true }),
                _ => target,
            };
            let (left,right) = if left_target { (new_target,source) } else { (source,new_target) };
            let rebuilt = p.clone().with_new_children(vec![left,right])?;
            let rebuilt_join = rebuilt.downcast_ref::<HashJoinExec>().unwrap();
            let source_left = self.policy == "guard";
            let output = if source_left == left_target { rebuilt_join.swap_inputs(*rebuilt_join.partition_mode())? } else { rebuilt };
            self.observations.lock().unwrap().push(json!({"target_masked":guarded,"initial_build":if source_left {"source"} else {"target"}}));
            Ok(Transformed::yes(output))
        })?.data)
    }
}

fn collect_metrics(plan: &Arc<dyn ExecutionPlan>, path: String, output: &mut Vec<Value>) {
    let metrics = plan.metrics().map(|set| set.iter().map(|m| json!({"partition":m.partition(),"name":m.value().name(),"value":m.value().to_string(),"numeric":m.value().as_usize()})).collect::<Vec<_>>()).unwrap_or_default();
    output.push(json!({"path":path,"name":plan.name(),"display":format!("{}",displayable(plan.as_ref()).one_line()),
        "statistics":stats_json(plan),"partitioning":format!("{:?}",plan.properties().output_partitioning()),"metrics":metrics}));
    for (i,c) in plan.children().iter().enumerate() { collect_metrics(c,format!("{path}/{i}"),output); }
}

fn row_bytes(batch: &RecordBatch, index: usize) -> ProbeResult<usize> {
    let mut bytes = 0;
    for array in batch.columns() {
        bytes += match array.data_type() {
            DataType::Int64 | DataType::UInt64 => 9,
            DataType::Binary => if array.is_null(index) {5} else {array.as_binary::<i32>().value(index).len()+5},
            DataType::LargeBinary => if array.is_null(index) {9} else {array.as_binary::<i64>().value(index).len()+9},
            DataType::Utf8 => if array.is_null(index) {5} else {array.as_string::<i32>().value(index).len()+5},
            DataType::LargeUtf8 => if array.is_null(index) {9} else {array.as_string::<i64>().value(index).len()+9},
            other => return Err(format!("Byte-split spike does not implement {other:?}").into()),
        };
    }
    Ok(bytes)
}

#[derive(Debug)]
struct IpcPartition {
    path: PathBuf,
    schema: SchemaRef,
    producer: PathBuf,
    split_bytes: usize,
    consumed: std::sync::atomic::AtomicBool,
}
impl PartitionStream for IpcPartition {
    fn schema(&self) -> &SchemaRef { &self.schema }
    fn execute(&self, _:Arc<TaskContext>) -> SendableRecordBatchStream {
        assert!(!self.consumed.swap(true,Ordering::SeqCst),"one-shot source executed twice");
        let reader = FileReader::try_new(File::open(&self.path).unwrap(),None).unwrap();
        let producer = self.producer.clone();
        let split_bytes = self.split_bytes;
        let mut reader=reader;
        let mut pending:Option<(RecordBatch,usize)>=None;
        let batches=std::iter::from_fn(move || {
            let item:ProbeResult<Option<RecordBatch>>=(|| {
                if pending.is_none() {
                    let Some(batch)=reader.next() else {return Ok(None);};
                    pending=Some((batch?,0));
                }
                let (batch,start)=pending.as_ref().unwrap();
                let (output,next)=if split_bytes==0 { (batch.clone(),batch.num_rows()) } else {
                    let mut end=*start;let mut bytes=0;
                    while end<batch.num_rows() {
                        let size=row_bytes(batch,end)?;
                        if end>*start && bytes+size>split_bytes {break;}
                        bytes+=size;end+=1;
                    }
                    let indices=UInt32Array::from_iter_values((*start..end).map(|x|x as u32));
                    (arrow_select::take::take_record_batch(batch,&indices)?,end)
                };
                let input_bytes=batch.get_array_memory_size();
                if next==batch.num_rows() {pending=None;} else {pending.as_mut().unwrap().1=next;}
                let line=json!({"rows":output.num_rows(),"bytes":output.get_array_memory_size(),"input_batch_bytes":input_bytes,"split_target":split_bytes});
                writeln!(OpenOptions::new().create(true).append(true).open(&producer)?,"{line}")?;
                Ok(Some(output))
            })();
            match item {Ok(Some(batch))=>Some(Ok(batch)),Ok(None)=>None,Err(e)=>Some(Err(DataFusionError::Execution(e.to_string())))}
        });
        Box::pin(RecordBatchStreamAdapter::new(self.schema.clone(),stream::iter(batches)))
    }
}
fn provider(spec:&Value,dir:&std::path::Path) -> ProbeResult<Arc<dyn TableProvider>> {
    let path=PathBuf::from(spec["source_ipc"].as_str().unwrap());
    let reader=FileReader::try_new(File::open(&path)?,None)?;
    let schema=reader.schema();
    if spec["source_form"] == "complete" {
        let batches=reader.collect::<std::result::Result<Vec<_>,_>>()?;
        for b in &batches { writeln!(OpenOptions::new().create(true).append(true).open(dir.join("producer.jsonl"))?,"{}",json!({"rows":b.num_rows(),"bytes":b.get_array_memory_size()}))?; }
        Ok(Arc::new(MemTable::try_new(schema,vec![batches])?))
    } else {
        Ok(Arc::new(StreamingTable::try_new(schema.clone(),vec![Arc::new(IpcPartition {path,schema,producer:dir.join("producer.jsonl"),split_bytes:number(spec,"split_bytes",0),consumed:std::sync::atomic::AtomicBool::new(false)})])?))
    }
}
fn manifest_bytes(dataset:&Dataset) -> usize {
    dataset.fragments().iter().flat_map(|f|f.files.iter()).map(|f|f.file_size_bytes.get().map(|x|x.get()).unwrap_or(0) as usize).sum()
}
fn context(spec:&Value,dataset:&Dataset,dir:&std::path::Path) -> ProbeResult<(MergeBudget,Arc<ObservedPool>,Arc<Mutex<Vec<Value>>>)> {
    let bytes=number(spec,"pool_bytes",1<<30);
    let pool=Arc::new(ObservedPool::new(bytes));
    let runtime=Arc::new(RuntimeEnvBuilder::new().with_memory_pool(pool.clone()).build()?);
    let mut budget=MergeBudget::new(dataset,None);
    let mut state=budget.session_ctx.state();
    let options=state.config_mut().options_mut();
    options.execution.target_partitions=number(spec,"partitions",16);
    options.execution.batch_size=number(spec,"batch_size",8192);
    options.optimizer.join_reordering=flag(spec,"join_reordering",true);
    options.optimizer.repartition_joins=flag(spec,"repartition_joins",true);
    options.optimizer.enable_round_robin_repartition=flag(spec,"round_robin",true);
    options.optimizer.use_statistics_registry=flag(spec,"statistics_registry",true);
    let observations=Arc::new(Mutex::new(Vec::new()));
    let policy=Arc::new(HypothesisPolicy {policy:spec["policy"].as_str().unwrap_or("p").to_string(),manifest_bytes:manifest_bytes(dataset),observations:observations.clone()});
    let mut rules=state.physical_optimizers().to_vec();
    let index=rules.iter().position(|r|r.name()=="join_selection").unwrap();
    rules.insert(index,policy);
    let state=SessionStateBuilder::new_from_existing(state).with_runtime_env(runtime).with_physical_optimizer_rules(rules).build();
    budget.session_ctx=SessionContext::new_with_state(state);
    if spec["scan_batch_rows"].is_number() { budget.batch_rows=Some(number(spec,"scan_batch_rows",8)); }
    if spec["scan_io_bytes"].is_number() { budget.scan_io_bytes=number(spec,"scan_io_bytes",16<<20) as u64; }
    save(dir.join("context.json"),&json!({"pool_bytes":bytes,"options":format!("{:?}",budget.session_ctx.copied_config()),
        "scan_batch_rows":budget.batch_rows,"scan_io_bytes":budget.scan_io_bytes,"manifest_file_bytes":manifest_bytes(dataset),"instrumentation":"ObservedPool wraps FairSpillPool; includes a mutex around reservation mutations"}))?;
    Ok((budget,pool,observations))
}
fn process_io() -> BTreeMap<String,u64> {
    std::fs::read_to_string("/proc/self/io").unwrap().lines().filter_map(|line|{
        let (k,v)=line.split_once(": ")?;Some((k.to_string(),v.parse().ok()?))
    }).collect()
}
fn process_cpu() -> f64 {
    let stat=std::fs::read_to_string("/proc/self/stat").unwrap();
    let columns=stat.rsplit_once(')').unwrap().1.split_whitespace().collect::<Vec<_>>();
    (columns[11].parse::<u64>().unwrap()+columns[12].parse::<u64>().unwrap()) as f64 / 100.0
}

async fn merge_probe(spec:&Value,dir:&std::path::Path) -> ProbeResult<Value> {
    let dataset=Arc::new(Dataset::open(dir.join("dataset").to_str().unwrap()).await?);
    let before=dataset.version().version;
    let input=provider(spec,dir)?;
    let (budget,pool,observations)=context(spec,&dataset,dir)?;
    let mut builder=MergeInsertBuilder::try_new(dataset.clone(),vec!["id".into()])?;
    builder.use_index(false).when_matched(WhenMatched::UpdateAll).when_not_matched(if flag(spec,"insert",false) { WhenNotMatched::InsertAll } else { WhenNotMatched::DoNothing });
    let job=builder.try_build()?;
    let start=Instant::now();
    let plan=job.create_plan_in(input,&budget).await?;
    let planning_seconds=start.elapsed().as_secs_f64();
    std::fs::write(dir.join("plan-before.txt"),format!("{}",displayable(plan.as_ref()).indent(true)))?;
    save(dir.join("statistics-before-selection.json"),&json!(*observations.lock().unwrap()))?;
    if flag(spec,"plan_only",false) { return Ok(json!({"status":"plan_only","planning_seconds":planning_seconds,"pool":pool.snapshot()})); }
    let io_before=process_io(); let cpu=process_cpu(); let started=Instant::now();
    let execution:ProbeResult<Value>=async {
        let mut stream=plan.execute(0,budget.session_ctx.task_ctx())?;
        while let Some(batch)=stream.try_next().await? { assert_eq!(batch.num_rows(),0); }
        let sink=plan.downcast_ref::<exec::FullSchemaMergeInsertExec>().unwrap();
        let stats=sink.merge_stats().ok_or("missing writer completion stats")?;
        let transaction=sink.transaction().ok_or("missing writer transaction")?;
        let updated=CommitBuilder::new(dataset.clone()).with_skip_auto_cleanup(true).execute(transaction).await?;
        Ok(json!({"num_updated_rows":stats.num_updated_rows,"num_inserted_rows":stats.num_inserted_rows,"num_deleted_rows":stats.num_deleted_rows,"version":updated.version().version}))
    }.await;
    let seconds=started.elapsed().as_secs_f64();let cpu_seconds=process_cpu()-cpu;
    let io=process_io().into_iter().map(|(k,v)|{let diff=v-io_before.get(&k).copied().unwrap_or(0);(k,diff)}).collect::<BTreeMap<_,_>>();
    let mut metrics=Vec::new();collect_metrics(&plan,"0".into(),&mut metrics);
    std::fs::write(dir.join("plan-after.txt"),format!("{}",displayable(plan.as_ref()).indent(true)))?;
    save(dir.join("operator-metrics.json"),&json!(metrics))?;
    let (status,stats,error)=match execution {
        Ok(value)=>("success",value,Value::Null),Err(error)=>("execution_error",Value::Null,json!(error.to_string())),
    };
    Ok(json!({"status":status,"error":error,"merge_stats":if stats.is_null(){Value::Null}else{json!({"num_updated_rows":stats["num_updated_rows"],"num_inserted_rows":stats["num_inserted_rows"],"num_deleted_rows":stats["num_deleted_rows"]})},
        "version_before":before,"version_after":stats["version"],"merge_seconds":seconds,"planning_seconds":planning_seconds,"timing_scope":"execute and commit; planning and complete-input materialization excluded, no comparison to old API times","cpu_seconds":cpu_seconds,"io_delta":io,"pool":pool.snapshot()}))
}

async fn repartition_probe(spec:&Value,dir:&std::path::Path) -> ProbeResult<Value> {
    let dataset=Dataset::open(spec["fixture"].as_str().unwrap()).await?;
    let (budget,pool,_)=context(spec,&dataset,dir)?;
    let input=provider(spec,dir)?.scan(&budget.session_ctx.state(),None,&[],None).await?;
    let partitions=number(spec,"partitions",16);
    let plan:Arc<dyn ExecutionPlan>=Arc::new(RepartitionExec::try_new(input,Partitioning::RoundRobinBatch(partitions))?);
    std::fs::write(dir.join("plan-before.txt"),format!("{}",displayable(plan.as_ref()).indent(true)))?;
    let cpu=process_cpu();let io_before=process_io();let started=Instant::now();
    let tasks=(0..partitions).map(|p|{
        let plan=plan.clone();let ctx=budget.session_ctx.task_ctx();let path=dir.join(format!("output-{p}.arrow"));
        async move {
            let mut stream=plan.execute(p,ctx)?;let mut writer=FileWriter::try_new(File::create(path)?,plan.schema().as_ref())?;let mut rows=0;let mut batches=0;let mut peak_batch=0;
            while let Some(batch)=stream.try_next().await? {rows+=batch.num_rows();batches+=1;peak_batch=peak_batch.max(batch.get_array_memory_size());writer.write(&batch)?;}
            writer.finish()?;Ok::<_,Box<dyn std::error::Error+Send+Sync>>(json!({"partition":p,"rows":rows,"batches":batches,"max_output_batch_bytes":peak_batch}))
        }
    });
    let distribution=futures::future::try_join_all(tasks).await;
    let seconds=started.elapsed().as_secs_f64();let cpu_seconds=process_cpu()-cpu;
    let io=process_io().into_iter().map(|(k,v)|{let diff=v-io_before.get(&k).copied().unwrap_or(0);(k,diff)}).collect::<BTreeMap<_,_>>();
    let mut metrics=Vec::new();collect_metrics(&plan,"0".into(),&mut metrics);save(dir.join("operator-metrics.json"),&json!(metrics))?;
    match distribution {
        Ok(distribution)=>Ok(json!({"status":"success","distribution":distribution,"merge_seconds":seconds,"cpu_seconds":cpu_seconds,"io_delta":io,"pool":pool.snapshot(),"timing_scope":"RoundRobin execution plus common IPC sink; not full merge API"})),
        Err(error)=>Ok(json!({"status":"execution_error","error":error.to_string(),"merge_seconds":seconds,"cpu_seconds":cpu_seconds,"io_delta":io,"pool":pool.snapshot()})),
    }
}

async fn take_probe(spec:&Value,dir:&std::path::Path) -> ProbeResult<Value> {
    let dataset=Arc::new(Dataset::open(spec["fixture"].as_str().unwrap()).await?);
    let (budget,pool,_)=context(spec,&dataset,dir)?;
    let ctx=&budget.session_ctx;
    let target=ctx.read_table(Arc::new(crate::datafusion::dataframe::LanceTableProvider::new_with_ordering(dataset.clone(),true,true,false)))?.alias("target")?;
    let source=ctx.read_table(provider(spec,dir)?)?.alias("source")?;
    let joined=target.join(source,JoinType::Inner,&["id"],&["id"],None)?;
    let early=spec["take_mode"]=="early";
    let mut fields=vec![logical_expr::col("source.id").alias("id"),logical_expr::col("source.c0").alias("c0"),logical_expr::col("source.c1").alias("c1"),logical_expr::col("target._rowaddr").alias(ROW_ADDR),logical_expr::lit(true).alias(MERGE_SOURCE_SENTINEL),logical_expr::lit(1u8).alias(MERGE_ACTION_COLUMN)];
    let missing=dataset.schema().fields.iter().filter(|f|!["id","c0","c1"].contains(&f.name.as_str())).map(|f|f.name.clone()).collect::<Vec<_>>();
    if early {fields.extend(missing.iter().map(|n|logical_expr::col(format!("target.{n}")).alias(n)));}
    let frame=joined.select(fields)?;
    let input=frame.create_physical_plan().await?;
    let plan:Arc<dyn ExecutionPlan>=match spec["take_mode"].as_str().unwrap() {
        "condition"=>Arc::new(deferred_reference::MergeConditionExec::try_new(input.clone(),&DFSchema::try_from(input.schema().as_ref().clone())?,dataset.clone(),None,None,&ctx.state())?.with_payload_columns(missing.clone())?),
        "generic"=>{
            let projection=missing.iter().try_fold(dataset.empty_projection(),|p,n|p.union_column(n,lance_core::datatypes::OnMissing::Error))?;
            Arc::new(crate::io::exec::TakeExec::try_new(dataset.clone(),input,projection)?.unwrap())
        },
        "early"=>input,
        other=>return Err(format!("unknown take mode {other}").into()),
    };
    std::fs::write(dir.join("plan-before.txt"),format!("{}",displayable(plan.as_ref()).indent(true)))?;
    let partitions=plan.properties().output_partitioning().partition_count();
    let cpu=process_cpu();let io_before=process_io();let started=Instant::now();
    let tasks=(0..partitions).map(|p|{
        let plan=plan.clone();let context=ctx.task_ctx();let path=dir.join(format!("output-{p}.arrow"));
        async move {
            let mut s=plan.execute(p,context)?;let mut writer=FileWriter::try_new(File::create(path)?,plan.schema().as_ref())?;let mut rows=0;let mut batches=0;
            while let Some(batch)=s.try_next().await? {rows+=batch.num_rows();batches+=1;writer.write(&batch)?;}
            writer.finish()?;Ok::<_,Box<dyn std::error::Error+Send+Sync>>(json!({"partition":p,"rows":rows,"batches":batches}))
        }
    });
    let result=futures::future::try_join_all(tasks).await;
    let seconds=started.elapsed().as_secs_f64();let cpu_seconds=process_cpu()-cpu;
    let io=process_io().into_iter().map(|(k,v)|{let diff=v-io_before.get(&k).copied().unwrap_or(0);(k,diff)}).collect::<BTreeMap<_,_>>();
    let mut metrics=Vec::new();collect_metrics(&plan,"0".into(),&mut metrics);save(dir.join("operator-metrics.json"),&json!(metrics))?;
    match result {
        Ok(distribution)=>Ok(json!({"status":"success","distribution":distribution,"merge_seconds":seconds,"cpu_seconds":cpu_seconds,"io_delta":io,"pool":pool.snapshot(),"timing_scope":"Actual Lance/DF join and payload node plus common IPC sink; no writer, commit, NULL-address or conditional-rule implementation"})),
        Err(error)=>Ok(json!({"status":"execution_error","error":error.to_string(),"merge_seconds":seconds,"cpu_seconds":cpu_seconds,"io_delta":io,"pool":pool.snapshot()})),
    }
}

#[tokio::test(flavor="multi_thread",worker_threads=16)]
async fn run_frozen_hypothesis() {
    let Some(path)=std::env::var_os("LANCE_HYPOTHESIS_SPEC") else {return;};
    let path=PathBuf::from(path);let dir=path.parent().unwrap();
    let spec:Value=serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
    let result=match spec["task"].as_str().unwrap() {
        "merge"=>merge_probe(&spec,dir).await,
        "repartition"=>repartition_probe(&spec,dir).await,
        "take"=>take_probe(&spec,dir).await,
        other=>Err(format!("Unknown task {other}").into()),
    };
    let result=match result {Ok(v)=>v,Err(e)=>json!({"status":"driver_error","error":e.to_string()})};
    save(dir.join("metrics.json"),&result).unwrap();
    assert_ne!(result["status"],"driver_error","{result}");
}
