use std::{collections::BTreeMap, sync::Arc, time::Instant};

use arrow_array::{Array, LargeStringArray, RecordBatch, builder::LargeStringBuilder};
use arrow_buffer::NullBuffer;
use futures::TryStreamExt;
use lance_core::{cache::LanceCache, datatypes::Schema};
use lance_encoding::decoder::{DecoderPlugins, FilterExpression};
use lance_file::{
    reader::{FileReader, FileReaderOptions, describe_encoding},
    testing::FsFixture,
    version::ConcreteFileVersion,
    versions::create_writer,
    writer::FileWriterOptions,
};
use lance_io::{ReadBatchParams, utils::CachedFileSize};
use rand::{Rng, SeedableRng, rngs::SmallRng};

const WIDE: usize = 180_000;

fn payload(rng: &mut SmallRng, row: usize, width: usize) -> String {
    let mut value = format!(r#"{{"row":{row:06},"message":""#);
    let words = [
        "winter ", "cloud ", "service ", "orange ", "render ", "ocean ", "east ", "stage ",
    ];
    while value.len() + 10 < width {
        value.push_str(words[rng.random_range(0..words.len())]);
    }
    value.push_str(&" ".repeat(width - value.len() - 2));
    value.push_str("\"}");
    value
}

fn input(kind: &str) -> RecordBatch {
    let rows = match kind {
        "consecutive" => 4_000,
        "mostly-short" => 2_200,
        _ => 400,
    };
    let mut rng = SmallRng::seed_from_u64(10526);
    let mut b = LargeStringBuilder::with_capacity(rows, rows * WIDE);
    let template = payload(&mut rng, 999_999, WIDE);
    let mut repeated = String::new();
    for row in 0..rows {
        match kind {
            "consecutive" => {
                if row % 80 == 0 {
                    repeated = payload(&mut rng, row, WIDE);
                }
                b.append_value(&repeated);
            }
            "constant" => b.append_value(&template),
            "dirty-null" if row % 2 != 0 || row == 0 => {
                if row == 0 {
                    b.append_value(&template);
                } else {
                    b.append_value(payload(&mut rng, row, WIDE));
                }
            }
            "dirty-null" => b.append_value(&template),
            "template" if row % 20 == (row / 20) % 20 => b.append_value(&template),
            "mostly-wide" if row % 20 == 0 => b.append_value(payload(&mut rng, row, 128)),
            "mostly-short" if row % 20 != 0 => b.append_value(payload(&mut rng, row, 31_000)),
            _ => b.append_value(payload(&mut rng, row, WIDE)),
        }
    }
    let strings = b.finish();
    let strings = if kind == "dirty-null" {
        let (offsets, bytes, _) = strings.into_parts();
        LargeStringArray::new(
            offsets,
            bytes,
            Some(NullBuffer::from(
                (0..rows).map(|i| i != 0 && i % 2 == 0).collect::<Vec<_>>(),
            )),
        )
    } else {
        strings
    };
    RecordBatch::try_from_iter([("payload", Arc::new(strings) as _)]).unwrap()
}

#[tokio::main(flavor = "multi_thread", worker_threads = 8)]
async fn main() {
    let args: Vec<_> = std::env::args().collect();
    let kind = &args[1];
    let version = match args[2].as_str() {
        "2.1" => ConcreteFileVersion::V2_1,
        "2.2" => ConcreteFileVersion::V2_2,
        "2.3" => ConcreteFileVersion::V2_3,
        _ => panic!("unknown version"),
    };
    let batch = input(kind);
    let values = batch
        .column(0)
        .as_any()
        .downcast_ref::<LargeStringArray>()
        .unwrap();
    let options = FileWriterOptions::default();
    for trial in 0..args[3].parse::<usize>().unwrap() {
        let fs = FsFixture::default();
        let schema = Schema::try_from(batch.schema().as_ref()).unwrap();
        let start = Instant::now();
        let mut writer = create_writer(
            version,
            fs.object_store.create(&fs.tmp_path).await.unwrap(),
            schema,
            options.clone(),
        )
        .unwrap();
        writer.write_batch(&batch).await.unwrap();
        writer.finish().await.unwrap();
        let write_ms = start.elapsed().as_secs_f64() * 1000.0;

        let start = Instant::now();
        let scheduler = fs
            .scheduler
            .open_file(&fs.tmp_path, &CachedFileSize::unknown())
            .await
            .unwrap();
        let reader = FileReader::try_open(
            scheduler,
            None,
            Arc::<DecoderPlugins>::default(),
            &LanceCache::no_cache(),
            FileReaderOptions::default(),
        )
        .await
        .unwrap();
        let batches: Vec<RecordBatch> = reader
            .read_stream(
                ReadBatchParams::RangeFull,
                128,
                4,
                FilterExpression::no_filter(),
            )
            .await
            .unwrap()
            .try_collect()
            .await
            .unwrap();
        let read_ms = start.elapsed().as_secs_f64() * 1000.0;
        let mut offset = 0;
        for read in batches {
            assert_eq!(
                read.column(0),
                &batch.column(0).slice(offset, read.num_rows())
            );
            offset += read.num_rows();
        }
        assert_eq!(offset, batch.num_rows());

        let metadata = reader.metadata();
        let pages = &metadata.column_metadatas[0].pages;
        let mut layouts = BTreeMap::new();
        let mut offset = 0;
        let mut raw_max = 0;
        let mut encoded_max = 0;
        let mut page_rows = Vec::new();
        for page in pages {
            let description = describe_encoding(page);
            *layouts.entry(description).or_insert(0) += 1;
            let next = offset + page.length as usize;
            raw_max = raw_max.max(values.value_offsets()[next] - values.value_offsets()[offset]);
            encoded_max = encoded_max.max(page.buffer_sizes.iter().sum::<u64>());
            page_rows.push(page.length);
            offset = next;
        }
        assert_eq!(offset, batch.num_rows());
        println!(
            "{}\t{}\t{}\t{}\t{}\t{}\t{}\t{write_ms:.3}\t{read_ms:.3}\t{:?}\t{:?}",
            args[2],
            kind,
            trial,
            metadata.file_size(),
            pages.len(),
            raw_max,
            encoded_max,
            page_rows,
            layouts
        );
    }
}
