# Deploy Bugs History — 部署问题与修复记录

> 2026-11-08 自 `docs/project/DEPLOY_PLAN.md` §9 拆分，编号沿用原 §9.x（含原始排列顺序 9.1/9.2/9.5/9.3/9.4）。
> 现行部署操作见 `docs/project/DEPLOY_PLAN.md`；生产发布记录见 `docs/project/DEPLOY_CHANGELOG.md`；产品缺陷史见 `docs/project/BUGS_HISTORY.md`。

---

## 9. 2026-08-15/16 部署问题与修复记录

> 本节记录本次全量部署过程中发现并修复的生产问题，供后续部署参考。

### 9.1 生产 Redis 任务队列无消费者（worker 服务缺失）— 重大

**现象：** 任务健康监控持续报 `ANSWER_PROJECTION_BACKLOG` + `QUEUE_STALLED`；practice_records 多条无 `answer_behaviors` 投影回执，对账器每小时重建修复任务但无人执行。

**根因：** 生产 compose 只有 web + scheduler，**没有 `worker` 服务**。`run_dispatcher_v2`（Redis `taskq:v2:*` 唯一消费方）仅在 `PROCESS_ROLE=worker` 时启动；scheduler 的 outbox dispatcher 只负责把 outbox 发布到 Redis，不消费。因此掌握度/Leitner/自适应/推荐反馈等派生状态从未更新。

**修复：** `deploy/docker-compose.prod.yml` 新增 `worker` 服务（与 scheduler 同镜像，`python -m app.worker_main`，mem_limit 384m，挂 `exports_data` 卷）。

**验证：** worker 启动后 `v2 Dispatcher started`，投影积压清零，健康监控 `Async task health recovered`。

> ⚠️ **`deploy.sh update-all` 只重建 app+scheduler+admin，不覆盖 worker。** worker 需单独执行：
> ```bash
> docker compose --env-file backend/.env -f deploy/docker-compose.prod.yml build worker
> docker compose --env-file backend/.env -f deploy/docker-compose.prod.yml up -d --no-deps worker
> ```

### 9.2 worker 服务生产校验要点（启动被拦截的坑）

worker 启动经过两道校验，缺一不可：

| 校验 | 要求 | 坑 |
|------|------|-----|
| `production_config_validator` | `OCR_USE_GPU` 必须显式 `false`（对所有角色强制，config 默认 True） | 漏配即拒绝启动 |
| 同上 | `EXPORT_DIR` 目录可写 | 必须显式 `EXPORT_DIR=/opt/22408-ai/exports` 且挂 `exports_data` 卷（首次挂载继承镜像 chown 的 app:app）；漏配会按相对路径 `var/exports` 创建失败 |
| `OcrRuntimeConfig`（`_init_worker_dependencies` 无条件调用 `get_runtime_config()`） | `OCR_EXECUTION_BACKEND=disabled` 时无需 remote token | 若为 `paddlex_http` 且 production，强制要求 `remote_auth_token` |

**OCR 配置原则：** 服务器 OCR 仅由 **web 进程经外部 API**（PaddleOCR-VL aistudio，paddlex_http）完成，worker 不承载 OCR。因此 worker 环境硬编码：

```yaml
OCR_USE_GPU: ${OCR_USE_GPU:-false}
OCR_EXECUTION_BACKEND: "disabled"
```

> ⚠️ `OCR_EXECUTION_BACKEND` 必须**硬编码 `disabled`**，不可写 `${OCR_EXECUTION_BACKEND:-disabled}`——服务器 `.env` 的 `paddlex_http` 会覆盖变量默认值，导致 worker 再次因缺 `remote_auth_token` 拒绝启动。

### 9.5 函数图像真机渲染慢优化（2026-09-20）

**现象：** 管理端上传的函数图像在miniprogram函数图像列表页（`subpackages/formulas/library`）与速记卡阅读页（`subpackages/formulas/reader`）真机渲染明显缓慢，列表滚动时图像逐张长时间空白。

**根因（按影响排序）：**
1. **上传主图未压缩**：`formula_graph_asset_service` 曾按原图存储（最大 8000×8000、10MB），PNG 无损未优化；生成型图像固定 1600×1000 PNG。真机经 HTTPS 拉取数 MB 图像耗时数秒。
2. **列表页加载大图**：`graphPreviewUrl` 优先取 `graphImageUrl`（全尺寸主图），而列表卡片显示区仅 360rpx 高。
3. **阅读页无渐进加载**：仅挂大图 URL，慢网络下长时间空白。

**修复：**
- 后端上传路径（`backend/app/services/formula_graph_asset_service.py`）：主图统一缩放至长边 ≤1600（`MAX_STORED_DIMENSION`）并 PNG `optimize` 重编码；缩略图同样 `optimize`。仅影响新上传。
- 存量回填（`backend/scripts/backfill_formula_graph_image_size.py`，`--dry-run`/`--apply`）：本地存储（`STORAGE_BACKEND=local`）的就地重压缩，同对象键覆写并更新 DB 宽高/大小；外部对象存储 URL 自动跳过。服务器执行：
  ```bash
  cd /opt/22408-ai/backend
  docker compose --env-file backend/.env -f deploy/docker-compose.prod.yml exec app \
    python scripts/backfill_formula_graph_image_size.py --dry-run   # 先预览
  # 确认后再 --apply
  ```
- 小程序列表页：`graphPreviewUrl` 改为 `resolveGraphPreviewUrl()`（缩略图优先，无缩略图回退主图），逻辑收敛在 `subpackages/formulas/utils/formula-graph.js`。
- 小程序阅读页：`formula-card` 组件渐进加载——先显示缩略图，页内隐藏 preloader `<image>` 预载主图，`bindload` 后切换为主图；主图失败时保留缩略图。状态机 `computeDisplayGraphUrl()` 与列表页共用。
- 小程序阅读页图像显示比例（同日补充修复）：`.fc-graph-image` 曾带历史遗留的 `transform: scale(1.12)`（整体放大 12% 并被 `overflow:hidden` 裁边），且主图用 `widthFix` 按自然比例撑高，加载完成后区块突然变高。现改为**固定宽高比视口**：`fc-graph-viewport` 用内联 `padding-bottom:{{graphViewportRatio}}%` 钉住高度（比例取 `graph_asset.width/height`，钳制 25%–125%，缺元数据回退 75% 即 4:3），图像统一 `aspectFit` 填充（`computeGraphViewportRatio()` 位于 `formula-graph.js`）。缩略图→主图切换零布局跳动，异常长图在视口内 letterbox 显示而非拉伸卡片。
- nginx `/static/formulas/` 已有 `expires 30d; Cache-Control public, immutable`（URL 含内容寻址段），压缩后字节数下降直接减少真机首屏流量；无需改动。

**持久化：** `deploy/docker-compose.prod.yml` 中 app、scheduler、worker 都挂载命名卷 `formulas_data:/app/static/formulas`。运行期上传写在卷内 `graphs/{id}/uploaded`，容器重建不丢图。空卷首次挂载会带入镜像里已有的公式静态文件。

**AI 预热题图：** `prewarm_analysis` 在 worker 中运行，必须与 app 共享 `question_assets_data` 卷；app 与 worker 共同挂载 `/app/static/question-assets`（生产启动校验要求该目录可写）。否则 worker 无法从本地读取运行期上传的题图，在远程抓取不可用时会将有题图的题目误判为 `vision_input_missing`。仅修改 Compose 文件不会更新运行中的容器；应用时需单独重建 worker 容器（不删除卷），并按需手动重试已经进入死信队列的任务。

**2026-11-06 共享 AI 健康与预热重试修复（后端已发布，客户端与真实任务待复验）：** 旧版成功标识仅 30 秒有效，过期后的 `checking` 与实际服务故障均返回不可重试的 `ai_service_unavailable`，预热 worker 将尝试预算缩为 1 并立即死信，手动重试继续继承此预算。新逻辑共享成功状态 30 分钟、5 分钟后按需后台刷新且保留有效入口；实际成功续期，失败按类型冷却，配置指纹继续隔离。检查中、暂时故障与状态存储不可用沿现有队列有界退避，管理员重试历史可用性死信时恢复至少 3 次尝试。app 与 worker 已配套更新，真实连接探测和跨容器共享 Redis 状态通过，详见 `docs/project/DEPLOY_CHANGELOG.md` §0.2；未重放历史死信或验证真实题目预热。后续从后台审计入口逐条重试，观察原因和最终缓存，不能把点击重试当成成功。

**回填脚本提交注意：** `.gitignore` 第 98 行忽略 `backend/scripts/`，该目录既有脚本均为 `git add -f` 跟踪；新脚本需同样 `git add -f backend/scripts/backfill_formula_graph_image_size.py`。

**暂存目录：** `WORKER_SCRATCH_DIR=/tmp/scratch` 用容器 1777 `/tmp` 临时区即可，**不要挂命名卷**（命名卷 root 属主，非 root 的 app 用户不可写）。

### 9.3 `ai_service.py` `analyze_error` 的 `model_name` 未定义 bug

**现象：** worker 的 prewarm 任务（以及同步 `/api/v1/ai` 错因解析）全部失败，日志 `NameError: name 'model_name' is not defined`。

**根因：** `result.get("model", model_name or "")` 的默认值会先于 `.get` 求值，而 `model_name` 从未定义，导致任何成功到达该行的 AI 解析都抛 NameError。

**修复：** 两处（`_meta` 与返回响应）改为 `result.get("model", "")`。`chat_with_db_model` 返回始终含 `model` 键，默认值不会触发。

### 9.4 容器时区与北京时间时差

**现象：** 容器日志时间比北京时间慢 8 小时。

**根因：** 服务器系统时区是 `Asia/Beijing`（正确），但 Docker 容器默认 UTC（TZ 为空）。

**修复：** compose 给 app/scheduler/worker/admin 设 `TZ: Asia/Shanghai`。**安全性**：DB 时间戳一律 `utcnow()`（显式 UTC，不受进程 TZ 影响）；APScheduler 显式 `AsyncIOScheduler(timezone="UTC")` 调度不变；产品时区（study_day/pomodoro）用显式 UTC+8 换算。裸 `datetime.now()` 仅用于 ID 后缀/瞬时 Redis 状态/时长差，无入库污染。

> admin 镜像缺 tzdata，容器内 OS `date` 仍显示 UTC；但 Node 进程尊重 `TZ`，SSR 显示北京时间正确，无需处理。

---

---

## 相关链接

- [[docs/project/DEPLOY_PLAN.md|DEPLOY_PLAN]] — 部署架构、流程与环境变量（现行操作）
- [[docs/project/DEPLOY_CHANGELOG.md|DEPLOY_CHANGELOG]] — 生产发布与部署变更记录
- [[docs/project/BUGS_HISTORY.md|BUGS_HISTORY]] — 产品缺陷历史归档
- [[docs/project/CHANGELOG.md|CHANGELOG]] — 项目变更记录
- [[docs/INDEX.md|INDEX]] — 文档总索引
