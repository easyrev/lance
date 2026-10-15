# Preserved implementation evidence

The twelve files listed below are byte-identical copies from the implementation task's local evidence directory.
This index was added during publication. Original logs lack embedded source hashes.
Current explanations live in [the reports](../README.md); historical wording in copied notes describes their original stage.

| File | Role and stage |
| --- | --- |
| [design.md](design.md) | Original design and validation notes; contains the implementation-stage summary |
| [review-description.md](review-description.md) | Original proposed PR description; no PR was submitted |
| [resource-diagnostic.jsonl](resource-diagnostic.jsonl) | Six debug diagnostic runs; no historical baseline or build fingerprint |
| [clippy-final.log](clippy-final.log) | Full workspace Clippy after final input-batching changes |
| [final-resource-tests.log](final-resource-tests.log) | Final builder, scheduler, and dataset resource filters |
| [final-shuffler-tests.log](final-shuffler-tests.log) | Final 56-case shuffler module run |
| [wide-input-tests.log](wide-input-tests.log) | Final fixed-vector and multivector input cases |
| [storage-tests.log](storage-tests.log) | Earlier two-case source-ownership run |
| [default-regressions.log](default-regressions.log) | Earlier default-path regressions; includes a zero-test filter and a superseded resource case |
| [builder-tests.log](builder-tests.log) | Earlier 28-case builder run, superseded by the final 29-case run |
| [input-batch-regressions.log](input-batch-regressions.log) | Intermediate builder and partition-adjustment checks |
| [clippy.log](clippy.log) | Earlier Clippy run, superseded by `clippy-final.log` |

The original notes also report spill and metadata test results whose raw outputs were not retained here.
See [validation provenance](../reports/validation-report.md) before citing those results.
