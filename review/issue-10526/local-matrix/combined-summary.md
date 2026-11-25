| Workload | Variant | n | File B | Pages | Max raw B | Max encoded B | Layouts | Write ms | Read ms | Read vs fix |
|---|---|---:|---:|---:|---:|---:|---|---:|---:|---:|
| unique | fix | 7 | 10278014 | 3 | 24120000 | 3443538 | FullZipLayout | 20.39 | 21.26 | +0.0% |
| unique | p1-compatible | 7 | 10278014 | 3 | 24120000 | 3443538 | FullZipLayout | 19.76 | 21.31 | +0.2% |
| unique | p2-compatible | 7 | 10278014 | 3 | 24120000 | 3443538 | FullZipLayout | 19.38 | 21.25 | -0.0% |
| consecutive | fix | 7 | 102754490 | 1 | 720000000 | 102754164 | FullZipLayout | 266.21 | 151.85 | +0.0% |
| consecutive | p1-compatible | 7 | 5113907 | 22 | 32760000 | 292293 | MiniBlockLayout | 15.14 | 45.07 | -70.3% |
| consecutive | p2-compatible | 7 | 5113907 | 22 | 32760000 | 292293 | MiniBlockLayout | 16.23 | 45.38 | -70.1% |
| template | fix | 22 | 10277498 | 1 | 72000000 | 10277143 | FullZipLayout | 20.11 | 20.52 | +0.0% |
| template | p1-compatible | 22 | 10277822 | 3 | 24120000 | 3443146 | FullZipLayout | 19.09 | 21.49 | +4.7% |
| template | p2-compatible | 22 | 10277822 | 3 | 24120000 | 3443146 | FullZipLayout | 19.09 | 21.69 | +5.7% |
| constant | fix | 7 | 180247 | 1 | 72000000 | 180028 | ConstantLayout | 3.15 | 4.47 | +0.0% |
| constant | p1-compatible | 7 | 180247 | 1 | 72000000 | 180028 | ConstantLayout | 4.59 | 4.58 | +2.5% |
| constant | p2-compatible | 7 | 180247 | 1 | 72000000 | 180028 | ConstantLayout | 4.53 | 4.35 | -2.7% |
| dirty-null | fix | 7 | 181090 | 1 | 72000000 | 180828 | ConstantLayout | 4.73 | 2.85 | +0.0% |
| dirty-null | p1-compatible | 7 | 181090 | 1 | 72000000 | 180828 | ConstantLayout | 5.96 | 2.92 | +2.3% |
| dirty-null | p2-compatible | 7 | 181090 | 1 | 72000000 | 180828 | ConstantLayout | 6.21 | 2.91 | +2.0% |
| mostly-wide | fix | 22 | 9765818 | 1 | 68402560 | 9765496 | FullZipLayout | 21.60 | 19.34 | +0.0% |
| mostly-wide | p1-compatible | 22 | 9765818 | 1 | 68402560 | 9765496 | FullZipLayout | 20.12 | 19.26 | -0.4% |
| mostly-wide | p2-compatible | 22 | 9766142 | 3 | 22860896 | 3264134 | FullZipLayout | 19.23 | 20.94 | +8.3% |
| mostly-short | fix | 22 | 12349370 | 1 | 84590000 | 12349046 | FullZipLayout | 28.64 | 24.74 | +0.0% |
| mostly-short | p1-compatible | 22 | 12349370 | 1 | 84590000 | 12349046 | FullZipLayout | 28.08 | 24.39 | -1.4% |
| mostly-short | p2-compatible | 22 | 12349694 | 3 | 28211000 | 4118543 | FullZipLayout | 24.28 | 22.76 | -8.0% |
