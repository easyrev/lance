"""Freeze reviewed source and actual imports after all build/test gates pass."""
import hashlib
import json
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
C = Path("/mnt/lance/checkouts/C")


def sha(path):
    return hashlib.file_digest(Path(path).open("rb"), "sha256").hexdigest()


def main():
    assert not (ROOT / "freeze.json").exists()
    required = ("C-final-unit-tests.log", "C-native-tests.log", "C-late-lineage-tests.log", "C-clippy-final.log", "C-final-build-retry.log", "C-python-tests.log", "C-semantic-tests.log")
    for name in required:
        assert (ROOT / "logs" / name).exists(), name
    review = ROOT / "diagnostics" / "review-r2.md"
    assert "FINAL CLEARANCE" in review.read_text(), "reviewer must clear final evidence"
    changed = subprocess.check_output(["git", "diff", "--name-only", "HEAD"], cwd=C, text=True).splitlines()
    untracked = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"], cwd=C, text=True).splitlines()
    sources = sorted(set(changed + untracked))
    patch = subprocess.check_output(["git", "diff", "--binary", "HEAD"], cwd=C)
    for name in untracked:
        patch += subprocess.run(["git", "diff", "--no-index", "--binary", "/dev/null", name], cwd=C, stdout=subprocess.PIPE).stdout
    (ROOT / "C.patch").write_bytes(patch)
    with tarfile.open(ROOT / "C-source.tar.gz", "w:gz") as archive:
        for name in sources:
            archive.add(C / name, arcname=name)
    identities = {}
    for variant, checkout in (("U", "U"), ("B", "B"), ("P_reconstructed", "P"), ("C", "C")):
        script = "import hashlib,json,sys,lance,lance.lance as e,pyarrow; from pathlib import Path; p=Path(e.__file__); print(json.dumps(dict(module=lance.__file__,extension=str(p),extension_sha256=hashlib.file_digest(p.open('rb'),'sha256').hexdigest(),version=lance.__version__,python=sys.version,pyarrow=pyarrow.__version__,arrow_allocator=pyarrow.default_memory_pool().backend_name)))"
        identity = json.loads(subprocess.check_output(["/root/.local/bin/uv", "run", "--no-sync", "python", "-c", script], cwd=f"/mnt/lance/checkouts/{checkout}/python", text=True))
        identities[variant] = identity
        (ROOT / "logs" / f"{variant}-frozen-identity.json").write_text(json.dumps(identity, indent=2) + "\n")
    freeze = dict(input_hashes={name:sha(Path("/mnt/lance/validation-9505")/name) for name in ("BENCHMARK-PROMPT.md", "lance-9505-unified-design.md", "codex-ecs-validation.md")}, handoff_sha256=sha("/mnt/lance/RESTORED-ENVIRONMENT.md"), revision="C-r2", frozen_at=datetime.now(timezone.utc).isoformat(), source_hashes={name: sha(C / name) for name in sources}, patch_sha256=sha(ROOT / "C.patch"), identities=identities, harness_hashes={name:sha(ROOT/name) for name in ("bench.py", "finite.py", "semantic.py", "first-seen.py", "pool.py", "native-extra.py", "latency.py", "summarize.py", "planned-matrix.json")}, cargo_lock_sha256=sha(C/"Cargo.lock"), python_cargo_lock_sha256=sha(C/"python/Cargo.lock"), profile_sha256=sha(C/".cargo/config.toml"), test_binary_source_state="pre-visibility-lint; see logs/test-binary-source-state.json and test-binary-to-final-visibility.patch", test_binary_sha256=sha("/mnt/lance/targets/C/release-with-debug/deps/lance-31a368c8670aef12"), reviewer_sha256=sha(review))
    (ROOT / "freeze.json").write_text(json.dumps(freeze, indent=2) + "\n")
    manifest = json.loads((ROOT / "manifest.json").read_text())
    manifest.update(status="reviewed and frozen; ready for mechanism measurements", freeze=freeze)
    (ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({variant:identity["extension_sha256"] for variant,identity in identities.items()}, indent=2))


if __name__ == "__main__":
    main()
