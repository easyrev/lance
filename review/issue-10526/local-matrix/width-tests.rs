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

