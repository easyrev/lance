# Independent control group

Original baseline: `46d7bfdda8ac303d5363c851d6883facb249cb56`.

The user identified the existing remote #7207 pair as a control group and requested a new branch pair for this implementation.

| Role | Branch | Observed commit |
| --- | --- | --- |
| Control pure | `origin/fix/7207-reclaim-lost-commit-indices` | `02d6ed30dc995d9c5420a51ce1d23da89d020bc5` |
| Control review | `origin/review/7207-reclaim-lost-commit-indices` | `297b020bfb582938e2b785a406800f750e9aaf4b` |
| This implementation | `fix/7207-reclaim-lost-commit-indices-option-b` | Initially `35be8cd539d65d28e60d6addc497e543132a960a` |
| This review | `review/7207-reclaim-lost-commit-indices-option-b` | Contains this implementation and review material |

Neither control ref is modified by the Option B work. No control commit is merged or cherry-picked into this implementation.
The histories share the original baseline. The control also merges upstream snapshot `1afd963c16911f1476ba623d5f8037058ec51c2f`.
Therefore measurements from the two histories must identify their source revision and must not be treated as interchangeable.

The control contains its own cleanup implementation and an additional ownership path for newly generated CreateIndexBuilder UUIDs.
This implementation excludes CreateIndex and keeps the narrower scope selected in DESIGN.md.
The tests and lint logs in this review validate only their recorded local implementation commits.
No control-group performance or test result is claimed by this investigation.

The observed control refs and commit metadata are preserved in results/origin-heads-refresh.txt,
results/remote-pure-checkpoint.json, and results/remote-review-checkpoint.json.
