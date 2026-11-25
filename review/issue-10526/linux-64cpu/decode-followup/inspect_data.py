import hashlib
import json
import sys
from pathlib import Path

from lance.file import LanceFileReader

(dataset, expected_pages) = sys.argv[1:]
[file] = (Path(dataset) / "data").glob("*.lance")
columns = LanceFileReader(str(file)).metadata().columns
assert len(columns) == 1
page_count = len(columns[0].pages)
assert page_count == int(expected_pages), (page_count, expected_pages)
with file.open("rb") as stream:
    digest = hashlib.file_digest(stream, "sha256").hexdigest()
print(
    json.dumps(
        {"pages": page_count, "file_bytes": file.stat().st_size, "sha256": digest}
    )
)
