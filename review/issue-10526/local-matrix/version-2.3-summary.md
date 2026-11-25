| Workload | Variant | n | File B | Pages | Max raw B | Max encoded B | Layouts | Write ms | Read ms | Read vs fix |
|---|---|---:|---:|---:|---:|---:|---|---:|---:|---:|
| unique | fix | 1 | 10278044 | 3 | 24120000 | 3443538 | PlanarLayout | 21.66 | 21.57 | +0.0% |
| unique | p1-compatible | 1 | 10278044 | 3 | 24120000 | 3443538 | PlanarLayout | 21.06 | 20.91 | -3.1% |
| unique | p2-compatible | 1 | 10278044 | 3 | 24120000 | 3443538 | PlanarLayout | 20.10 | 21.64 | +0.3% |
| consecutive | fix | 1 | 102754500 | 1 | 720000000 | 102754164 | PlanarLayout | 279.42 | 156.72 | +0.0% |
| consecutive | p1-compatible | 1 | 5114083 | 22 | 32760000 | 292293 | PlanarLayout | 16.65 | 45.67 | -70.9% |
| consecutive | p2-compatible | 1 | 5114083 | 22 | 32760000 | 292293 | PlanarLayout | 21.95 | 47.88 | -69.4% |
| template | fix | 1 | 10277508 | 1 | 72000000 | 10277143 | PlanarLayout | 26.59 | 20.97 | +0.0% |
| template | p1-compatible | 1 | 10277852 | 3 | 24120000 | 3443146 | PlanarLayout | 22.13 | 23.08 | +10.1% |
| template | p2-compatible | 1 | 10277852 | 3 | 24120000 | 3443146 | PlanarLayout | 33.72 | 22.51 | +7.4% |
| constant | fix | 1 | 73093 | 1 | 72000000 | 72674 | PlanarLayout | 5.29 | 3.66 | +0.0% |
| constant | p1-compatible | 1 | 73093 | 1 | 72000000 | 72674 | PlanarLayout | 6.74 | 3.56 | -2.5% |
| constant | p2-compatible | 1 | 73093 | 1 | 72000000 | 72674 | PlanarLayout | 6.67 | 3.61 | -1.4% |
| dirty-null | fix | 1 | 5107668 | 1 | 72000000 | 5107339 | PlanarLayout | 64.41 | 12.95 | +0.0% |
| dirty-null | p1-compatible | 1 | 5107668 | 1 | 72000000 | 5107339 | PlanarLayout | 65.13 | 14.44 | +11.5% |
| dirty-null | p2-compatible | 1 | 5107668 | 1 | 72000000 | 5107339 | PlanarLayout | 65.84 | 15.29 | +18.1% |
| mostly-wide | fix | 1 | 9765828 | 1 | 68402560 | 9765496 | PlanarLayout | 26.18 | 19.88 | +0.0% |
| mostly-wide | p1-compatible | 1 | 9765828 | 1 | 68402560 | 9765496 | PlanarLayout | 22.23 | 19.17 | -3.6% |
| mostly-wide | p2-compatible | 1 | 9766172 | 3 | 22860896 | 3264134 | PlanarLayout | 21.41 | 21.05 | +5.9% |
| mostly-short | fix | 1 | 12349380 | 1 | 84590000 | 12349046 | PlanarLayout | 38.12 | 25.31 | +0.0% |
| mostly-short | p1-compatible | 1 | 12349380 | 1 | 84590000 | 12349046 | PlanarLayout | 34.89 | 25.50 | +0.7% |
| mostly-short | p2-compatible | 1 | 12349724 | 3 | 28211000 | 4118543 | PlanarLayout | 29.54 | 22.28 | -12.0% |
