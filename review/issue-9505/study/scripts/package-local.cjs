// Check the copied records and package review evidence. No workload execution.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const child = require('node:child_process');
const assert = require('node:assert/strict');
const root = path.resolve(process.argv[2] || path.join(__dirname, '..'));
const read = name => JSON.parse(fs.readFileSync(path.join(root, name), 'utf8'));
const digest = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const frozen = read('freeze-v1.json');
const frozenHash = digest(path.join(root, 'freeze-v1.json'));
assert.equal(read('audit-final.json').status, 'passed');
assert.equal(read('audit-final.json').source_freeze_sha256, frozenHash);
assert.equal(read('reconstruction-check.json').status, 'passed');
for (const [name, expected] of Object.entries(frozen.harness_hashes)) {
  assert.equal(digest(path.join(root, name)), expected, name);
}
for (const [name, expected] of Object.entries(read('source/metadata.json').files)) {
  assert.equal(digest(path.join(root, 'source', name)), expected, name);
}
for (const [name, expected] of Object.entries(read('vendor/metadata.json').files)) {
  assert.equal(digest(path.join(root, name)), expected, name);
}
for (const [name, expected] of Object.entries(read('source/legacy-C/metadata.json').files)) {
  assert.equal(digest(path.join(root, 'source/legacy-C', name)), expected, name);
}
const supplement = read('reconstruction-supplement.json');
assert.equal(digest(path.join(root, 'full-reconstruction.patch')), supplement.full_reconstruction_patch_sha256);
assert.equal(digest(path.join(root, 'implementation.patch')), frozen.implementation_patch_sha256);
const report = read('results.json');
assert.equal(report.records.length, 53);
assert.deepEqual(report.counts, {execution_error: 4, success: 47, plan_only: 2});
assert(report.comparisons.every(item => item.complete && item.values.length === 3));
let count = 0;
for (const item of report.records) {
  const directory = path.join('runs', item.name);
  const record = read(path.join(directory, 'result.json'));
  assert.equal(record.freeze_sha256, frozenHash);
  assert.equal(digest(path.join(root, directory, 'spec.json')), record.spec_sha256);
  assert.deepEqual(record.metrics, read(path.join(directory, 'metrics.json')));
  assert.deepEqual(record.validation, read(path.join(directory, 'validate.json')));
  assert(record.validation.validated);
  count++;
}
fs.writeFileSync(path.join(root, 'local-record-audit.json'), JSON.stringify({
  status: 'passed', records: count, complete_three_round_comparisons: report.comparisons.length,
  frozen_harness_unchanged: true, source_exports_unchanged: true,
  historical_C_source_matches_its_freeze: true, source_freeze_sha256: frozenHash,
  scope: 'Local copies, metadata, embedded raw records and patch checks; no remote workload replay.'
}, null, 2) + '\n');
const files = [];
function visit(relative = '') {
  for (const entry of fs.readdirSync(path.join(root, relative), {withFileTypes: true})) {
    if (['__pycache__', '.DS_Store', 'SHA256SUMS'].includes(entry.name)) continue;
    const name = path.join(relative, entry.name);
    if (entry.isDirectory()) {
      assert(!(relative === '' && ['fixtures', 'bin'].includes(entry.name)), name);
      assert(!(relative.startsWith('runs') && entry.name === 'dataset') && !entry.name.endsWith('-tmp'), name);
      visit(name);
    } else {
      assert(entry.isFile(), `Unexpected non-file ${name}`);
      assert(!/^output-.*\.arrow$/.test(entry.name), name);
      files.push(name);
    }
  }
}
visit();
files.sort();
fs.writeFileSync(path.join(root, 'SHA256SUMS'), files.map(name => `${digest(path.join(root, name))}  ${name}\n`).join(''));
const archive = `${root}.zip`;
assert(!fs.existsSync(archive), 'Refuse to replace an existing archive');
const base = path.basename(root);
child.execFileSync('zip', ['-q', archive, '-@'], {cwd: path.dirname(root), input: files.concat('SHA256SUMS').map(name => `${base}/${name}\n`).join('')});
const zipTest = child.execFileSync('unzip', ['-tq', archive], {encoding: 'utf8'}).trim();
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'lance-hypotheses-archive-'));
child.execFileSync('unzip', ['-qq', archive, '-d', temporary]);
const checks = child.execFileSync('shasum', ['-a', '256', '-c', 'SHA256SUMS'], {cwd: path.join(temporary, base), encoding: 'utf8', maxBuffer: 4 << 20});
assert.equal(checks.trim().split('\n').length, files.length);
fs.rmSync(temporary, {recursive: true});
const verification = {status: 'passed', zip_test: zipTest, extracted_checksum_files: files.length,
  archive_sha256: digest(archive), archive_bytes: fs.statSync(archive).size,
  archive, frozen_binary_sha256: frozen.binary.sha256};
fs.writeFileSync(`${archive}.verification.json`, JSON.stringify(verification, null, 2) + '\n');
process.stdout.write(JSON.stringify(verification, null, 2) + '\n');
