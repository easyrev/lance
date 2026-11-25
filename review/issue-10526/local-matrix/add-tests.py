from pathlib import Path
import sys

tests = Path(__file__).parent / 'candidate-tests.rs'
file = Path(sys.argv[1])
source = file.read_text().replace(
    '        let num_rows = array.len() as u64;',
    '''        plan_wide_binary_with_budget(array, max_page_bytes, None)
    }

''' + tests.read_text() + '''    fn plan_wide_binary_with_budget(
        array: LargeBinaryArray,
        max_page_bytes: u64,
        max_dict_bytes: Option<usize>,
    ) -> Option<Vec<usize>> {
        let num_rows = array.len() as u64;''', 1,
)
source = source.replace(
    '        let field = Field::try_from(&ArrowField::new("wide", DataType::LargeBinary, true)).unwrap();',
    '''        let metadata = max_dict_bytes
            .map(|limit| (DICT_MAX_SIZE_META_KEY.to_string(), limit.to_string()))
            .into_iter()
            .collect();
        let field = Field::try_from(
            &ArrowField::new("wide", DataType::LargeBinary, true).with_metadata(metadata),
        )
        .unwrap();''', 1,
)
file.write_text(source)
