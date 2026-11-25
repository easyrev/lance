import runpy
import sys

from lance.tracing import trace_to_chrome

trace_to_chrome(file=sys.argv.pop(1))
runpy.run_path(sys.argv.pop(1), run_name="__main__")
