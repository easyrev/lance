# 三项复核

## 环境对照

使用系统 pip 的 `--python <venv>/bin/python freeze --all`。

| 环境 | 非 editable 条目数 | editable pylance 来源 |
|---|---|---|
| base | 72 | `git+https://github.com/easyrev/lance@cb8c25692e0d35d682be5459644a698f8d49655a#egg=pylance&subdirectory=../../../base/python` |
| pure | 72 | `git+https://github.com/easyrev/lance@16e3c99b1faa6014c17e33331f35cce726302243#egg=pylance&subdirectory=../../../shared-buffer-pure/python` |
| var | 72 | `git+https://github.com/easyrev/lance@6f16adfc7b2f6f2027926f2014fbcfebc7febb8c#egg=pylance&subdirectory=../../../shared-buffer-var/python` |
| final | 72 | `git+https://github.com/easyrev/lance@d0020f4291a0cb18790ac731df7c24890a169ca1#egg=pylance&subdirectory=../../../final/python` |
| final-b | 72 | `git+https://github.com/easyrev/lance@ed0a18841f39f845a8e963fd80cfb4d7689d5d43#egg=pylance&subdirectory=../../../shared-buffer-final/python` |
| matched | 72 | `/root/lance/tmp/shared-buffer-followup/matched-project/python` |

以 base 为参照，非 editable 条目差异如下。

- pure 新增 []，缺少 []
- var 新增 []，缺少 []
- final 新增 []，缺少 []
- final-b 新增 []，缺少 []
- matched 新增 []，缺少 []

以下 RSS 单位为 MiB，格式为中位数 [min–max]。每环境和导入方式各 5 个新进程。

| 环境 | import pyarrow | import numpy |
|---|---|---|
| base | 61.96 [61.94–62.51] | 28.34 [27.91–28.93] |
| pure | 66.27 [66.22–66.30] | 33.52 [33.40–34.45] |
| var | 66.25 [65.73–66.32] | 33.89 [33.45–33.99] |
| final | 61.92 [61.36–62.02] | 28.34 [27.86–28.43] |
| final-b | 66.28 [66.22–66.43] | 33.52 [33.41–33.95] |

pyarrow 进程只显式导入 pyarrow，numpy 是它的传递导入。所有采样进程在采样点均未导入 lance。

| 单页构建 | import lance 后 | dataset open 后 | 首次 take(128) 后 |
|---|---|---|---|
| base | 142.74 [141.95–142.87] | 158.34 [157.93–158.87] | 201.34 [200.58–202.89] |
| pure | 150.25 [149.80–150.56] | 166.56 [165.81–166.98] | 210.76 [209.52–211.43] |
| var | 149.96 [149.67–150.61] | 166.30 [166.08–167.20] | 210.33 [208.39–211.87] |
| matched-base | 150.86 [150.50–150.99] | 166.86 [166.55–166.99] | 209.88 [209.23–210.67] |
| matched-pure | 150.34 [150.01–150.93] | 166.35 [165.70–167.05] | 211.32 [209.25–211.73] |

| 比较 | import 后差值 | open 后差值 | 首次 take 后差值 |
|---|---|---|---|
| pure − base | +7.52 | +8.23 | +9.42 |
| var − base | +7.23 | +7.97 | +8.99 |
| matched-pure − matched-base | -0.51 | -0.51 | +1.44 |
| matched-base − base | +8.12 | +8.52 | +8.54 |
| matched-pure − pure | +0.09 | -0.21 | +0.56 |

## 快路径覆盖

| 构建 | 数据集 | 操作 | decode_variable_into | concat_decoded_arrays |
|---|---|---|---|---|
| pure | binary-medium-default | take | 0 | 1 |
| pure | binary-medium-default | scan | 0 | 98 |
| pure | mixed | take | 0 | 1 |
| pure | mixed | scan | 32 | 8 |
| pure | binary-zstd-medium | take | 56 | 0 |
| pure | binary-zstd-medium | scan | 122 | 37 |
| var | binary-medium-default | take | 56 | 0 |
| var | binary-medium-default | scan | 122 | 37 |
| var | mixed | take | 26 | 0 |
| var | mixed | scan | 38 | 5 |
| var | binary-zstd-medium | take | 56 | 0 |
| var | binary-zstd-medium | scan | 122 | 37 |
| final-b | wide-repeated | take | 0 | 1 |
| final-b | wide-repeated | scan | 0 | 8 |
| final-b | wide-clustered | take | 0 | 1 |
| final-b | wide-clustered | scan | 0 | 25 |

## Scan 峰值 RSS

| 序列 | 构建 | 峰值 RSS MiB（每组 7 进程） |
|---|---|---|
| ab | pure | 2249.32 [2083.51–2455.83] |
| ab | var | 2295.77 [2001.70–2492.98] |
| a1 | pure | 2384.70 [2106.71–2495.45] |
| a2 | pure | 2303.61 [2037.22–2371.57] |

- A/B，pure-B-var − pure-B，中位数差 +46.46 MiB（+2.07%）。
- A/A，第二组 − 第一组，中位数差 -81.09 MiB（-3.40%）。
