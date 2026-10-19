#!/usr/bin/env node
'use strict';

// Read local records and write the derived report to stdout. No experiment is run.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { isDeepStrictEqual: equal } = require('node:util');

const BLOCKS = [1, 2, 3];
const METRICS = {
  merge_seconds: r => r.merge_seconds,
  input_and_api_seconds: r => r.input_and_api_seconds,
  cpu_seconds: r => r.cpu_seconds,
  sampled_peak_rss_bytes: r => r.sampled_peak_rss_bytes,
  cgroup_peak_bytes: r => r.cgroup_peak_bytes,
  ru_maxrss_before_execute_bytes: r => r.ru_maxrss_before_execute_bytes,
  ru_maxrss_after_execute_bytes: r => r.ru_maxrss_after_execute_bytes,
  process_read_bytes: r => r.process_io_delta?.read_bytes,
  process_write_bytes: r => r.process_io_delta?.write_bytes,
  process_rchar: r => r.process_io_delta?.rchar,
  process_wchar: r => r.process_io_delta?.wchar,
  process_read_calls: r => r.process_io_delta?.syscr,
  process_write_calls: r => r.process_io_delta?.syscw,
  new_data_file_bytes: r => r.new_data_file_bytes,
  new_data_file_count: r => r.new_data_file_count,
  sampled_tmp_peak_bytes: r => r.execution?.sampled_tmp_peak_bytes,
  sampled_tmp_peak_allocated_bytes: r => r.execution?.sampled_tmp_peak_allocated_bytes,
  sampled_tmp_peak_file_count: r => r.execution?.sampled_tmp_peak_file_count,
};
const CONTRACT_FIELDS = ['workload', 'pool_bytes', 'cgroup_bytes', 'cache', 'input_form', 'timeout_seconds'];
const read = filename => JSON.parse(fs.readFileSync(filename, 'utf8'));
const maybeRead = filename => fs.existsSync(filename) ? read(filename) : null;
const sha = filename => crypto.createHash('sha256').update(fs.readFileSync(filename)).digest('hex');
const finite = value => typeof value === 'number' && Number.isFinite(value) && value >= 0;
const median = values => [...values].sort((a, b) => a - b)[1];
const label = cell => `${cell.variant}/${cell.write_mode}`;
const select = (object, keys) => Object.fromEntries(keys.map(key => [key, object[key]]));

function distribution(values) {
  const observed = values.filter(finite);
  const complete = values.length === 3 && observed.length === 3;
  return {
    values: values.map(value => finite(value) ? value : null),
    n: observed.length, status: complete ? 'complete' : 'incomplete',
    median: complete ? median(observed) : null,
    minimum: complete ? Math.min(...observed) : null,
    maximum: complete ? Math.max(...observed) : null,
  };
}

function ratioSummary(blocks) {
  const metrics = ['merge_seconds', 'input_and_api_seconds'];
  const output = {};
  for (const metric of metrics) {
    const values = BLOCKS.map(block => {
      const row = blocks.find(item => item.block === block);
      const top = row?.numerator?.[metric], bottom = row?.denominator?.[metric];
      return row?.eligible && finite(top) && top > 0 && finite(bottom) && bottom > 0 ? top / bottom : null;
    });
    output[metric] = distribution(values);
  }
  return output;
}

function residencySummary(cache, phase) {
  if (!cache) return { status: 'missing', files: 0, observed_files: 0, resident_fraction: null };
  let bytes = 0, pages = 0, resident = 0, observed = 0;
  const errors = [];
  for (const item of cache.files) {
    const value = item[phase];
    if (!value || ![value.bytes, value.pages, value.resident_pages].every(finite) || value.resident_pages > value.pages) {
      errors.push({ file: item.file, error: item[`${phase}_error`] || 'Missing or invalid mincore observation' });
      continue;
    }
    bytes += value.bytes; pages += value.pages; resident += value.resident_pages; observed++;
  }
  const complete = observed === cache.files.length && observed > 0;
  return { status: complete ? 'observed' : 'incomplete', files: cache.files.length, observed_files: observed,
    bytes, pages, resident_pages: resident, resident_fraction: complete && pages > 0 ? resident / pages : null, errors };
}

function loadCell(root, plan, frozen, cell, errors) {
  const directory = path.join(root, 'runs', cell.run_id);
  const resultPath = path.join(directory, 'result.json');
  const referencePath = path.join(root, 'references', `${cell.run_id}.json`);
  const result = maybeRead(resultPath), reference = maybeRead(referencePath);
  const base = { block: cell.block, run_id: cell.run_id, cell, status: 'missing', eligible: false, reasons: [], metrics: null };
  if (result && reference) errors.push(`${cell.run_id}: both an execution and a reference exist`);
  if (!result) return { ...base, status: reference ? reference.status : 'missing',
    reasons: [reference ? 'Reference is not a new execution' : 'Result is not present'],
    reference_path: reference ? referencePath : null };
  base.status = result.status;
  base.result_sha256 = sha(resultPath);
  const check = (condition, message, structural = false) => {
    if (!condition) { base.reasons.push(message); if (structural) errors.push(`${cell.run_id}: ${message}`); }
  };
  check(equal(result.cell, cell) && result.run_id === cell.run_id && result.plan === plan.name && result.kind === plan.kind,
    'Result does not match its planned cell', true);
  check(result.executed === true && result.status === 'validated_success', 'Execution is not a new validated success');
  check(equal(result.identity, frozen.identities[cell.variant]?.imported), 'Execution identity differs from freeze', true);
  const resource = result.execution;
  check(resource?.operation === 'execute' && resource.exit_code === 0 && !resource.timeout && !resource.confirmed_oom && !resource.cleanup_error,
    'Execute resource record is not successful');
  check(resource?.configured_pool_bytes === cell.pool_bytes && Number(resource?.before?.['memory.max']) === cell.cgroup_bytes
    && resource?.before?.['memory.swap.max'] === '0', 'Execute limits differ from plan', true);
  check(equal(resource, maybeRead(path.join(directory, 'execute-resources.json'))), 'Embedded execute resource record differs', true);
  const metrics = maybeRead(path.join(directory, 'metrics.json'));
  const oracle = maybeRead(path.join(directory, 'validate.json'));
  const validation = maybeRead(path.join(directory, 'validate-resources.json'));
  const spec = maybeRead(path.join(directory, 'spec.json'));
  if (result.status === 'validated_success') {
    check(maybeRead(path.join(directory, 'cache-before.json'))?.mode === cell.cache
      && maybeRead(path.join(directory, 'cache-after-execute.json'))?.mode === 'observation_only',
      'Cache operation differs from plan', true);
    check(metrics?.status === 'execute_returned' && equal(metrics.identity, result.identity), 'Execute metrics are missing or invalid', true);
    check(oracle?.validated === true && oracle.unchanged === false, 'Successful full-value oracle is missing', true);
    check(equal(oracle?.validator_identity, frozen.identities[frozen.config.validator]?.imported), 'Validator identity differs from freeze', true);
    check(validation?.exit_code === 0 && !validation.timeout && !validation.confirmed_oom && !validation.cleanup_error,
      'Validation resource record is not successful', true);
    check(spec && result.producer?.yielded_rows === spec.source_rows && result.producer?.truncated_final_record === false,
      'Source consumption is incomplete', true);
    check(equal(metrics?.merge_stats, oracle?.expected_counts), 'API statistics differ from full-value oracle', true);
    check(Array.isArray(oracle?.validated_field_names) && equal(Object.keys(oracle?.hashes || {}), oracle.validated_field_names)
      && equal(metrics?.schema?.split('\n').map(field => field.split(':')[0]), oracle.validated_field_names),
      'Oracle field coverage differs from execution schema', true);
  }
  check(finite(result.merge_seconds) && result.merge_seconds > 0, 'API duration is missing or invalid');
  base.eligible = base.reasons.length === 0 && !reference;
  if (base.eligible) {
    base.metrics = Object.fromEntries(Object.entries(METRICS).map(([key, getter]) => [key, finite(getter(result)) ? getter(result) : null]));
    base.oracle_sha256 = sha(path.join(directory, 'validate.json'));
  }
  return base;
}

function extractReport(root, requested = []) {
  root = path.resolve(root);
  const errors = [], groups = [], comparisons = [], cold = [], plans = [];
  const allPlans = fs.readdirSync(path.join(root, 'plans')).filter(name => name.endsWith('.json')).sort().map(name => {
    const filename = path.join(root, 'plans', name);
    return { filename, plan: read(filename) };
  });
  for (const name of requested) if (!allPlans.some(item => item.plan.name === name)) throw new Error(`Unknown plan: ${name}`);
  const chosen = allPlans.filter(({ plan }) => requested.length ? requested.includes(plan.name)
    : plan.kind === 'pairs' || plan.cells.some(cell => cell.cache === 'evict_attempt'));
  const seen = new Set();
  for (const { filename, plan } of chosen) {
    const freezePath = path.join(root, 'freezes', `${plan.freeze}.json`);
    if (sha(freezePath) !== plan.freeze_sha256) throw new Error(`Freeze SHA mismatch: ${plan.name}`);
    const frozen = read(freezePath), rows = [];
    for (const cell of plan.cells) {
      if (seen.has(cell.run_id)) throw new Error(`Duplicate run ID: ${cell.run_id}`);
      seen.add(cell.run_id);
      const row = loadCell(root, plan, frozen, cell, errors);
      rows.push(row);
      if (cell.cache === 'evict_attempt') {
        const directory = path.join(root, 'runs', cell.run_id);
        const before = maybeRead(path.join(directory, 'cache-before.json'));
        const after = maybeRead(path.join(directory, 'cache-after-execute.json'));
        cold.push({ plan: plan.name, kind: plan.kind, ...select(row, ['run_id', 'status', 'eligible', 'cell']),
          mincore_before_attempt: residencySummary(before, 'before'),
          mincore_after_attempt: residencySummary(before, 'after'),
          mincore_after_execute: residencySummary(after, 'after'),
          fadvise_returned_files: before?.files.filter(item => item.fadvise_returned === true).length ?? 0,
          fadvise_errors: before?.files.filter(item => item.fadvise_error).map(item => ({ file: item.file, error: item.fadvise_error })) ?? [],
          merge_seconds: row.metrics?.merge_seconds ?? null,
          process_read_bytes: row.metrics?.process_read_bytes ?? null,
          process_rchar: row.metrics?.process_rchar ?? null });
      }
    }
    plans.push({ name: plan.name, kind: plan.kind, plan_sha256: sha(filename), freeze: plan.freeze,
      freeze_sha256: plan.freeze_sha256, planned_cells: rows.length,
      statuses: Object.fromEntries([...new Set(rows.map(row => row.status))].map(status => [status, rows.filter(row => row.status === status).length])),
      eligible_successes: rows.filter(row => row.eligible).length });
    if (plan.kind !== 'pairs') continue;
    const grouped = new Map();
    for (const row of rows) {
      const contract = select(row.cell, ['variant', 'write_mode', ...CONTRACT_FIELDS]);
      const key = JSON.stringify(contract);
      if (!grouped.has(key)) grouped.set(key, { contract, rows: [] });
      grouped.get(key).rows.push(row);
    }
    for (const { contract, rows: members } of grouped.values()) {
      const blocks = BLOCKS.map(block => {
        const found = members.filter(row => row.block === block);
        if (found.length > 1) throw new Error(`Duplicate block: ${plan.name}/${contract.workload}/${contract.variant}/${block}`);
        return found[0] || { block, status: 'unplanned', eligible: false, reasons: ['Block was not planned'], metrics: null };
      });
      const metrics = Object.fromEntries(Object.keys(METRICS).map(key => [key,
        distribution(blocks.map(row => row.eligible ? row.metrics?.[key] : null))]));
      const complete = members.length === 3 && blocks.every(row => row.eligible)
        && Object.values(metrics).every(metric => metric.status === 'complete');
      groups.push({ plan: plan.name, ...contract, identity: frozen.identities[contract.variant].imported,
        pool_policy: frozen.identities[contract.variant].pool_policy,
        status: complete ? 'complete' : 'incomplete', blocks, metrics });
    }
    for (const workload of plan.workloads) for (const pair of plan.comparisons) {
      if (!Array.isArray(pair) || pair.length !== 2) throw new Error(`Invalid registered comparison in ${plan.name}`);
      const [numerator, denominator] = pair;
      const blocks = BLOCKS.map(block => {
        const selectRows = wanted => rows.filter(row => row.cell.workload === workload && row.block === block && label(row.cell) === wanted);
        const tops = selectRows(numerator), bottoms = selectRows(denominator);
        if (tops.length > 1 || bottoms.length > 1) throw new Error(`Ambiguous comparison: ${plan.name}/${workload}/${block}`);
        const top = tops[0], bottom = bottoms[0];
        const compatible = top && bottom && equal(select(top.cell, CONTRACT_FIELDS), select(bottom.cell, CONTRACT_FIELDS));
        if (top && bottom && !compatible) errors.push(`${plan.name}/${workload}/${block}: paired contracts differ`);
        return { block, eligible: Boolean(top?.eligible && bottom?.eligible && compatible),
          contract: compatible ? select(top.cell, CONTRACT_FIELDS) : null,
          numerator_run_id: top?.run_id ?? null, denominator_run_id: bottom?.run_id ?? null,
          numerator_status: top?.status ?? 'unplanned', denominator_status: bottom?.status ?? 'unplanned',
          numerator: top?.metrics ?? null, denominator: bottom?.metrics ?? null,
          reasons: [...(top?.reasons || ['Numerator was not planned']), ...(bottom?.reasons || ['Denominator was not planned']),
            ...(top && bottom && !compatible ? ['Paired contracts differ'] : [])] };
      });
      const contracts = blocks.map(row => row.contract).filter(Boolean);
      const sameContract = contracts.every(contract => equal(contract, contracts[0]));
      if (!sameContract) {
        errors.push(`${plan.name}/${workload}: comparison contract changes between blocks`);
        for (const row of blocks) {
          row.eligible = false;
          row.reasons.push('Comparison contract changes between blocks');
        }
      }
      const ratios = ratioSummary(blocks);
      comparisons.push({ plan: plan.name, workload, numerator, denominator,
        contract: sameContract ? contracts[0] ?? null : null,
        status: Object.values(ratios).every(value => value.status === 'complete') ? 'complete' : 'incomplete',
        definition: 'numerator_seconds / denominator_seconds within each registered block; median of those three ratios',
        blocks, ratios });
    }
  }
  const complete = groups.length > 0 && comparisons.length > 0
    && groups.every(group => group.status === 'complete') && comparisons.every(row => row.status === 'complete')
    && plans.every(plan => plan.eligible_successes === plan.planned_cells);
  return { extraction: 'Read-only local record extraction; does not replace audit-results.py or re-read dataset values',
    root, generated_at: new Date().toISOString(), extractor_sha256: sha(__filename),
    scope: 'Only the selected plan files currently present locally; complete does not certify that the final experiment matrix has been created or synced',
    status: errors.length ? 'invalid' : complete ? 'complete' : 'incomplete', errors, plans, groups, comparisons, cold,
    notes: [
      'Missing, failed, referenced, diagnostic, or ineligible executions never contribute latency or resource samples.',
      'Three-block medians and ranges are null until all three values are available; individual observed values remain visible.',
      'API and input-plus-API ratios are calculated within each block before taking their median. Separate medians are never divided.',
      'Configured pool, input form, cache mode, writer, cgroup, and timeout remain part of every group contract.',
      'RSS is the sampled maximum single-process RSS, not a process-tree sum. Cgroup peak includes charged cache and can exclude shared pages charged elsewhere.',
      'Process read_bytes/write_bytes and rchar/wchar are distinct; these deltas cover the execute API timing boundary. Input materialization is separately timed.',
      'TMP peak is a sampled live footprint, not cumulative spill writes, and can miss unlinked or short-lived files.',
      'fadvise is an eviction attempt. Mincore totals combine sequential per-file observations, not a simultaneous cold snapshot.',
      'No physical dataset files, source files, extension bytes, or third-party dependency contents are rehashed by this extractor.',
    ] };
}

function markdown(report) {
  const lines = [`# Selected pair report: ${report.status}`, '', report.extraction, '', report.scope, ''];
  const show = value => value === null || value === undefined ? '—' : Number.isInteger(value) ? String(value) : value.toFixed(6);
  const escape = value => String(value).replaceAll('|', '\\|').replaceAll('\n', ' ');
  for (const group of report.groups) {
    lines.push(`## ${group.plan} / ${group.workload} / ${group.variant}/${group.write_mode}`, '',
      `Status: **${group.status}**. Input: ${group.input_form}; cache: ${group.cache}; pool: ${group.pool_bytes} B; cgroup: ${group.cgroup_bytes} B; timeout: ${group.timeout_seconds} s.`, '',
      `Blocks: ${group.blocks.map(row => `b${row.block}=${row.status}${row.reasons.length ? ` (${row.reasons.join('; ')})` : ''}`).join(', ')}.`, '',
      '| Metric (named units) | b1 | b2 | b3 | Median | Range [min, max] |', '|---|---:|---:|---:|---:|---:|');
    for (const [name, metric] of Object.entries(group.metrics)) lines.push(`| ${name} | ${metric.values.map(show).join(' | ')} | ${show(metric.median)} | [${show(metric.minimum)}, ${show(metric.maximum)}] |`);
    lines.push('');
  }
  lines.push('## Registered within-block ratios', '', '| Plan/workload | Numerator / denominator | Timer | Status | b1 | b2 | b3 | Median ratio |', '|---|---|---|---|---:|---:|---:|---:|');
  for (const row of report.comparisons) for (const [timer, metric] of Object.entries(row.ratios))
    lines.push(`| ${row.plan}/${row.workload} | ${row.numerator} / ${row.denominator} | ${timer} | ${metric.status} | ${metric.values.map(show).join(' | ')} | ${show(metric.median)} |`);
  lines.push('', '## Eviction attempts and mincore', '',
    '| Run | Status | fadvise returned/files | Resident pages before → after attempt → after execute | API s | Process read bytes | Process rchar |',
    '|---|---|---:|---|---:|---:|---:|');
  const pages = observed => `${observed.resident_pages ?? '?'}/${observed.pages ?? '?'} (${observed.status})`;
  for (const row of report.cold) lines.push(`| ${row.run_id} | ${row.status} | ${row.fadvise_returned_files}/${row.mincore_after_attempt.files} | ${[row.mincore_before_attempt, row.mincore_after_attempt, row.mincore_after_execute].map(pages).join(' → ')} | ${show(row.merge_seconds)} | ${show(row.process_read_bytes)} | ${show(row.process_rchar)} |`);
  lines.push('', ...report.notes.map(note => `- ${note}`));
  if (report.errors.length) lines.push('', '## Invalid evidence', '', ...report.errors.map(error => `- ${escape(error)}`));
  return lines.join('\n') + '\n';
}

function main() {
  let root = __dirname, format = 'json'; const selected = [];
  const args = process.argv.slice(2);
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--help') {
      process.stdout.write('Usage: node extract-report.cjs [--root EVIDENCE_ROOT] [--format json|markdown] [--plan NAME ...]\nReads local records only; stdout is the report. Exit codes: 0 complete, 2 incomplete/no pairs, 1 invalid evidence.\n');
      return;
    }
    if (!['--root', '--format', '--plan'].includes(args[i]) || !args[i + 1]) throw new Error(`Invalid argument: ${args[i]}`);
    const flag = args[i++], value = args[i];
    if (flag === '--root') root = value;
    else if (flag === '--format') format = value;
    else selected.push(value);
  }
  if (!['json', 'markdown'].includes(format)) throw new Error(`Invalid format: ${format}`);
  const report = extractReport(root, selected);
  process.stdout.write(format === 'json' ? JSON.stringify(report, null, 2) + '\n' : markdown(report));
  process.exitCode = report.status === 'complete' ? 0 : report.status === 'incomplete' ? 2 : 1;
}

module.exports = { distribution, ratioSummary, residencySummary, extractReport, markdown };
if (require.main === module) {
  try { main(); } catch (error) { process.stderr.write(`${error.stack}\n`); process.exitCode = 1; }
}
