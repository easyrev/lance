import json
import re
import sys
from pathlib import Path

raw = Path(sys.argv[1])
paths = sorted(raw.glob("phase2-pages-*-final-detail.json"))
assert len(paths) == 9, paths
uncompressed = []
for path in paths:
    for index, page in enumerate(json.loads(path.read_text())):
        if "FullZipLayout(" in page and re.search(
            r"value_compression: Some\(\s*CompressiveEncoding \{\s*compression: Some\(\s*Variable\(",
            page,
        ):
            uncompressed.append((path.name, index))
print("var" if uncompressed else "pure")
for path, index in uncompressed:
    print(path, index)
