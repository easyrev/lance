# U 首次 Python 测试包装记录

首次选择器为 `-k "merge_insert or unified_merge"`，未选中外部 `test_merge_semantics.py` 的三个函数。保留的 `U-python-initial-tests.log` 显示原 38 项通过，实际扩展 SHA256 前后相同，pytest 返回 0；该次 shell wrapper 的退出码文件为 2。因此这次记录不能当作三个补充测试通过，也不能当作整个 wrapper 成功。

在该 wrapper 尚未退出时修改并同步了选择器文件；wrapper 异常与此时序相容，但没有保留独立的初次 driver stderr，不能确认退出 2 的具体原因。后续不在执行期间修改包装脚本。

随后使用 `-k "merge_insert or test_merge_semantics"` 完整重跑：`U-python-tests.log` 记录 41 passed、pytest 返回 0、扩展 SHA256 前后相同，`U-python-exit-code` 为 0。D 使用修正后的脚本也得到 41 passed 和 wrapper 退出 0。此处均为正确性测试，不是性能样本。
