你当前位于 MemoGrad / postgraduate-ai 项目根目录。

请以完全无人值守方式，实际执行《计算机组成原理.pdf》（实际文件名：cs_ds.pdf）的导入、逐题审核、
错误修正和修正后复核。

不要只分析代码、提出建议或生成示例命令。必须真实运行后端、调用 OCR MCP、
执行导入、查询数据库、调用题目编辑接口、核验修改结果并生成审计报告。

本任务运行期间没有用户在线。不得暂停等待用户回答，不得请求用户确认。
遇到存在多种选择的情况，始终采取最保守、可恢复、不污染数据库的方案。

任务参数：

PDF_FILENAME=cs_ds.pdf
PDF_DISPLAY_NAME=计算机组成原理.pdf
AUTO_PUBLISH=false
MAX_PIPELINE_RETRIES=2
MAX_REPAIR_ROUNDS_PER_QUESTION=3
BATCH_PAGE_SIZE=25
TRIAL_PAGE_START=1
TRIAL_PAGE_END=10

AUTO_PUBLISH=false 表示：
完成审核后，题目只保留在 question_imports 暂存审核区，不发布到正式
questions 表。不得擅自修改该设置。

==================================================
一、最终目标
==================================================

完成以下工作：

1. 找到《计算机组成原理.pdf》（实际文件名：cs_ds.pdf）的真实绝对路径。
2. 使用项目已有后端 import pipeline 导入题目。
3. 导入结果首先写入 question_imports 暂存区。
4. 对本次导入的每一道题与原始 PDF 页面进行逐题核验。
5. 使用 OCR MCP 对原始页面进行独立 OCR 和疑难区域复核。
6. 发现有明确原页证据的 OCR、拆题或选项错误时，通过项目现有题目编辑
   API/service 修正。
7. 每次修改后重新核验，不得修改后直接标记为正确。
8. 所有题目达到可验证的一致性标准后，才允许标记任务成功。
9. 不能可靠确认的题目不得猜测，必须进入 needs_manual_review 清单。
10. 不得伪造完成状态，不得把“已提交 Pipeline”当作“已经导入完成”。

==================================================
二、不可违反的安全约束
==================================================

1. 只允许操作本地开发环境或隔离测试环境。

2. 如果出现以下任一情况，立即安全停止：
   - APP_ENV=production；
   - DATABASE_URL 指向生产数据库；
   - 无法确定数据库是否为开发库；
   - PDF 文件不存在；
   - 数据库无法可靠备份；
   - 当前数据库处于损坏状态；
   - 编辑接口可能修改正式 questions 表；
   - OCR MCP 返回结果无法追溯到具体页面；
   - 必须执行系统级破坏性操作才能继续。

3. 禁止执行：
   - rm -rf；
   - git reset --hard；
   - git clean -fd；
   - git push；
   - 强制覆盖用户已有文件；
   - 清空 questions；
   - 清空全部 question_imports；
   - 删除不属于本次任务的数据库记录；
   - 修改生产配置；
   - 自动升级项目全部依赖；
   - 直接向正式 questions 表插入数据。

4. 不允许使用直接 SQL INSERT/UPDATE 绕过项目业务逻辑修改题目。

5. SQL 只允许用于：
   - 只读查询；
   - 数据完整性检查；
   - 导入前后计数；
   - 明确属于本批次的事务回滚验证。

6. 题目修正必须优先调用项目已有：
   - 管理端编辑 API；
   - review service；
   - question import edit service；
   - 项目已有等价业务接口。

7. 如果没有可用的编辑接口，允许实现最小范围的内部修正脚本，但必须：
   - 调用 ORM/service；
   - 使用事务；
   - 只修改本次 batch_id/pipeline_id 的 question_imports；
   - 保存修改前后值；
   - 添加测试；
   - 不修改 questions 表。

8. 原 PDF 没有答案时：
   - answer 必须为空；
   - answer_status 必须是 missing 或项目现有等价状态；
   - 不得根据学科知识、网络知识或 AI 推理生成答案；
   - 不得把 AI 猜测答案标记为原始答案。

9. 不允许为了达到成功标准而降低校验阈值、删除错误记录或隐藏失败页面。

==================================================
三、检查项目实际实现
==================================================

首先读取并理解当前代码，不要仅依赖文件名猜测：

- CLAUDE.md
- README.md
- .env
- .env.example
- backend/app/main.py
- 导入 API 路由
- import_pipeline_service
- pipeline_orchestrator
- OCR service
- OCR mode/router
- question_splitter
- structure_freeze_stage
- question_normalizer
- batch_validation
- similarity_matcher
- review_service
- 题目编辑 API/service
- question_imports ORM
- questions ORM
- import_pipelines ORM
- import_pipeline_chunks ORM
- subjects ORM
- Alembic migrations
- Pipeline 查询、恢复、重试和 artifact 机制

确认并记录：

1. 上传接口的真实路径和请求参数。
2. Pipeline 启动方式。
3. PDF 页码范围参数。
4. OCR 模式及默认模式。
5. Pipeline worker 的运行方式。
6. Pipeline 的所有终态。
7. chunk 状态查询方式。
8. batch_id 与 pipeline_id 的关联方式。
9. question_imports 的来源页字段。
10. 题目编辑接口的真实请求格式。
11. 批次回滚方式。
12. 发布接口是否与审核接口严格分离。

列出当前会话实际可用的所有 MCP 工具。

找到 OCR MCP 的真实 server 名称和工具名称，确认其是否支持：

- PDF；
- 图片；
- 页码范围；
- 图片裁剪区域；
- Markdown、JSON 或纯文本输出；
- bounding box；
- confidence；
- 表格、公式、代码和图形题。

不得虚构 MCP 工具调用结果或工具名称。

==================================================
四、建立工作目录和状态文件
==================================================

创建：

artifacts/computer-organization-import/
artifacts/computer-organization-import/source/
artifacts/computer-organization-import/source-pages/
artifacts/computer-organization-import/backend-ocr/
artifacts/computer-organization-import/mcp-ocr/
artifacts/computer-organization-import/crops/
artifacts/computer-organization-import/audit/
artifacts/computer-organization-import/reports/
artifacts/computer-organization-import/backups/
artifacts/computer-organization-import/logs/

任务开始时创建：

artifacts/computer-organization-import/RUNNING

内容包括：

- started_at
- PID
- git_commit
- pdf_path
- database_url 的脱敏版本
- APP_ENV

任务成功时：

1. 删除 RUNNING；
2. 创建 SUCCESS；
3. SUCCESS 中写入关键统计和报告路径。

任务安全失败时：

1. 删除 RUNNING；
2. 创建 FAILED_SAFE；
3. 记录失败阶段、原因、最后成功页码、可恢复方式和报告路径。

==================================================
五、确认原始 PDF
==================================================

在项目根目录及合理的上级目录中查找精确文件名：

cs_ds.pdf

该文件对应的资料显示名为《计算机组成原理.pdf》。搜索和导入时必须以实际文件名 `cs_ds.pdf` 为准，不得使用相似文件名或仅凭显示名替代。

如果存在多个同名文件：

1. 计算 SHA-256；
2. 记录文件大小和页数；
3. 优先选择项目目录内最新但非临时副本；
4. 如果仍无法唯一确认，安全停止，不得猜测。

建立：

artifacts/computer-organization-import/source/manifest.json

至少包含：

- absolute_path
- filename
- sha256
- file_size
- total_pages
- page_width
- page_height
- embedded_text_available
- scanned_pdf
- created_at

检查 PDF 是否可正常打开，页数是否稳定，是否存在损坏页面。

==================================================
六、检查并备份数据库
==================================================

读取真实 DATABASE_URL。

SQLite：

1. 确认数据库绝对路径。
2. 执行 PRAGMA quick_check。
3. 使用 SQLite backup API、sqlite3 .backup 或 VACUUM INTO 备份。
4. 不要在数据库活动写入时仅使用普通 cp。
5. 正确处理 WAL 和 SHM。
6. 再次打开备份并执行 quick_check。

PostgreSQL：

1. 确认是本地开发数据库。
2. 使用 pg_dump 创建一致性备份。
3. 验证备份文件非空且命令成功。

备份保存到：

artifacts/computer-organization-import/backups/

记录导入前基线：

- questions 总数；
- question_imports 总数；
- question_imports 按 status 分组；
- import_pipelines 总数；
- import_pipeline_chunks 总数；
- subjects 内容；
- 最近的 pipeline_id；
- 最近的 batch_id；
- 数据库完整性结果；
- questions 表中与“计算机组成原理”相关的题目数量。

==================================================
七、运行环境准备
==================================================

确认：

- Python 虚拟环境；
- 后端依赖；
- OCR 依赖；
- Redis；
- 数据库迁移；
- FastAPI 服务；
- Pipeline worker；
- OCR 服务；
- OCR MCP。

允许在项目虚拟环境中安装明确缺失的 Python 依赖，但必须：

1. 仅安装当前项目 requirements 已声明的依赖；
2. 不全局安装；
3. 不升级无关依赖；
4. 记录安装命令；
5. 安装失败时安全停止。

如果需要 apt、brew、系统驱动、CUDA 驱动或管理员权限，不得自动安装，
应安全停止并生成报告。

==================================================
八、试运行第 1—10 页
==================================================

先查询 subjects 表，寻找最合适的计算机组成原理科目。

不得创建重复科目。

如果不存在计算机组成原理科目，允许通过项目现有科目 service/API 创建唯一科目，
并记录创建信息。

使用后端现有 import pipeline 导入第 1—10 页。

要求：

- page_start=1
- page_end=10
- 唯一 idempotency key
- 记录 pipeline_id
- 记录 batch_id
- 启用现有结构分析、拆题、校验和去重
- 不自动发布
- 不猜答案
- 不绕过 Pipeline

启动后持续查询：

- pipeline status
- chunk status
- stage status
- progress
- errors
- warnings
- artifacts
- question_count

必须等待明确终态。

只有所有相关 chunk 都完成，Pipeline 才能视为 completed。

如果失败：

1. 保存完整错误；
2. 使用项目已有 resume/checkpoint 重试；
3. 最多重试 MAX_PIPELINE_RETRIES 次；
4. 不得重复写入成功记录；
5. 仍失败则安全停止。

==================================================
九、建立原始页面证据
==================================================

将试运行页面以 250—300 DPI 渲染为 PNG：

page-0001.png
page-0002.png
...

不得裁掉：

- 题号；
- 题干；
- A/B/C/D；
- 图表；
- CPU 数据通路图、控制器框图、流水线时序图；
- Cache 映射图、存储器芯片连接图、地址译码图；
- 总线结构图、中断与 DMA 流程图、微程序控制流程图；
- 指令格式、存储字格式、波形图、真值表、状态表；
- 汇编代码、RTL/微操作、伪代码和公式；
- 页眉和页脚。

保存后端 OCR 的原始输出、中间清洗结果和最终拆题结果。

对第 1—10 页调用 OCR MCP 独立识别。

OCR MCP 的结果保存到：

artifacts/computer-organization-import/mcp-ocr/trial/

OCR MCP 结果只用于复核，不能直接写入数据库。

==================================================
十、逐题一致性审核
==================================================

对本次产生的每一条 question_imports 记录进行逐题审核。

必须同时比较：

A. 原始 PDF 页面；
B. 页面高分辨率渲染图；
C. 后端原始 OCR；
D. 后端清洗文本；
E. 后端拆题结果；
F. question_imports 数据；
G. OCR MCP 独立识别结果。

审核以下字段：

- 来源页；
- 原题号；
- 题型；
- 题干；
- A 选项；
- B 选项；
- C 选项；
- D 选项；
- 其他选项；
- 答案；
- 解析；
- 图片、表格、CPU 数据通路图、控制器框图、流水线时序图、Cache 映射图、存储器芯片连接图、地址译码图、总线结构图、中断与 DMA 流程图、微程序控制流程图、指令格式、存储字格式、波形图、真值表、状态表、公式、汇编代码、RTL/微操作和伪代码；
- 题目顺序；
- 跨页关系。

重点检查计算机组成原理题常见高风险内容：

1. O、0、Q 混淆；
2. I、l、1 混淆；
3. B、8 混淆；
4. 十进制、二进制、八进制、十六进制数字及下标混淆；
5. `0x`、`0b`、H、B、D、O/Q 等进制标记；
6. 正负号、补码符号位、小数点和隐含小数点位置；
7. `+`、`-`、`×`、`÷`、`<<`、`>>`、`>>>`、`&`、`|`、`^`、`~`；
8. `=`、`==`、`!=`、`<`、`>`、`<=`、`>=`；
9. `->`、`=>`、`<-`、`↔` 以及数据通路、控制信号和总线方向；
10. 中括号、圆括号、花括号、上标、下标和位编号范围；
11. bit、Byte、KB、MB、GB、KiB、MiB、GiB 及 2 的幂次；
12. 字、字节、半字、双字、机器字长、存储字长、指令字长和地址字长；
13. 大端/小端字节序、按字节编址/按字编址及地址递增方向；
14. 原码、反码、补码、移码的符号位、数值范围、零表示和转换关系；
15. 定点数加减、溢出判定、进位/借位以及 CF、OF、ZF、SF 等标志位；
16. 移位运算中的逻辑移位、算术移位、循环移位和符号扩展；
17. 乘除法算法中的 Booth、恢复余数、不恢复余数、部分积和商位顺序；
18. IEEE 754 单精度/双精度的符号位、阶码、尾数、偏置值、隐藏位、规格化数、非规格化数、±0、∞ 和 NaN；
19. BCD、ASCII、奇偶校验、海明码的校验位位置、码距和纠错位编号；
20. CPU 性能公式中的主频、时钟周期、CPI、IPC、指令数、CPU 执行时间、MIPS、MFLOPS、加速比和 Amdahl 定律；
21. 指令格式中的操作码、寻址方式位、寄存器号、地址码、立即数和位宽；
22. 零地址、一地址、二地址、三地址指令的操作数来源和结果去向；
23. 立即、直接、间接、寄存器、寄存器间接、基址、变址、相对、堆栈等寻址方式及有效地址计算；
24. PC、IR、MAR、MDR/MBR、ACC、SP、PSW、通用寄存器等缩写与微操作；
25. 取指、间址、执行、中断周期及机器周期、时钟周期的边界；
26. 单周期、多周期 CPU 数据通路中的多路选择器、ALU 输入、寄存器写回和控制信号；
27. 硬布线控制与微程序控制的区别，控制存储器容量、微指令字段、水平型/垂直型微指令和下地址形成；
28. RISC/CISC、定长/变长指令、Load/Store、寄存器数量和流水线友好性；
29. 流水线阶段 IF、ID、EX、MEM、WB 的先后关系及周期编号；
30. 流水线时空图中的执行区间、气泡、停顿、冲刷、转发路径和分支转移点；
31. 结构、数据和控制冒险，RAW/WAR/WAW，forwarding/bypassing、stall 和 branch prediction；
32. 流水线吞吐率、加速比、效率、时钟周期和填充/排空时间；
33. SRAM、DRAM、ROM、PROM、EPROM、EEPROM、Flash 的组织方式与读写特性；
34. 存储芯片容量表示（如 `1K×8`）、地址线、数据线、片选线及位扩展/字扩展；
35. 地址译码、片选范围、存储器地址空间、交叉编址和低位/高位交叉；
36. Cache 的直接映射、全相联、组相联，块号、组号、标记 Tag、行号/索引和块内偏移；
37. Cache 行大小、组数、路数、容量、有效位、脏位和替换状态位；
38. 命中率、缺失率、命中时间、缺失损失、平均访存时间 AMAT；
39. 写直达/写回、写分配/非写分配及一致性相关描述；
40. LRU、FIFO、Random 等 Cache 替换算法及访问序列；
41. 主存与 Cache 地址划分图、标记比较器和数据选择路径；
42. 虚拟地址、物理地址、页号、页内偏移、页表、TLB 与 Cache 的先后关系（如题目涉及）；
43. 总线宽度、总线频率、传输周期、突发传输、带宽和总线利用率；
44. 同步总线、异步总线、集中仲裁、分布仲裁及菊花链优先级；
45. 程序查询、中断驱动、DMA、I/O 通道的工作阶段和 CPU 参与程度；
46. 中断请求、响应、屏蔽字、优先级、向量地址、现场保护和返回顺序；
47. DMA 中周期窃取、独占总线、透明传输、数据块长度和传送方向；
48. 磁盘/外存题中的柱面、磁道、扇区、转速、寻道时间、旋转延迟和传输时间；
49. 汇编语言、机器指令、RTL/微操作中的寄存器名、立即数、地址、分号、逗号、冒号和位字段；
50. `M[AR]`、`(PC)`、`R1←R2`、`PC←PC+1` 等存储器/寄存器传送记号；
51. 组合逻辑、时序逻辑、触发器、状态机、真值表、状态表和时序波形的边沿与电平；
52. 否定词：
    - 不正确；
    - 错误；
    - 不包括；
    - 不能；
    - 不属于；
    - 不会；
    - 无法；
53. 页眉、页脚、水印误入题干；
54. 一题被拆成两题；
55. 两题被合成一题；
56. 选项串题；
57. 选项缺失；
58. 选项顺序错误；
59. 原页无答案但数据库出现答案；
60. 原页包含数据通路图、流水线时序图、Cache/主存映射图、存储器芯片连接图、总线图、中断/DMA 图、微程序控制图或波形图，但数据库完全丢失图形信息；
61. 跨页题目的指令格式、地址划分、访问序列、时序图、代码、表格或公式被截断。

为每题生成状态：

- exact
- normalized_equivalent
- minor_mismatch
- major_mismatch
- missing_question
- extra_question
- wrong_page_mapping
- duplicate
- uncertain
- needs_manual_review

状态定义：

exact：
字符、结构、题号、选项和页面映射均与原页一致。

normalized_equivalent：
只存在不影响语义的换行、连续空格、全角半角或 Unicode 规范化差异。

minor_mismatch：
轻微格式问题，不改变题目含义，但仍应尽量修正。

major_mismatch：
题干、选项、数字、进制、位宽、补码、浮点字段、地址划分、指令格式、控制信号、流水线时序、Cache 映射、存储芯片连接、总线参数、I/O 时序、代码、公式、图形关系或否定词错误，可能影响作答。

uncertain：
原图模糊、OCR 引擎冲突，或数据通路图、流水线图、Cache/主存映射图、存储器连接图、总线图、中断/DMA 图、微程序控制图、波形图无法可靠还原。

needs_manual_review：
自动流程无法可靠确认或修复。

不得仅凭文本相似度认定 exact。

==================================================
十一、差异核验顺序
==================================================

发生差异时按以下顺序处理：

1. 查看高分辨率原始页面图。
2. 检查后端 OCR bounding box 和原始 OCR。
3. 检查是否由清洗、拆题或标准化阶段引入。
4. 调用 OCR MCP 识别整页。
5. 对具体题目区域生成裁剪图。
6. 使用 OCR MCP 对裁剪图再次识别。
7. 必要时以更高 DPI 重新渲染。
8. 比较两个 OCR 引擎。
9. 最终以原始页面视觉证据为最高依据。

两个 OCR 引擎结果相同，不代表必然正确。

==================================================
十二、自动修正规则
==================================================

只有在原始页面证据明确时才能自动修正。

允许修正：

- 明确 OCR 错字；
- 明确数字或字母混淆；
- 明确运算符错误；
- 明确括号、箭头、进制、位宽、补码位、浮点字段、地址位、周期参数、控制信号或代码符号错误；
- 明确题号错误；
- 明确选项错位；
- 明确选项遗漏；
- 明确页眉、页脚或水印污染；
- 明确来源页映射错误；
- 明确拆题边界错误；
- 本次重试产生的明确重复暂存记录。

禁止修正：

- 无法从原页确认的字符；
- 原 PDF 不存在的答案；
- 原 PDF 不存在的解析；
- 依靠学科知识猜出的内容；
- OCR MCP 推测但页面无法确认的内容；
- CPU 数据通路、流水线时序、Cache/主存映射、存储器芯片连接、总线结构、中断/DMA、微程序控制或波形图无法准确重建的题目；
- 不属于本次 batch_id 的题目。

每次修正必须记录：

- database_id
- pipeline_id
- batch_id
- pdf_page
- field
- value_before
- value_after
- reason
- source_evidence
- mcp_evidence
- edit_api
- edited_at

保存到：

artifacts/computer-organization-import/audit/auto-fixes.jsonl

使用项目现有编辑 API/service 修改。

每次修改后：

1. 重新读取数据库；
2. 重新执行规范化比较；
3. 重新检查原始页面；
4. 必要时再次调用 OCR MCP；
5. 重新生成审核状态。

每道题最多执行 MAX_REPAIR_ROUNDS_PER_QUESTION 轮。

达到上限仍无法通过时，标记 needs_manual_review，不得无限循环。

==================================================
十三、试运行通过条件
==================================================

第 1—10 页必须同时满足：

- Pipeline completed；
- 所有 chunk completed；
- 页面覆盖完整；
- 没有 missing_question；
- 没有 extra_question；
- 没有 wrong_page_mapping；
- 没有 major_mismatch；
- 没有无法解释的 duplicate；
- 所有选择题选项结构正确；
- CPU 数据通路图、流水线时序图、Cache/主存映射图、存储器芯片连接图、总线图、中断/DMA 图、微程序控制图和波形图已保留可刷题所需信息，或进入人工复核；
- 没有 AI 猜测答案；
- questions 表数量与导入前一致；
- 数据库完整性检查通过。

如果不满足：

1. 定位代码、配置或数据根因；
2. 做最小修改；
3. 添加或运行针对性测试；
4. 回滚本次试运行批次；
5. 使用新 idempotency key 重试；
6. 最多进行两轮试运行修复。

两轮后仍不满足，进入 FAILED_SAFE，不得继续全量导入。

==================================================
十四、全量导入
==================================================

试运行通过后，从第 11 页开始导入到 PDF 最后一页。

优先使用项目现有 chunk、checkpoint 和 resume 机制。

如果需要显式分页，使用 BATCH_PAGE_SIZE=25：

11—35
36—60
依此类推，最后一批按实际页数结束。

每批必须：

1. 使用唯一 idempotency key；
2. 记录 pipeline_id；
3. 记录 batch_id；
4. 等待明确终态；
5. 检查所有 chunk；
6. 检查新增题目数量；
7. 检查页面覆盖；
8. 立即进行逐题审核；
9. 修正有明确证据的问题；
10. 修正后重新审核；
11. 保存本批报告；
12. 再开始下一批。

某批失败时：

- 只重试失败批次或失败 chunk；
- 不删除其他成功批次；
- 最多重试 MAX_PIPELINE_RETRIES 次；
- 使用 checkpoint/resume；
- 防止重复入库；
- 失败仍无法解决时进入 FAILED_SAFE。

==================================================
十五、逐页完整性检查
==================================================

建立页面级映射：

每一个 PDF 页码都必须对应以下一种状态：

- imported_and_verified
- imported_needs_manual_review
- intentionally_no_question
- failed

不得存在未记录状态的页面。

对每页检查：

- 原页题目数；
- 数据库题目数；
- 原题号；
- 数据库题号；
- 顺序；
- 选项数量；
- 图形数量及类型（CPU 数据通路图、控制器框图、流水线时序图、Cache/主存映射图、存储器芯片连接图、地址译码图、总线图、中断/DMA 图、微程序控制图、波形图等）；
- 是否跨页；
- 是否重复；
- 是否缺失。

保存：

artifacts/computer-organization-import/audit/page-summary.csv

==================================================
十六、输出逐题审核文件
==================================================

生成：

artifacts/computer-organization-import/audit/items.jsonl
artifacts/computer-organization-import/audit/items.csv
artifacts/computer-organization-import/audit/manual-review.csv
artifacts/computer-organization-import/audit/page-summary.csv
artifacts/computer-organization-import/audit/auto-fixes.jsonl
artifacts/computer-organization-import/audit/differences.md

items.csv 至少包含：

- database_id
- pipeline_id
- batch_id
- pdf_page
- source_question_no
- question_type
- stem_status
- option_a_status
- option_b_status
- option_c_status
- option_d_status
- answer_status
- diagram_status
- code_status
- page_mapping_status
- overall_status
- backend_ocr_confidence
- mcp_ocr_confidence
- auto_fixed
- repair_rounds
- needs_manual_review
- difference_summary
- evidence_path

==================================================
十七、最终验收查询
==================================================

任务结束前执行：

1. 本次新增 question_imports 总数；
2. 本次 pipeline 总数；
3. 本次 batch 总数；
4. completed chunk 数量；
5. failed chunk 数量；
6. PDF 总页数；
7. 成功覆盖页数；
8. 失败页数；
9. 未覆盖页数；
10. exact 数量；
11. normalized_equivalent 数量；
12. minor_mismatch 数量；
13. major_mismatch 数量；
14. missing_question 数量；
15. extra_question 数量；
16. wrong_page_mapping 数量；
17. duplicate 数量；
18. uncertain 数量；
19. needs_manual_review 数量；
20. 自动修正数量；
21. 自动修正后通过数量；
22. 题干为空数量；
23. 客观题选项结构异常数量；
24. 来源页为空数量；
25. 来源页越界数量；
26. 原题号为空数量；
27. 有答案数量；
28. 缺失答案数量；
29. 疑似 AI 猜答案数量；
30. 图形缺失数量；
31. 汇编代码、RTL/微操作或伪代码结构异常数量；
32. 数制、原码/反码/补码/移码或定点运算异常数量；
33. 浮点格式、阶码、尾数或规格化异常数量；
34. 指令格式、寻址方式或有效地址计算异常数量；
35. 数据通路、控制信号或微程序控制结构异常数量；
36. 流水线时序、冒险、停顿、转发或分支处理异常数量；
37. Cache 映射、地址划分、替换策略或 AMAT 计算异常数量；
38. 存储芯片组织、地址译码、位扩展/字扩展异常数量；
39. 总线带宽、仲裁、中断、DMA 或 I/O 时序异常数量；
40. 校验码、海明码、奇偶校验或状态机/波形异常数量；
41. 重试产生的重复题数量；
42. questions 表导入前后数量差异；
43. 数据库完整性检查结果。

硬约束：

- AUTO_PUBLISH=false 时，questions 表数量必须保持不变；
- 所有题目必须可通过 pipeline_id 和 batch_id 追踪；
- 所有题目必须可追踪到原始页；
- failed chunk 不得标记为 completed；
- 未确认题目不得标记为 exact；
- 缺失页面不得静默忽略；
- 原 PDF 无答案时不得出现推测答案。

==================================================
十八、成功终态
==================================================

只有满足以下全部条件，才能创建 SUCCESS：

1. 所有页面均有明确状态。
2. 所有 Pipeline 和 chunk 均完成。
3. missing_question=0。
4. extra_question=0。
5. wrong_page_mapping=0。
6. major_mismatch=0。
7. uncertain=0。
8. needs_manual_review=0。
9. CPU 数据通路图、控制器框图、流水线时序图、Cache/主存映射图、存储器芯片连接图、地址译码图、总线图、中断/DMA 图、微程序控制图和波形图均已正确保留，或不存在此类题目。
10. 数制与编码、补码与浮点运算、指令格式与寻址、流水线时序、Cache 地址划分、存储器扩展、总线与 I/O、汇编代码、RTL/微操作和公式均完成视觉复核。
11. 没有疑似 AI 猜测答案。
12. questions 表未被修改。
13. 数据库完整性检查通过。
14. 所有自动修正均有证据和审计记录。
15. 所有修改后都重新通过核验。

不得将 normalized_equivalent 视为错误。
minor_mismatch 必须修正或确认确实不影响内容后才能成功。

==================================================
十九、安全失败终态
==================================================

出现以下任一情况，创建 FAILED_SAFE：

- 达到重试上限仍有失败 Pipeline；
- 有页面无法识别；
- 有题目无法可靠对应原页；
- 有 major_mismatch 无法修正；
- 有 uncertain；
- 有 needs_manual_review；
- CPU 数据通路图、流水线时序图、Cache/主存映射图、存储器芯片连接图、总线图、中断/DMA 图、微程序控制图或波形图无法可靠保留；
- 数制与编码、补码/浮点运算、指令格式、寻址计算、流水线周期、Cache 地址划分、存储器扩展、总线/I/O 参数、代码、RTL/微操作或公式无法可靠确认；
- 数据库完整性异常；
- questions 表被意外修改且无法安全恢复；
- 必须执行高风险操作才能继续。

FAILED_SAFE 不等于任务完全失败。

必须保留：

- 已成功导入的数据；
- 所有日志；
- 所有证据图；
- 所有 pipeline_id；
- 所有 batch_id；
- 所有待处理题目；
- 清晰的恢复步骤。

==================================================
二十、测试要求
==================================================

如果修改源码，运行相关测试，至少覆盖：

- PDF 页码范围；
- OCR 规范化；
- 选择题拆分；
- 选项结构冻结；
- 数制标记、字长、位宽、地址位和容量单位符号；
- 原码、反码、补码、移码及溢出标志的来源保留；
- IEEE 754 符号位、阶码、尾数、偏置和特殊值的来源保留；
- 指令格式、寻址方式、有效地址和寄存器编号的来源保留；
- CPU 数据通路、控制信号、RTL/微操作和微程序字段的来源保留；
- 流水线时空图、冒险、停顿、转发和分支处理的来源保留；
- Cache 映射、Tag/Index/Offset、替换与写策略的来源保留；
- 存储芯片容量、地址译码、位扩展/字扩展和片选范围的来源保留；
- 总线带宽、仲裁、中断、DMA 和 I/O 时序的来源保留；
- 奇偶校验、海明码、状态表、真值表和波形图的来源保留；
- 来源页映射；
- 空答案保留；
- 编辑接口；
- 修改后重新审核；
- Pipeline 幂等；
- 重试不重复入库；
- 事务回滚；
- questions 表不受影响。

不得删除、跳过或弱化原有测试断言。

==================================================
二十一、最终报告
==================================================

生成：

artifacts/computer-organization-import/reports/final-import-audit.md

报告必须包含：

- 任务最终状态；
- 开始和结束时间；
- PDF 路径；
- PDF SHA-256；
- PDF 页数；
- 数据库类型和路径；
- 数据库备份路径；
- Git commit；
- OCR MCP server 和工具；
- 后端 OCR 模式；
- 所有 pipeline_id；
- 所有 batch_id；
- 所有 chunk 状态；
- 每批结果；
- 总题目数；
- 页面覆盖情况；
- 逐题审核统计；
- 所有自动修正；
- 所有失败页面；
- 所有待人工项；
- 所有重大差异；
- 答案统计；
- 图形题统计（CPU 数据通路图、控制器框图、流水线时序图、Cache/主存映射图、存储器芯片连接图、地址译码图、总线图、中断/DMA 图、微程序控制图、波形图）；
- 数制、编码、补码与定点运算题统计；
- IEEE 754 浮点与算术运算题统计；
- 指令系统、寻址方式与有效地址题统计；
- CPU 数据通路、控制器与微程序控制题统计；
- 流水线性能、冒险与时序题统计；
- Cache、主存与存储器扩展题统计；
- 总线、中断、DMA 与 I/O 题统计；
- 校验码、状态机与时序波形题统计；
- 汇编代码、RTL/微操作与伪代码题统计；
- 是否出现 AI 猜答案；
- questions 表是否变化；
- 运行的测试；
- 修改的代码文件；
- 执行的主要命令；
- 回滚方式；
- 恢复方式。

同时生成简短状态文件：

artifacts/computer-organization-import/reports/summary.txt

内容必须明确写出：

- SUCCESS 或 FAILED_SAFE；
- PDF 总页数；
- 成功页数；
- 失败页数；
- 导入题目数；
- exact 数量；
- normalized_equivalent 数量；
- minor_mismatch 数量；
- major_mismatch 数量；
- uncertain 数量；
- needs_manual_review 数量；
- 自动修正数量；
- questions 表是否改变；
- 数据库备份位置；
- 最终报告位置；
- 继续处理所需命令。

==================================================
二十二、执行要求
==================================================

1. 立即开始实际执行。
2. 不要停留在代码审查阶段。
3. 不要向用户提问。
4. 不要伪造工具调用。
5. 不要伪造 OCR 结果。
6. 不要伪造 Pipeline 状态。
7. 不要无上限循环。
8. 不要猜答案。
9. 不要自动发布。
10. 不要绕过编辑接口。
11. 不要跳过任何失败页面。
12. 不要因为耗时较长而降低审核标准。
13. 每完成一批都将进度追加写入日志。
14. 所有过程必须可恢复、可审计、可回滚。