| Workload | Variant | n | File B | Pages | Max raw B | Max encoded B | Layouts | Write ms | Read ms | Read vs fix |
|---|---|---:|---:|---:|---:|---:|---|---:|---:|---:|
| unique | fix | 1 | 10278014 | 3 | 24120000 | 3443538 | FullZipLayout | 29.47 | 30.64 | +0.0% |
| unique | p1-compatible | 1 | 10278014 | 3 | 24120000 | 3443538 | FullZipLayout | 31.42 | 29.98 | -2.1% |
| unique | p2-compatible | 1 | 10278014 | 3 | 24120000 | 3443538 | FullZipLayout | 28.86 | 31.60 | +3.1% |
| consecutive | fix | 1 | 102754490 | 1 | 720000000 | 102754164 | FullZipLayout | 267.88 | 157.65 | +0.0% |
| consecutive | p1-compatible | 1 | 12607270 | 22 | 32760000 | 720090 | MiniBlockLayout | 14.74 | 45.56 | -71.1% |
| consecutive | p2-compatible | 1 | 12607270 | 22 | 32760000 | 720090 | MiniBlockLayout | 14.84 | 42.91 | -72.8% |
| template | fix | 1 | 10277498 | 1 | 72000000 | 10277143 | FullZipLayout | 24.82 | 21.06 | +0.0% |
| template | p1-compatible | 1 | 10277822 | 3 | 24120000 | 3443146 | FullZipLayout | 21.26 | 21.48 | +2.0% |
| template | p2-compatible | 1 | 10277822 | 3 | 24120000 | 3443146 | FullZipLayout | 19.19 | 22.72 | +7.9% |
| constant | fix | 1 | 180403 | 1 | 72000000 | 180050 | MiniBlockLayout | 4.21 | 3.26 | +0.0% |
| constant | p1-compatible | 1 | 180403 | 1 | 72000000 | 180050 | MiniBlockLayout | 5.72 | 2.80 | -14.2% |
| constant | p2-compatible | 1 | 180403 | 1 | 72000000 | 180050 | MiniBlockLayout | 5.77 | 3.21 | -1.7% |
| dirty-null | fix | 1 | 5108862 | 1 | 72000000 | 5108543 | FullZipLayout | 27.02 | 10.61 | +0.0% |
| dirty-null | p1-compatible | 1 | 5108862 | 1 | 72000000 | 5108543 | FullZipLayout | 30.97 | 10.68 | +0.7% |
| dirty-null | p2-compatible | 1 | 5108862 | 1 | 72000000 | 5108543 | FullZipLayout | 23.46 | 10.18 | -4.0% |
| mostly-wide | fix | 1 | 9765818 | 1 | 68402560 | 9765496 | FullZipLayout | 23.13 | 18.82 | +0.0% |
| mostly-wide | p1-compatible | 1 | 9765818 | 1 | 68402560 | 9765496 | FullZipLayout | 33.73 | 19.23 | +2.2% |
| mostly-wide | p2-compatible | 1 | 9766142 | 3 | 22860896 | 3264134 | FullZipLayout | 19.79 | 21.47 | +14.1% |
| mostly-short | fix | 1 | 12349370 | 1 | 84590000 | 12349046 | FullZipLayout | 31.50 | 24.55 | +0.0% |
| mostly-short | p1-compatible | 1 | 12349370 | 1 | 84590000 | 12349046 | FullZipLayout | 27.18 | 24.74 | +0.8% |
| mostly-short | p2-compatible | 1 | 12349694 | 3 | 28211000 | 4118543 | FullZipLayout | 24.89 | 22.98 | -6.4% |
