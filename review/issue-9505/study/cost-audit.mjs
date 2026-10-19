import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import crypto from 'node:crypto';
import { execFileSync } from 'node:child_process';

const root = path.dirname(new URL(import.meta.url).pathname);
const repository = path.resolve(root, '../..');
const base = '0a0d327082988018a25f56147d3b6d02f6c79ecc';
const variants = ['B', 'P', 'D', 'CTX', 'DB', 'DP'];
const sha256 = text => crypto.createHash('sha256').update(text).digest('hex');

function testBoundary(text) {
  const match = /^#\[cfg\(test\)\]\r?\n(?:#\[[^\n]*\]\r?\n)*mod \w+/m.exec(text);
  return match ? text.slice(0, match.index).split('\n').length : Infinity;
}

function category(file, line, boundary) {
  if (file.includes('/tests/') || line >= boundary) return 'tests';
  if (file === 'python/python/lance/dataset.py') return 'python_documentation';
  return 'production_rust';
}

function canonicalCounts(file, original, source) {
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'lance-cost-'));
  const before = path.join(temporary, 'before');
  const after = path.join(temporary, 'after');
  fs.writeFileSync(before, original);
  fs.writeFileSync(after, source);
  let diff;
  try {
    diff = execFileSync('git', ['diff', '--no-index', '--no-ext-diff', '--no-color', '--diff-algorithm=myers', before, after], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
  } catch (error) {
    if (error.status !== 1) throw error;
    diff = error.stdout;
  } finally {
    fs.unlinkSync(before);
    fs.unlinkSync(after);
    fs.rmdirSync(temporary);
  }
  const counts = { production_rust: { added: 0, deleted: 0 }, python_documentation: { added: 0, deleted: 0 }, tests: { added: 0, deleted: 0 } };
  let oldLine = 0;
  let newLine = 0;
  for (const line of diff.split('\n')) {
    if (line.startsWith('@@ ')) {
      const match = line.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
      oldLine = Number(match[1]);
      newLine = Number(match[2]);
    } else if (line.startsWith('+') && !line.startsWith('+++')) {
      counts[category(file, newLine++, testBoundary(source))].added++;
    } else if (line.startsWith('-') && !line.startsWith('---')) {
      counts[category(file, oldLine++, testBoundary(original))].deleted++;
    } else if (line.startsWith(' ')) {
      oldLine++;
      newLine++;
    }
  }
  return counts;
}

const rows = [];
for (const variant of variants) {
  const patchFile = path.join(root, 'ports', variant, 'implementation.patch');
  const patch = fs.readFileSync(patchFile, 'utf8');
  const files = [];
  let current;
  let oldLine = 0;
  let newLine = 0;
  for (const line of patch.split('\n')) {
    if (line.startsWith('diff --git ')) {
      const file = line.match(/^diff --git a\/(.*) b\/(.*)$/)?.[2];
      if (!file) throw new Error(`Unsupported diff header: ${line}`);
      const source = fs.readFileSync(path.join(root, 'ports', variant, 'source', file), 'utf8');
      let original = '';
      try {
        original = execFileSync('git', ['show', `${base}:${file}`], { cwd: repository, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] });
      } catch (error) {
        if (!patch.includes(`${line}\nnew file mode `)) throw error;
      }
      current = { file, source_sha256: sha256(source), old_test_start: testBoundary(original), new_test_start: testBoundary(source),
        canonical: canonicalCounts(file, original, source),
        production_rust: { added: 0, deleted: 0 }, python_documentation: { added: 0, deleted: 0 }, tests: { added: 0, deleted: 0 } };
      files.push(current);
    } else if (line.startsWith('@@ ')) {
      const match = line.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
      oldLine = Number(match[1]);
      newLine = Number(match[2]);
    } else if (line.startsWith('+') && !line.startsWith('+++')) {
      current[category(current.file, newLine, current.new_test_start)].added++;
      newLine++;
    } else if (line.startsWith('-') && !line.startsWith('---')) {
      current[category(current.file, oldLine, current.old_test_start)].deleted++;
      oldLine++;
    } else if (line.startsWith(' ')) {
      oldLine++;
      newLine++;
    }
  }
  const totals = {};
  for (const type of ['production_rust', 'python_documentation', 'tests']) {
    totals[type] = { added: files.reduce((sum, file) => sum + file[type].added, 0), deleted: files.reduce((sum, file) => sum + file[type].deleted, 0) };
  }
  const numstat = execFileSync('git', ['apply', '--numstat', patchFile], { cwd: repository, encoding: 'utf8' });
  const gitTotals = numstat.trim().split('\n').reduce((sum, row) => {
    const [added, deleted] = row.split('\t').map(Number);
    return { added: sum.added + added, deleted: sum.deleted + deleted };
  }, { added: 0, deleted: 0 });
  const counted = Object.values(totals).reduce((sum, value) => ({ added: sum.added + value.added, deleted: sum.deleted + value.deleted }), { added: 0, deleted: 0 });
  if (JSON.stringify(counted) !== JSON.stringify(gitTotals)) throw new Error(`Line totals differ for ${variant}`);
  const canonicalTotals = {};
  for (const type of ['production_rust', 'python_documentation', 'tests']) {
    canonicalTotals[type] = { added: files.reduce((sum, file) => sum + file.canonical[type].added, 0), deleted: files.reduce((sum, file) => sum + file.canonical[type].deleted, 0) };
  }
  rows.push({ variant, patch_sha256: sha256(patch), totals, total: counted, canonical_totals: canonicalTotals, files });
}
fs.writeFileSync(path.join(root, 'cost-audit.json'), JSON.stringify({ base, method: 'Canonical counts use git diff --no-index --diff-algorithm=myers between base file bytes and port source bytes, including comments and blank lines. Inline Rust test modules are split at their top-level cfg(test); integration and Python test files are all tests. Python dataset.py changes were manually verified to be documentation/doctest text only. Raw patch totals are also retained and cross-checked against git apply --numstat; hunk alignment can differ without any source change.', variants: rows }, null, 2) + '\n');
process.stdout.write(rows.map(row => `${row.variant}: ${JSON.stringify(row.canonical_totals)}`).join('\n') + '\n');
