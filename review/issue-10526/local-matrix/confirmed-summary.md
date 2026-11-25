| Workload | Variant | n | File B | Pages | Max raw B | Max encoded B | Layouts | Write ms | Read ms | Read vs fix |
|---|---|---:|---:|---:|---:|---:|---|---:|---:|---:|
| unique | fix | 7 | 10278014 | 3 | 24120000 | 3443538 | FullZipLayout | 20.39 | 21.26 | +0.0% |
| unique | p1-compatible | 7 | 10278014 | 3 | 24120000 | 3443538 | FullZipLayout | 19.76 | 21.31 | +0.2% |
| unique | p2-compatible | 7 | 10278014 | 3 | 24120000 | 3443538 | FullZipLayout | 19.38 | 21.25 | -0.0% |
| consecutive | fix | 7 | 102754490 | 1 | 720000000 | 102754164 | FullZipLayout | 266.21 | 151.85 | +0.0% |
| consecutive | p1-compatible | 7 | 5113907 | 22 | 32760000 | 292293 | MiniBlockLayout | 15.14 | 45.07 | -70.3% |
| consecutive | p2-compatible | 7 | 5113907 | 22 | 32760000 | 292293 | MiniBlockLayout | 16.23 | 45.38 | -70.1% |
| template | fix | 7 | 10277498 | 1 | 72000000 | 10277143 | FullZipLayout | 19.41 | 20.23 | +0.0% |
| template | p1-compatible | 7 | 10277822 | 3 | 24120000 | 3443146 | FullZipLayout | 18.03 | 21.54 | +6.4% |
| template | p2-compatible | 7 | 10277822 | 3 | 24120000 | 3443146 | FullZipLayout | 18.03 | 21.14 | +4.5% |
| constant | fix | 7 | 180247 | 1 | 72000000 | 180028 | ConstantLayout | 3.15 | 4.47 | +0.0% |
| constant | p1-compatible | 7 | 180247 | 1 | 72000000 | 180028 | ConstantLayout | 4.59 | 4.58 | +2.5% |
| constant | p2-compatible | 7 | 180247 | 1 | 72000000 | 180028 | ConstantLayout | 4.53 | 4.35 | -2.7% |
| dirty-null | fix | 7 | 181090 | 1 | 72000000 | 180828 | ConstantLayout | 4.73 | 2.85 | +0.0% |
| dirty-null | p1-compatible | 7 | 181090 | 1 | 72000000 | 180828 | ConstantLayout | 5.96 | 2.92 | +2.3% |
| dirty-null | p2-compatible | 7 | 181090 | 1 | 72000000 | 180828 | ConstantLayout | 6.21 | 2.91 | +2.0% |
| mostly-wide | fix | 7 | 9765818 | 1 | 68402560 | 9765496 | FullZipLayout | 19.18 | 18.71 | +0.0% |
| mostly-wide | p1-compatible | 7 | 9765818 | 1 | 68402560 | 9765496 | FullZipLayout | 18.62 | 18.97 | +1.4% |
| mostly-wide | p2-compatible | 7 | 9766142 | 3 | 22860896 | 3264134 | FullZipLayout | 18.28 | 20.80 | +11.2% |
| mostly-short | fix | 7 | 12349370 | 1 | 84590000 | 12349046 | FullZipLayout | 26.81 | 24.61 | +0.0% |
| mostly-short | p1-compatible | 7 | 12349370 | 1 | 84590000 | 12349046 | FullZipLayout | 28.05 | 23.94 | -2.7% |
| mostly-short | p2-compatible | 7 | 12349694 | 3 | 28211000 | 4118543 | FullZipLayout | 23.20 | 22.57 | -8.3% |
