use std::{
    collections::{BTreeMap, BTreeSet},
    mem::MaybeUninit,
    sync::Arc,
    time::Instant,
};

use arrow_array::{Array, LargeBinaryArray, RecordBatch, UInt32Array};
use arrow_buffer::{Buffer, OffsetBuffer};
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

const ROWS: usize = 25_000;
const WIDTH: usize = 180_000;
const TAKE_ROWS: usize = 128;

fn cpu_seconds() -> f64 {
    let mut usage = MaybeUninit::<libc::rusage>::uninit();
    // SAFETY: getrusage initializes the output structure on success.
    let usage = unsafe {
        assert_eq!(libc::getrusage(libc::RUSAGE_SELF, usage.as_mut_ptr()), 0);
        usage.assume_init()
    };
    let seconds = |time: libc::timeval| time.tv_sec as f64 + time.tv_usec as f64 / 1e6;
    seconds(usage.ru_utime) + seconds(usage.ru_stime)
}

#[tokio::main(flavor = "multi_thread", worker_threads = 8)]
async fn main() {
    let start = Instant::now();
    let mut rng = SmallRng::seed_from_u64(10526);
    let pattern: Vec<u8> = (0..4096).map(|_| rng.random::<u8>()).collect();
    let mut payload = vec![0u8; ROWS * WIDTH];
    let mut fingerprint = 0xcbf29ce484222325u64;
    for (index, row) in payload.chunks_exact_mut(WIDTH).enumerate() {
        for chunk in row.chunks_mut(pattern.len()) {
            chunk.copy_from_slice(&pattern[..chunk.len()]);
        }
        row[..8].copy_from_slice(&(index as u64).to_le_bytes());
        for &byte in row.iter() {
            fingerprint ^= u64::from(byte);
            fingerprint = fingerprint.wrapping_mul(0x100000001b3);
        }
    }
    let values = Arc::new(LargeBinaryArray::new(
        OffsetBuffer::from_lengths(std::iter::repeat_n(WIDTH, ROWS)),
        Buffer::from(payload),
        None,
    ));
    let batch = RecordBatch::try_from_iter([("payload", values.clone() as _)]).unwrap();
    eprintln!(
        "pid={} rows={ROWS} width={WIDTH} bytes={} fnv64={fingerprint:016x} generation_s={:.3}",
        std::process::id(),
        ROWS * WIDTH,
        start.elapsed().as_secs_f64()
    );

    let fs = FsFixture::default();
    let schema = Schema::try_from(batch.schema().as_ref()).unwrap();
    let start_cpu = cpu_seconds();
    let start = Instant::now();
    let mut writer = create_writer(
        ConcreteFileVersion::V2_2,
        fs.object_store.create(&fs.tmp_path).await.unwrap(),
        schema,
        FileWriterOptions::default(),
    )
    .unwrap();
    writer.write_batch(&batch).await.unwrap();
    writer.finish().await.unwrap();
    let write_s = start.elapsed().as_secs_f64();
    let write_cpu_s = cpu_seconds() - start_cpu;
    eprintln!(
        "write_s={write_s:.6} write_cpu_s={write_cpu_s:.6} cores={:.4}",
        write_cpu_s / write_s
    );
    drop(batch);
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
    let start = Instant::now();
    let mut stream = reader
        .read_stream(
            ReadBatchParams::RangeFull,
            128,
            4,
            FilterExpression::no_filter(),
        )
        .await
        .unwrap();
    let mut row = 0;
    let mut scan_verify_s = 0.;
    while let Some(batch) = stream.try_next().await.unwrap() {
        let verify_start = Instant::now();
        assert_eq!(
            batch.column(0).as_ref(),
            &values.slice(row, batch.num_rows()) as &dyn Array
        );
        scan_verify_s += verify_start.elapsed().as_secs_f64();
        row += batch.num_rows();
    }
    assert_eq!(row, ROWS);
    let scan_s = start.elapsed().as_secs_f64();
    eprintln!("scan_s={scan_s:.6} scan_verify_s={scan_verify_s:.6}");

    let mut rows = BTreeSet::new();
    while rows.len() < TAKE_ROWS {
        rows.insert(rng.random_range(0..ROWS) as u32);
    }
    let rows: Vec<_> = rows.into_iter().collect();
    let start = Instant::now();
    let mut stream = reader
        .read_stream(
            ReadBatchParams::Indices(UInt32Array::from(rows.clone())),
            32,
            4,
            FilterExpression::no_filter(),
        )
        .await
        .unwrap();
    let mut index = 0;
    let mut take_verify_s = 0.;
    while let Some(batch) = stream.try_next().await.unwrap() {
        let verify_start = Instant::now();
        let read = batch
            .column(0)
            .as_any()
            .downcast_ref::<LargeBinaryArray>()
            .unwrap();
        for local in 0..read.len() {
            assert_eq!(read.value(local), values.value(rows[index] as usize));
            index += 1;
        }
        take_verify_s += verify_start.elapsed().as_secs_f64();
    }
    assert_eq!(index, TAKE_ROWS);
    let take_s = start.elapsed().as_secs_f64();

    let metadata = reader.metadata();
    let pages = &metadata.column_metadatas[0].pages;
    let mut raw_max = 0;
    let mut encoded_max = 0;
    let mut page_rows = Vec::new();
    let mut layouts = BTreeMap::new();
    for page in pages {
        *layouts.entry(describe_encoding(page)).or_insert(0) += 1;
        raw_max = raw_max.max(page.length * WIDTH as u64);
        encoded_max = encoded_max.max(page.buffer_sizes.iter().sum::<u64>());
        page_rows.push(page.length);
    }
    assert_eq!(page_rows.iter().sum::<u64>(), ROWS as u64);
    println!(
        "2.2\t{fingerprint:016x}\t{}\t{}\t{raw_max}\t{encoded_max}\t{write_s:.6}\t{write_cpu_s:.6}\t{:.4}\t{scan_s:.6}\t{scan_verify_s:.6}\t{take_s:.6}\t{take_verify_s:.6}\t{page_rows:?}\t{layouts:?}\t{rows:?}",
        metadata.file_size(),
        pages.len(),
        write_cpu_s / write_s
    );
}
