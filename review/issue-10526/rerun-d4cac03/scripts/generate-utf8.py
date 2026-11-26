"""Select the two requested inputs from the archived generator."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "reused/scripts/reused"))
import bench

bench.DATASETS = ("wide-unique", "wide-unique-8k")
bench.generate(Path(sys.argv[1]))
