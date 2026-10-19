#!/usr/bin/env node
// Read saved plan text only. This tool never imports Lance or executes a plan.
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';

function splitTopLevel(value) {
  const parts = [];
  let start = 0, depth = 0, quote = null;
  for (let i = 0; i < value.length; i++) {
    const char = value[i];
    if (quote) {
      if (char === quote && value[i - 1] !== '\\') quote = null;
    } else if (char === '"' || char === "'") quote = char;
    else if ('[({'.includes(char)) depth++;
    else if ('])}'.includes(char)) depth--;
    else if (char === ',' && depth === 0) {
      parts.push(value.slice(start, i).trim()); start = i + 1;
    }
  }
  parts.push(value.slice(start).trim());
  return parts.filter(Boolean);
}

function assignments(value) {
  const result = {};
  for (const part of splitTopLevel(value)) {
    const match = part.match(/^([A-Za-z_][A-Za-z_0-9]*)=(.*)$/s);
    if (match) result[match[1]] = match[2];
  }
  return result;
}

function numberFromDisplay(name, raw) {
  const match = raw.match(/^(\d+(?:\.\d+)?)\s*([A-Za-zµμ]*)$/);
  if (!match) return null;
  const value = Number(match[1]), suffix = match[2];
  const time = { ns: 1e-9, us: 1e-6, 'µs': 1e-6, 'μs': 1e-6, ms: 1e-3, s: 1 };
  if (suffix in time) return { approximate_value: value * time[suffix], unit: 'seconds', rounded: true };
  // DataFusion's built-in byte metrics use binary units; generic gauges/counts
  // use decimal K/M/B even when the underlying quantity is measured in bytes.
  const builtinBytes = ['output_bytes', 'spilled_bytes', 'mem_used'].includes(name);
  const scales = builtinBytes
    ? { '': 1, B: 1, KB: 1024, MB: 1024 ** 2, GB: 1024 ** 3, TB: 1024 ** 4 }
    : { '': 1, K: 1e3, M: 1e6, B: 1e9, T: 1e12 };
  if (!(suffix in scales)) return null;
  const bytes = builtinBytes || /bytes|mem_used/.test(name);
  return { approximate_value: value * scales[suffix], unit: bytes ? 'bytes' : 'count', rounded: suffix !== '' };
}

function extractPlans(path, content) {
  if (path.endsWith('.jsonl')) {
    return content.split('\n').filter(Boolean).flatMap((line, index) => {
      const record = JSON.parse(line);
      return typeof record.plan === 'string' ? [{ text: record.plan, record_line: index + 1, phase: record.phase ?? null }] : [];
    });
  }
  if (path.endsWith('.json')) {
    const value = JSON.parse(content);
    return (Array.isArray(value) ? value : [value]).filter(x => typeof x.plan === 'string').map(x => ({ text: x.plan }));
  }
  return [{ text: content }];
}

function inspect(plan) {
  const nodes = [], stack = [], ignored = [];
  for (const [index, line] of plan.text.split('\n').entries()) {
    if (!line.trim()) continue;
    const match = line.match(/^( *)([A-Za-z][A-Za-z_0-9]*)(?::\s*|,\s*|$)(.*)$/);
    if (!match) { ignored.push({ line: index + 1, text: line }); continue; }
    const [, spaces, operator, body] = match;
    const metricsAt = body.lastIndexOf('metrics=[');
    const metricText = metricsAt < 0 ? null : body.slice(metricsAt + 9).replace(/\]\s*$/, '');
    const rawMetrics = metricText === null ? {} : assignments(metricText);
    while (stack.length && nodes[stack.at(-1)].indent >= spaces.length) stack.pop();
    const node = {
      id: nodes.length, line: index + 1, indent: spaces.length,
      parent: stack.at(-1) ?? null, children: [], operator,
      attributes: assignments((metricsAt < 0 ? body : body.slice(0, metricsAt).replace(/,\s*$/, ''))
        .replace(/\]\s+payload=/g, '], payload=')),
      metrics_present: metricText !== null,
      metrics: Object.fromEntries(Object.entries(rawMetrics).map(([key, raw]) => [key, { raw, ...numberFromDisplay(key, raw) }])),
      raw_line: line,
    };
    if (node.parent !== null) nodes[node.parent].children.push(node.id);
    nodes.push(node); stack.push(node.id);
  }
  function descendants(id) { return [id, ...nodes[id].children.flatMap(descendants)]; }
  function branch(id) {
    if (id === undefined) return null;
    return { node: id, leaves: descendants(id).filter(i => !nodes[i].children.length).map(i => ({ node: i, operator: nodes[i].operator, attributes: nodes[i].attributes })) };
  }
  const joins = nodes.filter(n => n.operator === 'HashJoinExec').map(n => ({
    node: n.id, mode: n.attributes.mode ?? null, join_type: n.attributes.join_type ?? null,
    build_side: 'left', build: branch(n.children[0]), probe: branch(n.children[1]),
    child_count_valid: n.children.length === 2,
  }));
  const exchanges = nodes.filter(n => /Repartition|Sort/.test(n.operator)).map(n => {
    const join = joins.find(j => [j.build, j.probe].some(b => b && descendants(b.node).includes(n.id)));
    return {
      node: n.id, join_node: join?.node ?? null,
      join_edge: join ? (descendants(join.build.node).includes(n.id) ? 'build' : 'probe') : null,
      subtree: branch(n.id),
    };
  });
  return {
    ...Object.fromEntries(Object.entries(plan).filter(([key]) => key !== 'text')),
    plan_sha256: createHash('sha256').update(plan.text).digest('hex'),
    execution_complete: null,
    completeness_reason: 'Text cannot prove success: analyze_plan_with_context discards stream Err items. validated_diagnostic is not an execution-completion signal.',
    metric_scope: 'Aggregated by name across partitions; abbreviated display values are rounded.',
    nodes, joins, exchanges,
    scan_nodes: nodes.filter(n => /LanceRead|LanceScan|ScanExec/.test(n.operator)).map(n => n.id),
    materialization_nodes: nodes.filter(n => /Take|MergeCondition|MergePayload/.test(n.operator)).map(n => n.id),
    writer_nodes: nodes.filter(n => /^(MergeInsert|InPlaceMergeInsert)$/.test(n.operator)).map(n => n.id),
    ignored_lines: ignored,
    warnings: [
      'Left/right identify physical HashJoin inputs. Determine source/target from leaf URI, provider and projection; do not infer it from row counts.',
      'Missing metrics are unknown, never zero. LanceRead output_batches=0 can mean unsupported instrumentation.',
      'Scan batch-size distribution, decode concurrency and internal Take I/O/call count are not reconstructed from aggregate text.',
      'Writer output_rows may be zero because the writer emits no rows. Check mutation counters against an independently verified execute run.',
      ...(nodes.length === 0 ? ['No plan nodes were parsed.'] : []),
      ...(ignored.length ? ['Unparsed lines require review before interpreting this extraction.'] : []),
    ],
  };
}

if (process.argv.length < 3) {
  process.stderr.write('Usage: node inspect-plans.mjs PLAN.txt [PLAN.txt | candidate.jsonl ...]\n');
  process.exitCode = 2;
} else {
  const files = process.argv.slice(2).map(path => {
    const content = readFileSync(path, 'utf8');
    return { path, file_sha256: createHash('sha256').update(content).digest('hex'), plans: extractPlans(path, content).map(inspect) };
  });
  process.stdout.write(JSON.stringify({ schema_version: 1, files }, null, 2) + '\n');
}
