# 环境与导入 RSS

经确认沿用当前实例。两个 detached worktree 各用独立 Cargo target 和独立虚拟环境。构建配置为 `release-with-debug`，测量设置 `LANCE_CPU_THREADS=64`。base 构建完成后将 Cargo 缓存移至 tmpfs，安装后的扩展路径及 SHA256 保持一致。两套扩展和原始输出位于实例的持久磁盘（根卷）。首次迁移在隔离的命令环境中找不到宿主机上的目标目录。随后在宿主机重试，并复核了迁移前后的扩展哈希。等待构建的测量任务也改在宿主机重启，当时尚未生成数据或采样。详见 [缓存迁移记录](raw/target-base-relocation.log)。

| 构建 | 提交 | 扩展 SHA256 | 5 个进程的峰值 RSS（MiB） | 中位数 [min–max]（MiB） |
|---|---|---|---|---|
| base | `83593e1ada5ef3d01a58eeeb53f375e08416c696` | `28af7a091ad6c445bd4ff7cfbbd993f99e23698df12243645c17a72f5e2e5976` | 150.184, 150.250, 149.895, 149.930, 150.137 | 150.137 [149.895–150.250] |
| head | `d4cac03c93e441e5f3299d8a3a00ffe4365e98f1` | `839aae4cf3f9b50aced929a626b5ce81e419272cb8eaf624841b46158287df1e` | 149.992, 149.980, 149.539, 149.957, 150.512 | 149.980 [149.539–150.512] |

两份 `pip freeze --all` 去掉各自的 pylance 条目后逐字节一致。解释器的实际路径、版本和 SHA256 一致。两个 native 扩展 SHA256 不同。详见 [freeze 与环境审计](raw/environment-match.txt) 和 [完整机器记录](raw/machine.txt)。

## 构建前的宿主机空间

```text
2026-11-26T11:03:13Z
Filesystem      Size  Used Avail Use% Mounted on
/dev/nvme0n1p3   99G   63G   32G  67% /
tmpfs           124G   59G   65G  48% /dev/shm
```

## CPU、内存、系统和工具链

以下为预检命令环境快照。上表是实际执行构建的宿主机空间，后续宿主机快照见 [machine-host.txt](raw/machine-host.txt)。

```text
2026-11-26T11:02:57Z
Architecture:                            x86_64
CPU op-mode(s):                          32-bit, 64-bit
Address sizes:                           52 bits physical, 57 bits virtual
Byte Order:                              Little Endian
CPU(s):                                  64
On-line CPU(s) list:                     0-63
Vendor ID:                               AuthenticAMD
Model name:                              AMD EPYC 9T24 96-Core Processor
CPU family:                              25
Model:                                   17
Thread(s) per core:                      2
Core(s) per socket:                      32
Socket(s):                               1
Stepping:                                1
BogoMIPS:                                5400.00
Flags:                                   fpu vme de pse tsc msr pae mce cx8 apic sep mtrr pge mca cmov pat pse36 clflush mmx fxsr sse sse2 ht syscall nx mmxext fxsr_opt pdpe1gb rdtscp lm constant_tsc rep_good amd_lbr_v2 nopl xtopology nonstop_tsc cpuid extd_apicid aperfmperf tsc_known_freq pni pclmulqdq monitor ssse3 fma cx16 pcid sse4_1 sse4_2 x2apic movbe popcnt aes xsave avx f16c rdrand hypervisor lahf_lm cmp_legacy extapic cr8_legacy abm sse4a misalignsse 3dnowprefetch osvw ibs topoext perfctr_core perfctr_llc mwaitx ssbd perfmon_v2 ibrs ibpb stibp ibrs_enhanced vmmcall fsgsbase tsc_adjust bmi1 avx2 smep bmi2 erms invpcid avx512f avx512dq rdseed adx smap avx512ifma clflushopt clwb avx512cd sha_ni avx512bw avx512vl xsaveopt xsavec xgetbv1 xsaves avx512_bf16 clzero irperf xsaveerptr rdpru wbnoinvd arat avx512vbmi umip pku ospke avx512_vbmi2 gfni vaes vpclmulqdq avx512_vnni avx512_bitalg avx512_vpopcntdq rdpid fsrm amd_lbr_pmc_freeze
Hypervisor vendor:                       KVM
Virtualization type:                     full
L1d cache:                               1 MiB (32 instances)
L1i cache:                               1 MiB (32 instances)
L2 cache:                                32 MiB (32 instances)
L3 cache:                                128 MiB (4 instances)
NUMA node(s):                            1
NUMA node0 CPU(s):                       0-63
Vulnerability Gather data sampling:      Not affected
Vulnerability Indirect target selection: Not affected
Vulnerability Itlb multihit:             Not affected
Vulnerability L1tf:                      Not affected
Vulnerability Mds:                       Not affected
Vulnerability Meltdown:                  Not affected
Vulnerability Mmio stale data:           Not affected
Vulnerability Reg file data sampling:    Not affected
Vulnerability Retbleed:                  Not affected
Vulnerability Spec rstack overflow:      Mitigation; Safe RET
Vulnerability Spec store bypass:         Mitigation; Speculative Store Bypass disabled via prctl
Vulnerability Spectre v1:                Mitigation; usercopy/swapgs barriers and __user pointer sanitization
Vulnerability Spectre v2:                Mitigation; Enhanced / Automatic IBRS; IBPB conditional; STIBP always-on; PBRSB-eIBRS Not affected; BHI Not affected
Vulnerability Srbds:                     Not affected
Vulnerability Tsa:                       Vulnerable: Clear CPU buffers attempted, no microcode
Vulnerability Tsx async abort:           Not affected
Vulnerability Vmscape:                   Not affected
               total        used        free      shared  buff/cache   available
Mem:     265854095360 68034531328 140796104704 63454470144 122808414208 197819564032
Swap:              0           0           0
PRETTY_NAME="Debian GNU/Linux 13 (trixie)"
NAME="Debian GNU/Linux"
VERSION_ID="13"
VERSION="13 (trixie)"
VERSION_CODENAME=trixie
DEBIAN_VERSION_FULL=13.7
ID=debian
HOME_URL="https://www.debian.org/"
SUPPORT_URL="https://www.debian.org/support"
BUG_REPORT_URL="https://bugs.debian.org/"
Linux 6.12.113+deb13-amd64
Filesystem      Size  Used Avail Use% Mounted on
/dev/nvme0n1p3   99G   63G   32G  67% /
tmpfs           124G     0  124G   0% /dev/shm
TARGET      SOURCE                      FSTYPE OPTIONS
/root/lance /dev/nvme0n1p3[/root/lance] ext4   rw,nosuid,nodev,relatime,errors=remount-ro
rustc 1.98.1 (48a229cea 2026-09-01)
uv 0.13.10 (x86_64-unknown-linux-gnu)
```

## 磁盘整理

- `/root/lance/tmp/pr-prep-python-target`
- `/root/lance/tmp/pr-prep-target`
- `/root/lance/tmp/shared-buffer-build/target-pure`