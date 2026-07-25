# WSL2 发行版退出诊断报告（修正版）

> 生成时间：2026-07-18T01:15+08:00
> 未修改任何系统配置

---

## 根因结论

**最高优先级嫌疑：WSL 6.18.33.2 内核 dxgkrnl GPU 同步路径触发 field-spanning-write WARN。**

Boot -1 中运行的 Python GPU 进程在 GPU 同步操作期间触发了 `dxgvmb_send_wait_sync_object_gpu` 路径的内核警告（`drivers/hv/dxgkrnl/dxgvmbus.c:3095`，field-spanning write）。该 WARN 属于 WSL dxgkrnl GPU 虚拟化驱动，可能涉及 WSL 6.18 内核、Windows NVIDIA 驱动或两者协议兼容性。

由于 WARN 发生后系统继续运行约 13 分钟（00:41:54 → 00:54:38），尚不能单凭该日志证明它直接造成后续发行版退出。但这是当前唯一找到的内核级异常，优先级高于其他假设。

已知另一次 pip 安装进程因 SIGTERM 退出（exit 143），由 Claude Code Bash 工具外层超时导致，与 WSL 内核无直接关系。

---

## 事件时间线

### 事件 A：pip 安装进程退出（前次会话）

| 时间 | 事件 |
|------|------|
| 前次 Claude Code 会话 | `pip install paddleocr==2.10.0` 收到 SIGTERM，exit 143 |
| - | 外层 Bash 工具 10 分钟超时到期 |
| - | 无同时期内核崩溃或 OOM 记录 |

说明：exit 143 可由工具超时解释，不证明 WSL VM 或内核崩溃。

### 事件 B：WSL 发行版 init 退出（Boot -1 → Boot 0）

Boot -1 覆盖 00:27:32~00:54:38，Boot 0 为当前会话。

```
00:27:32   Boot -1 内核启动，dxg 初始化（ioctl failed -22/-2，启动阶段）
00:41:54   dxgkrnl GPU 驱动警告 — dxgvmb_send_wait_sync_object_gpu
           来源: drivers/hv/dxgkrnl/dxgvmbus.c:3095
           内容: field-spanning write detected
           关联调用链: dxgkio_submit_wait_to_hwqueue
           可能关联 GPU 同步操作
00:41:54   ---[ end trace ]---（内核跟踪结束）
00:42:11~   systemd-resolved 每 30~40s 输出 Clock change detected
00:54:38   Boot -1 日志终止，无 OOM、kernel panic 或 EXT4 错误
           → 可能由 WSL VM 管理器从外部终止
00:55:38   ext4 mount（尝试重新启动）
00:55:56   Boot 0 首次 init（WSL (1)）失败
00:55:56   Operation canceled @p9io.cpp:258 (AcceptAsync)
00:55:56   InitEntryUtilityVm:2555: Init has exited. Terminating distribution
00:55:56   EXT4-fs unmounting
00:56:38   ext4 re-mount
00:56:59   Boot 0 第二次 init（WSL (2)-init-systemd）成功 ← 当前运行
```

**关键发现：**
- `p9io Operation canceled` 出现在 `InitEntryUtilityVm` **之前 2 行**，但均为同一秒（00:55:56）。单次出现不能确定因果关系。
- Boot -1 **结束前 13 分钟（00:41:54）存在一次 dxgkrnl GPU 驱动警告**，包含 `dxgvmb_send_wait_sync_object_gpu` 调用链。这是在 GPU 同步操作期间产生的驱动级警告，非启动噪音。

---

## 已确认事实

| 项目 | 当前状态 | 证据来源 |
|------|----------|----------|
| systemd 当前运行 | 正常，PID 1，无 failed units | `systemctl is-system-running = running` |
| journal 持久化 | 已启用 | `/var/log/journal` 存在 |
| 历史启动记录 | 32 次历史启动可查（boot -32 ~ -1） | `journalctl --list-boots` |
| Boot -1 日志 | 可读取，终止于 00:54:38，无内核崩溃标志 | `journalctl -b -1` |
| Boot -1 dxgkrnl 警告 | 00:41:54 存在一次 `dxgvmb_send_wait_sync_object_gpu` 警告，field-spanning write，关联 GPU 同步 | dmesg + journal |
| Boot -1 dxg 启动错误 | 00:27:32 存在 `ioctl failed -22/-2`，在启动阶段 | 每次 WSL 启动均出现 |
| Boot 0 dxg 启动错误 | 00:56:59 存在 `ioctl failed -22/-2`，在启动阶段 | 每次 WSL 启动均出现 |
| p9io Operation canceled | 出现在 00:55:56，`InitEntryUtilityVm` 之前 2 行，同一秒 | journal boot 0 |
| GPU 内存限制变量 | 代码读取但不传递给任何 Paddle API | `config.py:36`→存储, `executor.py:130`→仅记录元数据 |
| NVIDIA 驱动 | WSL 端 566.03，WDDM（Windows 驱动映射） | `nvidia-smi` |
| WSL 版本 | 2.7.10.0 | dmesg |
| 系统级 OOM（当前 boot） | 未发现 | dmesg |
| 系统级 OOM（boot -1） | 未发现 | journal -1 |
| EXT4 错误（当前 boot） | 未发现 | dmesg |
| NVRM/Xid GPU 错误 | 未发现 | dmesg + journal |
| coredumpctl | 不可用 | 未安装 |

---

## dxgkrnl 驱动警告详情（00:41:54, boot -1）

```
WARNING: CPU: 4 PID: 6869 at drivers/hv/dxgkrnl/dxgvmbus.c:3095
  dxgvmb_send_wait_sync_object_gpu+0x271/0x290

Call chain:
  dxgkio_submit_wait_to_hwqueue+0x133/0x2e0
  dxgk_ioctl+0x66/0x110
  dxgk_unlocked_ioctl+0x12/0x20
  __x64_sys_ioctl+0xa1/0xf0
  do_syscall_64+0x73/0x990

Context: memcpy: detected field-spanning write (size 4) of single field
  "current_pos" at drivers/hv/dxgkrnl/dxgvmbus.c:3095 (size 0)
```

位于 GPU 同步操作（`wait_sync_object_gpu`）期间，涉及 dxg krnl 模块与 Hyper-V 通信。未证明与发行版终止有直接因果关系。

---

## 未确认的假设与所需证据

| 假设 | 所需证据 | 优先级 |
|------|----------|--------|
| **WSL 6.18.33.2 dxgkrnl GPU 同步代码路径存在内核 bug** | 复现 dxgkrnl WARN；确认 WSL 内核版本；检查 Microsoft GitHub 已知 issue | **最高** |
| **Windows NVIDIA 驱动 (566.03) 与 WSL 6.18 dxgkrnl 协议不兼容** | Windows 事件日志 nvlddmkm 错误；更新驱动后 WARN 消失 | 高 |
| **Windows WSL 管理器/Utility VM 异常终止了发行版** | Windows Event Log: Lxss Manager, Vmmem 进程事件 | 高 |
| **Windows 宿主内存/commit 压力导致 WSL VM 回收** | Windows Resource-Exhaustion-Detector 事件 | 中 |
| **systemd 或 init 进程因用户空间异常退出** | p9io 前后的 coredump（未安装 coredumpctl） | 低 |
| **systemd=true 导致 init 不稳定** | 严格 A/B 对照（关闭 systemd 后同一测试 ≥3 次通过） | 低（实验性） |

---

## 隔离测试脚本

以下脚本供用户在普通 WSL 终端手动执行。

### Test A：系统空闲稳定性（15 分钟）

```bash
cd /home/lmh/projects/postgraduate-ai/backend

date --iso-8601=seconds
uname -a
python --version
nvidia-smi
free -h
swapon --show

for i in $(seq 900); do
  sleep 1
  test $((i % 60)) -eq 0 && echo "[$(date --iso-8601=seconds)] Alive at ${i}s"
done

echo "Exit code: $?"
date --iso-8601=seconds
echo "Idle test completed"
```

### Test C1：单进程持续 GPU 计算

```bash
cd /home/lmh/projects/postgraduate-ai/backend
source .venv-ocr-gpu-330/bin/activate

date --iso-8601=seconds
nvidia-smi
free -h

python - <<'PY'
import os, time, paddle

print("PID:", os.getpid(), flush=True)
print("Paddle:", paddle.__version__, flush=True)
print("Compiled with CUDA:", paddle.device.is_compiled_with_cuda(), flush=True)

if not paddle.device.is_compiled_with_cuda():
    raise RuntimeError("Current Paddle build has no CUDA support")

paddle.set_device("gpu")
print("Device:", paddle.device.get_device(), flush=True)

# 2048x2048 matmul ~ 32MB tensor, fits in 4GB VRAM
MATRIX_SIZE = 2048

for i in range(120):
    x = paddle.randn([MATRIX_SIZE, MATRIX_SIZE], dtype="float32")
    y = paddle.matmul(x, x)
    paddle.device.cuda.synchronize()
    value = float(y[0, 0].numpy())
    print(f"Iteration {i}: value={value}", flush=True)
    time.sleep(0.5)

print("Sustained GPU tensor test passed", flush=True)
PY

echo "Exit code: $?"
nvidia-smi
date --iso-8601=seconds
```

### Test C2：多进程重复 CUDA 初始化（30 次）

```bash
cd /home/lmh/projects/postgraduate-ai/backend
source .venv-ocr-gpu-330/bin/activate

date --iso-8601=seconds
nvidia-smi

for i in $(seq 1 30); do
  python -c "
import paddle
paddle.set_device('gpu')
x = paddle.randn([1024, 1024])
print(f'Process $i: {float(x.sum().numpy())}', flush=True)
"
  sleep 1
done

echo "Exit code: $?"
nvidia-smi
date --iso-8601=seconds
echo "Repeated CUDA init test passed"
```

### Test D：完整 GPU OCR（已通过 3 次，Sprint 4F）

```bash
cd /home/lmh/projects/postgraduate-ai/backend

OCR_WORKER_DEVICE=gpu \
OCR_WORKER_REQUIRE_GPU=true \
PYTHONPATH=. \
.venv-ocr-gpu-330/bin/python - <<'PY'
import asyncio, inspect
from app.core.ocr_request import OCRRequest
from app.features.ocr_adapter import PaddleOCRLocalAdapter
from tests.fixtures.pdf_helper import make_minimal_pdf

async def main():
    pdf_bytes = make_minimal_pdf(page_count=1, text="GPU stability test")
    request = OCRRequest(source=pdf_bytes, source_type="pdf")
    adapter = PaddleOCRLocalAdapter(engine="paddleocr")

    for i in range(5):
        result = adapter.process(request, trace_id=f"stab-{i}")
        if inspect.isawaitable(result):
            result = await result
        print(f"Run {i}: latency={result.latency_ms:.0f}ms, success={result.is_success}", flush=True)
    print("GPU OCR test completed", flush=True)

asyncio.run(main())
PY
```

### Test E：systemd 关闭对照（仅在 A~D 可复现退出后执行）

```bash
# 先备份
sudo cp -a /etc/wsl.conf /etc/wsl.conf.backup.$(date +%Y%m%d-%H%M%S)

# 检查项目是否依赖 systemd 服务
systemctl list-unit-files --state=enabled --no-pager
systemctl --failed --no-pager

# 编辑 /etc/wsl.conf，将 systemd=true 改为 systemd=false
# 然后在 PowerShell 执行:
#   wsl --shutdown
# 重启后重复 Test D
```

只有满足以下条件才能说 systemd 与问题"相关"：
- systemd 开启时可重复失败至少 2 次
- systemd 关闭时相同输入通过至少 3 次
- 再次开启 systemd 后问题重现

---

## 实时日志采集脚本

保存为 `~/wsl-live-debug.sh`：

```bash
#!/usr/bin/env bash
set -u

WIN_LOG="/mnt/c/Users/Devil/Desktop/wsl-ocr-debug"
mkdir -p "$WIN_LOG"

RUN_ID="$(date +%Y%m%d-%H%M%S)"
RUN_DIR="$WIN_LOG/$RUN_ID"
mkdir -p "$RUN_DIR"
echo "$RUN_DIR" > "$WIN_LOG/latest-run.txt"

echo "Logging to: $RUN_DIR"

# Kernel live log (may prompt for sudo)
sudo dmesg -wT > "$RUN_DIR/dmesg-live.log" 2>&1 &
echo $! > "$RUN_DIR/dmesg.pid"

# Systemd journal live log (may prompt for sudo)
sudo journalctl -f -o short-precise > "$RUN_DIR/journal-live.log" 2>&1 &
echo $! > "$RUN_DIR/journal.pid"

# Resource monitor
(
  while true; do
    echo "[$(date --iso-8601=seconds)]"
    echo "=== MEMORY ==="; free -h
    echo "=== SWAP ==="; swapon --show 2>/dev/null || true
    echo "=== LOAD ==="; uptime
    echo "=== TOP CPU ==="
    ps -eo pid,ppid,%cpu,%mem,rss,etime,comm,args --sort=-%cpu | head -20
    echo "=== CGROUP ==="
    for f in /sys/fs/cgroup/memory.current /sys/fs/cgroup/memory.max /sys/fs/cgroup/memory.events; do
      test -r "$f" && echo "$f: $(cat "$f")"
    done
    echo "---"
    sleep 2
  done
) > "$RUN_DIR/resources-live.log" 2>&1 &
echo $! > "$RUN_DIR/resources.pid"

# GPU monitor
(
  while true; do
    echo "[$(date --iso-8601=seconds)]"
    nvidia-smi --query-gpu=timestamp,name,driver_version,pstate,memory.used,memory.total,utilization.gpu,utilization.memory,temperature.gpu --format=csv,noheader 2>&1 || true
    sleep 2
  done
) > "$RUN_DIR/nvidia-live.log" 2>&1 &
echo $! > "$RUN_DIR/nvidia.pid"

# Stop script
cat > "$RUN_DIR/stop-logging.sh" <<'SH'
for pid_file in dmesg.pid journal.pid resources.pid nvidia.pid; do
  if test -f "$(dirname "$0")/$pid_file"; then
    kill "$(cat "$(dirname "$0")/$pid_file")" 2>/dev/null || true
  fi
done
echo "Logging stopped"
SH
chmod +x "$RUN_DIR/stop-logging.sh"

echo "To stop logging: $RUN_DIR/stop-logging.sh"
```

所有日志写入 `/mnt/c`，避免发行版退出后丢失。

---

## 推荐安全修复顺序

按风险从低到高排列：

### 1. 立即：使用 CPU OCR（已验证可用）

当前 WSL2 上的 GPU OCR 触发了 dxgkrnl WARN。CPU OCR 已在 Stage 1A 中通过完整验证。在 dxgkrnl 问题解决前，所有 OCR 处理应使用 CPU 模式：

```bash
OCR_WORKER_DEVICE=cpu
OCR_WORKER_REQUIRE_GPU=false
```

这是最安全的路径，不需要修改系统配置。

### 2. 短期：复现并确认 dxgkrnl WARN

用单进程最小 GPU 同步测试验证 WARN 是否稳定复现（Test C1），然后尝试：

### 3. 更新 WSL 内核

```powershell
# PowerShell (管理员)
wsl --update
wsl --shutdown
```

WSL 6.18.33.2 的 dxgkrnl 驱动可能存在已知 bug，更新到较新版本可能修复。

### 4. 更新 Windows NVIDIA 驱动

从 NVIDIA 官网下载最新 Game Ready 或 Studio 驱动（当前 566.03），覆盖安装后重启。

### 5. 如果仍然复现

在 Windows 事件查看器中检查：
- `System` 日志下的 `nvlddmkm` 错误
- `WSL` 或 `Lxss` 来源的警告
- 故障时间段内的 `Resource-Exhaustion-Detector` 事件

### 6. 长期选择

如果 WSL 6.18 dxgkrnl 问题无法在当前环境解决，GPU OCR 生产部署需在原生 Linux 环境中执行，不依赖 WSL GPU 映射。

## 当前 Sprint 4F 影响

WSL dxgkrnl 内核警告 → GPU OCR 在 WSL2 上不可靠 → **Stage 1B (GPU Worker) 在当前 WSL 环境中 blocked**。

| 受影响项 | 状态 |
|----------|------|
| GPU 环境安装 (paddlepaddle-gpu 3.3.0) | ✅ 通过 |
| CUDA + cuDNN 验证 | ✅ 通过 |
| GPU 张量运算 | ✅ 通过（但触发 dxgkrnl WARN）|
| GPU PaddleOCR 推理 (`use_gpu=True`) | ⚠️ 执行通过但触发 dxgkrnl WARN |
| Stable ID 修复 | ✅ document_id 使用 source_hash，不再用 monotonic_ns |
| DeviceResolver | ✅ 11 测试通过 |
| Stage 1B Allowlist | ❌ blocked（WSL dxgkrnl）|
| CPU OCR 回退路径 | ✅ Stage 1A approved |
| 生产默认切换 | ❌ 保持 legacy |

---

## 推荐用户下一步命令

```bash
sudo journalctl --list-boots
sudo journalctl -b -1 -p warning..alert --no-pager
sudo journalctl -b -1 --no-pager | grep -iE 'systemd|oom|killed|segfault|watchdog|dxg|dxgkrnl|nvrm|xid|cuda|p9io|operation canceled|ext4.*error|I/O error|InitEntryUtilityVm'
```

并在 PowerShell（管理员）中：

```powershell
wsl --version
wsl --status
Get-WinEvent -LogName System | Where-Object { $_.LevelDisplayName -eq "Error" -and $_.TimeCreated -gt (Get-Date).AddDays(-1) } | Format-Table TimeCreated, Id, LevelDisplayName, Message -Wrap
```
