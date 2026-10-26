# LanceDB optimize ownership path

Lance baseline: `46d7bfdda8ac303d5363c851d6883facb249cb56`.

## lancedb-v0301-binding.rs at f5b21c0aa47238bd20d638bfd30c2784eab80ac5

```rust
655:             Duration::try_milliseconds(ms as i64)
656:         } else {
657:             None
658:         };
659:         future_into_py(self_.py(), async move {
660:             let compaction_stats = inner
661:                 .optimize(OptimizeAction::Compact {
662:                     options: lancedb::table::CompactionOptions::default(),
663:                     remap_options: None,
664:                 })
665:                 .await
666:                 .infer_error()?
667:                 .compaction
668:                 .unwrap();
669:             let prune_stats = inner
```

## lancedb-v0301-optimize.rs at f5b21c0aa47238bd20d638bfd30c2784eab80ac5

```rust
148: pub(crate) async fn compact_files_impl(
149:     table: &NativeTable,
150:     options: CompactionOptions,
151:     remap_options: Option<Arc<dyn IndexRemapperOptions>>,
152: ) -> Result<CompactionMetrics> {
153:     table.dataset.ensure_mutable()?;
154:     let mut dataset = (*table.dataset.get().await?).clone();
155:     let metrics = compact_files(&mut dataset, options, remap_options).await?;
156:     table.dataset.update(dataset);
```

## lancedb-python-binding.rs at 982b2a1229ecbce435ed10a24bd0e54d1228f7ca

```rust
1591:         future_into_py(self_.py(), async move {
1592:             let compaction_stats = inner
1593:                 .optimize(OptimizeAction::Compact {
1594:                     options: lancedb::table::CompactionOptions::default(),
1595:                     remap_options: None,
1596:                 })
1597:                 .await
1598:                 .infer_error()?
1599:                 .compaction
1600:                 .unwrap();
```

## lancedb-optimize.rs at 982b2a1229ecbce435ed10a24bd0e54d1228f7ca

```rust
197: pub(crate) async fn compact_files_impl(
198:     table: &NativeTable,
199:     options: CompactionOptions,
200:     remap_options: Option<Arc<dyn IndexRemapperOptions>>,
201: ) -> Result<CompactionMetrics> {
202:     table.dataset.ensure_mutable()?;
203:     let mut dataset = (*table.dataset.get().await?).clone();
204:     let metrics = compact_files(&mut dataset, options, remap_options).await?;
205:     table.dataset.update(dataset);
```
