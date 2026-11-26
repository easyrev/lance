import sys
from pathlib import Path
doc = Path(sys.argv[1]).read_text()
rows = [line for line in doc.splitlines() if line.startswith("| ") and "，回归" in line]
print(next(line for line in doc.splitlines() if line.startswith("| 数据集")))
print(next(line for line in doc.splitlines() if line.startswith("|---")))
print("\n".join(rows))
