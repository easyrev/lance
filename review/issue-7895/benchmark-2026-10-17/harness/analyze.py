# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright The Lance Authors

"""Summarize results/raw.jsonl into per-cell medians (stdlib only).

    python3 analyze.py [raw.jsonl] [--label LABEL]

p90 is nearest-rank, so with 5 samples it is the maximum.
"""

from __future__ import annotations

import json
import math
import statistics
import sys
from collections import defaultdict

MIB = 1 << 20


def p90(values):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.9 * len(ordered)) - 1)]


def load(path, label=None):
    with open(path) as f:
        rows = [json.loads(line) for line in f if line.strip()]
    return [r for r in rows if label is None or r.get("label") == label]


def cell_key(r):
    return (
        r["layer"],
        r["cache"],
        r.get("tmp_kind", "nvme"),
        r["tier"],
        r["source"],
        r["conflict"],
        r["variant"],
    )


def summarize(rows):
    cells = defaultdict(list)
    for r in rows:
        cells[cell_key(r)].append(r)
    out = []
    for key, runs in sorted(cells.items()):
        ok = [r for r in runs if r["exit_code"] == 0]
        entry = dict(
            zip(("layer", "cache", "tmp", "tier", "source", "conflict", "variant"), key)
        )
        entry["n"] = len(runs)
        entry["failed"] = len(runs) - len(ok)
        entry["verify_ok"] = sum(1 for r in ok if r.get("verify", {}).get("ok"))
        if ok:
            walls = [r["merge_wall_s"] for r in ok]
            entry.update(
                rows=ok[0]["source_rows"],
                arrow_mib=ok[0]["source_arrow_bytes"] / MIB,
                wall_med=statistics.median(walls),
                wall_p90=p90(walls),
                cpu_med=statistics.median(r["cpu_s"] for r in ok),
                merge_cpu_med=statistics.median(
                    r["merge_user_s"] + r["merge_sys_s"] for r in ok
                ),
                rss_med_mib=statistics.median(r["peak_rss_kib"] for r in ok) / 1024,
                rss_min_mib=min(r["peak_rss_kib"] for r in ok) / 1024,
                rss_max_mib=max(r["peak_rss_kib"] for r in ok) / 1024,
                spill_med_mib=statistics.median(r["spill_bytes_est_wchar"] for r in ok)
                / MIB,
                tmp_peak_med_mib=statistics.median(r["tmp_peak_bytes"] for r in ok)
                / MIB,
                written_med_mib=statistics.median(r["target_written_bytes"] for r in ok)
                / MIB,
                attempts=sorted({r["commit_attempts"] for r in ok}),
                spill_file=sorted({r["replay_buffer_on_disk"] for r in ok}),
            )
        else:
            entry["error"] = runs[0].get("error_tail", "")[-300:]
        out.append(entry)
    return out


def print_table(entries):
    header = (
        f"{'layer':5} {'cache':5} {'tmp':6} {'tier':5} {'source':13} c {'variant':8} "
        f"{'n':>2} {'ok':>2} {'wall_med':>8} {'wall_p90':>8} {'cpu':>7} {'mcpu':>7} "
        f"{'rss':>7} {'spill':>8} {'tmpPk':>8} {'written':>8} att"
    )
    print(header)
    for e in entries:
        if "wall_med" not in e:
            print(
                f"{e['layer']:5} {e['cache']:5} {e['tmp']:6} {e['tier']:5} "
                f"{e['source']:13} {e['conflict']} {e['variant']:8} {e['n']:>2} "
                f"FAILED {e.get('error', '')[-120:]!r}"
            )
            continue
        print(
            f"{e['layer']:5} {e['cache']:5} {e['tmp']:6} {e['tier']:5} {e['source']:13} "
            f"{e['conflict']} {e['variant']:8} {e['n']:>2} {e['verify_ok']:>2} "
            f"{e['wall_med']:8.2f} {e['wall_p90']:8.2f} {e['cpu_med']:7.1f} "
            f"{e['merge_cpu_med']:7.1f} {e['rss_med_mib']:7.0f} {e['spill_med_mib']:8.0f} "
            f"{e['tmp_peak_med_mib']:8.0f} {e['written_med_mib']:8.0f} {e['attempts']}"
        )


if __name__ == "__main__":
    args = sys.argv[1:]
    label = None
    if "--label" in args:
        i = args.index("--label")
        label = args[i + 1]
        del args[i : i + 2]
    path = args[0] if args else "/mnt/lance/bench-9617/results/raw.jsonl"
    print_table(summarize(load(path, label)))
