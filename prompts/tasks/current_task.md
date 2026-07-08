任务：修复 OCR 导入中“代码块题干被乱码化、答案未稳定透传”的问题。

背景：
当前测试图片 ocr_code_test_2.png 中，原题为二叉树遍历题，代码块原文应为：

typedef struct BiTNode {
    char data;
    struct BiTNode *lchild, *rchild;
} BiTNode, *BiTree;

但当前导入结果中，代码块被识别/纠错为：

typedef struct BiTNode {
char data;
(ltypu*  pltysl* apollta aonu2s
} BiTNode, *BiTree;

选项 A/B/C/D 能够保留，答案 A 在 OCR 原文中也出现过，但最终审核页/日志仍显示答案缺失或 answer=❌。

日志证据：
1. OCR-1 原始结果中，代码第三行已经识别失败：
   (1typu*  p1tysI* apo11ta aonu2s
2. OCR-5 AI纠错后，代码没有被恢复，反而变成：
   (ltypu*  pltysl* apollta aonu2s
3. split 阶段已经成功冻结选项 A/B/C/D。
4. match 阶段日志显示 Explicit answer extracted: answer=A。
5. normalize_schema/review 阶段仍显示答案 ❌，需要确认是字段未透传还是日志字段打印错误。

修复目标：
导入 ocr_code_test_2.png 后，审核页应得到：

题干：
已知二叉树的结点结构定义如下，若一棵二叉树的中序遍历序列为 DBEAFC，后序遍历序列为 DEBFCA，则其前序遍历序列为：

```c
typedef struct BiTNode {
    char data;
    struct BiTNode *lchild, *rchild;
} BiTNode, *BiTree;
```

选项：
A. ABDECF
B. ABDCEF
C. ABDFEC
D. ACBEDF

答案：
A

一、必须修复的问题

1. 禁止纯文本 LLM 对严重乱码代码块自由纠错
   当检测到 code_garbled_text / code_block_incomplete / code_line_break_suspicious 时：

- 不允许 deepseek_adapter 仅基于 OCR 乱码文本“猜代码”；
- 如果候选纠错后的代码仍包含乱码特征，必须 reject；
- 不得因为模型返回 confidence=0.85 就接受；
- 必须以规则质量检测结果为准，而不是模型自报置信度。

建议修改：
features/ocr_fix/router.py
features/ocr_fix/deepseek_adapter.py
features/ocr_quality_gate.py
features/code_integrity.py

新增候选验收逻辑：

- before_flags = detect_code_block_integrity(before).flags
- after_flags = detect_code_block_integrity(after).flags
- 如果 before 有 code_garbled_text，after 仍有 code_garbled_text，则 reject_continue
- 如果 after 的 garbled score 没有明显下降，则 reject_continue
- 如果代码块中连续出现大量非代码词、伪英文碎片、无法构成 C 语法的 token，则 reject_continue
- 被 reject 后保留原文或进入视觉回退，不得写入更差结果

1. PaddleOCR-VL 结果不能因“选项丢失”整体废弃
   当前 PaddleOCR-VL 被 reject 的原因是 options_dropped(4→0)，但这不代表它的代码识别结果没有价值。
   应改为“结构安全合并”：

- 选项、答案以原 OCR/冻结 registry 为准；
- VL 只负责替换题干中的代码块区域；
- 如果 VL 输出没有选项，不应直接废弃 VL 的代码识别结果；
- 应将 VL 的 code block 与原始 frozen options、原始 answer 合并。

建议新增函数：
merge_vl_code_with_frozen_structure(original_text, vl_text, frozen_options, original_answer)

合并规则：

- 从 original_text 中提取题干、选项、答案；
- 从 vl_text 中提取更可信的代码块；
- 只替换 fenced code block 内部内容；
- 原选项 A/B/C/D 不允许被 VL 覆盖；
- 原答案行不允许被 VL 删除；
- 合并后再次跑 code_integrity + option_integrity + answer_integrity。

1. 代码块视觉回退要走“代码区域 crop”，而不是整页文本纠错
   对于代码块题：

- local OCR 如果检测到代码乱码，应裁剪代码灰底区域；
- 对代码 crop 单独调用视觉 OCR/VL；
- prompt 明确要求：只识别代码，不要输出题干、选项、答案；
- 返回后只替换代码块。

建议新增：
features/code_region_cropper.py
features/vision_code_ocr.py

接口示例：
recognize_code_region(image_path, bbox=None) -> {
"code": "...",
"confidence": 0.0-1.0,
"engine": "paddleocr-vl",
"warnings": []
}

1. 修复 code_structure_reconstruct 的假成功
   当前日志显示 code_structure_reconstruct 执行成功，并标记 code_fixed=True，但这只是“缩进层级修复”，并没有修复乱码代码。后续不能把这种情况当作成功。

修改：
features/pipeline_stages/code_structure_stage.py

验收条件：

- 只修复缩进、括号、换行，不允许修复语义缺失的乱码 token；
- 如果输入含 code_garbled_text，code_structure_reconstruct 不应清除风险标；
- 如果输出仍有 code_garbled_text，不得提升 confidence_score；
- 不得把 risk_flags 从 code_garbled_text 改成空；
- code_fixed=True 只有在 code_integrity flags 明显减少时才成立。

1. 修复答案 A 的透传/显示问题
   日志显示 match 阶段已经提取到 answer=A，但 normalize_schema 和 review 日志仍显示答案 ❌。
   需要排查：

- matched_pairs 是否按 question_number 正确传入 normalize_question；
- question_number 类型是否 string/int 不一致导致 matched_by_num 取不到；
- normalize_schema_stage.py 是否只打印 parsed_answer，而真实字段是 answer；
- review_stage.py 是否也只打印 parsed_answer；
- review_service 写库时 parsed_answer 是否来自 q["answer"]。

验收：

- normalize_schema 结果中 answer == "A"
- review 入库 parsed_answer == "A"
- 前端审核页显示答案 A
- 日志中不得再显示 answer=❌

二、必须新增测试

新增测试文件建议：
tests/test_ocr_code_question_repair.py

测试 1：ocr_code_test_2 完整导入
输入：ocr_code_test_2.png
断言：

- question_type == single_choice
- stem 包含 "typedef struct BiTNode"
- stem 包含 "struct BiTNode *lchild, *rchild;"
- stem 不包含 "ltypu"
- stem 不包含 "pltysl"
- stem 不包含 "apollta"
- options == {
  "A": "ABDECF",
  "B": "ABDCEF",
  "C": "ABDFEC",
  "D": "ACBEDF"
  }
- answer == "A"
- parsed_answer == "A"
- risk_flags 不应包含 code_garbled_text
- confidence_score >= 0.8，或如果仍需人工审核，则必须明确标记 vision_fallback_failed，不能伪装为已修复

测试 2：VL 输出丢选项但代码正确
构造：
original_text 含乱码代码 + A/B/C/D + 答案 A
vl_text 只含正确代码块，不含选项
断言：

- 合并后保留 A/B/C/D
- 合并后保留答案 A
- 合并后代码替换为 VL 代码
- 不触发 options_dropped 失败

测试 3：文本 LLM 把乱码改成另一段乱码
构造：
before: (1typu* p1tysI* apo11ta aonu2s
after: (ltypu* pltysl* apollta aonu2s
断言：

- router 必须 reject_continue
- 不得接受模型自报 confidence=0.85
- 不得覆盖原题干

测试 4：答案透传
构造 raw_question number 为 "2" 和 matched question_number 为 2 两种情况
断言：

- string/int 题号都能匹配
- normalize_question 输出 answer == "A"
- review 写库 parsed_answer == "A"

三、实现优先级

P0：

- 修复答案透传/日志字段问题。
- 增加 OCR correction candidate 的代码质量验收，禁止接受更差乱码。
- code_structure_reconstruct 不得对 code_garbled_text 假成功。

P1：

- 实现 VL 代码块与 frozen options/answer 的安全合并。
- 对代码块启用视觉区域 crop 回退。

P2：

- 建立代码题 OCR 回归样例集，覆盖 C 结构体、链表、树、栈、队列、伪代码等常见 408 代码块。

四、最终验收标准

重新导入 ocr_code_test_2.png，审核页必须显示：

1. 正确代码：
   struct BiTNode *lchild, *rchild;
2. 四个选项完整；
3. 答案 A 正确显示；
4. 不再出现 ltypu / pltysl / apollta / aonu2s；
5. 日志中 OCR-7、OCR-8 均不再显示 answer=❌；
6. 如果视觉识别失败，必须进入人工复核并明确展示 code_garbled_text，不得把乱码题干当作“修复成功”。

```
重点一句：这轮要修的是**“代码块必须靠视觉/区域 OCR 或严格规则恢复，不能靠文本 LLM 猜；VL 结果要能只替换代码，不能因为丢选项整体废弃”**。
```
