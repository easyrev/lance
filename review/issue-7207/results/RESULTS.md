# End-to-end race measurement

Status: **Not measured**.

| Tested commit | Lost commits | Unreferenced `_indices/` directories | Total bytes | Wall time |
| --- | ---: | ---: | ---: | ---: |
| `88d8b1cc7dadf1e27eba67b853d2113ac2c6c318` (`upstream/main`) | Not measured | Not measured | Not measured | Not measured |
| `a108f280a` (pure branch) | Not measured | Not measured | Not measured | Not measured |

The measurement is optional for this change. The unit tests exercise injected
verified-loss outcomes, live-manifest protection, rebase UUID replacement, the
propagate-after-success case, and the reporter's preemption path. No generated
table or fabricated measurement is stored in this branch.

To collect the missing rows, run
[`bench/measure_lost_indices.py`](../bench/measure_lost_indices.py) against the
same local data-disk path shape on each checkout. Keep the generated JSON under
an external data directory first, then copy only the JSON result into this
directory if the run is accepted as review evidence.
