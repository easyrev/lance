from pathlib import Path

root = Path(__file__).parent
fix = (root / 'fix.rs').read_text()
p1 = fix.replace('if valid_count == 0 {', 'if valid_count < 2 {')
p1 = p1.replace(
    '// One more sample than the budget can hold as distinct wide values forces a repeat.\n    let required_samples =\n        max_dict_bytes / (PER_VALUE_COMPRESSION_MIN_VALUE_BYTES as usize + 1) + 1;',
    '''// Retain the bounded, evenly spaced sample. Sample at least two valid
    // values so tiny dictionary budgets can still distinguish a constant.
    let required_samples =
        (max_dict_bytes / (PER_VALUE_COMPRESSION_MIN_VALUE_BYTES as usize + 1) + 1).max(2);''',
)
p1 = p1.replace('    let mut array_start = 0;\n    for array in arrays {\n        let array_end', '''    let mut distinct_bytes = 0usize;
    let mut first_valid = None;
    let mut has_distinct_valid_values = false;
    'samples: for (array, array_start) in arrays.iter().scan(0, |start, array| {
        let previous = *start;
        *start += array.len();
        Some((array, previous))
    }) {
        let array_end''')
p1 = p1.replace(
    '''            if !seen.insert((value_len, xxh3_64(value))) {
                return Ok(None);
            }
        }
        array_start = array_end;
    }

    let counts''',
    '''            // Physical dictionary interning can see null payloads. Keep
            // the logical comparison separate even when a null used the
            // same bytes as this valid row earlier in the sample.
            if !has_distinct_valid_values
                && validity.as_ref().is_none_or(|valid| valid.value(index))
            {
                match first_valid {
                    Some(first) => has_distinct_valid_values = value != first,
                    None => first_valid = Some(value),
                }
            }

            // Hash collisions can only undercount sampled distinct bytes.
            if distinct_bytes <= max_dict_bytes && seen.insert((value_len, xxh3_64(value))) {
                distinct_bytes = distinct_bytes.saturating_add(value.len());
            }
            if distinct_bytes > max_dict_bytes && has_distinct_valid_values {
                break 'samples;
            }
        }
    }

    if distinct_bytes <= max_dict_bytes || !has_distinct_valid_values {
        return Ok(None);
    }

    let counts''',
)
p2 = p1.replace(
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
    for array in arrays {
        with_byte_array!(array, |bytes| {
            for len in value_lengths!(bytes) {
                non_empty_count += usize::from(len != 0);
                max_width = max_width.max(len);
            }
        });
    }
    if max_width <= PER_VALUE_COMPRESSION_MIN_VALUE_BYTES {
        return Ok(None);
    }''',
)
assert p1.count('first_valid') == 3
assert p2.count('max_width') == 4
(root / 'p1.rs').write_text(p1)
(root / 'p2.rs').write_text(p2)
