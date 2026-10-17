"""Restore the task's compressed DEV Rust metadata with checksum verification."""

import gzip
import hashlib
import json
import os
from pathlib import Path


MANIFEST = Path("/workspace/issue-7895-evidence/dev-rmeta-compression.jsonl")
for line in MANIFEST.read_text(encoding="utf-8").splitlines():
    item = json.loads(line)
    path = Path(item["path"])
    if path.exists():
        with path.open("rb") as source:
            checksum = hashlib.file_digest(source, "sha256").hexdigest()
        if checksum != item["sha256"]:
            raise RuntimeError(f"Refusing to replace existing changed artifact: {path}")
        os.utime(path, ns=(item["atime_ns"], item["mtime_ns"]))
        continue
    compressed = Path(item["compressed"])
    with compressed.open("rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != item["compressed_sha256"]:
            raise RuntimeError(f"Compressed file checksum mismatch: {compressed}")
    temporary = path.with_name(path.name + ".restore-tmp")
    checksum = hashlib.sha256()
    restored_size = 0
    with gzip.open(compressed, "rb") as source, temporary.open("xb") as destination:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            checksum.update(chunk)
            restored_size += len(chunk)
            destination.write(chunk)
    if checksum.hexdigest() != item["sha256"] or restored_size != item["size"]:
        temporary.unlink()
        raise RuntimeError(f"Restored file checksum mismatch: {path}")
    os.chmod(temporary, item["mode"])
    os.utime(temporary, ns=(item["atime_ns"], item["mtime_ns"]))
    temporary.replace(path)
    compressed.unlink()
print("Restored DEV .rmeta artifacts and their exact original timestamps.")
