# DataFusion RoundRobin batch 分派

该分支把整个输入 RecordBatch 送往一个输出 partition。它不把单批按行切成 num_partitions 份；不能据此推论多批输入或 Hash repartition 没有并行收益。

来源：Apache DataFusion `datafusion-physical-plan 54.1.0`（Apache-2.0）。原路径 `/Users/salamanca/.cargo/registry/src/index.crates.io-1949cf8c6b5b557f/datafusion-physical-plan-54.1.0/src/repartition/mod.rs`；完整原文件 SHA-256：`d8a7a1039ddf8a6b6479322e61ad787b7c763a71fc408773306cb23cc5125bbb`。Cargo.lock package checksum 与各段 hash 见 [metadata.json](metadata.json)。下列代码逐字提取；标题中的行号属于原文件。

## 原文件 779–791 行

```rust
    pub fn partition_iter(
        &mut self,
        batch: RecordBatch,
    ) -> Result<impl Iterator<Item = Result<(usize, RecordBatch)>> + Send + '_> {
        let it: Box<dyn Iterator<Item = Result<(usize, RecordBatch)>> + Send> =
            match &mut self.state {
                BatchPartitionerState::RoundRobin {
                    num_partitions,
                    next_idx,
                } => {
                    let idx = *next_idx;
                    *next_idx = (*next_idx + 1) % *num_partitions;
                    Box::new(std::iter::once(Ok((idx, batch))))
```
