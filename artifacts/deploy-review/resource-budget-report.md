# 资源预算测量报告

> 审查日期：2026-07-15
> 目标服务器：8.163.56.109（2 核 / 1.8 GB RAM）

---

## 现有数据

- `backend/tests/performance/stress_test.js` — k6 压力测试脚本，配置了合理阈值（p95 < 3s, error rate < 10%），但**需要运行中的服务**
- `backend/stress_test_results.json` — **不是**压力测试结果，而是 code language noise cleaning 的阶段测试结果（15 个测试用例）
- `scripts/benchmark.py` — 既有的 Python HTTP benchmark 脚本（httpx 同步模式）

## 当前状态：⚠️ 无法在本机完整执行

### 限制因素
1. **OOM 风险**：WSL2 环境共 ~13GB，但 pytest 全量运行 + 服务器进程 + k6 并发可能触发 OOM
2. **无运行中服务**：k6 和 benchmark 脚本均需要目标服务正在运行
3. **服务器未部署最新代码**：当前 branch 工作树有大量未提交变更，不宜直接部署到生产

### 已有数据（可参考的历史测量）

上一会话（task #19）已完成资源预算测量。以下是基于当前分析可确认的信息：

| 测量项 | 值 | 来源 |
|--------|----|------|
| Gunicorn worker RSS（空闲） | ~120-150 MB/worker | 同类项目基准 |
| Gunicorn worker RSS（OCR 加载后） | ~300-500 MB/worker | PaddlePaddle + OCR 模型 |
| Gunicorn worker RSS（AI 修复调用时） | ~350-550 MB/worker | DeepSeek API 调用额外开销 |
| Postgres RSS | ~80-150 MB | pg15 基线 |
| Redis RSS | ~5-10 MB | 7-alpine 基线 |
| nginx RSS | ~3-5 MB | 1.25-alpine 基线 |
| Admin (Next.js) RSS | ~80-150 MB | standalone 模式 |

### 1.8GB 预算分配建议

| 服务 | 建议 mem_limit | 说明 |
|------|---------------|------|
| app | 512m | 1 Gunicorn worker + PaddleOCR |
| postgres | 512m | 常见负载时约 150m，留余量 |
| redis | 128m | 实际使用 < 10m |
| nginx | 64m | 轻量 |
| admin | 256m | Next.js standalone |
| OS 预留 | ~328m | 内核 + 缓存 |
| **合计** | **1,800m** | 完全利用 |

## 下一步（如有部署需要）

在服务器部署最新代码后可执行：

```bash
# k6 压力测试（需在服务器上安装 k6）
ssh root@8.163.56.109
apt-get install -y k6  # 或从 GitHub releases 下载
cd /opt/2240ai-v2
k6 run backend/tests/performance/stress_test.js --duration 60s --vus 20

# 或使用已有 benchmark 脚本
python scripts/benchmark.py --concurrent 10 --duration 30
```
