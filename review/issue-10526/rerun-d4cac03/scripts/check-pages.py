"""Apply the archived encoding parser and enforce the requested page matrix."""
import ast
import collections
import json
import re
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
archived = root / "reused/scripts/datasets.py"
parser = next(node for node in ast.parse(archived.read_text()).body
              if isinstance(node, ast.FunctionDef) and node.name == "value_encoding")
namespace = {"re": re}
exec(compile(ast.Module(body=[parser], type_ignores=[]), str(archived), "exec"), namespace)
value_encoding = namespace["value_encoding"]

directory, name, batches, zstd, variable = sys.argv[1:]
directory = Path(directory)
written = json.loads((directory / f"write-{name}.json").read_text())
pages = json.loads((directory / f"pages-{name}-detail.json").read_text())
counts = collections.Counter(map(value_encoding, pages))
expected = collections.Counter({
    "FullZip/General/CompressionAlgorithmZstd": int(zstd),
    "FullZip/Variable": int(variable),
})
observed_batches = len(written["batch_bytes"])
print(json.dumps({"dataset": name, "batches": observed_batches, "encodings": counts}))
assert observed_batches == int(batches), (name, observed_batches, batches)
assert counts == expected, (name, counts, expected)
