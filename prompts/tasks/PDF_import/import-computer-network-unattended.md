# 计算机网络题库无人值守导入、逐题审核与修复 Prompt

你当前位于 MemoGrad / postgraduate-ai 项目根目录。

请以完全无人值守方式，实际执行《计算机网络题库.pdf》（ocr_test/import/cn_sc.pdf）的导入、逐题审核、
错误修正和修正后复核。

不要只分析代码、提出建议或生成示例命令。必须真实运行后端、调用 OCR MCP、
执行导入、查询数据库、调用题目编辑接口、核验修改结果并生成审计报告。

本任务运行期间没有用户在线。不得暂停等待用户回答，不得请求用户确认。
遇到存在多种选择的情况，始终采取最保守、可恢复、不污染数据库的方案。

任务参数：

PDF_FILENAME=cn_sc.pdf
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

1. 找到《计算机网络题库.pdf》（ocr_test/import/cn_sc.pdf）的真实绝对路径。
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
   - 不得根据教材知识、互联网资料或 AI 推理生成答案；
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

artifacts/computer-network-import/
artifacts/computer-network-import/source/
artifacts/computer-network-import/source-pages/
artifacts/computer-network-import/backend-ocr/
artifacts/computer-network-import/mcp-ocr/
artifacts/computer-network-import/crops/
artifacts/computer-network-import/audit/
artifacts/computer-network-import/reports/
artifacts/computer-network-import/backups/
artifacts/computer-network-import/logs/

任务开始时创建：

artifacts/computer-network-import/RUNNING

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

计算机网络题库.pdf

不得使用相似文件名替代。

如果存在多个同名文件：

1. 计算 SHA-256；
2. 记录文件大小和页数；
3. 优先选择项目目录内最新但非临时副本；
4. 如果仍无法唯一确认，安全停止，不得猜测。

建立：

artifacts/computer-network-import/source/manifest.json

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

artifacts/computer-network-import/backups/

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
- questions 表中与“计算机网络”相关的题目数量。

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

先查询 subjects 表，寻找最合适的计算机网络科目。

不得创建重复科目。

如果不存在计算机网络科目，允许通过项目现有科目 service/API 创建唯一科目，
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
- 网络拓扑图、协议分层图、分组交换时序图和 TCP 状态图；
- 以太网帧、IP 数据报、TCP/UDP 报文段、路由表、子网划分图和拥塞窗口曲线；
- 代码、伪代码和公式；
- 页眉和页脚。

保存后端 OCR 的原始输出、中间清洗结果和最终拆题结果。

对第 1—10 页调用 OCR MCP 独立识别。

OCR MCP 的结果保存到：

artifacts/computer-network-import/mcp-ocr/trial/

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
- 图片、表格、网络拓扑图、协议分层图、帧/分组/报文段格式图、TCP 时序图、路由表、子网划分图、拥塞窗口曲线、公式、代码和伪代码；
- 题目顺序；
- 跨页关系。

重点检查计算机网络题常见高风险内容：

1. O、0、Q 混淆；
2. I、l、1 混淆；
3. B、8、6 混淆；
4. 大于、小于、箭头、链路方向和报文传播方向；
5. `->`、`=>`、`<-`、`<->`、`↔`；
6. `==`、`!=`、`<=`、`>=`、`/`、`:`、`.`；
7. 中括号、圆括号、花括号、尖括号及位字段边界；
8. IPv4 点分十进制、IPv6 十六进制、双冒号压缩和前导零；
9. MAC 地址、IP 地址、端口号、接口名、AS 号、VLAN ID 和协议号；
10. CIDR 前缀长度、子网掩码、网络地址、广播地址、主机地址范围和 VLSM；
11. 二进制、十进制、十六进制转换及位数、字节序、比特序；
12. bit、Byte、bps、B/s、Kbps、Mbps、Gbps、KB、MB、MiB 及 10/2 的幂次；
13. OSI 七层、TCP/IP 分层、协议归属和 PDU 名称：bit、frame、packet/datagram、segment；
14. 协议缩写与拼写：ARP、RARP、ICMP、DHCP、DNS、HTTP/HTTPS、FTP、SMTP、POP3、IMAP、TCP、UDP、IP、NAT；
15. 局域网与链路层：Ethernet、CSMA/CD、CSMA/CA、PPP、HDLC、VLAN、STP；
16. 以太网帧字段：前导码、SFD、目的/源 MAC、Type/Length、802.1Q Tag、Payload、FCS；
17. ARP 请求/应答、ARP 表、交换机转发表、自学习、泛洪、过滤和老化；
18. CRC 生成多项式、模 2 除法、余数位数、奇偶校验、海明码位置和纠错位；
19. IPv4 首部字段：Version、IHL、Total Length、Identification、DF/MF、Fragment Offset、TTL、Protocol、Checksum；
20. IPv4 分片中的片偏移单位、首部长度、数据长度、MTU、DF/MF 和重组关系；
21. IPv6 首部、扩展首部、地址压缩、链路本地地址、组播地址和无广播特性；
22. ICMP 类型/代码、差错报告、Echo Request/Reply、TTL 超时和路径探测；
23. TCP/UDP 首部字段、源/目的端口、Length、Checksum、Sequence Number、Acknowledgment Number；
24. TCP 标志位：SYN、ACK、FIN、RST、PSH、URG，以及标志位组合；
25. TCP 三次握手、四次挥手、半关闭、同时打开/关闭和 TIME_WAIT；
26. TCP 状态迁移：LISTEN、SYN-SENT、SYN-RECEIVED、ESTABLISHED、FIN-WAIT、CLOSE-WAIT、LAST-ACK、TIME-WAIT；
27. TCP 序号空间、确认号含义、数据长度、累计确认、重复 ACK、超时重传和快速重传；
28. 滑动窗口、发送窗口、接收窗口、rwnd、cwnd、MSS、窗口缩放和零窗口；
29. 拥塞控制：Slow Start、Congestion Avoidance、Fast Retransmit、Fast Recovery、ssthresh、AIMD；
30. RTT、RTO、SampleRTT、EstimatedRTT、DevRTT、传播时延、发送时延、排队时延和处理时延；
31. 带宽时延积、吞吐量、利用率、往返时延、流水线协议和停止等待协议计算；
32. Go-Back-N、Selective Repeat 的窗口大小、序号空间、ACK/NAK、超时和重传范围；
33. 路由表字段：目的网络、掩码/前缀、下一跳、出接口、度量值和默认路由；
34. 最长前缀匹配中的候选路由、前缀比较和最终下一跳；
35. 距离向量与链路状态、Bellman-Ford、Dijkstra、RIP、OSPF、BGP、AS-PATH 和自治系统；
36. 网络拓扑图中的节点、链路、方向、权值、接口、下一跳、路径和最短路；
37. NAT/PAT 映射中的内网/公网地址、端口转换、方向和映射表项；
38. DHCP Discover/Offer/Request/ACK 顺序、租约、地址池、网关和 DNS 参数；
39. DNS 层次、递归/迭代查询、根/顶级/权威服务器、资源记录类型、TTL 和缓存；
40. HTTP 请求方法、状态码、首部字段、持久连接、Cookie、缓存验证、Host 和 Content-Length；
41. Socket/C/C++/Java/Python 或伪代码中的地址结构、字节序转换、bind/listen/accept/connect/send/recv 参数；
42. Wireshark/抓包文本、路由器/交换机配置命令中的冒号、斜杠、接口编号、缩进和字段对齐；
43. 无线网络中的信道、频率、SSID、BSSID、AP、隐藏终端、暴露终端和 RTS/CTS；
44. 上标、下标、数学公式、概率、对数和性能计算式；
45. 否定词：
    - 不正确；
    - 错误；
    - 不包括；
    - 不能；
    - 不属于；
    - 不会；
    - 无法；
46. 页眉、页脚、水印误入题干；
47. 一题被拆成两题；
48. 两题被合成一题；
49. 选项串题；
50. 选项缺失；
51. 选项顺序错误；
52. 原页无答案但数据库出现答案；
53. 原页包含网络拓扑图、协议栈图、帧/分组/报文段格式图、TCP 时序图、路由表、子网划分图或拥塞窗口曲线，但数据库完全丢失图形信息；
54. 跨页题目的地址表、路由表、报文序列、状态图、代码、公式或拓扑图被截断。

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
题干、选项、数字、IP/MAC 地址、端口、前缀长度、子网掩码、协议字段、序号/确认号、路由代价、时延参数、代码、图形关系或否定词错误，可能影响作答。

uncertain：
原图模糊、OCR 引擎冲突，或网络拓扑、协议报文格式、TCP 时序、路由表、子网划分、拥塞窗口曲线无法可靠还原。

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
- 明确括号、箭头、IP/MAC 地址、前缀长度、端口、协议字段、序号/确认号、校验和、时间参数或代码符号错误；
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
- 网络拓扑、帧/分组/报文段格式、TCP 时序、路由表、子网划分或拥塞窗口图无法准确重建的题目；
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

artifacts/computer-network-import/audit/auto-fixes.jsonl

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
- 网络拓扑图、协议报文格式图、TCP 时序图、路由表、子网划分图和拥塞窗口曲线已保留可刷题所需信息，或进入人工复核；
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
- 图形数量及类型（网络拓扑图、协议分层图、帧/分组/报文段格式图、TCP 时序图、路由表、子网划分图、拥塞窗口曲线等）；
- 是否跨页；
- 是否重复；
- 是否缺失。

保存：

artifacts/computer-network-import/audit/page-summary.csv

==================================================
十六、输出逐题审核文件
==================================================

生成：

artifacts/computer-network-import/audit/items.jsonl
artifacts/computer-network-import/audit/items.csv
artifacts/computer-network-import/audit/manual-review.csv
artifacts/computer-network-import/audit/page-summary.csv
artifacts/computer-network-import/audit/auto-fixes.jsonl
artifacts/computer-network-import/audit/differences.md

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
31. 代码或伪代码结构异常数量；
32. TCP 序号、确认号、窗口或状态迁移异常数量；
33. IP 地址、子网掩码、CIDR 前缀或路由表结构异常数量；
34. 以太网帧、IP 数据报、TCP/UDP 首部、CRC 或校验和异常数量；
35. 路由拓扑、路径、接口、下一跳或代价异常数量；
36. DNS/HTTP 报文、Socket 代码或网络配置结构异常数量；
37. 重试产生的重复题数量；
38. questions 表导入前后数量差异；
39. 数据库完整性检查结果。

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
9. 网络拓扑图、协议分层图、帧/分组/报文段格式图、TCP 时序图、路由表、子网划分图和拥塞窗口曲线均已正确保留，或不存在此类题目。
10. 子网计算、协议字段、序号/确认号、路由路径、时延计算、代码、伪代码和公式均完成视觉复核。
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
- 网络拓扑图、协议报文格式图、TCP 时序图、路由表、子网划分图或拥塞窗口曲线无法可靠保留；
- 子网计算、协议字段、序号/确认号、路由路径、时延计算、代码、伪代码或公式无法可靠确认；
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
- 计算机网络协议缩写、地址、端口、前缀长度、时间参数和单位符号；
- OSI/TCP-IP 分层、协议与 PDU 对应关系的来源保留；
- IPv4/IPv6 地址、子网掩码、CIDR、VLSM 和地址范围的来源保留；
- 以太网帧、VLAN、ARP、IP、ICMP、TCP、UDP 首部字段及位图的来源保留；
- TCP 三次握手、四次挥手、状态迁移、序号/确认号、滑动窗口和重传时序的来源保留；
- 路由表、最长前缀匹配、RIP/OSPF/BGP、网络拓扑、路径和代价的来源保留；
- DNS/HTTP/DHCP/NAT、Socket 代码、抓包文本和网络配置命令的来源保留；
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

artifacts/computer-network-import/reports/final-import-audit.md

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
- 图形题统计（网络拓扑图、协议分层图、帧/分组/报文段格式图、TCP 时序图、路由表、子网划分图、拥塞窗口曲线）；
- 子网划分、地址范围和最长前缀匹配计算题统计；
- 时延、吞吐量、带宽时延积和利用率计算题统计；
- TCP 连接管理、可靠传输、流量控制和拥塞控制题统计；
- 路由算法、DNS/HTTP/DHCP/NAT 和局域网协议题统计；
- 代码与伪代码题统计；
- 是否出现 AI 猜答案；
- questions 表是否变化；
- 运行的测试；
- 修改的代码文件；
- 执行的主要命令；
- 回滚方式；
- 恢复方式。

同时生成简短状态文件：

artifacts/computer-network-import/reports/summary.txt

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