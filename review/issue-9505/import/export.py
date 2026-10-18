from pathlib import Path
import collections
import hashlib
import io
import json
import subprocess
import tarfile

BASE = Path('/mnt/lance')
FINAL = BASE / 'killer-merge-final-20261019'
CHECKOUT = BASE / 'checkouts/K_check'
BASE_COMMIT = '0a0d327082988018a25f56147d3b6d02f6c79ecc'
PREFIX = 'review/issue-9505/'
OUT = Path('/root/codex-setup/issue-9505-deferred-payload.tar.gz')
ROOTS = sorted(list(BASE.glob('killer-merge*')) + list(BASE.glob('first-principles-9505*')))
freeze = json.loads((FINAL / 'freeze.json').read_text())
records, excluded, snapshots = [], [], {}

def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def git(checkout, *args):
    return subprocess.check_output(['git', '-C', str(checkout), *args])

def verify_final():
    checked = {}
    for variant, checkout in [('K', CHECKOUT), ('U_main', BASE / 'checkouts/U_main')]:
        identity = freeze['identities'][variant]
        tree = identity['tree']
        assert git(checkout, 'rev-parse', 'HEAD').decode().strip() == tree['head'] == BASE_COMMIT
        for name, expected in tree['source_hashes'].items():
            assert digest(checkout / name) == expected, (variant, name)
        assert hashlib.sha256(git(checkout, 'diff', '--binary', 'HEAD')).hexdigest() == tree['diff_sha256']
        imported = identity['imported']
        assert digest(Path(imported['extension'])) == imported['extension_sha256'], variant
        checked[variant] = {'source_hashes_verified': len(tree['source_hashes']), 'diff_matches': True, 'extension_matches': True}
    return checked

verified_before = verify_final()
changed = git(CHECKOUT, 'diff', '--name-only', 'HEAD').decode().splitlines()
assert changed == [
    'rust/lance/src/dataset/write/merge_insert.rs',
    'rust/lance/src/dataset/write/merge_insert/exec/condition.rs',
    'rust/lance/src/dataset/write/merge_insert/logical_plan.rs',
], changed
assert not git(CHECKOUT, 'ls-files', '--others', '--exclude-standard').strip()

with tarfile.open(OUT, 'w:gz') as archive:
    def add_bytes(data, name, source=None, mode=0o644):
        assert not Path(name).is_absolute() and '..' not in Path(name).parts
        info = tarfile.TarInfo(name)
        info.size, info.mode = len(data), mode
        archive.addfile(info, io.BytesIO(data))
        records.append({'path': name, 'kind': 'file', 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data), 'source': source})

    def add(path, name):
        if path.is_symlink():
            target = str(path.readlink())
            assert not Path(target).is_absolute(), (path, target)
            info = tarfile.TarInfo(name)
            info.type, info.linkname, info.mode = tarfile.SYMTYPE, target, 0o777
            archive.addfile(info)
            records.append({'path': name, 'kind': 'symlink', 'target': target, 'source': str(path)})
        else:
            assert path.is_file() and path.stat().st_size < 50 * 1024 * 1024, path
            add_bytes(path.read_bytes(), name, source=str(path), mode=path.stat().st_mode & 0o777)

    for name in changed:
        add(CHECKOUT / name, name)
    add_bytes(git(CHECKOUT, 'diff', '--binary', 'HEAD'), PREFIX + 'source-snapshots/final-K.patch', 'git diff --binary HEAD in /mnt/lance/checkouts/K_check')

    for root in ROOTS:
        for path in sorted(root.rglob('*')):
            if not (path.is_file() or path.is_symlink()):
                continue
            rel = path.relative_to(root)
            reason = None
            if '__pycache__' in rel.parts or path.suffix == '.pyc':
                reason = 'Python bytecode'
            elif path.name == '.coordinator.lock':
                reason = 'Runtime coordinator lock'
            elif 'dataset' in rel.parts:
                reason = 'Generated per-run dataset'
            elif rel.parts[0] == 'fixtures' and path.name not in ['fixture.json', 'spec.json']:
                reason = 'Generated fixture contents; hash manifests and generators retained'
            elif path.suffix in ['.lance', '.manifest', '.txn', '.arrow', '.so']:
                reason = 'Generated data or compiled binary'
            if reason:
                excluded.append({'source': str(path), 'bytes': path.lstat().st_size, 'reason': reason})
            else:
                add(path, PREFIX + 'results/' + root.name + '/' + str(rel))

    for label in ['K', 'K_check', 'K_noadmission_tests']:
        checkout = BASE / 'checkouts' / label
        paths = sorted(set(git(checkout, 'diff', '--name-only', 'HEAD').decode().splitlines() + git(checkout, 'ls-files', '--others', '--exclude-standard').decode().splitlines()))
        diff = git(checkout, 'diff', '--binary', 'HEAD')
        snapshots[label] = {'checkout': str(checkout), 'head': git(checkout, 'rev-parse', 'HEAD').decode().strip(), 'diff_sha256': hashlib.sha256(diff).hexdigest(), 'files': {name: digest(checkout / name) for name in paths}}
        add_bytes(diff, PREFIX + 'source-snapshots/' + label + '/tracked.patch', 'git diff --binary HEAD in ' + str(checkout))
        for name in paths:
            add(checkout / name, PREFIX + 'source-snapshots/' + label + '/files/' + name)
    add_bytes((json.dumps(snapshots, indent=2) + '\n').encode(), PREFIX + 'source-snapshots/snapshots.json', 'Read-only source snapshots at export time')
    for path in [BASE / 'RESTORED-ENVIRONMENT.md', BASE / 'env.sh', BASE / 'tmp/first-principles-9505-setup.py', BASE / 'tmp/first-principles-9505-compare.py']:
        add(path, PREFIX + 'inputs/' + path.name)

    verified_after = verify_final()
    for record in records:
        source = record.get('source')
        if source and source.startswith('/mnt/lance/'):
            path = Path(source)
            if record['kind'] == 'file':
                assert digest(path) == record['sha256'], 'File changed during export: ' + source
            else:
                assert str(path.readlink()) == record['target'], source
    meta = {
        'base_commit': BASE_COMMIT, 'final_checkout': str(CHECKOUT), 'final_result_root': str(FINAL),
        'final_source_paths': changed, 'source_roots': [str(p) for p in ROOTS],
        'verified_before': verified_before, 'verified_after': verified_after,
        'files': records, 'excluded': excluded,
        'policy': 'Original evidence bytes and relative symlink targets are preserved. Generated fixture and per-run dataset contents, Python bytecode, coordinator locks, environments, caches, and compiled extensions are excluded. Their recorded hashes and generator scripts are retained. Source snapshots are export-time snapshots; their relation to frozen measurements must be checked, not assumed.',
    }
    data = (json.dumps(meta, indent=2) + '\n').encode()
    info = tarfile.TarInfo(PREFIX + 'import/ecs-export.json')
    info.size, info.mode = len(data), 0o644
    archive.addfile(info, io.BytesIO(data))

print(json.dumps({'archive': str(OUT), 'sha256': digest(OUT), 'bytes': OUT.stat().st_size, 'records': len(records), 'excluded': len(excluded), 'excluded_by_reason': collections.Counter(e['reason'] for e in excluded), 'final_verification': verified_after}))
