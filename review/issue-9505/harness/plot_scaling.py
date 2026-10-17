"""Plot successful streaming-source scaling medians from summary.csv."""

import csv
from pathlib import Path
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import ScalarFormatter

root = Path(sys.argv[1])
rows = list(csv.DictReader((root / "results" / "summary.csv").open()))
series = [
    ("main", "main", "#b34439", "-"),
    ("statistics", "Small-source statistics", "#1769aa", "-"),
    ("pr10077", "#10077 + main", "#208266", "-"),
    ("fix", "Source-first experiment (rejected)", "#828282", "--"),
]
fig, axes = plt.subplots(1, 2, figsize=(11.5, 5.1))
for variant, label, color, style in series:
    points = []
    for size in (4_000_000, 16_000_000, 64_000_000):
        matches = [
            r
            for r in rows
            if r["variant"] == variant and r["case"] == f"fixed-{size}-streaming"
        ]
        assert len(matches) == 1 and matches[0]["completed"] == "2", matches
        points.append(matches[0])
    for ax, field in zip(axes, ("median_rss_gib", "median_seconds")):
        ax.plot(
            [4, 16, 64],
            [float(p[field]) for p in points],
            style,
            marker="o",
            color=color,
            label=label,
            linewidth=2,
        )
for ax, title, ylabel in zip(
    axes,
    ("Peak process memory", "Merge latency"),
    ("RSS (GiB, log scale)", "Seconds (log scale)"),
):
    ax.set_title(title, loc="left", fontsize=13, pad=12)
    ax.set_xlabel("Target rows (millions)")
    ax.set_ylabel(ylabel)
    ax.set_xscale("log", base=2)
    ax.set_xticks([4, 16, 64], ["4", "16", "64"])
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(ScalarFormatter())
    ax.grid(alpha=0.2, which="major")
    ax.spines[["top", "right"]].set_visible(False)
fig.suptitle(
    "Lance merge_insert: 100-row streamed source, 44-column target",
    x=0.07,
    ha="left",
    fontsize=15,
    fontweight="bold",
)
handles, labels = axes[0].get_legend_handles_labels()
fig.legend(
    handles,
    labels,
    loc="lower center",
    ncol=2,
    bbox_to_anchor=(0.5, 0.005),
    frameon=False,
    fontsize=9,
)
fig.text(
    0.07,
    0.14,
    "16 vCPU ECS · warm storage · 1 GiB pool requested (main ignores it) · 64 GiB cgroup\n"
    "Two runs per point; medians. Input generation and validation excluded from merge latency.",
    fontsize=8.5,
    color="#555555",
)
fig.subplots_adjust(left=0.07, right=0.98, top=0.82, bottom=0.31, wspace=0.27)
fig.savefig(root / "scaling.png", dpi=180, facecolor="white")
fig.savefig(root / "scaling.svg", facecolor="white")
