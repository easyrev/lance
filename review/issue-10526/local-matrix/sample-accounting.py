budget = 8 * 1024**2
sample_count = budget // (32 * 1024 + 1) + 1

for workload, rows in [('unique', 400), ('consecutive', 4000), ('template', 400),
                       ('constant', 400), ('dirty-null', 400),
                       ('mostly-wide', 400), ('mostly-short', 2200)]:
    def value(i):
        if workload == 'consecutive':
            return i // 80, 180_000
        if (workload == 'constant'
                or (workload == 'template' and i % 20 == (i // 20) % 20)
                or (workload == 'dirty-null' and i % 2 == 0)):
            return -1, 180_000
        if workload == 'mostly-wide' and i % 20 == 0:
            return i, 128
        if workload == 'mostly-short' and i % 20 != 0:
            return i, 31_000
        return i, 180_000
    physical = {i * rows // sample_count for i in range(sample_count)}
    valid = set(range(rows)) if workload != 'dirty-null' else set(range(2, rows, 2))
    valid = sorted(valid)
    sampled_valid_ranks = min(sample_count, len(valid))
    sampled = physical | {valid[i * len(valid) // sampled_valid_ranks] for i in range(sampled_valid_ranks)}
    physical_bytes = sum(width for _, width in {value(i) for i in sampled})
    full_bytes = sum(width for _, width in {value(i) for i in range(rows)})
    logical_count = len({value(i) for i in valid if i in sampled})
    print(f'{workload:12} sampled={len(sampled):3d} sampled_distinct_bytes={physical_bytes:9d} '
          f'full_distinct_bytes={full_bytes:9d} sampled_valid_distinct={logical_count:3d}')
