# Bugs History

## 2026-06-18 — 体验版冷启动 wx.redirectTo 在 onLoad 中被静默丢弃（已修复）

- **现象**：体验版小程序杀后台后重新冷启动，即使 storage 中 token 有效且 `[AUTH_DIAG] direct redirect: token valid` 日志已输出，用户仍停留在登录页，不会自动跳转首页。
- **原因**：`wx.redirectTo` 在页面 `onLoad` 阶段（冷启动流程中）被 WeChat 运行时静默忽略。此时视图层级尚未就绪，导航 API 调用不生效。手动点击登录按钮触发跳转正常，因为按钮事件在页面完全渲染后执行。
- **处理**：`_tryDirectRedirect()` 将 `wx.redirectTo` 替换为 `wx.reLaunch`（更彻底的页面栈重置）并包裹在 `setTimeout(..., 100)` 中，确保导航在 `onLoad` 返回、视图层级就绪后执行。
- **验证**：用户确认修复后体验版冷启动可自动跳转首页，问题解决。
- **说明**：WeChat 官方未明确记录此行为，属于运行时实现细节。后续类似 onLoad 中的导航都应使用 `setTimeout + wx.reLaunch` 模式。

## 2026-06-18 — `_extract_stem()` 圈号前缀行误剥离（已修复）

- **现象**：OCR 导入的多选题，题干末尾的 `① A. n + 1` 类行被错误剥离，导致选项 A 部分文本丢失、题干不完整。
- **原因**：`_extract_stem()` 中的 `_OPTION_LINE_RE` 匹配了以 `① A.` 开头的行并将其从题干中剔除，即使上游 OCR 解析并未实际检测到选项（`option_lines` 为空）。该行原本是题干末尾的提示性内容（如"① A. n + 1；② B. 2n"），不应被当成选项行清除。
- **修复**：在 `_OPTION_LINE_RE.match()` 前增加 `option_lines and` 守卫，仅当上游确实提取到选项时才剥离匹配行。
- **验证**：`test_circled_option_like_lines_stay_in_stem` 通过；全量 139 测试通过。

## 2026-06-14 — 小程序答题页整段题干重复显示（已修复）

- **现象**：文本导入后的部分题目在小程序答题页出现整段题干重复显示，尤其是包含多行程序代码和 LaTeX 标记的题干。
- **原因**：问题分两类：一类是题干文本本身出现 `题干块 + 空行 + 同一题干块` 的整段重复拼接；另一类参考 2026-06-02 的相似问题，简单 `$...$` inline math 进入 `mp-html` 富文本链路后可能发生视觉重复。此前只处理了整段文本重复，未覆盖 questionId=11 这类多行题干中包含简单 `$P_1$`、`$z$` 的富文本渲染重复。
- **处理**：`miniprogram/pages/practice/practice.js` 在题干去选项前先折叠重复题干块；同时对多行题干中的简单 `$...$` inline math 做保守纯文本化，避免简单公式题干进入 `mp-html`，复杂公式、HTML、`$$...$$` 仍保留原富文本/公式渲染链路。
- **验证**：`node --check miniprogram/pages/practice/practice.js` 通过；P2 重复块样例验证可折叠为单段；本地 questionId=11 内容验证渲染路径由 `mp-html` 降级为 `text`，且 `$P_1$` 等简单 inline math 被转为 `P₁`。
- **说明**：该修复仅作用于刷题页展示清洗，不修改题库原始数据、不影响答案提交逻辑。

## 2026-06-16 — OCR 规则层三连修：罗马子项假切分、指针箭头、水印过滤（已修复）

- **现象**：含罗马数字子项（I./II./III.）的多选题被误切成两题；OCR 将 `->` 识别成 `− >`（减号+空格+大于号）；水印行"后续关注公众号[研大]""永久微信1866224xxx"混入正文导致错误切分。
- **原因**：
  1. 行首 `I.` 的 OCR 纠正 `I→1` 将罗马子项标记变为阿拉伯题号 `1.`，触发 splitter 边界检测
  2. `->` 在 OCR 中被识别为 `− >`（Unicode 减号 + 空格 + 大于号），纯文本层未还原
  3. 水印行无过滤，被当作题干处理
- **处理**：
  1. `_has_roman_subitem_list` 检测文本中 ≥2 个不同罗马标记时关闭行首 `I.→1.` 纠正；splitter `_find_question_boundaries` 跳过罗马标记行作为边界
  2. `_fix_pointer_arrows` 用正则 `(?<![<>])\s*(?:−|-–|—|–|—)\s*>\s*(?=[a-zA-Z_])` 还原指针箭头
  3. `_RE_WATERMARK` 扩展覆盖「后续关注/关注公众号/永久微信/微信号/公众号/[研大]」等整行水印
- **验证**：4 张实拍图片通过完整管线验证（`faulty_case_1~3.png` + `success_case.png`），假切分消除、指针箭头还原、水印过滤均工作。
- **说明**：镜像乱码、字符误识等引擎层问题仍存在，需在本地 GPU 环境优化 PaddleOCR。

## 2026-06-17 — Canonical Output Layer（统一输出兼容层）（已修复）

- **现象**：Qwen-VL 返回 JSON（`{"option": [...]}`）而非 prompt 要求的纯文本时，`_extract_plain_text` 提取失败 → JSON 检测 → 触发 router 降级 DeepSeek → 浪费请求费用 + 增加响应延迟。若 DeepSeek 也不可用，最终 0 题入库。
- **原因**：Qwen-VL 不严格遵循"禁止输出 JSON"的 prompt 指令；旧架构将 JSON 直接判为失败，未尝试将 JSON 内容转换为可用文本。
- **处理**：新增 `canonical_output.py` 统一输出兼容层，支持：
  - 纯文本 → 直通
  - Markdown 代码块 → 自动剥离
  - JSON（裸或 ` ```json ``` 包裹）→ `json_to_text()` 提取
  - 混合格式 → 容错处理
  JSON 不再直接判定失败，只有无法提取有效内容时才触发 fallback。
  同时增加结构化日志 `[CanonicalOutput] model= type= strategy= length=→`。
- **验证**：30 个单元测试覆盖所有输出类型；Qwen 返回 JSON 时可正确提取选项文本并继续管线。
- **说明**：QwenAdapter 的 `_extract_plain_text`、`_looks_like_json`、`_JSON_CODE_BLOCK_RE` 已删除，统一由 `canonicalize()` 接管。

## 2026-06-17 — Qwen 题干恢复保护层（已修复）

- **现象**：PaddleOCR 识别出带题号 `06.` 的完整文本（题干 + 4 个乱码选项），Qwen-VL JSON 输出被 `canonicalize` 提取后只得到 4 行选项文本，题干完全丢失。block 的 `normalized_text` 被替换为纯选项 → splitter 找不到题号边界 → 创建低置信 fallback 题目 → 入库后题干为空、选项为空、`type=subjective`。
- **原因**：Qwen-VL 只返回 JSON 选项数组（`{"option": [...]}`），不包含题号和题干。`canonicalize` 正确提取了 JSON 中唯一的内容（选项），但失去题干后 splitter 无法正常工作。
- **处理**：`QwenFixer.fix()` 新增 `_preserve_stem_from_original()`：检测 `corrected` 是否为"纯选项"（首行为 `A.`/`B.` 开头）→ 从原文 `ocr_text` 提取题号行及之前的题干 → 拼接到修正文本前。修正文本已有题干 / 原文无题号时不做修改。
- **验证**：4 个单元测试覆盖选项纯文本恢复、已有题干不修改、原文无题号不修改等场景。34 个新测试全部通过。
- **说明**：该保护层与 `canonical_output.py` 协同工作：canonicalize 负责提取，stem preservation 负责补全。

## 2026-06-08 — 文本导入内联格式解析失败（已修复）

- **现象**：文本导入粘贴的题目格式化被破坏（题干、选项、答案、解析全部连成一行），解析器将所有内容归入题干，选项数为 0，答案和解析为空。
- **原因**：三重解析缺陷叠加：
  1. `_INLINE_BATCH_SEP_RE` 要求 `---` 后至少一个空白字符（`\s+`），但粘贴文本中 `---` 紧跟 `**` 无空白，导致多题无法拆分
  2. 行级启发式解析器 `_parse_unlabeled_block` 对单行输入无能为力，全部内容落入 stem
  3. 选项值末尾内联附加答案/解析（如 `D. 8 -8 目标地址 = ...`）时，答案和解析被合并到选项值中
- **处理**：
  1. `_INLINE_BATCH_SEP_RE` 末尾 `\s+` → `\s*`，允许 `---` 后紧跟非空白字符
  2. 新增 `_break_inline_text()` 函数，在选项标记（`A.xxx B.xxx`）前插入换行，将单行文本恢复为多行结构
  3. `_parse_unlabeled_block` 输入 ≤2 行时自动调用 `_break_inline_text()`
  4. `_parse_options_from_text` 新增内联多选项拆分（`_INLINE_OPTION_SPLIT_RE`），一行含多个 `A.xxx B.xxx` 时正确拆分
  5. 选项值解析增加双空格答案/解析分离（`"  "` 分隔）和单字母答案嵌入识别（如 `指令系统 C 虚拟存储器`），含 `len(clean_val) > 4` 防误匹配守卫
- **验证**：回归测试 6 种已有格式通过；`logs.txt` 中两道 408 计组单选题均正确解析出选项、答案和完整解析。
- **说明**：修复仅增强内联/退化文本的容错能力，不影响正常标签格式和行级启发式解析路径。

## 2026-06-07 — OCR/PDF 多空选择题首个选项组 A 选项丢失（已修复）

- **现象**：OCR/PDF 导入后，多空选择题已识别为 `multi_blank_choice`，但审核页中第一个 `blank_option_groups` 只有 B/C/D，第二组为 A/B/C/D。
- **原因**：真实失败记录 `question_imports.id=1163` 的 `raw_text` 在进入 splitter 前已退化为两个普通 `（）`，选项行顺序为 `D/B/C/A/D/B/C`；退化空括号兜底拆组后第一组缺失 A。该问题不是 `①/(1)/Ⅰ` 显式 group marker 与 option prefix 正则冲突。
- **处理**：`question_splitter.py` 新增 `_repair_repeated_degraded_groups`，仅在普通空括号退化、存在完整组、缺 A 组已有 B/C/D 与完整组一致时，从完整组补回 A；显式 grouped options 路径保持不变。
- **验证**：新增真实失败形态回归测试和非重复组选项负例；运行 `PYTHONPATH=/home/lmh/projects/postgraduate-ai/backend pytest -q /home/lmh/projects/postgraduate-ai/backend/tests/test_services/test_question_splitter.py /home/lmh/projects/postgraduate-ai/backend/tests/test_services/test_review_service.py`，结果 `123 passed, 1 warning in 1.04s`。
- **说明**：该修复只作用于 OCR 退化后的多空选择题兜底拆组，不补齐内容不一致的组选项，避免污染非重复组。

## 2026-06-06 — OCR/PDF 教材正文误识别与风险标识缺失（已修复）

- **现象**：扫描版教材 / 书籍 PDF 导入时，正文、知识点讲解或例题解析可能被拆成低置信候选题；人工审核页此前缺少醒目的风险提示，批量通过时存在将正文型候选题发布到正式题库的误操作风险。
- **原因**：book 模式在习题区域漏检、split fallback、AI repair / validation 与 review 提交之间缺少统一风险信号贯通；前端审核页未读取 `question_imports.ai_metadata.risk_flags` 并提示低置信或疑似正文项。
- **处理**：后端已在 OCR/PDF 导入链路贯通 `risk_flags`，覆盖 `no_exercise_regions`、`book_pdf_prose_like`、`low_confidence`、`fallback_low_confidence`、`non_question_like` 等标识，并透传到 `question_imports.ai_metadata.risk_flags`；小程序 import-batch 审核页读取该字段映射中文风险徽章，且“全部通过”前若待审核题含风险标识则弹确认框。
- **验证**：后端风险字段底座提交 `7bbe3c8`；前端风险徽章与批量通过确认提交 `c990950`。
- **说明**：风险标识只辅助人工审核，不绕过 `question_imports` 人工确认流程；未知 flag 前端按原值降级展示。

## 2026-06-06 — 本地扫描 PDF OCR 导入进程被终止（已修复）

- **现象**：本地导入扫描版 PDF 时，后端在进入 OCR fallback 后持续处理页面，日志出现 `Terminated` / `Stopping reloader process`，没有 Python traceback；此前还曾因启动目录不正确出现 `ModuleNotFoundError: No module named 'app'`。
- **原因**：本地 OCR profile 过于激进，`use_gpu=True` 且 `max_workers=4`，扫描 PDF 页渲染、PNG 中间数据、PaddleOCR 推理和 `uvicorn --reload` 同进程叠加，容易触发本地资源压力并被外部终止。启动失败的 `No module named 'app'` 是单独的 `PYTHONPATH` 问题。
- **处理**：将 `backend/app/core/ocr_profile.py` 本地 profile 调整为 CPU 单 worker：`use_gpu=False`、`max_workers=1`，保留本地大文件导入能力但降低瞬时资源占用；启动后端时使用 `PYTHONPATH=/home/lmh/projects/postgraduate-ai/backend`。
- **验证**：后端启动日志确认 `ocr_profile=local (gpu=False, workers=1, max_pdf_pages=0)`；`/health` 返回 `{"status":"ok","env":"development"}`；当前 `logs.txt` 显示 OCR 后续导入链路已成功进入 AI enrich，`POST /api/v1/ai-import/enrich-batch/REVIEW_20260606_152730_c5d293 → 200`，随后 `GET /api/v1/import/batches/REVIEW_20260606_152730_c5d293 → 200`。
- **说明**：本地扫描 PDF OCR 应优先稳定完成导入，不追求 GPU 并发吞吐；生产 2 核 2G 环境仍不建议执行大文件 OCR。

## 2026-06-03 — P0 书籍扫描版 PDF 导入解析超时（已修复）

- **现象**：导入 312 页王道 408 全文扫描 PDF 时，等待 1 小时仍未完成，前端轮询超时报 `request:fail timeout`，后端状态始终为 `parsing`。
- **原因**：多因素叠加：
  1. `_ocr_scanned_pdf()` 串行逐页处理 312 页，无超时保护
  2. 每页触发旋转候选（最多 4 次 OCR 推理），312×4=1248 次推理
  3. 已有的并发接口 `ocr_pages_with_boxes()` 未被使用
  4. `MAX_OCR_PAGES` 默认为 0（无限制）
  5. GPU 多线程并发时 CUDA 冲突导致部分页面失败
- **处理**：
  1. 添加 `OCR_TIMEOUT_SECONDS`（默认 300s）超时保护，超时后返回已处理的部分结果
  2. 批量 PDF 处理跳过旋转候选（`skip_rotation=True`），每页仅 1 次 OCR
  3. 改用 `ocr_pages_with_boxes()` 分批并发处理
  4. 添加 `_ocr_lock` 序列化 GPU 推理，防止 CUDA 冲突
  5. `OCR_MAX_WORKERS` 默认值从 4 降为 2
  6. `.env` 设置 `MAX_OCR_PAGES=200`、`OCR_TIMEOUT_SECONDS=300`
  7. 添加 `ocr_progress` 字段到 pipeline status，前端可显示进度
- **验证**：修复后 312 页 PDF 在 321s 内处理了 148 页（含超时中断），成功返回 41 blocks 并正常进入后续 pipeline 阶段。
- **说明**：生产服务器（2 核 2G）不应运行大文件 OCR，仅在本地开发机（i7+3060）执行后迁移数据。

## 2026-06-02 — 刷题页 `$...$` 简单公式导致题干/选项重复显示（已修复）

- **现象**：OCR 导入的简单 inline math 题目在刷题页出现重复文本，例如题干重复显示，选项显示为 `A. A. S.value < 0`、`B. B. S.value ≤ 0`。
- **原因**：部分 OCR 结果把整组选项写成 `$A. ...$`、`$B. ...$`，而刷题页本身还会渲染选项 key；同时简单 `$...$` 内容进入富文本/LaTeX 渲染链路后，在当前小程序渲染链路中容易出现重复展示。
- **处理**：在 `miniprogram/pages/practice/practice.js` 中对简单 inline math 做保守纯文本化：将常见 LaTeX 命令如 `\\leq`、`\\geq` 转为普通符号；对选项值去除已内嵌的 A/B/C/D 前缀；复杂公式、HTML、`$$...$$` 仍走原有 `mp-html` / `math-question` 渲染。
- **验证**：`node --check miniprogram/pages/practice/practice.js` 通过；`git diff --check -- miniprogram/pages/practice/practice.js` 通过；微信开发者工具验证问题题目已不再重复显示。
- **说明**：该修复仅作用于刷题页展示预处理，不修改题库数据、不修改提交逻辑、不修改 `math-question` / `mp-html` 组件。

## 2026-06-01 — PaddleOCR 本地依赖链导致误报缺失（已修复） 

- **现象**：本地后端调试图片 OCR 时，PaddleOCR 被报告为缺失或不可用。
- **原因**：根因不是单一 Python 包缺失，而是依赖 / 运行时链路问题：先缺少系统库 `libgomp.so.1`，恢复后又遇到 NumPy 2.x 与 `opencv-python` 4.6.x 的 ABI 不兼容。
- **处理**：通过 `run.sh` 统一使用后端虚拟环境解释器；恢复系统依赖 `libgomp1`；在 `backend/requirements-ocr.txt` 中约束 `numpy>=1.26,<2.0`，避免 OpenCV ABI 不兼容。
- **验证**：使用 `backend/.venv/bin/python` 成功导入 `numpy`、`cv2`、`paddleocr`。
- **说明**：后续若再次出现“PaddleOCR 缺失”，应优先检查系统运行库、解释器路径和 NumPy / OpenCV ABI 组合，而不是只重装 `paddleocr`。

## 2026-06-01 — P4 本地后端启动端口占用（已修复）

- **现象**：P4 本地后端依赖检查通过后，启动仍失败。
- **原因**：端口 `8000` 已被既有 `uvicorn` / reloader 进程占用，导致新进程无法绑定监听端口。
- **处理**：停止已有 `uvicorn` / reloader 进程后再启动；或在启动脚本中增加端口占用检查，提前给出明确提示。
- **验证**：依赖检查已通过，失败点定位为端口绑定冲突。
- **说明**：该问题不属于依赖安装失败；排查本地启动失败时应在依赖检查后继续确认端口占用。

## 2026-06-01 — 本地调试图片 OCR 功能未启用（已修复）

- **现象**：小程序本地调试上传图片时，仍提示 `图片OCR功能未启用`；响应详情在部分展示链路中显示为 `{"detail":"å¾ç OCR åè½æªå¯ç¨"}`。
- **原因**：小程序 `miniprogram/config.js` 中 `DEV=false` 时请求会走生产地址，不是本地后端；本地后端图片上传接口又会在进入 OCR 流水线前检查 `settings.OCR_ENABLED`，而 `backend/.env` 未设置 `OCR_ENABLED=true` 时会被提前拦截。乱码是中文错误详情的编码错显，原始后端错误为 `图片 OCR 功能未启用`。
- **处理**：本地调试配置切回 `DEV=true`；在 `backend/.env` 设置 `OCR_ENABLED=true`；OCR 关闭分支日志增加 `APP_ENV` 和 `OCR_ENABLED` 运行时配置输出。
- **验证**：`python3 -m py_compile backend/app/api/v1/imports.py backend/app/core/config.py backend/app/core/security.py backend/app/services/user_service.py` 通过；`node -e "require('/home/lmh/projects/postgraduate-ai/miniprogram/config.js'); console.log('config ok')"` 通过；`PYTHONPATH=/home/lmh/projects/postgraduate-ai/backend python3 -m pytest /home/lmh/projects/postgraduate-ai/backend/tests/test_services/test_dev_permissions.py -q` 通过。
- **说明**：修改 `.env` 后需要重启本地后端进程；否则运行时 `settings.OCR_ENABLED` 仍可能是旧值。

## 2026-05-31 — 开发者模式导入页 403 Permission denied（已修复）

- **现象**：小程序开发者模式进入导入页时，请求 `GET /api/v1/import/batches` 返回 403，前端显示 `Permission denied`，批次列表加载失败；若完全依赖服务端权限，首页题库导入入口又会在本地调试时被隐藏。
- **原因**：本地开发者应具备与超管同等权限，但此前只有前端 `config.DEV === true` 放开了入口，后端 `require_app_permission("import:read")` 仍按真实 RBAC 绑定校验；开发模式登录生成的是 `dev_` openid 普通小程序用户，不会自动建立 `app_user_admin_bindings`。
- **处理**：保留小程序端开发模式管理员入口；后端仅在 `APP_ENV` 为 `development/local/test` 且当前用户 openid 为 `dev_` 前缀时放行应用权限；`/users/me` 对本地开发用户返回 `is_admin=true`、`role=super_admin`、`permissions=["*"]`。
- **验证**：`node -e "require('/home/lmh/projects/postgraduate-ai/miniprogram/utils/auth.js'); console.log('auth ok')"` 通过；`PYTHONPATH=/home/lmh/projects/postgraduate-ai/backend python3 -m pytest /home/lmh/projects/postgraduate-ai/backend/tests/test_services/test_dev_permissions.py -q` 通过。
- **说明**：返回 403 而不是 401 说明 JWT 有效且用户存在，失败点是当前用户未命中 `import:read` 权限。生产环境不按 `dev_` openid 放行，仍要求后台绑定和 RBAC 权限。

## 2026-05-31 — users.is_banned 缺列导致登录/用户查询失败（已修复）

- **现象**：接口查询 `users` 时返回 `UndefinedColumnError: column users.is_banned does not exist`，导致按 openid 查询用户失败。
- **原因**：`User` 模型已包含封禁字段，但历史数据库表结构未完成对应迁移；开发环境 `create_all()` 不会补齐既有表缺失列。
- **处理**：在 `backend/app/core/database.py` 的开发环境 `init_db()` 中增加旧表修复逻辑，自动补齐 `is_banned`、`banned_reason`、`banned_at`、`banned_by` 和 `ix_users_is_banned`。
- **验证**：`PYTHONPATH=backend pytest backend/tests/test_api/test_admin_app_users.py backend/tests/test_services/test_admin_app_user_service.py -q` 通过；手工构造旧 SQLite `users` 表验证启动修复可补齐字段和索引。
- **生产说明**：生产 PostgreSQL 仍应执行 `alembic upgrade head`，对应迁移为 `backend/alembic/versions/g7b8c9d0e1f2_users_add_banned.py`。
