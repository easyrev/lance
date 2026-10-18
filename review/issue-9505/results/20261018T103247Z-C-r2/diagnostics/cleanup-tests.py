"""Exercise the actual post-exit cleanup and pre-worker guard AST blocks."""
import ast
import errno
import tempfile
from pathlib import Path
from types import SimpleNamespace

root = Path(__file__).resolve().parents[1]
module = ast.parse((root / 'bench.py').read_text())
function = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == 'isolated')
start = next(i for i, node in enumerate(function.body) if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'cleanup_started' for target in node.targets))
cleanup = compile(ast.Module(body=function.body[start:-1], type_ignores=[]), str(root / 'bench.py'), 'exec')
guard = compile(ast.Module(body=[function.body[0]], type_ignores=[]), str(root / 'bench.py'), 'exec')

for failures, error_code, expected_removed in [(0, errno.EBUSY, True), (2, errno.EBUSY, True), (1000, errno.EBUSY, False), (1, errno.EPERM, None)]:
    state = dict(now=0.0, calls=0)
    def remove():
        state['calls'] += 1
        if state['calls'] <= failures:
            raise OSError(error_code, 'injected cleanup error')
    class Group:
        rmdir = staticmethod(remove)
        def __truediv__(self, name):
            return SimpleNamespace(read_text=lambda: 'populated 0\nfrozen 0\n')
    saved = []
    result = dict(confirmed_oom=True, exit_code=-9)
    namespace = dict(time=SimpleNamespace(monotonic=lambda: state['now'], sleep=lambda delay: state.update(now=state['now'] + delay)),
                     group=Group(), result=result, errno=errno, directory=Path('/unused'), operation='execute', save=lambda path, value: saved.append(dict(value)))
    try:
        exec(cleanup, namespace)
        assert expected_removed is not None
        assert result['cleanup']['removed'] == expected_removed
        assert result['cleanup']['group_empty']
        assert saved[-1]['confirmed_oom'] and saved[-1]['exit_code'] == -9
        assert state['now'] <= 5.1
    except OSError as error:
        assert expected_removed is None and error.errno == errno.EPERM

with tempfile.TemporaryDirectory() as temporary:
    cgroups = Path(temporary)
    previous = cgroups / 'previous'
    previous.mkdir()
    (previous / 'cgroup.events').write_text('populated 0\nfrozen 0\n')
    exec(guard, dict(CGROUP_ROOT=cgroups))
    (previous / 'cgroup.events').write_text('populated 1\nfrozen 0\n')
    try:
        exec(guard, dict(CGROUP_ROOT=cgroups))
        raise AssertionError('populated worker was accepted')
    except RuntimeError as error:
        assert 'Previous worker group is still populated' in str(error)
print('6 cleanup and isolation-guard cases passed')
