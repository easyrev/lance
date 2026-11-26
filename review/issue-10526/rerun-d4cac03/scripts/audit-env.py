import base64
import csv
import hashlib
import sys
from pathlib import Path

disk = Path(sys.argv[1])
raw = disk / "raw"
variants = ("base", "head")


def manifest(variant, kind):
    return dict(
        (path, digest)
        for line in (raw / f"{kind}-{variant}.sha256").read_text().splitlines()
        for digest, path in [line.split("  ", 1)]
    )


def record(path):
    with path.open() as stream:
        return {name: (digest, size) for name, digest, size in csv.reader(stream)}


def sha_record(data):
    return "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip("=")


base = disk / "env-base"
first_site = base / "lib/python3.12/site-packages"
base_manifest = manifest("base", "site")
for variant in variants[1:]:
    environment = disk / f"env-{variant}"
    site = environment / "lib/python3.12/site-packages"
    for label in ("freeze-dependencies", "python"):
        assert (raw / f"{label}-base.txt").read_bytes() == (raw / f"{label}-{variant}.txt").read_bytes()
    assert (base / "pyvenv.cfg").read_bytes() == (environment / "pyvenv.cfg").read_bytes()
    assert manifest("base", "package") == manifest(variant, "package")
    current = manifest(variant, "site")
    assert base_manifest.keys() == current.keys()
    differences = [name for name in base_manifest if base_manifest[name] != current[name]]
    for name in differences:
        assert name.endswith(".dist-info/RECORD"), name
        original, updated = record(first_site / name), record(site / name)
        assert original.keys() == updated.keys(), name
        for path in original:
            if original[path] == updated[path]:
                continue
            assert path.startswith("../../../bin/"), path
            left, right = (first_site / path).read_bytes(), (site / path).read_bytes()
            assert original[path] == (sha_record(left), str(len(left))), path
            assert updated[path] == (sha_record(right), str(len(right))), path
            assert left.replace(str(base).encode(), b"<ENV>") == right.replace(str(environment).encode(), b"<ENV>"), path
    first_bins = {path.name: path for path in (base / "bin").iterdir()}
    last_bins = {path.name: path for path in (environment / "bin").iterdir()}
    assert first_bins.keys() == last_bins.keys()
    for name, first in first_bins.items():
        last = last_bins[name]
        if first.is_symlink():
            assert last.is_symlink() and first.readlink() == last.readlink(), name
        else:
            left, right = first.read_bytes(), last.read_bytes()
            assert left.replace(str(base).encode(), b"<ENV>") == right.replace(str(environment).encode(), b"<ENV>"), name
    print(f"{variant}: {len(current)} dependency files. Only {len(differences)} RECORD files differ, solely in valid executable hashes for the local environment path. Launchers match after path normalization.")
print("All freezes, interpreters and Lance Python package files match. Existing native extension targets differ as requested.")
