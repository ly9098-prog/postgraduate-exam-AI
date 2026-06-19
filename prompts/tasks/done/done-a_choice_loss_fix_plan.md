# 多空选择题首组选项 A 丢失修复记录

## 问题现象

实际 OCR/PDF 导入后，审核页中的多空选择题已识别为 `multi_blank_choice`，但第一个 `blank_option_groups` 缺少 `A` 选项：

```text
blankOptionGroups[0].optionKeys = ["B", "C", "D"]
blankOptionGroups[1].optionKeys = ["A", "B", "C", "D"]
```

原题两组选项都应为 `A/B/C/D`：

```text
若系统有 n 个进程，则就绪队列中进程的个数最多有（①）个；阻塞队列中进程的个数最多有（②）个。
① A. n+1  B. n  C. n−1  D. 1
② A. n+1  B. n  C. n−1  D. 1
```

## 实际根因（2026-06-07）

最初怀疑是圈号 group marker（如 `①/(1)/Ⅰ`）与 option prefix 正则冲突，导致 `① A.` 的 `A` 被吞掉。

进一步从 SQLite 审核池记录 `id=1163` 取到真实 `raw_data` 后确认：问题不是显式 grouped options 路径误判，而是进入 splitter 前文本已经退化：

```text
题干：含两个普通 `（）`
选项行顺序：D. 1 / B. n / C. n-1 / A. n+1 / D. 1 / B. n / C. n-1
raw_data.blank_option_groups：第一组 B/C/D，第二组 A/B/C/D
```

也就是说，第一组缺失 A 的真实失败形态是“普通空括号退化 + 重复组选项错位”，不是 `① A.` 显式 marker 被正则吞掉。

## 修复方式

修复位置：`backend/app/features/question_splitter.py`。

新增 `_repair_repeated_degraded_groups`，只在非常保守的退化场景补齐缺失 A：

1. 题干空位已经退化为普通 `（）`。
2. 已存在至少一组完整 `A/B/C/D` 组选项。
3. 某一缺 A 组已有的 `B/C/D` 与完整组一致。
4. 满足以上条件时，从完整组复制 `A` 回缺失组。

显式 `①/(1)/Ⅰ` grouped options 解析路径保持不变，不把本次兜底扩展到正常 marker 解析逻辑。

## 测试与验证

- 新增真实失败形态回归测试，覆盖 `D/B/C/A/D/B/C` 退化顺序下第一组补回 `A`。
- 加强已有 grouped options 测试断言，确认显式 `①/(1)/Ⅰ` 路径仍保留每组 `A/B/C/D`。
- 已运行：

```bash
PYTHONPATH=/home/lmh/projects/postgraduate-ai/backend pytest -q \
  /home/lmh/projects/postgraduate-ai/backend/tests/test_services/test_question_splitter.py \
  /home/lmh/projects/postgraduate-ai/backend/tests/test_services/test_review_service.py
```

结果：`123 passed, 1 warning in 1.04s`。

## 验收标准

- splitter 输出的 `blank_option_groups[0].options` 不再缺少 `A`。
- normalizer 输出仍为 `question_type = "multi_blank_choice"`、`options = []`。
- review 入池后 `parsed_content.blank_option_groups` 保留第一组 `A/B/C/D`。
- 显式 grouped options 路径无回归。
