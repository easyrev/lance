# DataFusion HashJoin build 分配

这些片段显示逐批保留、hash table 和 bitmap 的 reservation，以及批次拼接。try_grow 的错误通过 ? 传播；片段不声称所有数组分配均计入 pool。

来源：Apache DataFusion `datafusion-physical-plan 54.1.0`（Apache-2.0）。原路径 `/Users/salamanca/.cargo/registry/src/index.crates.io-1949cf8c6b5b557f/datafusion-physical-plan-54.1.0/src/joins/hash_join/exec.rs`；完整原文件 SHA-256：`873049b64f3d45b5bc9b1a2b152bf7aec7b453fe6d495414f69b818c86768dd9`。Cargo.lock package checksum 与各段 hash 见 [metadata.json](metadata.json)。下列代码逐字提取；标题中的行号属于原文件。

## 原文件 1907–1930 行

```rust
    let state = left_stream
        .try_fold(initial, |mut state, batch| async move {
            // Update accumulators if computing bounds
            if let Some(ref mut accumulators) = state.bounds_accumulators {
                for accumulator in accumulators {
                    accumulator.update_batch(&batch)?;
                }
            }

            // Decide if we spill or not
            let batch_size = get_record_batch_memory_size(&batch);
            // Reserve memory for incoming batch
            state.reservation.try_grow(batch_size)?;
            // Update metrics
            state.metrics.build_mem_used.add(batch_size);
            state.metrics.build_input_batches.add(1);
            state.metrics.build_input_rows.add(batch.num_rows());
            // Update row count
            state.num_rows += batch.num_rows();
            // Push batch to output
            state.batches.push(batch);
            Ok(state)
        })
        .await?;
```

## 原文件 1974–1989 行

```rust
            // Use `u32` indices for the JoinHashMap when num_rows ≤ u32::MAX, otherwise use the
            // `u64` indice variant
            // Arc is used instead of Box to allow sharing with SharedBuildAccumulator for hash map pushdown
            let mut hashmap: Box<dyn JoinHashMapType> = if num_rows > u32::MAX as usize {
                let estimated_hashtable_size =
                    estimate_memory_size::<(u64, u64)>(num_rows, fixed_size_u64)?;
                reservation.try_grow(estimated_hashtable_size)?;
                metrics.build_mem_used.add(estimated_hashtable_size);
                Box::new(JoinHashMapU64::with_capacity(num_rows))
            } else {
                let estimated_hashtable_size =
                    estimate_memory_size::<(u32, u64)>(num_rows, fixed_size_u32)?;
                reservation.try_grow(estimated_hashtable_size)?;
                metrics.build_mem_used.add(estimated_hashtable_size);
                Box::new(JoinHashMapU32::with_capacity(num_rows))
            };
```

## 原文件 2013–2025 行

```rust
            // Merge all batches into a single batch, so we can directly index into the arrays
            let batch = concat_batches(&schema, batches_iter.clone())?;

            let left_values = evaluate_expressions_to_arrays(&on_left, &batch)?;

            (Map::HashMap(hashmap), batch, left_values)
        };

    // Reserve additional memory for visited indices bitmap and create shared builder
    let visited_indices_bitmap = if with_visited_indices_bitmap {
        let bitmap_size = bit_util::ceil(batch.num_rows(), 8);
        reservation.try_grow(bitmap_size)?;
        metrics.build_mem_used.add(bitmap_size);
```
