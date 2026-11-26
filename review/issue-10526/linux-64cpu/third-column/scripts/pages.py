import json
import sys
from pathlib import Path

from lance.file import LanceFileReader

pages = []
for file in sorted((Path(sys.argv[1]) / "data").glob("*.lance")):
    metadata = LanceFileReader(str(file)).metadata()
    for column in metadata.columns:
        pages.extend(page.encoding for page in column.pages)
print(json.dumps(pages, indent=2))
