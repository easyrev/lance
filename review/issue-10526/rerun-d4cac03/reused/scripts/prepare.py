import argparse
import json
from pathlib import Path

import lance
import numpy as np
import pyarrow as pa

SEED = 10526
BATCH_BYTES = 32_000_000


def binary_input(path, rows, low, high, random_bytes, mixed):
    rng = np.random.default_rng(SEED)
    word_ids = rng.choice(26**7, size=4096, replace=False)
    alphabet = np.frombuffer(b"abcdefghijklmnopqrstuvwxyz", dtype=np.uint8)
    words = np.full((4096, 8), ord(" "), dtype=np.uint8)
    for position in range(6, -1, -1):
        words[:, position] = alphabet[word_ids % 26]
        word_ids //= 26
    lengths = rng.integers(low, high + 1, size=rows, dtype=np.int64)
    if mixed:
        lengths[rows // 2:] = rng.integers(65_536, 131_073, size=rows - rows // 2)
    missing, empty = np.split(rng.choice(rows, 2 * (rows // 100), replace=False), 2)
    lengths[missing] = lengths[empty] = 0
    offsets = np.concatenate(([0], np.cumsum(lengths)))
    data = np.empty(offsets[-1], dtype=np.uint8)
    for start, end in zip(offsets[:-1], offsets[1:]):
        length = int(end - start)
        if not length:
            continue
        if random_bytes:
            data[start:end] = rng.integers(0, 256, length, dtype=np.uint8)
        else:
            ids = rng.integers(0, len(words), (length + 7) // 8, dtype=np.uint16)
            data[start:end] = words[ids].reshape(-1)[:length]
    valid = np.ones(rows, dtype=np.uint8)
    valid[missing] = 0
    column = pa.Array.from_buffers(
        pa.large_binary(), rows,
        [pa.py_buffer(np.packbits(valid, bitorder="little")), pa.py_buffer(offsets), pa.py_buffer(data)],
    )
    batch = pa.record_batch([column], names=["payload"])
    with pa.OSFile(str(path), "wb") as sink, pa.ipc.new_file(sink, batch.schema) as writer:
        writer.write_batch(batch)


def write(input_path, output, stream, zstd):
    with pa.memory_map(str(input_path), "r") as source:
        batch = pa.ipc.open_file(source).get_batch(0)
        if zstd:
            schema = pa.schema([batch.schema.field(0).with_metadata({b"lance-encoding:compression": b"zstd"})])
            batch = pa.RecordBatch.from_arrays(batch.columns, schema=schema)
        sizes = []
        if stream:
            col = batch.column(0)
            offsets = np.frombuffer(col.buffers()[1], dtype=np.int64)
            def batches():
                start = 0
                while start < batch.num_rows:
                    limit = int(np.searchsorted(offsets, offsets[start] + BATCH_BYTES, side="right")) - 1
                    end = max(start + 1, min(batch.num_rows, limit))
                    sizes.append(int(offsets[end] - offsets[start]))
                    yield batch.slice(start, end - start)
                    start = end
            source_data = pa.RecordBatchReader.from_batches(batch.schema, batches())
        else:
            sizes.append(batch.nbytes)
            source_data = batch
        lance.write_dataset(source_data, output, data_storage_version="2.2", max_rows_per_group=batch.num_rows, max_rows_per_file=batch.num_rows)
        print(json.dumps({"source": str(input_path), "rows": batch.num_rows, "batch_bytes": sizes, "stream": stream, "zstd_metadata": zstd}))


parser = argparse.ArgumentParser()
commands = parser.add_subparsers(dest="command", required=True)
gen = commands.add_parser("generate")
gen.add_argument("input", type=Path)
for name in ("rows", "low", "high"):
    gen.add_argument(name, type=int)
gen.add_argument("--random-bytes", action="store_true")
gen.add_argument("--mixed", action="store_true")
w = commands.add_parser("write")
w.add_argument("input", type=Path)
w.add_argument("output", type=Path)
w.add_argument("--stream", action="store_true")
w.add_argument("--zstd", action="store_true")
args = parser.parse_args()
if args.command == "generate":
    binary_input(args.input, args.rows, args.low, args.high, args.random_bytes, args.mixed)
else:
    write(args.input, args.output, args.stream, args.zstd)
