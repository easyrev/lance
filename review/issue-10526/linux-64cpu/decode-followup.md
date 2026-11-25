# Issue 10526 follow-up decode measurements

[Scripts, raw trials and SHA256SUMS](decode-followup/) · [Original results](summary.md)

## Methods

Each cell reports median [minimum–maximum]. Each mode used three fresh processes
with `LANCE_CPU_THREADS=64`, the `release-with-debug` profile, and separate baseline,
final and experiment environments and targets. The experiment target and environment
were reused sequentially for A and B. The raw records include the machine configuration,
dataset file hashes and page counts.

For repeated `take`, each process opened one dataset handle before timing and
selected the same sorted row numbers from NumPy seed 10526 in all 20 calls.
Cold refers to the first take on that handle with the dataset on tmpfs.
The steady-state latency and RSS summaries pool calls 6–20 (45 samples).
The generated JSON also records the median of the three process medians.
RSS is the process high-water mark observed at the end of each call. The
final RSS row summarizes the high-water mark at the end of all 20 calls.
Standalone reads include dataset open, with `batch_size=1024` for scans.

The earlier run's Arrow IPC inputs were reused. The original writer rebuilt the Lance
files. A and B read the same final files as this round's final trials.

## Builds

| Build | Commit | Imported Python extension SHA-256 |
| --- | --- | --- |
| base (1p) | `cb8c25692e0d35d682be5459644a698f8d49655a` | `0e9064e38b9bc0caf08ad87111c69bbda4fd9fd752a37ac26d2061054ade9932` |
| final (135p / 44p) | `d0020f4291a0cb18790ac731df7c24890a169ca1` | `e25d2094bc551a8cfa58ee9b342c726bff63ee711c0f2ccf12b71b4b08924546` |
| exp-A (exact reserve) | `154270cf1fe06ff34524ca1fdcadbc8743302557` | `086adb709d90ef33adff7625a8b6eb0cf39f8a4d8838ad31e09026afacbb0460` |
| exp-B (page bridging) | `1d24f80fd2cae75eb81b2836be59256b3a2df4f4` | `b8de42c46c6c37ab729b470c0cd3f8e7475447b3d296145f0f01c0192cfee820` |

## Four-build comparison

| Metric | base (1p) | final (135p / 44p) | exp-A (exact reserve) | exp-B (page bridging) |
| --- | ---: | ---: | ---: | ---: |
| wide-unique take(128) call 1, ms | 28.293 [27.424–29.566] | 41.738 [41.394–41.787] | 39.816 [39.765–40.226] | 29.344 [29.338–29.450] |
| wide-unique take(128) call 1 peak RSS, MiB | 201.094 [199.184–202.094] | 219.926 [219.625–220.781] | 222.527 [222.102–222.844] | 208.562 [207.484–210.230] |
| wide-unique take(128) call 2, ms | 25.862 [25.024–26.677] | 34.289 [34.125–34.328] | 34.126 [34.065–34.151] | 24.356 [24.282–24.457] |
| wide-unique take(128) call 2 peak RSS, MiB | 228.082 [225.129–230.559] | 244.660 [244.016–244.695] | 246.480 [246.051–246.793] | 230.516 [229.617–232.793] |
| wide-unique take(128) calls 6–20, ms | 21.662 [21.406–22.561] | 23.335 [23.153–25.133] | 22.920 [22.824–23.148] | 21.914 [21.742–22.112] |
| wide-unique take(128) calls 6–20 peak RSS, MiB | 241.652 [239.801–242.801] | 268.508 [244.719–273.945] | 247.711 [246.152–248.996] | 232.066 [230.516–235.301] |
| wide-unique take(128) process peak RSS, MiB | 242.152 [242.070–242.801] | 268.508 [268.414–273.945] | 248.211 [247.652–248.996] | 233.066 [231.996–235.301] |
| wide-unique take(1024) call 1, ms | 198.934 [198.914–200.332] | 303.755 [302.580–311.491] | 292.677 [292.597–296.354] | 217.276 [215.978–219.380] |
| wide-unique take(1024) call 1 peak RSS, MiB | 406.605 [405.465–408.477] | 531.344 [530.520–535.777] | 530.543 [529.539–533.418] | 394.832 [394.164–395.883] |
| wide-unique take(1024) call 2, ms | 193.039 [192.998–193.499] | 266.882 [263.578–268.469] | 279.965 [279.272–280.858] | 215.873 [213.977–215.951] |
| wide-unique take(1024) call 2 peak RSS, MiB | 582.906 [582.527–585.176] | 749.340 [748.734–750.680] | 754.488 [751.992–754.578] | 584.387 [583.812–584.875] |
| wide-unique take(1024) calls 6–20, ms | 192.642 [192.199–193.402] | 270.121 [254.726–272.686] | 280.049 [277.397–282.405] | 215.329 [214.121–216.623] |
| wide-unique take(1024) calls 6–20 peak RSS, MiB | 586.770 [585.176–587.605] | 769.383 [764.387–774.172] | 771.199 [764.719–778.531] | 585.926 [585.457–586.707] |
| wide-unique take(1024) process peak RSS, MiB | 586.770 [585.809–587.605] | 772.957 [769.898–774.172] | 772.699 [767.934–778.531] | 585.926 [585.457–586.707] |
| wide-unique-8k scan, ms | 383.619 [367.580–392.433] | 353.871 [352.344–376.097] | 348.236 [346.561–362.185] | 323.068 [319.448–325.963] |
| wide-unique-8k scan peak RSS, MiB | 2047.293 [2035.715–2047.293] | 2555.379 [2484.270–2563.492] | 2422.512 [2403.504–2483.883] | 2001.887 [2001.715–2066.387] |
| wide-unique-8k take, ms | 32.643 [32.519–32.649] | 45.546 [45.308–45.620] | 43.553 [43.085–44.453] | 33.440 [33.121–33.889] |
| wide-unique-8k take peak RSS, MiB | 202.199 [200.633–203.871] | 218.664 [217.551–219.820] | 225.184 [224.961–225.531] | 206.641 [206.145–206.875] |
| wide-unique scan, ms | 743.254 [742.482–777.858] | 638.392 [617.669–674.812] | 620.915 [614.228–640.295] | 555.182 [554.897–585.036] |
| wide-unique scan peak RSS, MiB | 5629.887 [5604.598–5736.887] | 4741.480 [4455.105–5330.379] | 4955.340 [4680.707–4968.922] | 3821.527 [3601.801–3842.875] |

## Median changes

| Metric | base → final | final → exp-A | exp-A → exp-B | final → exp-B |
| --- | ---: | ---: | ---: | ---: |
| wide-unique take(128) call 1 | +13.445 ms (+47.52%) | -1.923 ms (-4.61%) | -10.471 ms (-26.30%) | -12.394 ms (-29.69%) |
| wide-unique take(128) call 2 | +8.427 ms (+32.58%) | -0.163 ms (-0.48%) | -9.770 ms (-28.63%) | -9.933 ms (-28.97%) |
| wide-unique take(128) calls 6–20 | +1.672 ms (+7.72%) | -0.415 ms (-1.78%) | -1.006 ms (-4.39%) | -1.421 ms (-6.09%) |
| wide-unique take(128) process peak RSS | +26.355 MiB (+10.88%) | -20.297 MiB (-7.56%) | -15.145 MiB (-6.10%) | -35.441 MiB (-13.20%) |
| wide-unique take(1024) call 1 | +104.821 ms (+52.69%) | -11.079 ms (-3.65%) | -75.401 ms (-25.76%) | -86.479 ms (-28.47%) |
| wide-unique take(1024) call 2 | +73.843 ms (+38.25%) | +13.083 ms (+4.90%) | -64.092 ms (-22.89%) | -51.009 ms (-19.11%) |
| wide-unique take(1024) calls 6–20 | +77.479 ms (+40.22%) | +9.928 ms (+3.68%) | -64.720 ms (-23.11%) | -54.793 ms (-20.28%) |
| wide-unique take(1024) process peak RSS | +186.188 MiB (+31.73%) | -0.258 MiB (-0.03%) | -186.773 MiB (-24.17%) | -187.031 MiB (-24.20%) |
| wide-unique-8k scan | -29.748 ms (-7.75%) | -5.635 ms (-1.59%) | -25.168 ms (-7.23%) | -30.803 ms (-8.70%) |
| wide-unique-8k scan peak RSS | +508.086 MiB (+24.82%) | -132.867 MiB (-5.20%) | -420.625 MiB (-17.36%) | -553.492 MiB (-21.66%) |
| wide-unique-8k take | +12.902 ms (+39.52%) | -1.993 ms (-4.38%) | -10.112 ms (-23.22%) | -12.105 ms (-26.58%) |
| wide-unique-8k take peak RSS | +16.465 MiB (+8.14%) | +6.520 MiB (+2.98%) | -18.543 MiB (-8.23%) | -12.023 MiB (-5.50%) |
| wide-unique scan | -104.862 ms (-14.11%) | -17.478 ms (-2.74%) | -65.732 ms (-10.59%) | -83.210 ms (-13.03%) |
| wide-unique scan peak RSS | -888.406 MiB (-15.78%) | +213.859 MiB (+4.51%) | -1133.812 MiB (-22.88%) | -919.953 MiB (-19.40%) |

## Exact reads

Both experiments compared all scan and take values to the Arrow IPC inputs.
The verify JSON records checked row counts, nulls, and value lengths.

| Dataset | Scan rows per build | Take rows per build | Null | Empty | Short nonempty |
| --- | ---: | ---: | ---: | ---: | ---: |
| wide-unique | 25000 | 25000 | 0 | 0 | 0 |
| wide-unique-8k | 8000 | 8000 | 0 | 0 | 0 |
| wide-mixed | 25000 | 25000 | 125 | 125 | 1000 |

## Rust checks

- A and B ran `cargo test -q -p lance-encoding --profile release-with-debug`. [A test log](decode-followup/raw/test-exp-A.log) · [B test log](decode-followup/raw/test-exp-B.log)
- Both builds ran `cargo fmt --all -- --check` with exit status 0.
- B ran `cargo clippy -p lance-encoding --tests --profile release-with-debug -- -D warnings` with exit status 0. [Clippy log](decode-followup/raw/clippy-exp-B.log)

## Evidence wording for the page-splitting PR

The first call in each process used a newly opened dataset handle. Both builds used the same row selection and files from the same Arrow input.

- `take(128)` median latency went from 28.29 → 41.74 ms (+47.52%) on the first call, 25.86 → 34.29 ms (+32.58%) on the second call, 21.66 → 23.33 ms (+7.72%) on calls 6–20.
- `take(1024)` median latency went from 198.93 → 303.76 ms (+52.69%) on the first call, 193.04 → 266.88 ms (+38.25%) on the second call, 192.64 → 270.12 ms (+40.22%) on calls 6–20.

The 1,024 selected values contain 184.32 MB (175.78 MiB) of payload. The steady-state base-to-final gap is +77.479 ms (+40.22%).

## Follow-up effects

### final → exp-A

- Wide take medians, first call and calls 6–20. For 128 rows, -1.923 ms (-4.61%) and -0.415 ms (-1.78%). For 1024 rows, -11.079 ms (-3.65%) and +9.928 ms (+3.68%).
- wide-unique-8k scan changed by -5.635 ms (-1.59%) in median time and -132.867 MiB (-5.20%) in peak RSS.
- wide-unique scan changed by -17.478 ms (-2.74%) in median time and +213.859 MiB (+4.51%) in peak RSS.

### exp-A → exp-B

- Wide take medians, first call and calls 6–20. For 128 rows, -10.471 ms (-26.30%) and -1.006 ms (-4.39%). For 1024 rows, -75.401 ms (-25.76%) and -64.720 ms (-23.11%).
- wide-unique-8k scan changed by -25.168 ms (-7.23%) in median time and -420.625 MiB (-17.36%) in peak RSS.
- wide-unique scan changed by -65.732 ms (-10.59%) in median time and -1133.812 MiB (-22.88%) in peak RSS.

The original 8k scan peak RSS increase was +25.86%, with a +10% criterion. In the new run, the baseline-to-final change was +508.086 MiB (+24.82%). The baseline-to-A change was +375.219 MiB (+18.33%) and the baseline-to-B change was -45.406 MiB (-2.22%). [Original RSS criterion and results](summary.md)
