# DataFusion join 统计比较与 CollectLeft 选择

保留 bytes 优先、rows 回退、Exact/Inexact get_value 与单侧 collect 分支。实际计划仍取决于具体 join 类型、统计和 optimizer 配置。

来源：Apache DataFusion `datafusion-physical-optimizer 54.1.0`（Apache-2.0）。原路径 `/Users/salamanca/.cargo/registry/src/index.crates.io-1949cf8c6b5b557f/datafusion-physical-optimizer-54.1.0/src/join_selection.rs`；完整原文件 SHA-256：`77f99aa2b07b8d20e2de1c0114bf0eff6b1c7495e1923b8308a123812f044219`。Cargo.lock package checksum 与各段 hash 见 [metadata.json](metadata.json)。下列代码逐字提取；标题中的行号属于原文件。

## 原文件 87–140 行

```rust
pub(crate) fn should_swap_join_order(
    left: &dyn ExecutionPlan,
    right: &dyn ExecutionPlan,
    config: &ConfigOptions,
    registry: Option<&StatisticsRegistry>,
) -> Result<bool> {
    if !config.optimizer.join_reordering {
        return Ok(false);
    }

    let left_stats = get_stats(left, registry)?;
    let right_stats = get_stats(right, registry)?;

    // First compare total_byte_size, then fall back to num_rows if byte
    // sizes are unavailable.
    match (
        left_stats.total_byte_size.get_value(),
        right_stats.total_byte_size.get_value(),
    ) {
        (Some(l), Some(r)) => Ok(l > r),
        _ => match (
            left_stats.num_rows.get_value(),
            right_stats.num_rows.get_value(),
        ) {
            (Some(l), Some(r)) => Ok(l > r),
            _ => Ok(false),
        },
    }
}

fn supports_collect_by_thresholds(
    plan: &dyn ExecutionPlan,
    threshold_byte_size: usize,
    threshold_num_rows: usize,
    registry: Option<&StatisticsRegistry>,
) -> bool {
    let Ok(stats) = get_stats(plan, registry) else {
        return false;
    };

    // Stats use `Precision<T>` to represent stats, where `Absent` means unknown.
    // `Exact(0)` and `Inexact(0)` are both valid stats, and we should not treat
    // them as unknown, `Absent` will return None (this is in regards to why
    // `!=0` is not checked)
    if let Some(byte_size) = stats.total_byte_size.get_value() {
        *byte_size < threshold_byte_size
    } else if let Some(num_rows) = stats.num_rows.get_value() {
        *num_rows < threshold_num_rows
    } else {
        false
    }
}

impl PhysicalOptimizerRule for JoinSelection {
```

## 原文件 199–260 行

```rust
pub(crate) fn try_collect_left(
    hash_join: &HashJoinExec,
    ignore_threshold: bool,
    config: &ConfigOptions,
    registry: Option<&StatisticsRegistry>,
) -> Result<Option<Arc<dyn ExecutionPlan>>> {
    let left = hash_join.left();
    let right = hash_join.right();
    let optimizer_config = &config.optimizer;

    let left_can_collect = ignore_threshold
        || supports_collect_by_thresholds(
            &**left,
            optimizer_config.hash_join_single_partition_threshold,
            optimizer_config.hash_join_single_partition_threshold_rows,
            registry,
        );
    let right_can_collect = ignore_threshold
        || supports_collect_by_thresholds(
            &**right,
            optimizer_config.hash_join_single_partition_threshold,
            optimizer_config.hash_join_single_partition_threshold_rows,
            registry,
        );

    match (left_can_collect, right_can_collect) {
        (true, true) => {
            // Don't swap null-aware anti joins as they have specific side requirements
            if hash_join.join_type().supports_swap()
                && !hash_join.null_aware
                && should_swap_join_order(&**left, &**right, config, registry)?
            {
                Ok(Some(hash_join.swap_inputs(PartitionMode::CollectLeft)?))
            } else {
                Ok(Some(Arc::new(
                    hash_join
                        .builder()
                        .with_partition_mode(PartitionMode::CollectLeft)
                        .build()?,
                )))
            }
        }
        (true, false) => Ok(Some(Arc::new(
            hash_join
                .builder()
                .with_partition_mode(PartitionMode::CollectLeft)
                .build()?,
        ))),
        (false, true) => {
            // Don't swap null-aware anti joins as they have specific side requirements
            if optimizer_config.join_reordering
                && hash_join.join_type().supports_swap()
                && !hash_join.null_aware
            {
                hash_join.swap_inputs(PartitionMode::CollectLeft).map(Some)
            } else {
                Ok(None)
            }
        }
        (false, false) => Ok(None),
    }
}
```
