#!/usr/bin/env python3
"""Estimate disk and serial-runtime lower bounds for Stage 3."""

from __future__ import annotations

import json
import shutil

GIB = 1024**3


def main() -> int:
    experiment_1_runs = 78
    experiment_2_runs = 36
    experiment_3_runs = 54
    experiment_4_runs = 24
    experiment_5_runs = 6
    cold_cache_runs = 18
    parquet_variant_runs = 36
    parquet_reruns = 19
    total_runs = (
        experiment_1_runs
        + experiment_2_runs
        + experiment_3_runs
        + experiment_4_runs
        + experiment_5_runs
        + cold_cache_runs
        + parquet_variant_runs
        + parquet_reruns
    )

    max_target_gib = 16e6 * (8 + 768 * 4 + 200 + 8 + 4) / GIB
    max_source_gib = 100_000 * (8 + 8 + 4) / GIB
    build_artifacts_gib = 0.3
    loop_device_gib = 4
    retained_sources_gib = 43
    original_target_gib = 12
    max_new_target_gib = 16
    max_replay_spill_gib = 16
    experiment_1_peak_gib = (
        retained_sources_gib
        + original_target_gib
        + max_new_target_gib
        + max_replay_spill_gib
        + 1
    )
    experiment_3_peak_gib = max_target_gib + max_source_gib + 1
    experiment_5_peak_gib = (
        original_target_gib
        + max_replay_spill_gib
        + loop_device_gib
        + 1
    )
    peak_gib = max(
        experiment_1_peak_gib,
        experiment_3_peak_gib,
        experiment_5_peak_gib,
    )
    initial_free_gib = shutil.disk_usage("/mnt/lance").free / GIB
    usable_with_20_percent_reserve_gib = initial_free_gib * 0.8
    required_total_free_gib = peak_gib / 0.8
    capacity_shortfall_gib = max(
        0,
        required_total_free_gib - initial_free_gib,
    )

    report = {
        "estimated_runs": total_runs,
        "estimated_peak_local_gib": peak_gib,
        "experiment_1_peak_gib": experiment_1_peak_gib,
        "experiment_3_peak_gib": experiment_3_peak_gib,
        "experiment_5_peak_gib": experiment_5_peak_gib,
        "initial_free_gib": initial_free_gib,
        "usable_with_20_percent_reserve_gib": usable_with_20_percent_reserve_gib,
        "required_total_free_gib": required_total_free_gib,
        "capacity_shortfall_gib": capacity_shortfall_gib,
        "recommended_additional_gib": (
            40 if capacity_shortfall_gib > 0 else 0
        ),
        "wheels_gib": build_artifacts_gib,
        "max_experiment_3_target_gib": max_target_gib,
        "max_experiment_3_source_gib": max_source_gib,
        "notes": [
            "Peak space includes retained sources, the original target, new target data, and U replay spill.",
            "OSS data is remote. Local TMPDIR and wheel storage remain on the data disk.",
        ],
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
