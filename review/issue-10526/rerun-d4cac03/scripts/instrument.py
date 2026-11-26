"""Add diagnostic markers to a disposable checkout of the pinned head."""
import sys
from pathlib import Path

root = Path(sys.argv[1]) / "rust/lance-encoding/src"


def replace(source, old, new):
    assert source.count(old) == 1, old
    return source.replace(old, new)


def failure(reason):
    return f'eprintln!("PR1_BRIDGE reason {reason}")'


def trace_option(expression, reason):
    return f'{expression}.or_else(|| {{ {failure(reason)}; None }})'


def edit(path, start, end, changes):
    path = root / path
    source = path.read_text()
    before, tail = source.split(start, 1)
    section, after = tail.split(end, 1)
    for old, new in changes:
        section = replace(section, old, new)
    path.write_text(before + start + section + end + after)


field = "encodings/logical/primitive/field.rs"
edit(field, "impl StructuralCompositeDecodeArrayTask {", "    fn decode_variable(",
     [("if self.tasks.len() <= 1 {", "if self.tasks.len() <= 1 {\n            " + failure("field.rs:934 single-page") + ";"),
      ("_ => return None,", "_ => { " + failure("field.rs:940 unsupported-array-type") + "; return None; },"),
      ("task.variable_decode_plan()?", trace_option("task.variable_decode_plan()", "field.rs:946 page-plan-none") + "?"),
      ("if plan.bits_per_offset != bits_per_offset {", "if plan.bits_per_offset != bits_per_offset {\n                " + failure("field.rs:947 offset-width-mismatch") + ";"),
      ("num_values.checked_add(plan.num_values)?", trace_option("num_values.checked_add(plan.num_values)", "field.rs:950 value-count-overflow") + "?"),
      ("decompressed_bytes.checked_add(plan.decompressed_bytes)?", trace_option("decompressed_bytes.checked_add(plan.decompressed_bytes)", "field.rs:951 byte-count-overflow") + "?"),
      ("if bits_per_offset == 32 && decompressed_bytes > i32::MAX as u64 {", "if bits_per_offset == 32 && decompressed_bytes > i32::MAX as u64 {\n            " + failure("field.rs:954 i32-offset-overflow") + ";")])
edit(field, "impl StructuralDecodeArrayTask for StructuralCompositeDecodeArrayTask {",
     "/// Returns the total bytes", [
         ("return self.decode_variable(plan, page_plans);", '''let pages = self.tasks.len();
            let result = self.decode_variable(plan, page_plans);
            match &result {
                Ok(_) => eprintln!("PR1_BRIDGE outcome bridge pages={pages}"),
                Err(err) => eprintln!("PR1_BRIDGE outcome error pages={pages} error={err:?}"),
            }
            return result;'''),
         ("let mut arrays = Vec::with_capacity(self.tasks.len());", '''eprintln!("PR1_BRIDGE outcome concat pages={}", self.tasks.len());
        let mut arrays = Vec::with_capacity(self.tasks.len());'''),
     ])
edit("decoder.rs", "    fn variable_decode_plan(&self) -> Option<VariablePageDecodePlan> {",
     "    /// Appends this page", [("\n        None", "\n        " + failure("decoder.rs:3807 default-page-plan-none") + ";\n        None")])
edit("compression.rs", "    fn appended_size(&self, _data:", "    ///", [
    ("\n        None", "\n        " + failure("compression.rs:1387 default-appended-size-none") + ";\n        None"),
])
edit("encodings/logical/primitive/fullzip_decode.rs", "    fn variable_decode_plan(&self)",
     "    fn decode_variable_into(", [
         ("_ => return None,", "_ => { " + failure("fullzip_decode.rs:1843 unsupported-offset-width") + "; return None; },"),
         (".checked_add(1)?", ".checked_add(1).or_else(|| { " + failure("fullzip_decode.rs:1847 offset-count-overflow") + "; None })?"),
         (".checked_mul(bytes_per_offset)?", ".checked_mul(bytes_per_offset).or_else(|| { " + failure("fullzip_decode.rs:1848 offset-size-overflow") + "; None })?"),
         ("if self.offsets.len() as u64 != expected_offsets_bytes {", "if self.offsets.len() as u64 != expected_offsets_bytes {\n            " + failure("fullzip_decode.rs:1849 offset-size-mismatch") + ";"),
         (")?,\n            bits_per_offset", ").or_else(|| { " + failure("fullzip_decode.rs:1854 appended-size-none") + "; None })?,\n            bits_per_offset"),
     ])
block = "encodings/physical/block.rs"
edit(block, "    fn appended_size(&self, data:", "    fn decompress_into(", [
    ("read_offset(offsets_bytes, 0, bits_per_offset)?", trace_option("read_offset(offsets_bytes, 0, bits_per_offset)", "block.rs:1259 first-offset-unreadable") + "?"),
    ("!= 0 {", "!= 0 {\n            " + failure("block.rs:1259 first-offset-nonzero") + ";"),
])
edit(block, "fn sum_decompressed_sizes(", "fn read_offset(", [
    ("return None;", failure("block.rs:1328 offset-buffer-shape") + "; return None;"),
    ("start.checked_sub(base)?", trace_option("start.checked_sub(base)", "block.rs:1344 start-before-base") + "?"),
    ("end.checked_sub(base)?", trace_option("end.checked_sub(base)", "block.rs:1345 end-before-base") + "?"),
    ("data.get(val_start..val_end)?", trace_option("data.get(val_start..val_end)", "block.rs:1350 value-slice-out-of-bounds") + "?"),
    ("size_of_value(value_bytes)?", trace_option("size_of_value(value_bytes)", "block.rs:1351 missing-exact-frame-size") + "?"),
])
