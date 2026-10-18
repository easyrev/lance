# Boundary, skew and FirstSeen decision

All C checks passed independent readback. Source100000 stops at EOF after four
batches. Source1000000 stops at 163840 rows after five batches and keeps Prefix;
it builds and updates exactly1000000 rows through the remaining stream. B's
one-million-row cell returns resource_exhausted and is not repeated. Its error
consumer and full message remain in its metrics.json. No failed timing enters
a latency pair.

The skew fixture has10 fragments, with90% of rows in its first two fragments
and all100 hot matched keys in its first fragment. B, Cbudget and Ccore complete
in0.226899,0.206114 and0.166617 seconds respectively. Each is a single smoke,
so no stable regression or performance claim follows. No skew expansion is
triggered.

The F4 FirstSeen smoke runs through the frozen optimized Rust test binary,
with its documented visibility-only source exception. It reads200 rows in two
ordered source batches, retains100 first winners and reports100 skipped
duplicates in the returned MergeStats. Its candidate operator counter does
not include preparation-level duplicate removal; use returned MergeStats for
the total. Independent U readback validates all4M rows and fields. This is
mechanism evidence, not a comparison of Rust and Python API latency. Native
scan output is14; one scan builds100 retained source rows.

No additional boundary, skew or FirstSeen performance expansion is triggered.
