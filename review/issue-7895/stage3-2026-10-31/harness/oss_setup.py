#!/usr/bin/env python3
"""Load OSS credentials, verify access, and upload Experiment 4 data."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from bench_worker import load_oss_env


def make_filesystem():
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


def delete_prefix(fs, bucket: str, prefix: str) -> int:
    import pyarrow.fs as pafs

    selector = pafs.FileSelector(
        f"{bucket}/{prefix}",
        recursive=True,
        allow_not_found=True,
    )
    files = [
        info.path
        for info in fs.get_file_info(selector)
        if info.type == pafs.FileType.File
    ]
    for path in files:
        fs.delete_file(path)
    return len(files)


def upload_tree(
    fs,
    bucket: str,
    local_root: Path,
    remote_root: str,
) -> int:
    import pyarrow.fs as pafs

    local_fs = pafs.LocalFileSystem()
    selector = pafs.FileSelector(str(local_root), recursive=True)
    files = [
        info.path
        for info in local_fs.get_file_info(selector)
        if info.type == pafs.FileType.File
    ]
    for source in files:
        relative = Path(source).relative_to(local_root).as_posix()
        destination = f"{bucket}/{remote_root}/{relative}"
        pafs.copy_files(source, destination, destination_filesystem=fs)
    return len(files)


def main() -> int:
    load_oss_env()
    import lance
    import pyarrow as pa
    import pyarrow.fs as pafs

    bucket = os.environ["OSS_BUCKET"]
    prefix = os.environ.get("LANCE_9617_PREFIX", "_stage3_9617")
    region = os.environ["OSS_REGION"]
    native_endpoint = os.environ.get(
        "OSS_NATIVE_ENDPOINT",
        f"https://oss-{region}-internal.aliyuncs.com",
    )
    storage = {
        "oss_endpoint": native_endpoint,
        "oss_region": region,
        "oss_access_key_id": os.environ["AWS_ACCESS_KEY_ID"],
        "oss_secret_access_key": os.environ["AWS_SECRET_ACCESS_KEY"],
    }
    fs = make_filesystem()

    started = time.time()
    removed = delete_prefix(fs, bucket, prefix)
    small = f"{bucket}/{prefix}/probe.bin"
    payload = b"9617-stage3-oss-probe" * 1024
    with fs.open_output_stream(small) as stream:
        stream.write(payload)
    with fs.open_input_stream(small) as stream:
        if stream.read() != payload:
            raise AssertionError("PyArrow OSS round trip failed")
    fs.delete_file(small)

    probe_uri = f"oss://{bucket}/{prefix}/lance-probe"
    probe = pa.table({"id": [1, 2], "value": ["a", "b"]})
    lance.write_dataset(
        probe,
        probe_uri,
        storage_options=storage,
        mode="overwrite",
    )
    loaded = lance.dataset(probe_uri, storage_options=storage)
    if loaded.count_rows() != 2:
        raise AssertionError("Lance OSS round trip failed")
    delete_prefix(fs, bucket, f"{prefix}/lance-probe")

    fixture = Path("/mnt/lance/9617-bench/fixtures/experiment1-4m")
    uploads = {
        "target.lance": "exp4/target.lance",
        "source-4gib.lance": "exp4/source-4gib.lance",
        "source-4gib.parquet": "exp4/source-4gib.parquet",
    }
    counts = {}
    for local_name, remote_name in uploads.items():
        source = fixture / local_name
        if source.is_dir():
            counts[local_name] = upload_tree(
                fs,
                bucket,
                source,
                f"{prefix}/{remote_name}",
            )
        else:
            pafs.copy_files(
                str(source),
                f"{bucket}/{prefix}/{remote_name}",
                destination_filesystem=fs,
            )
            counts[local_name] = 1

    target = lance.dataset(
        f"oss://{bucket}/{prefix}/exp4/target.lance",
        storage_options=storage,
    )
    source = lance.dataset(
        f"oss://{bucket}/{prefix}/exp4/source-4gib.lance",
        storage_options=storage,
    )
    parquet = pafs.S3FileSystem(
        access_key=os.environ["AWS_ACCESS_KEY_ID"],
        secret_key=os.environ["AWS_SECRET_ACCESS_KEY"],
        session_token=os.environ.get("AWS_SESSION_TOKEN"),
        endpoint_override=os.environ["OSS_ENDPOINT"],
        region=region,
        force_virtual_addressing=True,
        scheme="https",
    )
    import pyarrow.dataset as pads

    arrow_source = pads.dataset(
        f"{bucket}/{prefix}/exp4/source-4gib.parquet",
        filesystem=parquet,
        format="parquet",
    )
    result = {
        "status": "ok",
        "removed_existing_objects": removed,
        "uploaded_files": counts,
        "target_rows": target.count_rows(),
        "target_versions": len(target.versions()),
        "lance_source_rows": source.count_rows(),
        "parquet_source_rows": arrow_source.count_rows(),
        "elapsed_s": time.time() - started,
    }
    (Path("/mnt/lance/9617-bench/state/oss-setup.json")).write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
