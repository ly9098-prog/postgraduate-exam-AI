# OCR 导题 P5 改造任务：Pipeline 渐进拆分与回归门槛治理

## 任务背景

P0～P4 已完成：

1. OCR 主路径统一。
2. 内存治理、PDF bytes 落盘释放、消除双 OCR。
3. OCR 清洗统一。
4. AI safety gate、风险字段、审核页风险展示。
5. 公式截图、表格 Markdown、原图对照、低风险批量通过。
6. 真实公式截图 URL 闭环。
7. 低风险跳过 AI repair。
8. PaddleOCR 结果缓存。
9. stage checkpoint、resume 接口、真 artifact resume。
10. review 幂等入库。
11. 导入质量报告与真实样本验收脚本。
12. token budget 统一。
13. complete → enrich 风险门禁。

当前系统已经具备比较完整的 OCR 导题能力。下一阶段不要继续堆功能，而是降低工程复杂度，避免后续维护风险。

当前主要结构问题：

1. `pipeline_orchestrator.py` 仍然过大，承担：
   - 多阶段编排
   - OCR 调度
   - checkpoint / artifact resume
   - diagnostics
   - math/table detect
   - repair
   - review
2. `question_pipeline.py` 仍然过大，承担：
   - 标准化
   - AI complete
   - AI enrich
   - draft generation
   - import writing
   - token budget 调用
3. 真实导题验收脚本存在，但还缺少明确回归门槛。
4. 代码语义等价性检查、多列选项错序仍是遗留质量问题。

---

# 本轮总目标

P5 只做四件事：

```text
1. 渐进拆分 pipeline_orchestrator.py
2. 渐进拆分 question_pipeline.py
3. 给真实导题验收增加质量门槛
4. 补两个遗留质量检查：代码语义等价性、多列选项错序
```

本轮以“搬家式拆分”为主，不重写业务逻辑。

------

# 全局约束

请严格遵守：

1. 不重写 OCR pipeline。
2. 不改变现有 API 行为。
3. 不改变已有字段含义。
4. 不改小程序端。
5. 不改变 P0～P4 已完成能力。
6. 不新增大规模数据库迁移。
7. 不引入新的 OCR 模型。
8. 不缓存 LLM 输出。
9. 拆分时优先保持函数签名和输入输出不变。
10. 每拆出一个模块都要有对应测试或复用现有测试。
11. 如果发现拆分风险大，优先停止并输出风险，不要强行大改。

------

# P5-1：审计当前 `pipeline_orchestrator.py` 可拆分边界

## 目标

先确认哪些逻辑适合搬出，哪些逻辑暂时留在 orchestrator。

## 需要检查

```text
backend/app/features/pipeline_orchestrator.py
backend/app/features/pipeline_artifacts.py
backend/app/features/ai_repair.py
backend/app/features/math_import_profile.py
backend/app/features/table_region_detector.py
backend/app/features/review_service.py
```

## 输出要求

请输出：

| 当前函数 / 方法 | 职责 | 建议目标文件 | 是否可安全搬迁 | 风险 |
| --------------- | ---- | ------------ | -------------- | ---- |
|                 |      |              |                |      |

至少覆盖：

```text
extract
normalize
ocr_correction
split
match
normalize_schema
math_detect
table_detect
repair
review
checkpoint
artifact resume
diagnostics
quality_report
```

## 验收标准

1. 明确哪些模块先拆。
2. 明确哪些模块暂缓。
3. 不直接改行为。

------

# P5-2：新增 `pipeline_stages/` 目录并做搬家式拆分

## 目标

将稳定的 stage 逻辑从 `pipeline_orchestrator.py` 中搬到独立文件，降低主文件复杂度。

## 建议新增目录

```text
backend/app/features/pipeline_stages/
  __init__.py
  extract_stage.py
  normalize_stage.py
  ocr_correction_stage.py
  split_stage.py
  match_stage.py
  normalize_schema_stage.py
  math_detect_stage.py
  table_detect_stage.py
  repair_stage.py
  review_stage.py
```

## 拆分原则

1. 第一轮优先拆纯逻辑、低耦合 stage：
   - math_detect
   - table_detect
   - normalize_schema
   - repair
   - review
2. 暂缓拆高耦合部分：
   - checkpoint 主循环
   - artifact resume 主调度
   - pipeline status 更新
   - diagnostics 总装配
3. `ImportPipeline` 仍然作为总编排器。
4. stage 文件只负责执行具体业务，不负责全局状态生命周期。
5. 原有测试必须继续通过。

## 示例结构

```python
# pipeline_stages/math_detect_stage.py

async def run_math_detect_stage(
    questions: list[dict],
    context: PipelineStageContext,
) -> list[dict]:
    ...
```

可以新增轻量 context：

```python
@dataclass
class PipelineStageContext:
    pipeline_id: str
    options: dict
    diagnostics: dict
    page_image_refs: dict | None = None
    artifact_store: object | None = None
```

## 验收标准

1. `pipeline_orchestrator.py` 行数明显下降。
2. 原 stage 行为不变。
3. pipeline E2E 测试通过。
4. OCR regression 测试通过。
5. artifact resume 行为不变。

------

# P5-3：拆分 `question_pipeline.py` 的 AI 后处理逻辑

## 目标

把 AI complete / enrich / draft generation 从 `question_pipeline.py` 中拆出，降低耦合。

## 建议新增文件

```text
backend/app/features/question_ai_complete.py
backend/app/features/question_ai_enrich.py
backend/app/features/question_draft_generator.py
backend/app/features/question_import_writer.py
```

## 拆分原则

1. `question_pipeline.py` 保留兼容入口函数。
2. 原有 API 调用不改。
3. 旧函数可以变成薄包装。
4. complete→enrich 风险门禁必须保留。
5. token budget 统计必须保留。
6. ai_answer_flag 逻辑必须保留。
7. 不改变返回结构。

## 验收标准

1. 现有 complete / enrich / batch_complete 调用不变。
2. 相关测试通过。
3. Type hints 清晰。
4. 不影响管理端 AI 补全 / 丰富功能。

------

# P5-4：真实导题验收增加质量门槛

## 目标

P4 已新增真实验收脚本，现在给验收结果增加明确门槛。

## 修改文件

```text
tests/ocr_acceptance/run_acceptance.py
tests/ocr_acceptance/README.md
```

## 建议门槛

```json
{
  "question_count_recall_min": 0.95,
  "option_integrity_min": 0.98,
  "answer_match_rate_min": 0.96,
  "math_image_presence_min": 0.90,
  "code_symbol_preservation_min": 0.99,
  "table_structure_presence_min": 0.85,
  "manual_review_rate_max": 0.35
}
```

## 要求

1. 默认只输出 warning，不阻断。
2. 支持 `--strict` 模式阻断。
3. 支持按 case 类型设置门槛：
   - math
   - code
   - table
   - mixed
4. 输出 JSON 报告。
5. README 写明如何放置本地真实样本。

## 验收标准

1. 本地 acceptance 能输出 pass/warn/fail。
2. strict 模式能失败退出。
3. 不影响普通 unit test。
4. 报告能看出哪类题退化。

------

# P5-5：代码语义等价性检查

## 目标

防止 OCR correction / AI repair 修改 408 代码逻辑。

## 建议新增文件

```text
backend/app/features/code_semantic_guard.py
```

## 检查对象

重点保护：

```text
->
==
!=
<=
>=
&&
||
*
&
[]
{}
()
++
--
=
+=
-=
*=
/=
%
```

## 实现思路

不做完整编译器，只做轻量语义 guard：

1. 提取修复前后的 code block。
2. 比较关键符号 multiset。
3. 比较控制结构：
   - if
   - for
   - while
   - switch
   - return
4. 比较数组访问数量。
5. 比较指针访问数量。
6. 如果变化异常，拒绝 AI 改动或加 high risk flag。

## 新增 risk_flags

```text
code_semantic_changed
code_operator_changed
code_control_flow_changed
```

## 验收标准

1. `p->next` 被改坏时能检测。
2. `==` 被改成 `=` 时能检测。
3. `&&` / `||` 被改坏时能检测。
4. 非代码题不受影响。
5. 与 ai_safety 集成。

------

# P5-6：多列选项错序进一步优化

## 目标

继续提升 408 / 高数资料中多列选择题的选项顺序恢复能力。

## 修改文件

```text
backend/app/features/question_splitter.py
backend/app/features/visual_boundary_detector.py
```

## 问题场景

```text
A B 两列
C D 两列
OCR 按行读取导致 B 出现在 A 前
左右栏合并导致 A/C/B/D 错序
```

## 实现思路

1. 如果 OCR boxes 存在，按 x 坐标聚类。
2. 判断选项 bbox 的列分布。
3. 对 A/B/C/D 进行空间重排。
4. 如果空间顺序和文本顺序冲突，添加 risk flag。
5. 不确定时不强行重排，进入人工审核。

## 新增 risk_flags

```text
multi_column_options_detected
option_order_spatial_corrected
option_order_uncertain
```

## 验收标准

1. 双列选项题 A/B/C/D 顺序更稳定。
2. 不确定时不会错误重排。
3. 高风险时审核页能看到原因。
4. 真实回归样本覆盖。

------

# P5-7：更新工程文档

## 目标

P0～P5 后 OCR 导题链路已经明显变化，需要更新文档，避免后续维护混乱。

## 需要更新

```text
docs/architecture/OCR_FLOW.md
docs/architecture/OCR_USAGE.md
docs/ai/AI_PIPELINE.md
docs/audit/ocr-pipeline-full-engineering-audit.md
```

## 要求

1. 更新当前 pipeline 阶段。
2. 标明哪些 stage 已拆分。
3. 标明 artifact resume 机制。
4. 标明 risk_flags 体系。
5. 标明 math_image / table_markdown / source_region。
6. 标明 acceptance gates。
7. 标明仍未完成事项。

## 验收标准

1. 文档与代码一致。
2. 新人能通过文档理解 OCR 导题流程。
3. 不再保留明显过时描述。

------

# 测试要求

请至少运行：

```bash
pytest tests/test_features/test_pipeline_e2e.py
pytest tests/test_features/test_pipeline_resume.py
pytest tests/test_features/test_pipeline_checkpoint.py
pytest tests/ocr_regression
```

如果修改前端：

```bash
cd admin-frontend
npm run typecheck
```

如果新增 acceptance gate：

```bash
python tests/ocr_acceptance/run_acceptance.py --case-dir tests/ocr_acceptance/cases
python tests/ocr_acceptance/run_acceptance.py --case-dir tests/ocr_acceptance/cases --strict
```

------

# 不做事项

本轮明确不做：

1. 不换 OCR 模型。
2. 不做复杂表格 OCR 引擎。
3. 不重写 pipeline。
4. 不改变 API 行为。
5. 不改小程序端。
6. 不缓存 LLM 输出。
7. 不删除旧兼容入口。
8. 不做数据库大迁移。

------

# 最终输出格式

执行完成后，请输出：

## 1. 本轮完成了哪些 P5 任务

逐项说明 P5-1 到 P5-7 是否完成。

## 2. 修改了哪些文件

用表格列出：

| 文件 | 修改内容 | 对应任务 |
| ---- | -------- | -------- |
|      |          |          |

## 3. 拆分前后结构

说明：

```text
拆分前：
拆分后：
```

## 4. 保持兼容的入口

列出旧函数 / 新函数映射：

| 旧入口 | 新实现 | 是否兼容 |
| ------ | ------ | -------- |
|        |        |          |

## 5. 新增 risk_flags

| risk_flag | 风险等级 | 触发条件 |
| --------- | -------- | -------- |
|           |          |          |

## 6. Acceptance gate 结果

输出示例：

```json
{
  "overall": "warn",
  "failed_gates": [],
  "warning_gates": ["manual_review_rate"],
  "metrics": {}
}
```

## 7. 运行测试结果

输出实际运行命令和结果。

## 8. 未完成事项

如果某项任务未完成，请说明原因。

## 9. 风险和注意事项

说明是否影响：

- PDF 导入
- 图片导入
- Excel 导入
- 文本导入
- resume
- artifact
- OCR cache
- AI complete
- AI repair
- 管理端审核

## 10. 下一轮建议

下一轮优先考虑：

1. 更细粒度 pipeline_stage 单元测试。
2. question_pipeline 剩余逻辑继续拆分。
3. 真实样本扩充。
4. 性能 profile。

