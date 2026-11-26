// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: Copyright The Lance Authors

use std::{any::Any, collections::VecDeque, ops::Range, sync::Arc};

use arrow_array::{Array, ArrayRef, new_empty_array, new_null_array};
use arrow_buffer::ScalarBuffer;
use arrow_schema::DataType;
use bytes::Bytes;
use futures::FutureExt;
use futures::future::BoxFuture;

use lance_core::{
    Error, Result,
    cache::{Context, DeepSizeOf},
    utils::tokio::spawn_cpu,
};

use crate::{
    EncodingsIo,
    buffer::LanceBuffer,
    compression::VariableWidthOffsets,
    decoder::{PageEncoding, VariablePageDecodePlan},
    encoder::EncodedPage,
    encodings::logical::primitive::{
        CachedPageData, PageInitialization, PageInitializationBuffers, PageLoadTask,
    },
    format::EncodingUtils,
    repdef::{DefinitionInterpretation, RepDefUnraveler, max_visible_level},
};

pub(crate) fn encode_constant_page(
    column_idx: u32,
    scalar: ArrayRef,
    repdef: crate::repdef::SerializedRepDefs,
    row_number: u64,
    num_rows: u64,
) -> Result<EncodedPage> {
    let inline_value = lance_arrow::scalar::try_inline_value(&scalar);
    let value_buffer = if inline_value.is_some() {
        None
    } else {
        Some(LanceBuffer::from(
            lance_arrow::scalar::encode_scalar_value_buffer(&scalar)?,
        ))
    };

    let description = EncodingUtils::constant_layout(&repdef.def_meaning, inline_value);

    let has_repdef = repdef.repetition_levels.is_some() || repdef.definition_levels.is_some();

    let data = if !has_repdef {
        value_buffer.into_iter().collect::<Vec<_>>()
    } else {
        let rep_bytes = repdef
            .repetition_levels
            .as_ref()
            .map(|rep| LanceBuffer::reinterpret_slice(rep.clone()))
            .unwrap_or_else(LanceBuffer::empty);
        let def_bytes = repdef
            .definition_levels
            .as_ref()
            .map(|def| LanceBuffer::reinterpret_slice(def.clone()))
            .unwrap_or_else(LanceBuffer::empty);

        match value_buffer {
            Some(value_buffer) => vec![value_buffer, rep_bytes, def_bytes],
            None => vec![rep_bytes, def_bytes],
        }
    };

    Ok(EncodedPage {
        column_idx,
        data,
        description: PageEncoding::Structural(description),
        num_rows,
        row_number,
    })
}

#[derive(Debug)]
struct CachedConstantState {
    scalar: ArrayRef,
    rep: Option<ScalarBuffer<u16>>,
    def: Option<ScalarBuffer<u16>>,
}

impl DeepSizeOf for CachedConstantState {
    fn deep_size_of_children(&self, _ctx: &mut Context) -> usize {
        self.scalar.get_buffer_memory_size()
            + self.rep.as_ref().map(|buf| buf.len() * 2).unwrap_or(0)
            + self.def.as_ref().map(|buf| buf.len() * 2).unwrap_or(0)
    }
}

impl CachedPageData for CachedConstantState {
    fn as_arc_any(self: Arc<Self>) -> Arc<dyn Any + Send + Sync + 'static> {
        self
    }
}

#[derive(Debug, Clone)]
enum ScalarSource {
    Inline(Vec<u8>),
    ValueBuffer(usize),
}

/// The (scalar, rep, def) file ranges a constant page reads, in the order
/// `init_layout` declares and `init_from_buffers` consumes them.  Any field is
/// `None` when that buffer is absent. Computed once at construction so the two
/// halves share one source of truth and their buffer order cannot drift.
#[derive(Debug)]
struct ConstantBufferLayout {
    scalar: Option<Range<u64>>,
    rep: Option<Range<u64>>,
    def: Option<Range<u64>>,
}

#[derive(Debug)]
pub struct ConstantPageScheduler {
    pub(super) structural_projection: Option<super::structure::StructuralProjection>,
    scalar_source: ScalarSource,
    data_type: DataType,
    def_meaning: Arc<[DefinitionInterpretation]>,
    max_rep: u16,
    max_visible_def: u16,
    layout: ConstantBufferLayout,
    repdef: Option<Arc<CachedConstantState>>,
}

impl ConstantPageScheduler {
    pub fn try_new(
        buffer_offsets_and_sizes: Arc<[(u64, u64)]>,
        inline_value: Option<Bytes>,
        data_type: DataType,
        def_meaning: Arc<[DefinitionInterpretation]>,
    ) -> Result<Self> {
        let max_rep = def_meaning.iter().filter(|d| d.is_list()).count() as u16;
        let max_visible_def = max_visible_level(&def_meaning);

        let (scalar_source, rep_buf_idx, def_buf_idx) =
            match (inline_value, buffer_offsets_and_sizes.len()) {
                (Some(inline), 0) => (ScalarSource::Inline(inline.to_vec()), None, None),
                (Some(inline), 2) => (ScalarSource::Inline(inline.to_vec()), Some(0), Some(1)),
                (None, 1) => (ScalarSource::ValueBuffer(0), None, None),
                (None, 3) => (ScalarSource::ValueBuffer(0), Some(1), Some(2)),
                (Some(_inline), 1) => {
                    return Err(Error::invalid_input(format!(
                        "Invalid constant layout: inline_value present with {} buffers",
                        1
                    )));
                }
                (Some(_inline), 3) => {
                    return Err(Error::invalid_input(
                        "Invalid constant layout: inline_value present with 3 buffers",
                    ));
                }
                (None, 0) => {
                    return Err(Error::invalid_input(
                        "Invalid constant layout: missing scalar source",
                    ));
                }
                (None, 2) => {
                    return Err(Error::invalid_input(
                        "Invalid constant layout: ambiguous (2 buffers and no inline_value)",
                    ));
                }
                (Some(_), n) => {
                    return Err(Error::invalid_input(format!(
                        "Invalid constant layout: inline_value present with {} buffers",
                        n
                    )));
                }
                (None, n) => {
                    return Err(Error::invalid_input(format!(
                        "Invalid constant layout: unexpected buffer count {}",
                        n
                    )));
                }
            };

        let range_of = |idx: usize| {
            let (pos, len) = buffer_offsets_and_sizes[idx];
            pos..pos + len
        };
        let layout = ConstantBufferLayout {
            scalar: match &scalar_source {
                ScalarSource::ValueBuffer(idx) => Some(range_of(*idx)),
                ScalarSource::Inline(_) => None,
            },
            rep: rep_buf_idx
                .filter(|&idx| buffer_offsets_and_sizes[idx].1 > 0)
                .map(range_of),
            def: def_buf_idx
                .filter(|&idx| buffer_offsets_and_sizes[idx].1 > 0)
                .map(range_of),
        };

        Ok(Self {
            scalar_source,
            structural_projection: None,
            data_type,
            def_meaning,
            max_rep,
            max_visible_def,
            layout,
            repdef: None,
        })
    }
}

impl crate::encodings::logical::primitive::StructuralPageScheduler for ConstantPageScheduler {
    fn init_layout(&self) -> Result<PageInitialization> {
        // Order must match `init_from_buffers`' consumption: scalar, rep, def.
        Ok(PageInitialization::new([
            self.layout
                .scalar
                .clone()
                .filter(|_| self.structural_projection.is_none()),
            self.layout.rep.clone(),
            self.layout.def.clone(),
        ]))
    }

    fn init_from_buffers<'a>(
        &'a mut self,
        buffers: PageInitializationBuffers,
        _io: &Arc<dyn EncodingsIo>,
    ) -> BoxFuture<'a, Result<Arc<dyn CachedPageData>>> {
        // Consume `buffers` in the same scalar, rep, def order `init_layout`
        // declared them, using the shared layout's presence flags.
        let scalar_source = self.scalar_source.clone();
        let data_type = self.data_type.clone();
        let structural_projection = self.structural_projection.clone();
        async move {
            let [scalar_buffer, rep_buffer, def_buffer] = buffers.try_into_array("constant")?;

            let scalar = if let Some(projection) = structural_projection {
                arrow_array::make_array(
                    projection
                        .placeholder_values(1)?
                        .into_arrow(data_type, true)?,
                )
            } else {
                match (scalar_source, scalar_buffer) {
                    (ScalarSource::Inline(inline), None) => {
                        lance_arrow::scalar::decode_scalar_from_inline_value(&data_type, &inline)?
                    }
                    (ScalarSource::ValueBuffer(_), Some(bytes)) => {
                        // Copying wide scalars into compact Arrow buffers releases any larger
                        // coalesced page-init `Bytes` slice (which may pin neighboring compressed
                        // pages in `LanceCache`) while running UTF-8 validation off the tokio I/O
                        // thread concurrently across `FuturesOrdered` initializations.
                        const CONSTANT_SCALAR_SPAWN_CPU_THRESHOLD_BYTES: usize = 32 * 1024;
                        let buf = LanceBuffer::from_bytes(bytes, 1);
                        if buf.len() >= CONSTANT_SCALAR_SPAWN_CPU_THRESHOLD_BYTES {
                            let dt = data_type.clone();
                            spawn_cpu(move || {
                                lance_arrow::scalar::decode_scalar_from_value_buffer(
                                    &dt,
                                    buf.as_ref(),
                                )
                            })
                            .await?
                        } else {
                            lance_arrow::scalar::decode_scalar_from_value_buffer(
                                &data_type,
                                buf.as_ref(),
                            )?
                        }
                    }
                    _ => {
                        return Err(Error::internal(
                            "Constant page scalar buffer does not match its initialization layout",
                        ));
                    }
                }
            };

            let rep = rep_buffer.map(|rep| {
                let rep = LanceBuffer::from_bytes(rep, 2);
                rep.borrow_to_typed_slice::<u16>()
            });

            let def = def_buffer.map(|def| {
                let def = LanceBuffer::from_bytes(def, 2);
                def.borrow_to_typed_slice::<u16>()
            });

            let cached = Arc::new(CachedConstantState { scalar, rep, def });
            Ok(cached as Arc<dyn CachedPageData>)
        }
        .boxed()
    }

    fn try_load(&mut self, data: &Arc<dyn CachedPageData>) -> Result<()> {
        let cached: Arc<CachedConstantState> =
            data.clone().as_arc_any().downcast().map_err(|_| {
                Error::invalid_input_source(
                    "Cached constant page data has an unexpected type".into(),
                )
            })?;
        if cached.scalar.data_type() != &self.data_type {
            return Err(Error::invalid_input_source(
                format!(
                    "Cached constant page scalar has data type {:?}, expected {:?}",
                    cached.scalar.data_type(),
                    self.data_type
                )
                .into(),
            ));
        }
        self.repdef = Some(cached);
        Ok(())
    }

    fn schedule_ranges(
        &self,
        ranges: &[Range<u64>],
        _io: &Arc<dyn EncodingsIo>,
    ) -> Result<Vec<PageLoadTask>> {
        let num_rows = ranges.iter().map(|r| r.end - r.start).sum::<u64>();
        let decoder = Box::new(ConstantPageDecoder {
            ranges: VecDeque::from_iter(ranges.iter().cloned()),
            scalar: self.repdef.as_ref().unwrap().scalar.clone(),
            rep: self.repdef.as_ref().unwrap().rep.clone(),
            def: self.repdef.as_ref().unwrap().def.clone(),
            def_meaning: self.def_meaning.clone(),
            max_rep: self.max_rep,
            max_visible_def: self.max_visible_def,
            cursor_row: 0,
            cursor_level: 0,
            num_rows,
        })
            as Box<dyn crate::encodings::logical::primitive::StructuralPageDecoder>;
        Ok(vec![PageLoadTask {
            decoder_fut: std::future::ready(Ok(decoder)).boxed(),
            num_rows,
        }])
    }
}

#[derive(Debug)]
struct ConstantPageDecoder {
    ranges: VecDeque<Range<u64>>,
    scalar: ArrayRef,
    rep: Option<ScalarBuffer<u16>>,
    def: Option<ScalarBuffer<u16>>,
    def_meaning: Arc<[DefinitionInterpretation]>,
    max_rep: u16,
    max_visible_def: u16,
    cursor_row: u64,
    cursor_level: usize,
    num_rows: u64,
}

impl ConstantPageDecoder {
    fn drain_ranges(&mut self, num_rows: u64) -> Vec<Range<u64>> {
        let mut rows_desired = num_rows;
        let mut ranges = Vec::with_capacity(self.ranges.len());
        while rows_desired > 0 {
            let front = self.ranges.front_mut().unwrap();
            let avail = front.end - front.start;
            if avail > rows_desired {
                ranges.push(front.start..front.start + rows_desired);
                front.start += rows_desired;
                rows_desired = 0;
            } else {
                ranges.push(self.ranges.pop_front().unwrap());
                rows_desired -= avail;
            }
        }
        ranges
    }

    fn take_row(&mut self) -> Result<()> {
        let start = self.cursor_level;
        let end = if let Some(rep) = &self.rep {
            if start >= rep.len() {
                return Err(Error::internal(
                    "Invalid constant layout: repetition buffer too short",
                ));
            }
            if rep[start] != self.max_rep {
                return Err(Error::internal(
                    "Invalid constant layout: row did not start at max_rep",
                ));
            }
            let mut end = start + 1;
            while end < rep.len() && rep[end] != self.max_rep {
                end += 1;
            }
            end
        } else {
            start + 1
        };

        self.cursor_level = end;
        self.cursor_row += 1;
        Ok(())
    }

    fn skip_to_row(&mut self, target_row: u64) -> Result<()> {
        debug_assert!(
            target_row >= self.cursor_row,
            "rows must be requested in order"
        );
        if self.rep.is_none() {
            // Without repetition every row is exactly one level, so jump straight there
            self.cursor_row = self.cursor_row.max(target_row);
            self.cursor_level = self.cursor_row as usize;
            return Ok(());
        }
        while self.cursor_row < target_row {
            self.take_row()?;
        }
        Ok(())
    }
}

impl crate::encodings::logical::primitive::StructuralPageDecoder for ConstantPageDecoder {
    fn drain(&mut self, num_rows: u64) -> Result<Box<dyn crate::decoder::DecodePageTask>> {
        let drained_ranges = self.drain_ranges(num_rows);

        let mut level_slices: Vec<Range<usize>> = Vec::new();
        let mut visible_items_total: u64 = 0;

        // Each row range is one contiguous level slice, so locate both ends rather than
        // stepping through it row by row
        for range in drained_ranges {
            self.skip_to_row(range.start)?;
            let level_start = self.cursor_level;
            self.skip_to_row(range.end)?;
            let level_range = level_start..self.cursor_level;
            // With definition levels `decode` counts the visible items from the sliced levels
            if self.def.is_none() {
                visible_items_total += level_range.len() as u64;
            }
            if let Some(last) = level_slices.last_mut()
                && last.end == level_range.start
            {
                last.end = level_range.end;
                continue;
            }
            level_slices.push(level_range);
        }

        Ok(Box::new(DecodeConstantTask {
            scalar: self.scalar.clone(),
            rep: self.rep.clone(),
            def: self.def.clone(),
            level_slices,
            visible_items_total,
            def_meaning: self.def_meaning.clone(),
            max_visible_def: self.max_visible_def,
        }))
    }

    fn num_rows(&self) -> u64 {
        self.num_rows
    }
}

#[derive(Debug)]
struct DecodeConstantTask {
    scalar: ArrayRef,
    rep: Option<ScalarBuffer<u16>>,
    def: Option<ScalarBuffer<u16>>,
    level_slices: Vec<Range<usize>>,
    visible_items_total: u64,
    def_meaning: Arc<[DefinitionInterpretation]>,
    max_visible_def: u16,
}

impl DecodeConstantTask {
    fn slice_levels(
        levels: &Option<ScalarBuffer<u16>>,
        slices: &[Range<usize>],
    ) -> Option<Vec<u16>> {
        levels.as_ref().map(|levels| {
            let total = slices.iter().map(|r| r.end - r.start).sum();
            let mut out = Vec::with_capacity(total);
            for r in slices {
                out.extend(levels[r.start..r.end].iter().copied());
            }
            out
        })
    }

    /// Repeats the scalar once per visible item.  Items that are null (definition
    /// level > 0) are materialized as nulls instead of copies of the scalar so that
    /// a large scalar with many null slots does not amplify into an oversized array
    /// (e.g. overflowing i32 offsets for utf8/binary).
    fn materialize_values(&self, def: Option<&[u16]>, num_values: u64) -> Result<ArrayRef> {
        if num_values == 0 {
            return Ok(new_empty_array(self.scalar.data_type()));
        }

        if let DataType::Struct(fields) = self.scalar.data_type()
            && fields.is_empty()
        {
            return Ok(Arc::new(arrow_array::StructArray::new_empty_fields(
                num_values as usize,
                None,
            )) as ArrayRef);
        }

        if let Some(def) = def
            && self.scalar.null_count() == 0
            && def.iter().any(|d| *d != 0 && *d <= self.max_visible_def)
        {
            let null_slot = new_null_array(self.scalar.data_type(), 1);
            let source = arrow_select::concat::concat(&[self.scalar.as_ref(), null_slot.as_ref()])?;
            let indices = arrow_array::UInt64Array::from(
                def.iter()
                    .filter(|d| **d <= self.max_visible_def)
                    .map(|d| if *d == 0 { 0u64 } else { 1u64 })
                    .collect::<Vec<_>>(),
            );
            debug_assert_eq!(indices.len() as u64, num_values);
            return Ok(arrow_select::take::take(source.as_ref(), &indices, None)?);
        }

        let indices = arrow_array::UInt64Array::from(vec![0u64; num_values as usize]);
        Ok(arrow_select::take::take(
            self.scalar.as_ref(),
            &indices,
            None,
        )?)
    }
}

use arrow_array::cast::AsArray;

impl DecodeConstantTask {
    fn scalar_variable_bytes(&self) -> Option<(u8, &[u8])> {
        if self.scalar.len() != 1 || self.scalar.null_count() != 0 {
            return None;
        }
        match self.scalar.data_type() {
            DataType::Utf8 => Some((32, self.scalar.as_string::<i32>().value(0).as_bytes())),
            DataType::LargeUtf8 => Some((64, self.scalar.as_string::<i64>().value(0).as_bytes())),
            DataType::Binary => Some((32, self.scalar.as_binary::<i32>().value(0))),
            DataType::LargeBinary => Some((64, self.scalar.as_binary::<i64>().value(0))),
            _ => None,
        }
    }

    fn append_constant_values_into(
        scalar_bytes: &[u8],
        def: Option<&[u16]>,
        visible_items_total: u64,
        max_visible_def: u16,
        out_data: &mut Vec<u8>,
        out_offsets: &mut VariableWidthOffsets,
    ) -> Result<()> {
        let push_offset = |out_offsets: &mut VariableWidthOffsets, len: usize| -> Result<()> {
            match out_offsets {
                VariableWidthOffsets::U32(offsets) => {
                    if len > i32::MAX as usize {
                        return Err(Error::corrupt_file_named(
                            "constant",
                            format!("decompressed size {len} exceeds 32-bit offsets"),
                        ));
                    }
                    offsets.push(len as u32);
                }
                VariableWidthOffsets::U64(offsets) => {
                    let end = u64::try_from(len).map_err(|_| {
                        Error::corrupt_file_named(
                            "constant",
                            format!("decompressed size {len} exceeds 64-bit offsets"),
                        )
                    })?;
                    offsets.push(end);
                }
            }
            Ok(())
        };

        if let Some(def) = def {
            for &d in def {
                if d <= max_visible_def {
                    if d == 0 && !scalar_bytes.is_empty() {
                        out_data.extend_from_slice(scalar_bytes);
                    }
                    push_offset(out_offsets, out_data.len())?;
                }
            }
        } else if scalar_bytes.is_empty() {
            let end = out_data.len();
            match out_offsets {
                VariableWidthOffsets::U32(offsets) => {
                    if end > i32::MAX as usize {
                        return Err(Error::corrupt_file_named(
                            "constant",
                            format!("decompressed size {end} exceeds 32-bit offsets"),
                        ));
                    }
                    offsets.resize(offsets.len() + visible_items_total as usize, end as u32);
                }
                VariableWidthOffsets::U64(offsets) => {
                    let end = u64::try_from(end).map_err(|_| {
                        Error::corrupt_file_named(
                            "constant",
                            format!("decompressed size {end} exceeds 64-bit offsets"),
                        )
                    })?;
                    offsets.resize(offsets.len() + visible_items_total as usize, end);
                }
            }
        } else {
            for _ in 0..visible_items_total {
                out_data.extend_from_slice(scalar_bytes);
                push_offset(out_offsets, out_data.len())?;
            }
        }
        Ok(())
    }
}

impl crate::decoder::DecodePageTask for DecodeConstantTask {
    fn decode(self: Box<Self>) -> Result<crate::decoder::DecodedPage> {
        let rep = Self::slice_levels(&self.rep, &self.level_slices);
        let def = Self::slice_levels(&self.def, &self.level_slices);

        let visible_items_total = if let Some(def) = &def {
            def.iter().filter(|d| **d <= self.max_visible_def).count() as u64
        } else {
            self.visible_items_total
        };

        let values = self.materialize_values(def.as_deref(), visible_items_total)?;
        let data = crate::data::DataBlock::from_decoded_array(values);
        let unraveler =
            RepDefUnraveler::new(rep, def, self.def_meaning.clone(), visible_items_total);

        Ok(crate::decoder::DecodedPage {
            data,
            repdef: unraveler,
        })
    }

    fn variable_decode_plan(&self) -> Option<VariablePageDecodePlan> {
        let (bits_per_offset, scalar_bytes) = self.scalar_variable_bytes()?;
        let (num_values, valid_values) = if let Some(def) = &self.def {
            let mut visible = 0u64;
            let mut valid = 0u64;
            for range in &self.level_slices {
                for &d in &def[range.start..range.end] {
                    if d <= self.max_visible_def {
                        visible += 1;
                        if d == 0 {
                            valid += 1;
                        }
                    }
                }
            }
            (visible, valid)
        } else {
            (self.visible_items_total, self.visible_items_total)
        };
        let decompressed_bytes = valid_values.checked_mul(scalar_bytes.len() as u64)?;
        Some(VariablePageDecodePlan {
            num_values,
            decompressed_bytes,
            bits_per_offset,
        })
    }

    fn variable_decode_utf8_proven(&self) -> bool {
        self.scalar_variable_bytes().is_some()
    }

    fn decode_variable_into(
        self: Box<Self>,
        out_data: &mut Vec<u8>,
        out_offsets: &mut VariableWidthOffsets,
    ) -> Result<RepDefUnraveler> {
        let Some((bits_per_offset, scalar_bytes)) = self.scalar_variable_bytes() else {
            return Err(Error::not_supported(
                "Direct variable-width decoding is not supported for this constant page"
                    .to_string(),
            ));
        };
        let matches_offsets = matches!(
            (bits_per_offset, &*out_offsets),
            (32, VariableWidthOffsets::U32(_)) | (64, VariableWidthOffsets::U64(_))
        );
        if !matches_offsets {
            return Err(Error::invalid_input(format!(
                "Destination offsets do not match constant page {bits_per_offset}-bit offsets"
            )));
        }

        let rep = Self::slice_levels(&self.rep, &self.level_slices);
        let def = Self::slice_levels(&self.def, &self.level_slices);
        let visible_items_total = if let Some(def) = &def {
            def.iter().filter(|d| **d <= self.max_visible_def).count() as u64
        } else {
            self.visible_items_total
        };

        Self::append_constant_values_into(
            scalar_bytes,
            def.as_deref(),
            visible_items_total,
            self.max_visible_def,
            out_data,
            out_offsets,
        )?;
        Ok(RepDefUnraveler::new(
            rep,
            def,
            self.def_meaning,
            visible_items_total,
        ))
    }
}

#[cfg(test)]
mod tests {
    use arrow_array::BooleanArray;

    use super::*;
    use crate::encodings::logical::primitive::StructuralPageScheduler;

    #[test]
    fn rejects_cached_scalar_with_different_data_type() {
        let mut scheduler = ConstantPageScheduler::try_new(
            Arc::from([]),
            Some(Bytes::new()),
            DataType::UInt8,
            Arc::from([DefinitionInterpretation::AllValidItem]),
        )
        .unwrap();
        let cached: Arc<dyn CachedPageData> = Arc::new(CachedConstantState {
            scalar: Arc::new(BooleanArray::from(vec![true])),
            rep: None,
            def: None,
        });

        let error = scheduler.try_load(&cached).unwrap_err();
        assert!(matches!(error, Error::InvalidInput { .. }));
        assert!(error.to_string().contains("Boolean"));
        assert!(error.to_string().contains("UInt8"));
    }

    #[rstest::rstest]
    #[case::utf8_non_null(DataType::Utf8, 32, false)]
    #[case::utf8_nullable(DataType::Utf8, 32, true)]
    #[case::large_utf8_non_null(DataType::LargeUtf8, 64, false)]
    #[case::large_utf8_nullable(DataType::LargeUtf8, 64, true)]
    fn decode_constant_task_variable_decode_plan_and_into(
        #[case] data_type: DataType,
        #[case] expected_bits: u8,
        #[case] nullable: bool,
    ) {
        use crate::decoder::DecodePageTask;
        use arrow_array::{LargeStringArray, StringArray};

        let scalar_str = "const-value-β";
        let scalar: ArrayRef = match data_type {
            DataType::Utf8 => Arc::new(StringArray::from(vec![scalar_str])),
            DataType::LargeUtf8 => Arc::new(LargeStringArray::from(vec![scalar_str])),
            _ => unreachable!(),
        };

        let make_task = || {
            Box::new(DecodeConstantTask {
                scalar: scalar.clone(),
                rep: None,
                def: nullable.then(|| ScalarBuffer::from(vec![0_u16, 1, 0])),
                level_slices: vec![0..if nullable { 3 } else { 2 }],
                visible_items_total: if nullable { 3 } else { 2 },
                def_meaning: Arc::from([if nullable {
                    DefinitionInterpretation::NullableItem
                } else {
                    DefinitionInterpretation::AllValidItem
                }]),
                max_visible_def: if nullable { 1 } else { 0 },
            })
        };

        let task = make_task();
        assert!(task.variable_decode_utf8_proven());
        let plan = task.variable_decode_plan().expect("plan");
        assert_eq!(plan.bits_per_offset, expected_bits);
        assert_eq!(plan.num_values, if nullable { 3 } else { 2 });
        assert_eq!(plan.decompressed_bytes, (2 * scalar_str.len()) as u64);

        let mut out_data = Vec::new();
        let mut out_offsets = if expected_bits == 32 {
            VariableWidthOffsets::U32(vec![0])
        } else {
            VariableWidthOffsets::U64(vec![0])
        };
        let repdef = task
            .decode_variable_into(&mut out_data, &mut out_offsets)
            .unwrap();

        let expected_bytes = [scalar_str.as_bytes(), scalar_str.as_bytes()].concat();
        assert_eq!(out_data, expected_bytes);
        let len = scalar_str.len() as u64;
        match out_offsets {
            VariableWidthOffsets::U32(offs) => {
                let expected = if nullable {
                    vec![0_u32, len as u32, len as u32, (2 * len) as u32]
                } else {
                    vec![0_u32, len as u32, (2 * len) as u32]
                };
                assert_eq!(offs, expected);
            }
            VariableWidthOffsets::U64(offs) => {
                let expected = if nullable {
                    vec![0_u64, len, len, 2 * len]
                } else {
                    vec![0_u64, len, 2 * len]
                };
                assert_eq!(offs, expected);
            }
        }
        let mut composite = crate::repdef::CompositeRepDefUnraveler::new(vec![repdef]);
        let validity = composite
            .unravel_validity(plan.num_values as usize)
            .unwrap();
        if nullable {
            let v = validity.expect("nullable validity");
            assert!(v.is_valid(0));
            assert!(v.is_null(1));
            assert!(v.is_valid(2));
        } else {
            assert!(validity.is_none());
        }
    }

    #[tokio::test]
    async fn init_from_buffers_offloads_wide_value_buffer_without_pinning() {
        use arrow_array::{StringArray, cast::AsArray};
        #[derive(Debug)]
        struct NoopEncodingsIo;
        impl EncodingsIo for NoopEncodingsIo {
            fn submit_request(
                &self,
                _ranges: Vec<Range<u64>>,
                _priority: u64,
            ) -> BoxFuture<'static, Result<Vec<Bytes>>> {
                std::future::ready(Ok(Vec::new())).boxed()
            }
        }

        let wide_val = "a".repeat(40 * 1024);
        let scalar_arr: ArrayRef = Arc::new(StringArray::from(vec![wide_val.as_str()]));
        let encoded = lance_arrow::scalar::encode_scalar_value_buffer(&scalar_arr).unwrap();

        // Embed the scalar buffer inside a larger coalesced backing allocation.
        let mut backing = vec![0xAB_u8; 128 * 1024];
        let offset = 64;
        backing[offset..offset + encoded.len()].copy_from_slice(&encoded);
        let backing_bytes = Bytes::from(backing);
        let backing_start = backing_bytes.as_ptr() as usize;
        let backing_end = backing_start + backing_bytes.len();
        let scalar_slice = backing_bytes.slice(offset..offset + encoded.len());

        let mut scheduler = ConstantPageScheduler::try_new(
            Arc::from([(offset as u64, encoded.len() as u64)]),
            None,
            DataType::Utf8,
            Arc::from([DefinitionInterpretation::AllValidItem]),
        )
        .unwrap();
        let init = scheduler.init_layout().unwrap();
        let buffers = init.with_buffers(vec![scalar_slice]).unwrap();
        let io: Arc<dyn EncodingsIo> = Arc::new(NoopEncodingsIo);
        let cached = scheduler.init_from_buffers(buffers, &io).await.unwrap();
        let cached_any = cached.as_arc_any();
        let state = cached_any.downcast_ref::<CachedConstantState>().unwrap();
        let decoded = state.scalar.as_string::<i32>();
        assert_eq!(decoded.value(0), wide_val);

        let val_ptr = decoded.value_data().as_ptr() as usize;
        assert!(
            val_ptr < backing_start || val_ptr >= backing_end,
            "decoded scalar must copy out of coalesced I/O backing buffer"
        );
    }
}
