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

