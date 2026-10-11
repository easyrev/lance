"""Recover task-local disk space without touching the performance target."""

import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time


EVIDENCE = Path("/workspace/issue-7895-evidence")
DEV = Path("/workspace/issue-7895-target/debug")
DOCS = Path(
    "/workspace/.rustup/toolchains/1.98.1-x86_64-unknown-linux-gnu/share/doc/rust"
)
LOG = EVIDENCE / "recover-dev-space.jsonl"


def digest(path):
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def record(event):
    with LOG.open("a", encoding="utf-8") as output:
        output.write(json.dumps(event, sort_keys=True) + "\n")


def free_bytes():
    return shutil.disk_usage("/workspace").free


def strip_elf(path):
    if path.is_symlink() or not path.is_file():
        return
    with path.open("rb") as stream:
        if stream.read(4) != b"\x7fELF":
            return
    before = path.stat()
    event = {
        "operation": "strip_debug",
        "path": str(path),
        "size_before": before.st_size,
        "sha256_before": digest(path),
        "mtime_ns": before.st_mtime_ns,
        "atime_ns": before.st_atime_ns,
        "command": ["strip", "--strip-debug", "--preserve-dates", str(path)],
    }
    result = subprocess.run(event["command"], text=True, capture_output=True)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    event.update(
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        size_after=path.stat().st_size,
        sha256_after=digest(path),
    )
    # Hashing can advance atime; restore both timestamps after the final read.
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    record(event)
    if result.returncode:
        raise RuntimeError(f"strip failed for {path}: {result.stderr}")


started_free = free_bytes()
record({"operation": "start", "time": time.time(), "free_bytes": started_free})
if DOCS.exists():
    files = [
        {"path": str(path), "size": path.lstat().st_size}
        for path in DOCS.rglob("*")
        if path.is_file() or path.is_symlink()
    ]
    with (EVIDENCE / "deleted-rust-docs-files.json").open("w", encoding="utf-8") as output:
        json.dump(files, output)
        output.write("\n")
    record({"operation": "delete_docs", "path": str(DOCS), "file_count": len(files)})
    shutil.rmtree(DOCS)
    record({"operation": "docs_removed", "free_bytes": free_bytes()})

for candidate in sorted((DEV / "deps").glob("*.so")):
    strip_elf(candidate)
for candidate in sorted((DEV / "build").rglob("*")):
    strip_elf(candidate)
record({"operation": "elf_strip_finished", "free_bytes": free_bytes()})

manifest_path = EVIDENCE / "dev-rmeta-compression.jsonl"
if manifest_path.exists():
    raise RuntimeError(f"Refusing to overwrite restoration manifest {manifest_path}")
for path in sorted(DEV.rglob("*.rmeta")):
    if path.is_symlink():
        raise RuntimeError(f"Unexpected rmeta symlink: {path}")
    original = path.stat()
    compressed = path.with_name(path.name + ".gz")
    if compressed.exists():
        raise RuntimeError(f"Refusing to overwrite compressed artifact {compressed}")
    item = {
        "path": str(path),
        "compressed": str(compressed),
        "size": original.st_size,
        "sha256": digest(path),
        "mode": original.st_mode & 0o7777,
        "atime_ns": original.st_atime_ns,
        "mtime_ns": original.st_mtime_ns,
    }
    with path.open("rb") as source, compressed.open("xb") as destination:
        with gzip.GzipFile(filename="", mode="wb", fileobj=destination, mtime=0) as stream:
            shutil.copyfileobj(source, stream, 1024 * 1024)
    checksum = hashlib.sha256()
    restored_size = 0
    with gzip.open(compressed, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            checksum.update(chunk)
            restored_size += len(chunk)
    if checksum.hexdigest() != item["sha256"] or restored_size != item["size"]:
        raise RuntimeError(f"Compressed artifact failed round-trip verification: {path}")
    item["compressed_size"] = compressed.stat().st_size
    item["compressed_sha256"] = digest(compressed)
    with manifest_path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(item, sort_keys=True) + "\n")
        output.flush()
        os.fsync(output.fileno())
    path.unlink()
record({"operation": "rmeta_compressed", "manifest": str(manifest_path)})
ended_free = free_bytes()
record(
    {
        "operation": "finish",
        "time": time.time(),
        "free_bytes": ended_free,
        "recovered_bytes": ended_free - started_free,
    }
)
print(json.dumps({"free_bytes": ended_free, "recovered_bytes": ended_free - started_free}))
