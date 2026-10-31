#!/usr/bin/env python3
"""Run one isolated merge-insert benchmark cell.

The parent process starts one copy of this program for each measurement.
Secrets are loaded from the OSS environment file before manager imports and
are removed from all JSON, exceptions, and log text.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Any

OSS_ENV_PATH = Path("/root/.lance-bench/oss.env")
BASE_TAG = "bench-base"
SPILL_PEAKS: dict[str, int] = {}
EXECUTION_WALLS: dict[str, float] = {}


def load_oss_env() -> dict[str, str]:
    """Load the host OSS environment without printing any values."""
    values: dict[str, str] = {}
    with OSS_ENV_PATH.open(encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:]
            key, separator, value = line.partition("=")
            if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            values[key] = value
            os.environ[key] = value
    return values


def secret_values() -> set[str]:
    secret_keys = (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "OSS_ACCESS_KEY_ID",
        "OSS_ACCESS_KEY_SECRET",
    )
    return {os.environ[key] for key in secret_keys if os.environ.get(key)}


def redact(text: str) -> str:
    for secret in secret_values():
        text = text.replace(secret, "[REDACTED]")
    text = re.sub(
        r"(?i)(access[_-]?key(?:[_-]?id)?|secret[_-]?(?:access[_-]?)?key|"
        r"session[_-]?token)\s*[:=]\s*[^\s,;]+",
        r"\1=[REDACTED]",
        text,
    )
    text = re.sub(r"(https?://)[^/@\s]+@", r"\1[REDACTED]@", text)
    return text


def storage_options() -> dict[str, str]:
    region = os.environ["OSS_REGION"]
    return {
        "oss_endpoint": os.environ.get(
            "OSS_NATIVE_ENDPOINT",
            f"https://oss-{region}-internal.aliyuncs.com",
        ),
        "oss_region": region,
        "oss_access_key_id": os.environ["AWS_ACCESS_KEY_ID"],
        "oss_secret_access_key": os.environ["AWS_SECRET_ACCESS_KEY"],
        **(
            {"oss_session_token": os.environ["AWS_SESSION_TOKEN"]}
            if os.environ.get("AWS_SESSION_TOKEN")
            else {}
        ),
    }


def directory_size(root: Path) -> int:
    total = 0
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                    except FileNotFoundError:
                        continue
        except FileNotFoundError:
            continue
    return total


class SpillSampler:
    def __init__(self, root: Path, interval_s: float = 0.02):
        self.root = root
        self.interval_s = interval_s
        self.peak_bytes = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._sample, daemon=True)

    def _sample(self) -> None:
        while not self._stop.is_set():
            self.peak_bytes = max(self.peak_bytes, directory_size(self.root))
            self._stop.wait(self.interval_s)
        self.peak_bytes = max(self.peak_bytes, directory_size(self.root))

    def __enter__(self) -> "SpillSampler":
        self.root.mkdir(parents=True, exist_ok=True)
        self._thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
        SPILL_PEAKS[str(self.root)] = self.peak_bytes


def dataset_uri(spec: dict[str, Any], key: str) -> str:
    if spec.get("storage") == "oss":
        return spec[key]
    return str(Path(spec[key]))


def open_dataset(uri: str, spec: dict[str, Any]):
    import lance

    options = storage_options() if uri.startswith("oss://") else None
    return lance.dataset(uri, storage_options=options)


def parquet_filesystem():
    import pyarrow.fs as pafs

    region = os.environ["OSS_REGION"]
    return pafs.S3FileSystem(
        access_key=os.environ["AWS_ACCESS_KEY_ID"],
        secret_key=os.environ["AWS_SECRET_ACCESS_KEY"],
        session_token=os.environ.get("AWS_SESSION_TOKEN"),
        endpoint_override=os.environ.get(
            "OSS_ENDPOINT",
            f"https://s3.oss-{region}-internal.aliyuncs.com",
        ),
        region=region,
        force_virtual_addressing=True,
        scheme="https",
    )


def parquet_source(path: str, spec: dict[str, Any]):
    import pyarrow.dataset as pads
    import pyarrow.parquet as pq

    if spec.get("storage") == "oss":
        filesystem = parquet_filesystem()
        if not path.startswith("oss://"):
            raise ValueError("OSS Parquet source must use oss://")
        bucket_and_key = path.removeprefix("oss://")
        return (
            pads.dataset(bucket_and_key, filesystem=filesystem, format="parquet"),
            pq.ParquetFile(bucket_and_key, filesystem=filesystem),
        )
    return pads.dataset(path, format="parquet"), pq.ParquetFile(path)


def apply_parquet_adapter_variant(
    variant: str,
    *,
    batch_size: int | None = None,
) -> dict[str, int]:
    """Apply an uncommitted scanner patch inside this child process."""
    import pyarrow.dataset as pads

    from lance import types as lance_types

    options: dict[str, int] = {
        "batch_readahead": 1,
        "fragment_readahead": 1,
    }
    if variant == "byte_budget":
        if batch_size is None:
            raise ValueError("byte_budget variant requires batch_size")
        options["batch_size"] = batch_size

    def variant_arrow_dataset_source(data_obj, schema=None):
        scanner = pads.Scanner.from_dataset(data_obj, **options)
        mode = (
            "replayable"
            if lance_types._arrow_dataset_replayable(data_obj)
            else "streaming"
        )
        return lance_types._WriteSource(
            scanner.projected_schema,
            scanner.to_reader,
            mode,
        )

    lance_types._coerce_source.register(pads.Dataset)(
        variant_arrow_dataset_source
    )
    return options


def normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): normalize(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [normalize(item) for item in value]
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat(sep=" ")
    if hasattr(value, "item"):
        return normalize(value.item())
    return value


def value_key(value: Any) -> str:
    raw = json.dumps(
        normalize(value),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def verify_result(
    target,
    expected_rows: int,
    expected_versions: int,
    samples: list[dict[str, Any]],
) -> dict[str, Any]:
    rows = target.count_rows()
    versions = target.versions()
    if rows != expected_rows:
        raise AssertionError(f"row count {rows} != expected {expected_rows}")
    if len(versions) != expected_versions:
        raise AssertionError(
            f"version count {len(versions)} != expected {expected_versions}"
        )

    ids = [sample["id"] for sample in samples]
    sampled = target.to_table(
        columns=[column["name"] for column in samples[0]["columns"]],
        filter=f"id IN ({','.join(str(value) for value in ids)})",
    )
    expected_keys = {
        sample["id"]: value_key(
            {
                column["name"]: column["value"]
                for column in sample["columns"]
            }
        )
        for sample in samples
    }
    actual_row_keys = {
        row["id"]: value_key(
            {
                field.name: row[field.name]
                for field in sampled.schema
            }
        )
        for row in sampled.to_pylist()
    }
    for identifier, expected in expected_keys.items():
        if actual_row_keys.get(identifier) != expected:
            raise AssertionError(f"sampled row mismatch for id={identifier}")
    return {
        "rows": rows,
        "version_count": len(versions),
        "sampled_ids": ids,
        "sampled_rows": len(actual_row_keys),
    }


def reset_to_base(uri: str, spec: dict[str, Any], expected_rows: int) -> None:
    target = open_dataset(uri, spec)
    base = target.checkout_version(BASE_TAG)
    base.restore()
    latest = open_dataset(uri, spec)
    if latest.count_rows() != expected_rows:
        raise AssertionError(
            f"reset row count {latest.count_rows()} != {expected_rows}"
        )
    latest.cleanup_old_versions(
        older_than=dt.timedelta(microseconds=1),
        retain_versions=None,
        error_if_tagged_old_versions=False,
        delete_unverified=True,
    )


def net_received() -> int:
    total = 0
    with open("/proc/net/dev", encoding="ascii") as net_file:
        for line in net_file:
            if ":" not in line:
                continue
            _interface, values = line.split(":", 1)
            fields = values.split()
            if fields:
                total += int(fields[0])
    return total


def disk_counters() -> dict[str, int]:
    keys = (
        "reads_completed",
        "read_sectors",
        "read_ms",
        "writes_completed",
        "write_sectors",
        "write_ms",
    )
    with open("/proc/diskstats", encoding="ascii") as stats_file:
        for line in stats_file:
            fields = line.split()
            if len(fields) >= 14 and fields[2] == "nvme0n1":
                return {
                    "reads_completed": int(fields[3]),
                    "read_sectors": int(fields[5]),
                    "read_ms": int(fields[6]),
                    "writes_completed": int(fields[7]),
                    "write_sectors": int(fields[9]),
                    "write_ms": int(fields[10]),
                }
    raise RuntimeError("cannot find nvme0n1 in /proc/diskstats")


def run(args: argparse.Namespace, spec: dict[str, Any]) -> dict[str, Any]:
    target_uri = dataset_uri(spec, "target_uri")
    source_path = dataset_uri(spec, "source_uri")
    target = open_dataset(target_uri, spec)
    expected_versions = len(target.versions()) + 1 + int(args.conflict)
    expected_rows = int(spec["expected_rows_after"])

    run_tmp = Path(args.tmpdir)
    if run_tmp.exists():
        shutil.rmtree(run_tmp)
    run_tmp.mkdir(parents=True)
    os.environ["TMPDIR"] = str(run_tmp)

    if spec["source_format"] == "lance":
        source = open_dataset(source_path, spec)
        source_rows = source.count_rows()
        parquet_metadata = None
        adapter_options: dict[str, int] = {}
    else:
        source, parquet_metadata = parquet_source(source_path, spec)
        source_rows = source.count_rows()
        adapter_options = {}
        variant = spec.get("parquet_adapter_variant")
        if variant:
            metadata = parquet_metadata.metadata
            row_group = metadata.row_group(0)
            uncompressed = sum(
                row_group.column(index).total_uncompressed_size
                for index in range(row_group.num_columns)
            )
            row_width = max(1, int(uncompressed / row_group.num_rows))
            batch_size = (
                max(1, (64 * 1024**2) // row_width)
                if variant == "byte_budget"
                else None
            )
            adapter_options = apply_parquet_adapter_variant(
                variant,
                batch_size=batch_size,
            )
    if source_rows != int(spec["source_rows"]):
        raise AssertionError(
            f"source rows {source_rows} != expected {int(spec['source_rows'])}"
        )

    builder = (
        target.merge_insert("id")
        .when_matched_update_all()
        .when_not_matched_insert_all()
        .write_mode(spec.get("write_mode", "auto"))
    )
    if not spec.get("use_default_retry_settings"):
        retries = int(spec.get("conflict_retries", 2))
        builder = builder.conflict_retries(retries)
        if args.conflict and retries > 0:
            builder = builder.retry_timeout(dt.timedelta(minutes=30))

    if args.analyze:
        try:
            plan = builder.analyze_plan(source)
            plan_path = Path(args.plan_out)
            plan_path.parent.mkdir(parents=True, exist_ok=True)
            plan_path.write_text(redact(plan), encoding="utf-8")
            return {
                "status": "ok",
                "analysis_only": True,
                "plan_path": str(plan_path),
                "plan_sha256": hashlib.sha256(plan.encode()).hexdigest(),
                "build": args.build,
                "experiment": spec.get("experiment"),
                "case": spec.get("case"),
                "run": args.run_number,
                "conflict": args.conflict,
            }
        finally:
            reset_to_base(target_uri, spec, int(spec["base_rows"]))
    if args.conflict:
        competing = open_dataset(target_uri, spec)
        conflict_id = int(spec["conflict_id"])
        competing.update(
            {"label": f"'conflict-{time.time_ns()}'"},
            where=f"id = {conflict_id}",
        )

    received_before = net_received() if spec.get("storage") == "oss" else 0
    disk_before = disk_counters() if spec.get("storage") != "oss" else {}
    started = time.perf_counter()
    try:
        try:
            with SpillSampler(run_tmp) as sampler:
                stats = builder.execute(source)
        except BaseException:
            EXECUTION_WALLS[str(run_tmp)] = time.perf_counter() - started
            raise
        wall_s = time.perf_counter() - started
        received_after = net_received() if spec.get("storage") == "oss" else 0
        disk_after = disk_counters() if spec.get("storage") != "oss" else {}

        latest = open_dataset(target_uri, spec)
        verification = verify_result(
            latest,
            expected_rows,
            expected_versions,
            spec["samples"],
        )
    finally:
        reset_to_base(target_uri, spec, int(spec["base_rows"]))

    result: dict[str, Any] = {
        "status": "ok",
        "wall_s": wall_s,
        "spill_peak_bytes": sampler.peak_bytes,
        "merge_stats": stats,
        "verification": verification,
        "received_bytes": received_after - received_before,
        "disk_read_bytes": (
            (disk_after["read_sectors"] - disk_before["read_sectors"]) * 512
            if disk_before
            else 0
        ),
        "disk_reads": (
            disk_after["reads_completed"] - disk_before["reads_completed"]
            if disk_before
            else 0
        ),
        "disk_read_ms": (
            disk_after["read_ms"] - disk_before["read_ms"]
            if disk_before
            else 0
        ),
        "disk_write_bytes": (
            (disk_after["write_sectors"] - disk_before["write_sectors"]) * 512
            if disk_before
            else 0
        ),
        "disk_write_ms": (
            disk_after["write_ms"] - disk_before["write_ms"]
            if disk_before
            else 0
        ),
        "build": args.build,
        "experiment": spec.get("experiment"),
        "case": spec.get("case"),
        "run": args.run_number,
        "conflict": args.conflict,
        "parquet_adapter_variant": spec.get("parquet_adapter_variant"),
        "parquet_adapter_options": adapter_options,
    }
    if spec["source_format"] == "parquet":
        metadata = parquet_metadata.metadata
        row_group = metadata.row_group(0)
        total_uncompressed = sum(
            row_group.column(index).total_uncompressed_size
            for index in range(row_group.num_columns)
        )
        result["parquet_rows_per_row_group"] = row_group.num_rows
        result["parquet_uncompressed_bytes_per_row"] = (
            total_uncompressed / row_group.num_rows
        )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", required=True)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--run-number", type=int, required=True)
    parser.add_argument("--tmpdir", required=True)
    parser.add_argument("--conflict", action="store_true")
    parser.add_argument("--oss", action="store_true")
    parser.add_argument("--analyze", action="store_true")
    parser.add_argument("--plan-out", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    loaded: dict[str, str] = {}
    try:
        if args.oss:
            loaded = load_oss_env()
        spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
        if "extends" in spec:
            base_path = Path(spec["extends"])
            base = json.loads(base_path.read_text(encoding="utf-8"))
            base.update(spec)
            spec = base
        result = run(args, spec)
        print(redact(json.dumps(result, sort_keys=True)))
        return 0
    except BaseException as exc:
        payload = {
            "status": "error",
            "error_type": type(exc).__name__,
            "message": redact(str(exc)),
            "build": args.build,
            "run": args.run_number,
            "conflict": args.conflict,
            "spill_peak_bytes": SPILL_PEAKS.get(
                args.tmpdir,
                directory_size(Path(args.tmpdir)),
            ),
            "execute_wall_s": EXECUTION_WALLS.get(args.tmpdir),
        }
        print(redact(json.dumps(payload, sort_keys=True)))
        return 1
    finally:
        secrets = secret_values() | set(loaded.values())
        for key in list(os.environ):
            if key in {
                "AWS_ACCESS_KEY_ID",
                "AWS_SECRET_ACCESS_KEY",
                "AWS_SESSION_TOKEN",
                "OSS_ACCESS_KEY_ID",
                "OSS_ACCESS_KEY_SECRET",
            }:
                os.environ.pop(key, None)
        for secret in secrets:
            if secret:
                os.environ.pop(secret, None)


if __name__ == "__main__":
    sys.exit(main())
