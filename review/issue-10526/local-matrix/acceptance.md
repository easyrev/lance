# Acceptance criteria recorded before measurements

- All variants use one upstream commit, the same deterministic Arrow inputs, default writer budgets, and the same Lance file version and runtime settings.
- Verify readback for each trial. Targeted splits must produce multiple pages with max raw bytes <= 32 MiB plus one maximum-width value. Constant and dirty-null logical constant controls must remain one page.
- Require <=2% file-size increase and <=10% median full-scan time increase against the rebased existing fix per workload. Recheck noisy timing comparisons with a second, interleaved run before rejecting. Record write timing and treat sustained material write regressions as costs in the adoption decision.
- P1 must help the 5% template workload or wide consecutive repeats while retaining wide-unique splitting. Keep consecutive blocks of 80 identical rows, with enough distinct bytes to cross the default dictionary budget within one candidate writer batch.
- P2 is evaluated as maximum physical width versus all-wide on the same P1 policy, with a separate existing-fix control. Adopt only if mostly-wide data splits and narrow-dominated data shows no harmful splitting or regression.
- Preserve the existing fix's scoped assertions, including its split behavior when the caller explicitly sets a page budget below the dictionary budget. Measure the literal P1 separately so any compatibility adjustment is visible.
