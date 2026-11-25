from pathlib import Path

root = Path(__file__).parent
source = (root / 'p1.rs').read_text()
source = source.replace('    let mut distinct_bytes = 0usize;', '''    let mut distinct_bytes = 0usize;
    let mut has_duplicate = false;''')
source = source.replace(
    """    'samples: for (array, array_start) in arrays.iter().scan(0, |start, array| {
        let previous = *start;
        *start += array.len();
        Some((array, previous))
    }) {""",
    """    let mut array_start = 0;
    'samples: for array in arrays {""",
)
source = source.replace(
    '''            if distinct_bytes <= max_dict_bytes && seen.insert((value_len, xxh3_64(value))) {
                distinct_bytes = distinct_bytes.saturating_add(value.len());
            }''',
    '''            if distinct_bytes <= max_dict_bytes {
                if seen.insert((value_len, xxh3_64(value))) {
                    distinct_bytes = distinct_bytes.saturating_add(value.len());
                } else {
                    has_duplicate = true;
                }
            }''',
)
source = source.replace(
    '''        }
    }

    if distinct_bytes <= max_dict_bytes || !has_distinct_valid_values {
        return Ok(None);
    }''',
    '''        }
        array_start = array_end;
    }

    // A caller can request smaller pages than the dictionary budget. Retain
    // splitting for an entirely distinct sample in that case.
    let has_distinct_sample_below_page_limit =
        ctx.max_page_bytes < max_dict_bytes as u64 && !has_duplicate;
    if !has_distinct_valid_values
        || (distinct_bytes <= max_dict_bytes && !has_distinct_sample_below_page_limit)
    {
        return Ok(None);
    }''',
)
source = source.replace('has_distinct_sample_below_page_limit', 'has_distinct_sample_with_small_page_limit')
(root / 'p1-compatible.rs').write_text(source)
source = source.replace(
    '''                    Some(first) => has_distinct_valid_values = value != first,''',
    '''                    // Its physical bytes were already counted at the first
                    // sampled valid occurrence.
                    Some(first) if value == first => continue,
                    Some(_) => has_distinct_valid_values = true,''',
)
(root / 'p1-compatible.rs').write_text(source)
source = source.replace(
    '''    let mut non_empty_count = 0;
    for array in arrays {
        if with_byte_array!(array, |bytes| value_lengths!(bytes).any(|len| {
            non_empty_count += usize::from(len != 0);
            len != 0 && len <= PER_VALUE_COMPRESSION_MIN_VALUE_BYTES
        })) {
            return Ok(None);
        }
    }''',
    '''    let mut non_empty_count = 0;
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
    }''',
)
source = source.replace(
    'ctx.max_page_bytes < max_dict_bytes as u64 && !has_duplicate;',
    '!has_short_values && ctx.max_page_bytes < max_dict_bytes as u64 && !has_duplicate;',
)
# The equality shortcut also observes a duplicate for the low-cap exception.
for name in ('p1-compatible.rs', 'p2-compatible.rs'):
    if name == 'p1-compatible.rs':
        text = (root / name).read_text()
    else:
        text = source
    text = text.replace('Some(first) if value == first => continue,', '''Some(first) if value == first => {
                        has_duplicate = true;
                        continue;
                    }''')
    (root / name).write_text(text)
