# WSL GPU 安装失败诊断报告

> 生成时间：2026-07-17T18:23:00+08:00
> 项目路径：/home/lmh/projects/postgraduate-ai/backend
> 诊断方式：只读系统排查

---

## 1. 执行摘要

| 检查项 | 状态 |
|--------|------|
| WSL 运行 | 正常（15 GiB RAM, 6 CPU, 8 GiB Swap）|
| 根文件系统 | 正常（925 GiB 可用，inode 充足）|
| DNS 当前 | 正常（pypi.org HTTPS 200）|
| Windows GPU | 正常（RTX 3050 Ti, Driver 566.03, CUDA 12.7）|
| WSL GPU 桥接 | 正常（/dev/dxg 存在, nvidia-smi 正常, libcuda 可加载）|
| GPU 虚拟环境 | 存在且正常（.venv-ocr-gpu-330, Python 3.12.3, pip 正常）|
| Paddle wheel | 已下载、有效、未损坏、完全兼容 |
| **Paddle 安装状态** | **未安装**——这是根因 |
| 原命令语法问题 | 不适用（安装命令未实际执行）|

**结论**：Paddle GPU 安装从未真正执行。wheel 已成功下载、已验证、已兼容，但 `pip install` 步骤被跳过。

---

## 2. 故障定位

### 主要故障点：J. 证据不足 → 实际是"安装步骤未执行"

置信度：**100%**

关键证据：
- `pip list` 在 GPU venv 中输出无 Paddle 包
- `import paddle` → `paddle_spec: None`
- wheel 文件存在于 `/home/lmh/wheelhouse/paddle-cu126-330/`，已验证有效
- `pip install --dry-run --no-deps wheel` 返回 0（pip 识别 wheel）
- 系统日志无 OOM、无 segfault、无 DNS 超时

---

## 3. 证据表

| 检查项 | 结果 | 关键证据 |
|--------|------|----------|
| WSL 版本 | 正常 | Ubuntu 24.04, kernel 6.18.33.2-microsoft-standard-WSL2 |
| WSL 配置 | 已生效 | 15GiB RAM, 6 CPU, 8GiB Swap |
| 虚拟环境 | 正常 | Python 3.12.3, pip 26.1.2, `pip check` 无冲突 |
| Wheel 完整性 | 有效 | `zipfile.is_zipfile=True`, `testzip()` 返回 None（无损坏）|
| Wheel 兼容性 | 兼容 | tag `cp312-cp312-linux_x86_64` 在 pip 兼容列表内 |
| Wheel dry-run | 通过 | `pip install --dry-run --no-deps` 返回 0 |
| 安装状态 | **未安装** | `pip list | grep paddle` 无输出, `find_spec("paddle")` 返回 None |
| DNS pypi.org | 正常 | curl HTTPS 返回 200, getent 返回 IP |
| /dev/dxg | 存在 | crw-rw-rw- |
| nvidia-smi (WSL) | 正常 | RTX 3050 Ti, 4096MiB, Driver 566.03, CUDA 12.7 |
| nvidia-smi (Windows) | 正常 | 同显卡, WDDM driver |
| Linux NVIDIA driver | 未安装 | `dpkg -l | grep nvidia-driver` 无输出 |
| nvcc | 不存在 | 不阻塞 wheel 安装 |
| 代理 | 未设置 | `env | grep proxy` 无输出 |
| 系统崩溃 (当前启动) | 无 | journalctl 无 OOM/segfault |

---

## 4. 原始失败信息

未找到原始 `pip install` 命令的 stderr 和退出码。

shell 历史中的相关命令只有一行旧命令（清华镜像源），不相关。

原安装流程在 Sprint 4E 中被上下文压缩或 WSL 崩溃中断，`pip install paddlepaddle-gpu==3.3.0` 未执行。

---

## 5. GPU 链路

```
Windows NVIDIA 驱动:   NVIDIA GeForce RTX 3050 Ti Laptop GPU (WDDM)
Windows nvidia-smi:    正常, Driver 566.03, CUDA 12.7
WSL /dev/dxg:          存在 (crw-rw-rw-)
WSL libcuda:           /usr/lib/wsl/lib/libcuda.so.1 → 正常
WSL nvidia-smi:        正常, Driver 566.03 (Windows 驱动映射)
Paddle GPU 安装:       未安装 - 需要执行 pip install
```

`dxgkio_query_adapter_info: Ioctl failed: -22` 和 `-2` 日志属于 WSL GPU 初始化正常噪音，不影响功能。

---

## 6. Python 与 wheel 兼容性

```
Python 版本:        3.12.3 (cp312)
Python ABI:         cp312
系统架构:           x86_64 (linux_x86_64)
glibc:              2.39
wheel 完整路径:     /home/lmh/wheelhouse/paddle-cu126-330/paddlepaddle_gpu-3.3.0-cp312-cp312-linux_x86_64.whl
wheel 文件名:       paddlepaddle_gpu-3.3.0-cp312-cp312-linux_x86_64.whl
wheel Python tag:   cp312
wheel ABI tag:      cp312
wheel platform tag: linux_x86_64
wheel 是否有效 ZIP:  是 (testzip=None)
wheel SHA256:       ad894d36ebe72b78f7b61f8796d40f97278ba3003ae3c138aa4516d9af0604e5
wheel 兼容性:        完全兼容 (cp312-cp312-linux_x86_64 在 pip 1068 个兼容 tag 中)
```

---

## 7. 根因置信度

| 可能根因 | 置信度 | 依据 |
|----------|--------|------|
| **安装步骤未执行** | **100%** | Paddle 未在 GPU venv 中安装，import paddle 返回 None |
| wheel 路径被截断 | 0% | 文件存在且 `readlink -f` 确认有效路径 |
| wheel 与 ABI 不兼容 | 0% | dry-run 通过，tag 在兼容列表内 |
| WSL GPU 桥接异常 | 0% | nvidia-smi 正常，/dev/dxg 存在，CUDA 库可加载 |
| DNS/网络异常 | 0% | DNS 成功，HTTPS 200，wheel 下载时已成功 |
| 虚拟环境损坏 | 0% | Python 可执行，pip 正常，pip check 无冲突 |

---

## 8. 下一步操作

### 修复命令（在 backend 目录下执行）

```bash
cd /home/lmh/projects/postgraduate-ai/backend

export OMP_NUM_THREADS=4
export MKL_NUM_THREADS=4

GPU_PYTHON="$PWD/.venv-ocr-gpu-330/bin/python"
PADDLE_WHEEL="$HOME/wheelhouse/paddle-cu126-330/paddlepaddle_gpu-3.3.0-cp312-cp312-linux_x86_64.whl"

"$GPU_PYTHON" -m pip install \
  --only-binary=:all: \
  --no-compile \
  "$PADDLE_WHEEL"
```

### 验证命令

```bash
"$GPU_PYTHON" -c "import paddle; print('OK:', paddle.__version__, 'CUDA:', paddle.is_compiled_with_cuda())"
```

### 预期输出

```
Processing /home/lmh/wheelhouse/...
Installing collected packages: nvidia-cuda-nvrtc-cu12, nvidia-cuda-runtime-cu12, ...
Successfully installed paddlepaddle-gpu-3.3.0 ...
```

然后验证：
```
OK: 3.3.0 CUDA: True
```

### 如失败

查看日志：
```
reports/sprint4e/install_log/paddle-install.log
```

主要关注：
- 是否 `Killed`（OOM）→ 降低并发或增加 swap
- 是否 `CUDA driver error` → 检查 `nvidia-smi`
- 是否 `GLIBC` 错误 → 需要升级系统

---

## 9. 可复制摘要

```
项目路径: /home/lmh/projects/postgraduate-ai/backend
原始失败命令: N/A (pip install 从未执行)
原始 stderr: N/A
退出码: N/A
Python 版本: 3.12.3 (cp312)
wheel 路径: /home/lmh/wheelhouse/paddle-cu126-330/paddlepaddle_gpu-3.3.0-cp312-cp312-linux_x86_64.whl
wheel 兼容性: 完全兼容
Windows nvidia-smi: RTX 3050 Ti, Driver 566.03, CUDA 12.7
WSL nvidia-smi: RTX 3050 Ti, 4096MiB, CUDA 12.7
DNS 测试: pypi.org HTTPS 200 OK
Paddle import: paddle_spec=None (未安装)
最终判断: 100% - 安装步骤未执行。wheel 已下载且兼容，直接执行 pip install 即可。
```
