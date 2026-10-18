# Gate 2 decision

All 18 smoke cells have terminal records: 17 validated successes and one expected
P_reconstructed resource exhaustion on R. Ccore F4/R and the guarded Auto
counterexample completed and passed independent full-value readback.

F4 Cbudget/Ccore share policy M=1073741824, P=14, decode tasks=14,
width=396 and I/O=268435456 bytes. Each initializes one scan and builds 100 source
rows once. Cbudget retains a single scan output and RoundRobin; Ccore has 14 scan
outputs and no scan-boundary Repartition. Peak active tasks are 14 and 13.

R consumes a whole crossing batch: Prefix, 163840 rows, 57692800 Arrow bytes.
The initial small_fixed_target policy uses the actual narrow target projection,
not all 44 columns. Normal optimization produces Partitioned, target build of
100000 rows, native output P=14. It updates 100000 and inserts 2900000 rows.
An initial policy label is not a promise of final CollectLeft.

Wauto retains its first 25-row, 262144624-byte batch without observing EOF.
The actual target variable-width projection is wrapped with rows=Absent and
bytes=Absent. Normal Auto produces Partitioned with source build. Its scan
output remains one. It completes 25 updates with independent payload-content
validation. Unsafe bytes-only execution was not attempted; that counterfactual
is tested with allocation-free plans under both registry settings.

Wide Ccore labels do not imply native multi-output execution: Wn, Ws and Wauto
all retain one scan output in their actual optimized plans. Each uses one shared
scan initialization and at most 14 active tasks. Retain this distinction when
interpreting their timings. The source threshold overshoot and scan estimates
are not process memory bounds.

See gate2-mechanisms.json and each runs/g2-*/candidate.jsonl for raw evidence.
This decision permits core3; it does not establish performance retention.
