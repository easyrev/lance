# Lance Take 地址分组与输出顺序

这段代码只支持每次 Take 的地址排序、按 fragment 分组和结果重排说明；它不能证明多个独立 Take 调用已经合并、缓存复用或对象存储请求数量。

来源：[固定基线 take.rs](https://github.com/lance-format/lance/blob/0a0d327082988018a25f56147d3b6d02f6c79ecc/rust/lance/src/dataset/take.rs#L284-L345)。从本地 Git 对象提取，完整原文件 SHA-256 已与 freeze 的 U source_hashes 相等：`78048f2e623356aaac861eaa0697d96d7d6a5b2a9fe79e6b3fe83b2638a87e0a`。Git blob：`7defe769b8e225975a6a34b32039b9b073f4e6cf`。

## 原文件 284–345 行

```rust
    } else {
        // Slow case: need to re-map data into expected order
        let mut sorted_row_addrs = row_addrs.clone();
        sorted_row_addrs.sort();
        // Go ahead and dedup, we will reinsert duplicates during the remapping
        sorted_row_addrs.dedup();
        // Group ROW Ids by the fragment
        let mut row_addrs_per_fragment: BTreeMap<u32, Vec<u32>> = BTreeMap::new();
        sorted_row_addrs.iter().for_each(|row_addr| {
            let row_addr = RowAddress::from(*row_addr);
            let fragment_id = row_addr.fragment_id();
            let offset = row_addr.row_offset();
            row_addrs_per_fragment
                .entry(fragment_id)
                .and_modify(|v| v.push(offset))
                .or_insert_with(|| vec![offset]);
        });

        let addressed_ids: Vec<u32> = row_addrs_per_fragment.keys().copied().collect();
        let fragments = builder
            .dataset
            .get_existing_fragments_from_ids(&addressed_ids);
        let fragment_and_indices = fragments.into_iter().filter_map(|f| {
            let row_offset = row_addrs_per_fragment.remove(&(f.id() as u32))?;
            Some((f, row_offset))
        });

        let mut batches = futures::stream::iter(fragment_and_indices)
            .map(|(fragment, indices)| {
                do_take(
                    fragment,
                    indices,
                    physical_schema.clone(),
                    with_row_id_in_projection,
                    true,
                    with_row_created_at_version_in_projection,
                    with_row_last_updated_at_version_in_projection,
                )
            })
            .buffered(builder.dataset.object_store.io_parallelism())
            .try_collect::<Vec<_>>()
            .await?;
        let one_batch = if batches.len() > 1 {
            concat_batches(&batches[0].schema(), &batches)?
        } else {
            batches.pop().unwrap()
        };
        // Note: one_batch may contains fewer rows than the number of requested
        // row ids because some rows may have been deleted. Because of this, we
        // get the results with row ids so that we can re-order the results
        // to match the requested order.

        let returned_row_addr = one_batch
            .column_by_name(ROW_ADDR)
            .ok_or_else(|| Error::internal("_rowaddr column not found"))?
            .as_primitive::<UInt64Type>()
            .values();

        let addr_to_pos: HashMap<u64, u64> = returned_row_addr
            .iter()
            .enumerate()
            .map(|(i, addr)| (*addr, i as u64))
```
