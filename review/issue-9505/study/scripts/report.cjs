// Read-only extraction of recorded probes. No Lance import or workload execution.
const fs = require('node:fs');
const path = require('node:path');
const root = process.argv[2] || path.resolve(__dirname, '..');
const read = file => JSON.parse(fs.readFileSync(file, 'utf8'));
const median = values => { const sorted = values.slice().sort((a,b)=>a-b); return sorted[Math.floor(sorted.length/2)]; };
const records = [];
for (const name of fs.readdirSync(path.join(root,'runs')).sort()) {
  const directory = path.join(root,'runs',name);
  if (!fs.existsSync(path.join(directory,'result.json'))) continue;
  const result = read(path.join(directory,'result.json'));
  const samples = fs.readFileSync(path.join(directory,'execute-memory.jsonl'),'utf8').trim().split('\n').filter(Boolean).map(JSON.parse);
  const operators = fs.existsSync(path.join(directory,'operator-metrics.json')) ? read(path.join(directory,'operator-metrics.json')) : [];
  const joins = operators.filter(x=>x.name==='HashJoinExec').map(join=>{
    const left = operators.filter(x=>x.path.startsWith(join.path+'/0'));
    return {path:join.path,display:join.display,build:left.some(x=>/Lance|FilteredRead/.test(x.name))?'target':'source',
      build_rows:join.metrics.filter(x=>x.name==='build_input_rows').reduce((n,x)=>n+x.numeric,0),
      build_mem_used:join.metrics.filter(x=>x.name==='build_mem_used').reduce((n,x)=>n+x.numeric,0),
      per_partition:join.metrics.filter(x=>['build_input_rows','input_rows','output_rows','output_batches','build_mem_used'].includes(x.name))};
  });
  const repartitions=operators.filter(x=>x.name==='RepartitionExec').map(node=>({path:node.path,display:node.display,
    spill_count:node.metrics.filter(x=>x.name==='spill_count').reduce((n,x)=>n+x.numeric,0),
    spill_bytes:node.metrics.filter(x=>x.name==='spilled_bytes').reduce((n,x)=>n+x.numeric,0),
    per_partition:node.metrics.filter(x=>['output_rows','output_batches','spilled_rows','spilled_bytes'].includes(x.name))}));
  records.push({name,task:result.spec.task,workload:result.spec.workload,spec:result.spec,status:result.metrics.status,
    seconds:result.metrics.merge_seconds,cpu_seconds:result.metrics.cpu_seconds,
    pool:result.metrics.pool,sampled_peak_rss:Math.max(0,...samples.map(x=>x.VmRSS||0)),
    cgroup_peak:Number(result.resource.after['memory.peak']),tmp_peak:result.resource.sampled_tmp_peak_bytes,
    io:result.metrics.io_delta,joins,repartitions,distribution:result.metrics.distribution,
    error:result.metrics.error,validated:result.validation.validated,freeze_sha256:result.freeze_sha256});
}
const pairsFile=path.join(root,'paired-plan.json');let comparisons=[];
if(fs.existsSync(pairsFile)){
  const plan=read(pairsFile);
  comparisons=plan.comparisons.map(item=>{
    let values=[];
    for(let block=1;block<=3;block++){
      const lhs=records.find(x=>x.name===`${item.group}-b${block}-${item.numerator}`);
      const rhs=records.find(x=>x.name===`${item.group}-b${block}-${item.denominator}`);
      if(lhs&&rhs&&lhs.status==='success'&&rhs.status==='success'&&lhs.validated&&rhs.validated){
        values.push({block,ratio:lhs.seconds/rhs.seconds,numerator_seconds:lhs.seconds,denominator_seconds:rhs.seconds});
      }
    }
    return {...item,values,complete:values.length===3,median_ratio:values.length===3?median(values.map(x=>x.ratio)):null};
  });
}
const output={root,counts:records.reduce((v,x)=>(v[x.status]=(v[x.status]||0)+1,v),{}),records,comparisons,
  limits:['Stage probes and full merge timings have different explicit scopes.','Failures and plan-only records are not timing samples.','Sampled RSS and cgroup include different memory categories.','Active output partitions are not measured concurrent CPU utilization.']};
if(process.argv[3]==='markdown'){
  let lines=['# 本轮原始记录摘要','','完整配置、实际算子/分区指标及 scope 见对应 spec/metrics/plan；下表不构成跨计时范围排名。','','| case | status | seconds | CPU s | reservation peak MiB | RSS MiB | TMP MiB |','|---|---|---:|---:|---:|---:|---:|'];
  for(const r of records)lines.push(`| ${r.name} | ${r.status} | ${r.seconds?.toFixed(6)||'—'} | ${r.cpu_seconds?.toFixed(3)||'—'} | ${(r.pool.peak_reserved/2**20).toFixed(2)} | ${(r.sampled_peak_rss/2**20).toFixed(2)} | ${(r.tmp_peak/2**20).toFixed(2)} |`);
  lines.push('','## 同 block 配对','','| group | numerator / denominator | rounds | median ratio |','|---|---|---:|---:|');
  for(const p of comparisons)lines.push(`| ${p.group} | ${p.numerator}/${p.denominator} | ${p.values.length}/3 | ${p.median_ratio?.toFixed(6)||'incomplete'} |`);
  process.stdout.write(lines.join('\n')+'\n');
}else process.stdout.write(JSON.stringify(output,null,2)+'\n');
