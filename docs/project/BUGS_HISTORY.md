# Bugs History

## 2026-09-12 — 开发者工具代码扫描仍提示主包体积超限（已修复）

- **现象**：首次清理主包后，开发者工具代码扫描仍提示体积风险；实际检查发现 `study` 分包源码约 1.52MB，接近/超过部分工具按 1.5MB 执行的扫描阈值。
- **根因**：知识图谱页面（`knowledge-subject`、`knowledge-detail`）与刷题、错题等页面共用 `subpackages/study` 根目录，知识图谱页面及其约 125KB WXSS 使 study 分包达到边界。
- **处理**：新增独立 `subpackages/knowledge` 分包并迁移两个知识图谱页面；同步首页、学习看板、刷题结果和返回导航路径，首页/看板预加载新增 `knowledge` 分包；更新 sitemap 与主包体积回归配置。
- **验证**：使用微信官方 `miniprogram-ci` 静态分析，源码目录主包为 766,900 bytes（约 749KiB），Windows 镜像 `D:\workspace\postgraduate-ai\miniprogram` 主包为 674,556 bytes（约 659KiB）；`study` 分包为 1,242,239 bytes（约 1.21MiB），`knowledge` 分包为 282,574 bytes（约 276KiB），各包均低于 1.5MB 扫描阈值且无依赖错误。若开发者工具仍显示旧体积，应确认打开的是该 Windows 镜像并完全重载项目后再扫描，界面缓存结果尚未单独确认。

## 2026-09-11 — 微信小程序主包超过 1.5MB，开发者工具无法上传（已修复）

- **现象**：在微信开发者工具上传小程序代码时提示主包体积超过 1.5MB，代码无法上传。
- **根因**：主包目录中残留了未被运行时引用的重复资源，包括根目录 `utils/katex.min.js`（约 270KB）、根目录 AI 老师实现、重复的 `AnimatedView` 和 `mp-user-avatar` 组件；部分缓存及 Windows `Zone.Identifier` 文件也未明确排除。
- **处理**：删除上述无运行时引用的主包副本，继续使用 `subpackages/formulas`、`subpackages/study` 及页面本地组件中的实现；更新 `project.config.json` 排除 `.claude`、`.pytest_cache`、`.ruff_cache` 和 `.Zone.Identifier` 文件；新增 `miniprogram/tests/test-main-package-size.js` 主包体积回归检查，并修正 408 AI 回归脚本引用分包实现。
- **验证**：主包估算体积约 432.7KiB，低于微信 1.5MB 限制；主包体积检查、408 AI 老师及小程序代码模式、配置、导出、LaTeX、多空答案和渲染回归测试通过。

## 2026-06-27 — SQLAlchemy 全量日志刷屏 + question_imports 列表查询拉取大字段（已修复）

- **现象**：① 开发环境每次请求都输出完整 SQL 语句（`sqlalchemy.engine` INFO），淹没有价值的 OCR/import pipeline 日志；② 审核池/导入列表页每页 50 条 SELECT 包含 `raw_data`、`parsed_content`（JSON）、`parsed_options`、`parsed_analysis`、`ai_raw_response`、`math_regions` 等大字段。
- **根因**：① `create_async_engine(echo=True)` 在开发环境开启全量 SQL 日志，`logging_config.py` 未约束 `sqlalchemy.engine` 日志级别；② `list_review_queue` 和 `get_import_batch_detail` 使用 `select(QuestionImport)` 加载 ORM 全量实体。
- **处理**：
  1. engine 改用 `echo=settings.SQL_ECHO`（默认 False）+ `hide_parameters=True`；`logging_config.py` 新增 `sqlalchemy.engine`/`pool`/`dialects` logger 默认 WARNING
  2. 新增慢查询日志：`before_cursor_execute`/`after_cursor_execute` 监听器，超 `SLOW_QUERY_MS`（默认 500ms）才输出，SQL 压缩空白 + 截断 1200 字符
  3. `list_review_queue` 改为选择性列查询（`_LIST_COLUMNS`），排除 `raw_data`、`parsed_content`（仅 substr 前 160 字符为 `content_preview`）、`parsed_options`、`parsed_analysis`
  4. 新增 `GET /imports/questions/{import_id}` 详情端点返回完整字段
  5. 新增复合索引 `ix_question_imports_status_created_id` 和 `ix_question_imports_batch_status_created_id`
  6. 前端列表改用 `content_preview`，打开详情时调用 detail endpoint
- **验证**：10 个专项测试 + 全量 2220 个测试通过，0 回归。新增配置 `SQL_ECHO=false`、`SQL_LOG_LEVEL=WARNING`、`SLOW_QUERY_MS=500`。

## 2026-06-25 — 刷题页选项内容重复渲染 + 题干单行重复 + 选项 LaTeX 未渲染（已修复）

- **现象**：三个独立问题：① 含 `$...$` LaTeX 的选项渲染为两行（key 一行、mp-html 下一行），无 `$` 的选项正常；② 单行题干文本（如 "在线性表 a0, a1,.., a100，删除元素 a50 需要移动()个元素。"）连续显示两次；③ 选项中的数学公式以原始 LaTeX 文本显示，未转换。
- **根因**：
  1. 选项重复：`buildOptionList` 引入 `hasDollarLatex` 将含 `$...$` 的选项路由到 `<mp-html>`，但 mp-html 自定义组件在 `option-item` flex 布局中无法内联，`<p>` 内容被推到下一行。无 `$` 的选项走 `<text>` 路径正常。
  2. 题干单行重复：`_deduplicateRepeatedText` 半幅切分点不对齐句末边界，`lines.length===1` 时逐行去重循环不执行，导致两个完全相同副本漏判。后端 `deduplicate_repeated_text` 同样漏判。
  3. 选项 LaTeX 未渲染：`buildOptionList` 的 `_toPlainInlineMathText` 在 `needsRich` 前将 `$x^2$` 转为 Unicode 文本 `x²`（非空），`needsRich` 为 `false`，选项走 `<text>` 路径，未进入 mp-html KaTeX。
- **处理**：
  1. 选项恢复 `<text>` 渲染路径：移除 `hasDollarLatex` 逻辑，选项值使用 `_toPlainInlineMathText` 做 Unicode 数学转换（与原始行为一致）。选项中的 `$...$` LaTeX 通过 Unicode 近似呈现，不依赖 mp-html。
  2. 单行题干去重增强：`_deduplicateRepeatedText` 新增句末边界切分（`[。！？；\n]` 中点附近匹配），后端 `deduplicate_repeated_text` 相同增强。
  3. 选项值换行符清洗（前后端同步）：后端 `_sanitize_option_value` 正则化 `\r\n`→`\n`→`\r`→`\n`，`_fix_code_operator_splits` 后折叠 `\n+` 为空格。前端 `buildOptionList` / `_enrichBlankOptionGroups` 对选项文本做 `replace(/[\r\n]+/g, ' ')` 安全网。
  4. 注意：`deduplicate_repeated_text` 不应用于选项值——内部调用 `_split_inline_roman_subitems` 会破坏罗马数字选项（`"I、II、III"`→`"I、II"`）。
- **验证**：1041 个后端测试通过（含 22 个 dedup 专项测试）；三张实图截图确认选项单行显示、题干无重复。
- **说明**：选项 LaTeX 渲染的原始需求（含 `$` 公式的选项显示为渲染后的数学公式）因 mp-html 在 flex 布局中的兼容性问题暂无法实现。当前方案：选项中的 LaTeX 公式通过 `formatInlineMathText` 转为 Unicode 近似（`x^2`→`x²`、`\sqrt`→`√`），视觉上可读。如后续需要完整 KaTeX 渲染，需调整选项布局为独立行或改用 math-question 组件。

## 2026-06-25 — 代码题题干/选项部分缺失（第五次修复）——5种失败模式全部解决

- **现象**：5种含C代码块和4个选项的考研408图片在导入后出现不同形态的题干/选项损坏。案例一到五的根因各不相同，经过5轮迭代修复后全部通过。
- **案例一（栈定义+while循环）**：`#define` 外无序触发代码完整性告警，导致 `confidence=0.7` 的 VL 结果被 gate 丢弃。
  - **处理**：confidence gate 增加 `is_vl` 识别，VL 结果绕过 confidence 检查进入 AI safety gate。
- **案例二（BiTree树递归）**：VL_REBUILD 要求 `source_type=="pdf"`，图片导入被阻断。
  - **处理**：`_run_vl_rebuild_blocks` 移除 source_type 限制，支持图片文件；PDF 路径保留逐页渲染+VL OCR。
- **案例三（单链表while循环）**：`(>C` 噪声行未被识别为过渡区噪声，选项残留导致题干污染，VL_REBUILD 冻结注册表阻塞 splitter。
  - **处理**：`code_language_noise_layer` 新增 `在\w+中执行[：:]` 过渡区模式；`question_normalizer` 在 VL_REBUILD 路径下重新剥离题干选项文字；VL_REBUILD 替换 blocks 后清除 `frozen_option_registry`。
- **案例四（for循环）**：`}` 断裂+brace 告警。
  - **处理**：`code_structure_reconstruct` 阶段将 OCR 断裂的 `i++) {`、`sum += a[i];}` 等语句拼接闭合。
- **案例五（链表插入+typedef）**：`8→B` false conversion + `<1>` noise + 选项A垃圾污染 + 选项B丢失，根本原因是 PP-OCR 重跑文本和原始文本各有不同选项损坏（重跑：A正确B乱码；原始：B正确A乱码）。
  - **处理（5层修复）**：
    1. 题号 `8→B` 智能启发式修复 + `<1>` 提前清洗
    2. VL_REBUILD option count comparison + noise layer hallucination 清洗
    3. `_OCR_HALLUCINATION_RE` 防止代码关键字守卫误放过垃圾行
    4. **Phase 3 `original_raw_text` merge**：从首次 PP-OCR 原始结果中提取缺失选项，与重跑文本合并，得到完整 4 选项
    5. **AI repair `incomplete_options` trigger**：兜底检测选项中间缺失，触发 AI 恢复
- **涉及的代码文件**：`pipeline_orchestrator.py`、`code_language_noise_layer.py`、`ai_repair.py`、`batch_image_import_service.py`、`question_normalizer.py`
- **验证**：5 个 BUGS case 全部可通过 PP-OCRv6 图片 OCR + detect_options_from_text 验证。案例五经实图导入确认正确输出 4 个选项（A. `p->next = s->next; s->next = p`, B. `s->next = p->next; p->next = s`, C. `p->next = s; s = p->next`, D. `s = p; p->next = NULL`）。

## 2026-06-24 — 代码题选项系统性丢失（全部5种失败模式已修复）

- **现象**：导入含代码块和4个选项的考研408图片时，选项在审核页中全部缺失。5个不同代码形态（顺序栈定义+while循环、BiTree递归、单链表while、for循环、链表插入+typedef）各自呈现不同的丢失模式，包括OCR只捕获代码不捕获选项、VL输出选项前缀丢失、VL输出被LaTeX污染、VL API置信度为0等。
- **根因**：3个独立故障点叠加：
  1. **Fix A — VL confidence gate**：PaddleOCR-VL返回`confidence=0.0`（API不提供置信度时），`result.confidence and result.confidence > 0`短路为False，VL结果（含237 chars+选项）在进入AI safety gate前就被丢弃。
  2. **Fix B — VL_REBUILD PDF gate**：layout结构失败后触发`vl_rebuild`模式，但要求`source_type=="pdf"`，图片导入被阻断，无法调用PaddleOCR-VL重建blocks；同时`_run_vl_rebuild_blocks`硬编码`fitz.open(file_path, filetype="pdf")`不适用于图片文件。
  3. **VL输出质量**：VL对代码图片的选项区域输出不稳定，表现为HTML列表化输出（丢掉A/B/C/D前缀）、LaTeX数学符号污染（选项内容被`$$...$$`包裹）、选项字母缺失。
- **处理**：
  1. `pipeline_orchestrator.py:2443` confidence gate增加`is_vl`识别，VL结果绕过confidence检查进入AI safety gate正常评估。非VL模型（DeepSeek、rule fallback）保持原有confidence检查。
  2. `_run_vl_rebuild_blocks`移除`source_type=="pdf"`限制，支持图片文件直接读取（跳过PyMuPDF）；PDF路径保留逐页渲染+VL OCR。
  3. 双源OCR策略：VL_REBUILD中先运行PP-OCRv6（本地），检测到选项时直接使用（跳过VL API调用）。VL仅作为PP-OCRv6无选项时的语义回退。
  4. `repair_option_structure()`修复VL输出：HTML清理、LaTeX修复、裸选项恢复（无前缀行自动标记A/B/C/D）、种子文本匹配。6步修复管线。
  5. `force_options_probe()`debug诊断函数，暴力扫描全部7种option pattern并报告。
  6. 全链路TRACE日志：raw_input→text_detection→classifier_result→options_branch→final_options。
  7. 回归测试扩展：BUGS case 021-025新增`full_ocr`阶段，自动运行PP-OCRv6图片OCR+`detect_options_from_text`验证。
- **验证**：全部5个BUGS case通过OCR全链路回归测试（PP-OCRv6 → detect_options=True → extract_options≥2）。30个OCR回归测试+31个options pipeline测试全部PASS。实际PP-OCRv6 API调用验证：Case2 239 chars含4选项、Case3 122 chars含4选项、Case5 229 chars含3选项（B行OCR损坏但≥2 key）。
- **提交**：`0fed945`（Fix A confidence gate）、`be03159`（Fix B VL_REBUILD图片支持）、`62f4870`（双源OCR策略+repair）、`fe62032`（OCR全链路回归测试）。
- **说明**：该批次修复覆盖了代码题选项丢失的全部已知失败场景。VL输出质量仍然是Case3/5的潜在风险点，但双源策略通过PP-OCRv6优先避开了VL的结构性缺陷。Case4原本就是正确通过的基线，不需要修复。

## 2026-06-22 — OCR 代码块围栏断裂导致代码结构泄漏（已修复）

- **现象**：OCR 导入后，包含 C 结构体定义的代码题出现代码片段截断与乱码混合，导致题干结构破坏。例如 `typedef struct BiTNode { char data;` 后的完整 struct 定义被截断，`} BiTNode, *BiTree;` 泄漏到围栏外部混入正常文本，出现 `(1typu* p1tysI* apo11ta aonu2s` 等 OCR 噪声。
- **根因**：`code_detector.py` 的 `_fence_code_blocks()` 要求连续 ≥2 行且每行 score≥1 才包裹围栏。OCR 对 `struct BiTNode *lchild, *rchild;` 行的识别结果被打成乱码（`_score_line()` 返回 0），该行夹在两行代码行之间 → 围栏在乱码行前提前关闭 → `} BiTNode, *BiTree;` 泄漏出围栏 → `_merge_ocr_newlines()` 将关闭标记与乱码行合并 → 结构代码永久丢失。
- **处理**：`code_detector.py` `_fence_code_blocks()` 新增单行桥接规则（Step 1.5），在评分阶段对 score=0 但相邻两行均 score≥1 的孤立低分行提升为 score=1，维持围栏连续性。无需修改 OCR 管线、清洗规则、code_integrity 或 AI repair 模块。
- **验证**：22 个 OCR 回归测试全部 PASS（含 `019_code_struct_garbled_truncation` 精确 BUG-001 用例）；实际图片 OCR + 端到端管线验证结构定义完整保留在 ```text 围栏内。

## 2026-06-20 — mp-html 模板链导致刷题页题干重复显示（已修复）

- **现象**：小程序答题页中，非 LaTeX 题干（含多行换行的纯文本题干）整段重复显示，上下紧挨出现两个相同副本；微信开发者工具 DOM 检查器中可见 `<wx-node>` 内存在两个相同的 `<wx-rich-text>` 元素。
- **原因**：mp-html 内部渲染链路为 `mp-html/index.js` → `<node>` → `node.wxml` 5 层递归模板 → `<template is="el">` → `<rich-text>`。当题干内容变化（切换题目）时，`node.js` 的 `childs` observer 通过逐层 diff 产生子节点级增量更新（如 `nodes[0].children[2]`）而非全量数组替换。微信小程序的虚拟 DOM 协调在处理 `<template is="el">` 调用时未能正确移除旧的 `<rich-text>` 元素，导致新旧两个 `<rich-text>` 并存，页面出现重复文本。此前同类问题（2026-06-02、2026-06-14）通过在 `practice.js` 端做保守纯文本化/折叠重复块绕过，未触及 mp-html 内核。
- **处理**：
  1. `practice.js` `_showQuestion()`：对非 LaTeX 题干（无 `\commands`、无 `$$...$$`）直接构建 `<rich-text>` 节点数组 `_richTextNodes`，绕过 mp-html 完整模板链
  2. `practice.wxml`：渲染优先级调整为 `math-question` → 原生 `<rich-text>` → `mp-html`（仅 LaTeX 备用）→ `<text>`
  3. `node.js` `childs` observer：增加根节点是否变化的引用级检测，变化时执行全量 `setData({ nodes })` 而非增量 diff，确保后续通过 mp-html 渲染的内容（如选项）不受同样问题影响
  4. 移除 6 层运行时诊断日志和视觉标记（`【▼题干开始▼】`/`【▲题干结束▲】`），恢复代码整洁
- **验证**：通过逐层隔离测试确认：原生 `<text>` 无重复 → 原生 `<rich-text>` 无重复 → mp-html 全链路出现重复 → 绕过 mp-html 模板链后重复消失。6 次迭代诊断日志精确锁定了 `node.js` diff 路径与 `node.wxml` `<template>` 协调之间的交互为根因。
- **说明**：该修复不修改 mp-html 库的核心模板结构（`node.wxml` 的 5 层递归和 `el` 模板保持不变），仅在 node 组件增加全量替换守卫；题干渲染的主体路径改为更简单可控的原生 `<rich-text>` 直出。LaTeX 题干（含 `\` 命令或 `$$` 块公式）仍走 mp-html 插件链路以支持 KaTeX 渲染，但非 LaTeX 题干占绝大多数场景。

## 2026-06-19 — 题干罗马数字列举项换行符丢失 + 代码缩进丢失 + KaTeX 解析异常容错（已修复）

- **现象**：OCR/PDF 导入后，题干中 I./II./III./IV. 等罗马数字列举项之间的换行符全部丢失，所有分项连成一段；代码类题干的缩进和换行结构被破坏；printf 中的 `\n` 被 KaTeX 拦截导致 `KaTeX parse error` 显示在 UI 上。
- **原因**：
  1. `question_pipeline.py` 的 `_should_merge()` 和 `pdf_text_normalizer.py` 的 `_STRUCTURE_LINE_RE` 未将罗马数字（I./II./III./IV.…）识别为结构标记行，导致列举项被合并到上一行
  2. `ocr_service.py` 的 `clean_ocr_text()` 使用 `line.strip()` 同时去除行首和行尾空格，破坏了代码块的缩进结构
  3. `mp-html/latex/index.js` 在 KaTeX 解析失败时直接将错误信息渲染到 UI（如 `KaTeX parse error: Undefined control sequence: \n`），而不是回退显示原始文本
  4. `wrong-detail.js` 的 `_deduplicateLines()` 使用 Set 做全局去重（移除文本中所有重复行，而非仅连续重复），可能错误丢弃合法的重复代码行
- **处理**：
  1. `question_pipeline.py` `_should_merge()` 新增罗马数字检查：以 `I.`/`II.`/`III.`/`IV.`… 开头的行不再向上合并
  2. `pdf_text_normalizer.py` `_STRUCTURE_LINE_RE` 新增 `(?:VIII|VII|III|VI|IV|IX|II|V|X|I)\s*[.、)）]` 模式
  3. `ocr_service.py` `clean_ocr_text()` 将 `line.strip()` 改为 `line.rstrip()`，保留行首缩进
  4. `mp-html/latex/index.js` KaTeX 解析增加 try-catch，失败时回退为原始纯文本而非显示错误信息
  5. `wrong-detail.js` `_deduplicateLines()` 改为仅去重连续重复行，与 `practice.js` 保持一致
- **验证**：`test_question_pipeline.py`（12 passed）、`test_pdf_normalizer.py`（10 passed）、`test_question_splitter.py`（85 passed），全量 107 测试通过。
- **说明**：`text_normalizer.py` 此前已在 `_RE_STRUCTURE_LINE` 中包含罗马数字标记，无需额外修复。已入库的受影响题目（如 questions.id=20, 23）需手动修复或重新导入。

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
