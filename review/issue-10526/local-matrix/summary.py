import csv, re, statistics, sys
from collections import defaultdict

data = defaultdict(list)
for path in sys.argv[1:]:
    with open(path) as f:
        for row in csv.DictReader(f, delimiter='\t'):
            data[row['workload'], row['variant']].append(row)

print('| Workload | Variant | n | File B | Pages | Max raw B | Max encoded B | Layouts | Write ms | Read ms | Read vs fix |')
print('|---|---|---:|---:|---:|---:|---:|---|---:|---:|---:|')
for (workload, variant), rows in data.items():
    def med(rows, key):
        return statistics.median(float(row[key]) for row in rows)
    first = rows[0]
    for key in ('file_bytes', 'pages', 'max_raw_bytes', 'max_encoded_bytes', 'page_rows', 'layouts'):
        assert all(row[key] == first[key] for row in rows), (workload, variant, key)
    layouts = ', '.join(sorted(set(re.findall(r'layout: (?:Some\(\s*)?(\w+)\(', first["layouts"].replace(r"\n", " ")))))
    if not layouts and "PlanarLayout {" in first["layouts"]:
        layouts = "PlanarLayout"
    read = med(rows, 'read_ms')
    fix = med(data[workload, 'fix'], 'read_ms')
    print(f"| {workload} | {variant} | {len(rows)} | {first['file_bytes']} | {first['pages']} | {first['max_raw_bytes']} | {first['max_encoded_bytes']} | {layouts} | {med(rows, 'write_ms'):.2f} | {read:.2f} | {((read/fix)-1)*100:+.1f}% |")
