#!/usr/bin/env python3
"""Transfer a Git source snapshot to an independent ECS checkout using SSH/rsync."""

import argparse
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

# This receiver runs inside one SSH process, holding flock until verification ends.
RECEIVER = r"""
import fcntl, json, os, pathlib, subprocess, sys
def require(condition, message):
    if not condition:
        raise RuntimeError(message)
p = json.loads(sys.stdin.readline())
name = p['name']
root = pathlib.Path('/mnt/lance')
require(subprocess.check_output(['findmnt', '-rn', '-M', str(root), '-o', 'UUID'], text=True).strip() == (root/'volume.uuid').read_text().strip(), 'Wrong volume')
lock = open(root/'locks'/('worktree-' + name + '.lock'), 'a')
fcntl.flock(lock, fcntl.LOCK_EX)
state = root/'state'/name
state.mkdir(exist_ok=True)
(state/'verified').unlink(missing_ok=True)
checkout = root/'checkouts'/name
checkout.mkdir(exist_ok=True)
require(not checkout.is_symlink(), 'Checkout root is a symlink')
require(not (checkout/'.git').is_symlink(), 'Git directory is a symlink')
repository = root/'git'/(name + '.git')
if not repository.exists():
    subprocess.run(['git', 'init', '--bare', str(repository)], check=True, stdout=sys.stderr)
if not (checkout/'.git').exists():
    subprocess.run(['git', 'init', str(checkout)], check=True, stdout=sys.stderr)
old = json.loads((state/'paths.json').read_text()) if (state/'paths.json').exists() else []
paths = p['paths']
def safe(path):
    parts = pathlib.PurePosixPath(path).parts
    require(parts and not pathlib.PurePosixPath(path).is_absolute() and '..' not in parts, 'Unsafe path: ' + path)
    require(not set(parts) & {'.git', '.venv', 'venv', 'target', '__pycache__', '.pytest_cache'}, 'Protected path: ' + path)
    require(parts[0] not in {'output', 'results', 'cache', 'caches'}, 'Protected root: ' + path)
    result = checkout/path
    for parent in result.parents:
        if parent == checkout:
            break
        require(not parent.is_symlink(), 'Symlink ancestor: ' + str(parent))
    return result
for path in paths:
    dest = safe(path)
    require(path in old or not os.path.lexists(dest), 'Unmanaged collision: ' + path)
# Persist the union before mutations so an interrupted transfer is recoverable.
(state/'paths.json').write_text(json.dumps(sorted(set(old) | set(paths))))
for path in sorted(set(old) - set(paths), reverse=True):
    dest = safe(path)
    if os.path.lexists(dest):
        require(not dest.is_dir() or dest.is_symlink(), 'Managed path became directory: ' + path)
        dest.unlink()
# Prune empty managed parent directories (never recursively delete unknown files).
for path in sorted(old, reverse=True):
    parent = (checkout/path).parent
    while parent != checkout:
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent
print('READY', flush=True)
if sys.stdin.readline().strip() != 'PUSHED':
    sys.exit('Synchronization aborted before commit transfer')
subprocess.run(['git', '-C', str(checkout), 'fetch', '--update-shallow', str(repository), p['revision']], check=True, stdout=sys.stderr)
subprocess.run(['git', '-C', str(checkout), 'update-ref', 'HEAD', p['revision']], check=True)
subprocess.run(['git', '-C', str(checkout), 'read-tree', 'HEAD'], check=True)
print('TRANSFER', flush=True)
if sys.stdin.readline().strip() != 'VERIFIED':
    sys.exit('Synchronization aborted before source verification')
(state/'paths.json').write_text(json.dumps(paths))
(state/'revision').write_text(p['revision'] + '\n')
(state/'working.diff').write_text(p['diff'])
(state/'verified').write_text(json.dumps({'revision': p['revision'], 'files': len(paths), 'verification': 'rsync checksum, symlinks and executable modes; zero dry-run differences'}) + '\n')
print('DONE', flush=True)
"""


def included(path):
    parts = PurePosixPath(path).parts
    return (
        parts[0] not in {"output", "results", "cache", "caches"}
        and not set(parts)
        & {".git", ".venv", "venv", "target", "__pycache__", ".pytest_cache"}
        and not path.endswith((".so", ".dylib", ".pyc", ".profraw"))
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name", help="Independent remote worktree name")
    parser.add_argument("--host", default="lance-ecs")
    parser.add_argument("--source", default=".")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.name):
        parser.error("name must contain only letters, numbers, underscores or hyphens")
    if not re.fullmatch(r"[A-Za-z0-9_.@-]+", args.host) or args.host.startswith("-"):
        parser.error("host must be an SSH alias or user@host")
    source = Path(
        subprocess.check_output(
            ["git", "-C", args.source, "rev-parse", "--show-toplevel"], text=True
        ).strip()
    )
    revision = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    listing = subprocess.check_output(
        [
            "git",
            "-C",
            str(source),
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        ]
    )
    paths = sorted(
        {
            os.fsdecode(p)
            for p in listing.split(b"\0")
            if p
            and included(os.fsdecode(p))
            and os.path.lexists(source / os.fsdecode(p))
        }
    )
    diff = subprocess.check_output(
        ["git", "-C", str(source), "diff", "HEAD", "--binary"], text=True
    )
    with tempfile.TemporaryDirectory(prefix="lance-sync-") as tmp:
        snapshot = Path(tmp) / "source"
        snapshot.mkdir()
        for path in paths:
            origin, dest = source / path, snapshot / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            if origin.is_symlink():
                dest.symlink_to(os.readlink(origin))
                # Git stores link targets, not symlink permissions. Linux links
                # have mode 0777; macOS can create them with a different mode.
                if stat.S_IMODE(dest.lstat().st_mode) != 0o777:
                    os.chmod(dest, 0o777, follow_symlinks=False)
                # Stable link timestamps prevent unchanged syncs from invalidating Cargo.
                source_stat = origin.lstat()
                os.utime(
                    dest,
                    ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns),
                    follow_symlinks=False,
                )
            elif stat.S_ISREG(origin.stat().st_mode):
                shutil.copy2(origin, dest)
            else:
                raise RuntimeError("Unsupported source file: " + path)
        filelist = Path(tmp) / "paths"
        filelist.write_bytes(b"".join(os.fsencode(p) + b"\0" for p in paths))
        receiver = subprocess.Popen(
            [
                "ssh",
                "-o",
                "ControlPath=none",
                args.host,
                "python3 -u -c " + shlex.quote(RECEIVER),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )

        def send(value):
            receiver.stdin.write(value + "\n")
            receiver.stdin.flush()

        def expect(value):
            actual = receiver.stdout.readline().strip()
            if actual != value:
                raise RuntimeError(f"Receiver expected {value}, got {actual!r}")

        try:
            send(
                json.dumps(
                    {
                        "name": args.name,
                        "paths": paths,
                        "revision": revision,
                        "diff": diff,
                    }
                )
            )
            expect("READY")
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(source),
                    "-c",
                    "core.sshCommand=ssh -o ControlPath=none",
                    "push",
                    f"{args.host}:/mnt/lance/git/{args.name}.git",
                    f"+{revision}:refs/heads/source",
                ],
                check=True,
            )
            send("PUSHED")
            expect("TRANSFER")
            destination = f"{args.host}:/mnt/lance/checkouts/{args.name}/"
            options = [
                "rsync",
                "-e",
                "ssh -o ControlPath=none",
                "-rlpt",
                "--no-owner",
                "--no-group",
                "--from0",
                "--files-from=" + str(filelist),
            ]
            subprocess.run(options + [str(snapshot) + "/", destination], check=True)
            result = subprocess.run(
                options
                + [
                    "--checksum",
                    "--dry-run",
                    "--itemize-changes",
                    str(snapshot) + "/",
                    destination,
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            if result.stdout.strip():
                raise RuntimeError("Source verification failed:\n" + result.stdout)
            send("VERIFIED")
            expect("DONE")
            receiver.stdin.close()
            if receiver.wait() != 0:
                raise RuntimeError("Receiver failed")
        finally:
            if not receiver.stdin.closed:
                receiver.stdin.close()
            if receiver.poll() is None:
                receiver.wait()
            receiver.stdout.close()
    print(
        f"Verified {len(paths)} source paths at {revision} in {args.host}:{args.name}"
    )


if __name__ == "__main__":
    main()
