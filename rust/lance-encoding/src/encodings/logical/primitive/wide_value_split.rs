// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: Copyright The Lance Authors

use std::collections::HashSet;

use arrow_array::ArrayRef;
use arrow_array::cast::AsArray;
use arrow_schema::DataType;
use itertools::Itertools;
use lance_core::Result;
use xxhash_rust::xxh3::xxh3_64;

use crate::compression::PER_VALUE_COMPRESSION_MIN_VALUE_BYTES;
use crate::constants::{
    DICT_MAX_SIZE_META_KEY, STRUCTURAL_ENCODING_FULLZIP, STRUCTURAL_ENCODING_META_KEY,
};
use crate::repdef::SerializedRepDefs;

use super::{
    DEFAULT_DICT_MAX_SIZE_BYTES,
    structural_encoder::{PrimitivePlanContext, PrimitiveStructuralEncoder},
};

pub(super) fn balanced_page_value_counts(value_bytes: &[u64], max_page_bytes: u64) -> Vec<usize> {
    let max_page_bytes = u128::from(max_page_bytes);
    let mut minimum = Vec::new();
    let mut total = 0;
    let mut page_bytes = 0;
    let mut page_start = 0;
    for (index, &bytes) in value_bytes.iter().enumerate() {
        let bytes = u128::from(bytes);
        if page_bytes > 0 && bytes > 0 && page_bytes + bytes > max_page_bytes {
            minimum.push(index - page_start);
            page_start = index;
            page_bytes = 0;
        }
        page_bytes += bytes;
        total += bytes;
    }
    minimum.push(value_bytes.len() - page_start);

    let minimum_pages = minimum.len() as u128;
    let mut proportional = Vec::with_capacity(minimum.len());
    let mut before = 0;
    page_bytes = 0;
    page_start = 0;
    for (index, &bytes) in value_bytes.iter().enumerate() {
        let bytes = u128::from(bytes);
        let page_index = proportional.len() as u128;
        if page_bytes > 0
            && bytes > 0
            && (page_bytes + bytes > max_page_bytes
                || minimum_pages * (2 * before + bytes) > 2 * (page_index + 1) * total)
        {
            proportional.push(index - page_start);
            page_start = index;
            page_bytes = 0;
        }
        page_bytes += bytes;
        before += bytes;
    }
    proportional.push(value_bytes.len() - page_start);

    // Preserve the greedy page count so balancing cannot add a page.
    if proportional.len() == minimum.len() {
        proportional
    } else {
        minimum
    }
}

pub(super) fn wide_value_page_counts(
    ctx: &PrimitivePlanContext<'_>,
    arrays: &[ArrayRef],
    repdef: &SerializedRepDefs,
    num_rows: u64,
) -> Result<Option<Vec<usize>>> {
    let num_values = arrays.iter().map(|array| array.len()).sum::<usize>();
    if repdef.repetition_levels.is_some()
        || repdef.has_fixed_size_list_levels()
        || num_rows != num_values as u64
    {
        return Ok(None);
    }
    if !arrays.iter().all(|array| {
        matches!(
            array.data_type(),
            DataType::Utf8 | DataType::LargeUtf8 | DataType::Binary | DataType::LargeBinary
        )
    }) {
        return Ok(None);
    }
    if ctx
        .encoding_metadata
        .get(STRUCTURAL_ENCODING_META_KEY)
        .is_some_and(|encoding| !encoding.eq_ignore_ascii_case(STRUCTURAL_ENCODING_FULLZIP))
    {
        return Ok(None);
    }
    if num_values < 2 || ctx.max_page_bytes == 0 {
        return Ok(None);
    }

    macro_rules! with_byte_array {
        ($array:expr, |$bytes:ident| $body:expr) => {
            match $array.data_type() {
                DataType::Utf8 => {
                    let $bytes = $array.as_string::<i32>();
                    $body
                }
                DataType::LargeUtf8 => {
                    let $bytes = $array.as_string::<i64>();
                    $body
                }
                DataType::Binary => {
                    let $bytes = $array.as_binary::<i32>();
                    $body
                }
                DataType::LargeBinary => {
                    let $bytes = $array.as_binary::<i64>();
                    $body
                }
                _ => unreachable!(),
            }
        };
    }

    macro_rules! value_lengths {
        ($bytes:expr) => {
            $bytes
                .value_offsets()
                .windows(2)
                .map(|offsets| (offsets[1] - offsets[0]) as u64)
        };
    }

    let total: u64 = arrays
        .iter()
        .map(|array| {
            with_byte_array!(array, |bytes| {
                let offsets = bytes.value_offsets();
                (offsets[offsets.len() - 1] - offsets[0]) as u64
            })
        })
        .sum();
    if total <= ctx.max_page_bytes {
        return Ok(None);
    }

    let mut non_empty_count = 0;
    let mut max_width = 0;
    let mut has_short_values = false;
    for array in arrays {
        with_byte_array!(array, |bytes| {
            for len in value_lengths!(bytes) {
                non_empty_count += usize::from(len != 0);
                max_width = max_width.max(len);
                has_short_values |= len != 0 && len <= PER_VALUE_COMPRESSION_MIN_VALUE_BYTES;
            }
        });
    }
    if max_width <= PER_VALUE_COMPRESSION_MIN_VALUE_BYTES {
        return Ok(None);
    }

    let validity = PrimitiveStructuralEncoder::leaf_validity(repdef, num_values)?;
    let valid_count = validity
        .as_ref()
        .map_or(num_values, |valid| valid.count_set_bits());
    if valid_count < 2 {
        return Ok(None);
    }
    if non_empty_count != num_values {
        let Some(valid) = validity.as_ref() else {
            return Ok(None);
        };
        let mut array_start = 0;
        for array in arrays {
            if with_byte_array!(array, |bytes| value_lengths!(bytes)
                .enumerate()
                .any(|(index, len)| len == 0 && valid.value(array_start + index)))
            {
                return Ok(None);
            }
            array_start += array.len();
        }
    }

    let max_dict_bytes = match ctx.field.metadata.get(DICT_MAX_SIZE_META_KEY) {
        Some(limit) => match limit.parse::<usize>() {
            Ok(limit) => limit,
            Err(_) => return Ok(None),
        },
        None => DEFAULT_DICT_MAX_SIZE_BYTES,
    };
    // Retain the bounded, evenly spaced sample. Sample at least two valid
    // values so tiny dictionary budgets can still distinguish a constant.
    let required_samples =
        (max_dict_bytes / (PER_VALUE_COMPRESSION_MIN_VALUE_BYTES as usize + 1) + 1).max(2);
    let mut value_bytes = Vec::with_capacity(num_values);
    for array in arrays {
        with_byte_array!(array, |bytes| value_bytes.extend(value_lengths!(bytes)));
    }

    let sample_ranks = |count: usize| {
        let samples = count.min(required_samples);
        (0..samples).map(move |sample| (sample as u128 * count as u128 / samples as u128) as usize)
    };
    let mut non_empty_indices = (non_empty_count != num_values).then(|| {
        value_bytes
            .iter()
            .enumerate()
            .filter_map(|(index, &bytes)| (bytes != 0).then_some(index))
    });
    let mut next_non_empty_rank = 0;
    let physical_samples =
        sample_ranks(non_empty_count).map_while(|rank| match non_empty_indices.as_mut() {
            Some(indices) => {
                let index = indices.nth(rank - next_non_empty_rank);
                next_non_empty_rank = rank + 1;
                index
            }
            None => Some(rank),
        });
    let valid_samples = validity
        .iter()
        .filter(|_| valid_count != non_empty_count)
        .flat_map(|valid| {
            let mut indices = valid.set_indices();
            let mut next_valid_rank = 0;
            sample_ranks(valid_count).map_while(move |rank| {
                let index = indices.nth(rank - next_valid_rank);
                next_valid_rank = rank + 1;
                index
            })
        });
    let mut sample_indices = physical_samples.merge(valid_samples).dedup().peekable();
    let mut seen = HashSet::with_capacity(non_empty_count.min(required_samples));
    let mut distinct_bytes = 0usize;
    let mut has_duplicate = false;
    let mut first_valid = None;
    let mut has_distinct_valid_values = false;
    let mut array_start = 0;
    'samples: for array in arrays {
        let array_end = array_start + array.len();
        while let Some(index) = sample_indices.next_if(|&index| index < array_end) {
            let value_len = value_bytes[index];
            let value = with_byte_array!(array, |bytes| {
                let offset = bytes.value_offsets()[index - array_start] as usize;
                &bytes.value_data()[offset..offset + value_len as usize]
            });
            // Physical dictionary interning can see null payloads. Keep
            // the logical comparison separate even when a null used the
            // same bytes as this valid row earlier in the sample.
            if !has_distinct_valid_values
                && validity.as_ref().is_none_or(|valid| valid.value(index))
            {
                match first_valid {
                    // Its physical bytes were already counted at the first
                    // sampled valid occurrence.
                    Some(first) if value == first => {
                        has_duplicate = true;
                        continue;
                    }
                    Some(_) => has_distinct_valid_values = true,
                    None => first_valid = Some(value),
                }
            }

            // Hash collisions can only undercount sampled distinct bytes.
            if distinct_bytes <= max_dict_bytes {
                if seen.insert((value_len, xxh3_64(value))) {
                    distinct_bytes = distinct_bytes.saturating_add(value.len());
                } else {
                    has_duplicate = true;
                }
            }
            if distinct_bytes > max_dict_bytes && has_distinct_valid_values {
                break 'samples;
            }
        }
        array_start = array_end;
    }

    // A caller can request smaller pages than the dictionary budget. Retain
    // splitting for an entirely distinct sample in that case.
    let has_distinct_sample_with_small_page_limit =
        !has_short_values && ctx.max_page_bytes < max_dict_bytes as u64 && !has_duplicate;
    if !has_distinct_valid_values
        || (distinct_bytes <= max_dict_bytes && !has_distinct_sample_with_small_page_limit)
    {
        return Ok(None);
    }

    let counts = balanced_page_value_counts(&value_bytes, ctx.max_page_bytes);
    Ok((counts.len() > 1).then_some(counts))
}

#[cfg(test)]
pub(super) mod tests {
    use std::collections::HashMap;
    use std::sync::Arc;

    use arrow_array::{Array, LargeBinaryArray, StringArray};
    use arrow_buffer::{Buffer, NullBuffer, OffsetBuffer};
    use arrow_schema::{DataType, Field as ArrowField};
    use lance_core::datatypes::Field;
    use rand::rngs::SmallRng;
    use rand::{Rng, SeedableRng};
    use rstest::rstest;

    use crate::constants::DICT_MAX_SIZE_META_KEY;
    use crate::repdef::{MiniBlockRepDefBudget, RepDefBuilder};

    use super::{PrimitivePlanContext, balanced_page_value_counts, wide_value_page_counts};

    #[test]
    fn test_wide_values_with_shared_prefix_split() {
        let payload_bytes = 70 * 1024;
        let mut values = vec![0; 20 * payload_bytes];
        for (row, payload) in values.chunks_exact_mut(payload_bytes).enumerate() {
            payload[65_536] = row as u8;
        }
        let array = LargeBinaryArray::new(
            OffsetBuffer::from_lengths(std::iter::repeat_n(payload_bytes, 20)),
            Buffer::from(values),
            None,
        );
        assert_eq!(plan_wide_binary(array, 200 * 1024), Some(vec![2; 10]));
    }

    #[cfg_attr(coverage, coverage(off))]
    pub(in crate::encodings::logical::primitive) fn nullable_wide_constant() -> LargeBinaryArray {
        let payload_bytes = 32_769;
        let mut values = vec![0; 1_024 * payload_bytes];
        for (row, payload) in values.chunks_exact_mut(payload_bytes).enumerate() {
            if row % 4 == 0 {
                payload[0] = (row / 4) as u8;
            } else {
                payload.fill(u8::MAX);
            }
        }
        let nulls = NullBuffer::from((0..1_024).map(|row| row % 4 != 0).collect::<Vec<_>>());
        LargeBinaryArray::new(
            OffsetBuffer::from_lengths(std::iter::repeat_n(payload_bytes, 1_024)),
            Buffer::from(values),
            Some(nulls),
        )
    }

    #[test]
    fn test_nullable_wide_constant_stays_unsplit() {
        assert_eq!(
            plan_wide_binary(nullable_wide_constant(), 16 * 1024 * 1024),
            None
        );
    }

    #[cfg_attr(coverage, coverage(off))]
    pub(in crate::encodings::logical::primitive) fn wide_binary_with_null_payloads()
    -> LargeBinaryArray {
        let payload_bytes = 32_769;
        let mut values = vec![0; 1_024 * payload_bytes];
        for (row, payload) in values.chunks_exact_mut(payload_bytes).enumerate() {
            payload.fill((row % 255) as u8);
        }
        let nulls = NullBuffer::from((0..1_024).map(|row| row < 255).collect::<Vec<_>>());
        LargeBinaryArray::new(
            OffsetBuffer::from_lengths(std::iter::repeat_n(payload_bytes, 1_024)),
            Buffer::from(values),
            Some(nulls),
        )
    }

    #[test]
    fn test_wide_null_payloads_stay_unsplit() {
        assert_eq!(
            plan_wide_binary(wide_binary_with_null_payloads(), 16 * 1024 * 1024),
            None
        );
    }

    #[test]
    fn test_short_null_payload_stays_unsplit() {
        let lengths = (0..21).map(|row| if row == 10 { 10 } else { 32_769 });
        let values: Vec<_> = lengths
            .clone()
            .enumerate()
            .flat_map(|(row, length)| std::iter::repeat_n(row as u8, length))
            .collect();
        let nulls = NullBuffer::from((0..21).map(|row| row != 10).collect::<Vec<_>>());
        let array = LargeBinaryArray::new(
            OffsetBuffer::from_lengths(lengths),
            Buffer::from(values),
            Some(nulls),
        );
        assert_eq!(plan_wide_binary(array, 200 * 1024), None);
    }

    fn plan_wide_binary(array: LargeBinaryArray, max_page_bytes: u64) -> Option<Vec<usize>> {
        plan_wide_binary_with_budget(array, max_page_bytes, None)
    }

    #[rstest]
    #[case::ordinary_constant(&[0, 0, 0, 0], None, false)]
    #[case::dirty_null_constant(&[0, 0, 1, 0], Some([false, true, false, true]), false)]
    #[case::valid_after_same_null(&[0, 0, 0, 1], Some([false, true, false, true]), true)]
    #[case::occasional_template(&[0, 1, 2, 3, 0, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18], None, true)]
    fn test_sampled_wide_dictionary_budget(
        #[case] values: &[u8],
        #[case] validity: Option<[bool; 4]>,
        #[case] should_split: bool,
    ) {
        let value_bytes = 65_538;
        let array = LargeBinaryArray::new(
            OffsetBuffer::from_lengths(std::iter::repeat_n(value_bytes, values.len())),
            Buffer::from(
                values
                    .iter()
                    .flat_map(|&value| std::iter::repeat_n(value, value_bytes))
                    .collect::<Vec<u8>>(),
            ),
            validity.map(|valid| NullBuffer::from(valid.to_vec())),
        );
        let budget = if validity.is_none() && values.len() > 4 {
            4 * value_bytes
        } else {
            1
        };
        assert_eq!(
            plan_wide_binary_with_budget(array, (2 * value_bytes) as u64, Some(budget)).is_some(),
            should_split
        );
    }

    #[rstest]
    #[case::mostly_wide(65_538, 128, true)]
    #[case::mostly_short(31_000, 65_538, true)]
    #[case::threshold_width(31_000, 32_768, false)]
    fn test_mixed_width_values_split_over_dictionary_budget(
        #[case] typical_width: usize,
        #[case] rare_width: usize,
        #[case] should_split: bool,
    ) {
        let lengths = (0..8).map(|row| if row == 4 { rare_width } else { typical_width });
        let values: Vec<_> = lengths
            .clone()
            .enumerate()
            .flat_map(|(row, width)| std::iter::repeat_n(row as u8, width))
            .collect();
        let array = LargeBinaryArray::new(
            OffsetBuffer::from_lengths(lengths),
            Buffer::from(values),
            None,
        );
        let page_limit = 150_000;
        let counts = plan_wide_binary_with_budget(array, page_limit, Some(1));
        assert_eq!(counts.is_some(), should_split);
        if let Some(counts) = counts {
            assert!(counts.len() > 1);
            assert_eq!(counts.iter().sum::<usize>(), 8);
        }
    }

    fn plan_wide_binary_with_budget(
        array: LargeBinaryArray,
        max_page_bytes: u64,
        max_dict_bytes: Option<usize>,
    ) -> Option<Vec<usize>> {
        let num_rows = array.len() as u64;
        let mut repdef = RepDefBuilder::default();
        if let Some(nulls) = array.nulls() {
            repdef.add_validity_bitmap(nulls.clone());
        }
        let repdef = RepDefBuilder::normalize(vec![repdef]).serialize();
        let metadata = max_dict_bytes
            .map(|limit| (DICT_MAX_SIZE_META_KEY.to_string(), limit.to_string()))
            .into_iter()
            .collect();
        let field = Field::try_from(
            &ArrowField::new("wide", DataType::LargeBinary, true).with_metadata(metadata),
        )
        .unwrap();
        let ctx = PrimitivePlanContext {
            field: &field,
            encoding_metadata: &HashMap::new(),
            max_page_bytes,
        };
        wide_value_page_counts(&ctx, &[Arc::new(array)], &repdef, num_rows).unwrap()
    }

    #[cfg_attr(coverage, coverage(off))]
    pub(in crate::encodings::logical::primitive) fn repeated_wide_binary(
        distinct_values: usize,
        null_row: usize,
    ) -> LargeBinaryArray {
        let values: Vec<_> = (0..distinct_values)
            .map(|value_number| vec![value_number as u8; 32_769])
            .collect();
        (0..1_024)
            .map(|row| (row != null_row).then_some(values[row % distinct_values].as_slice()))
            .collect()
    }

    #[rstest]
    #[case::default_limit(255, 1_020, None)]
    #[case::custom_limit(31, 992, Some("1048576"))]
    fn test_dictionary_eligible_wide_values_stay_unsplit(
        #[case] distinct_values: usize,
        #[case] null_row: usize,
        #[case] dictionary_limit: Option<&str>,
    ) {
        let array = repeated_wide_binary(distinct_values, null_row);
        let mut repdef = RepDefBuilder::default();
        repdef.add_validity_bitmap(array.nulls().unwrap().clone());
        let repdef = RepDefBuilder::normalize(vec![repdef]).serialize();
        let metadata = dictionary_limit
            .map(|limit| (DICT_MAX_SIZE_META_KEY.to_string(), limit.to_string()))
            .into_iter()
            .collect();
        let field = Field::try_from(
            &ArrowField::new("wide", DataType::LargeBinary, false).with_metadata(metadata),
        )
        .unwrap();
        let ctx = PrimitivePlanContext {
            field: &field,
            encoding_metadata: &HashMap::new(),
            max_page_bytes: 16 * 1024 * 1024,
        };
        assert_eq!(
            wide_value_page_counts(&ctx, &[Arc::new(array)], &repdef, 1_024).unwrap(),
            None
        );
    }

    #[test]
    fn test_pure_validity_stays_within_miniblock_budget() {
        let num_rows = 70_000;
        let array: StringArray = (0..num_rows)
            .map(|row| (row % 2 == 0).then_some("short"))
            .collect();
        let mut repdef = RepDefBuilder::default();
        repdef.add_validity_bitmap(array.nulls().unwrap().clone());
        let (_, budget) = RepDefBuilder::normalize(vec![repdef])
            .serialize_with_miniblock_repdef_budget(
                super::super::miniblock::max_repdef_levels_per_chunk,
                num_rows,
                num_rows,
            )
            .unwrap();
        assert!(budget == MiniBlockRepDefBudget::WithinBudget);
    }

    #[rstest]
    #[case::equal_lengths(&[10; 10], &[3, 2, 3, 2])]
    #[case::mixed_lengths(&[10, 15, 12, 40, 5], &[2, 1, 1, 1])]
    #[case::one_per_page(&[25; 4], &[1, 1, 1, 1])]
    #[case::oversized_values(&[50, 50], &[1, 1])]
    #[case::uneven_tail(&[9; 11], &[3, 3, 2, 3])]
    #[case::zero_length_edges(&[0, 0, 40, 0], &[4])]
    #[case::zero_length_between_values(&[20, 0, 0, 20, 0], &[3, 2])]
    fn test_balanced_page_value_counts(#[case] value_bytes: &[u64], #[case] expected: &[usize]) {
        assert_eq!(balanced_page_value_counts(value_bytes, 30), expected);
    }

    #[test]
    fn test_balanced_page_value_counts_benchmark_input() {
        let counts = balanced_page_value_counts(&vec![180_000; 8_000], 32 * 1024 * 1024);
        assert_eq!(counts.len(), 44);
        assert_eq!(counts.iter().sum::<usize>(), 8_000);
        assert!(counts.iter().all(|&count| count == 181 || count == 182));
    }

    #[test]
    fn test_balanced_page_invariants() {
        let mut rng = SmallRng::seed_from_u64(10526);
        for _ in 0..256 {
            let max_page_bytes = rng.random_range(1..=256);
            let num_values = rng.random_range(2..=64);
            let mut value_bytes: Vec<u64> =
                (0..num_values).map(|_| rng.random_range(0..=512)).collect();
            value_bytes[0] = rng.random_range(1..=512);

            let counts = balanced_page_value_counts(&value_bytes, max_page_bytes);
            let mut greedy_pages = 1;
            let mut greedy_page_bytes = 0;
            for bytes in value_bytes.iter().copied().filter(|&bytes| bytes != 0) {
                if greedy_page_bytes != 0 && greedy_page_bytes + bytes > max_page_bytes {
                    greedy_pages += 1;
                    greedy_page_bytes = 0;
                }
                greedy_page_bytes += bytes;
            }
            assert_eq!(counts.len(), greedy_pages);
            assert_eq!(counts.iter().sum::<usize>(), value_bytes.len());
            let mut start = 0;
            for count in counts {
                assert!(count > 0);
                let page = &value_bytes[start..start + count];
                let page_bytes = page.iter().sum::<u64>();
                assert!(page_bytes > 0);
                assert!(
                    page_bytes <= max_page_bytes
                        || page.iter().filter(|&&bytes| bytes > 0).count() == 1
                );
                start += count;
            }
        }
    }
}
