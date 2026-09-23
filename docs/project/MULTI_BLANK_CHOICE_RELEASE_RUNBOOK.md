# Multi-Blank Choice Release Runbook

> **不要按本文中的旧服务器地址操作。** 文中 IP `8.163.56.109` 与目录 `/opt/2240ai-v2` 属于已停用环境。当前生产见 `docs/project/DEPLOY_PLAN.md`（`/opt/22408-ai`）。

> 多空选择题（`multi_blank_choice`）功能上线指导。

---

## 1. 发布前条件

- [ ] 后端部署（兼容新旧格式）
- [ ] 管理端部署
- [ ] 小程序审核通过（如需发布新版）
- [ ] 数据库备份完成（见 §2）
- [ ] 回填 dry-run 报告审核通过（见 §6）
- [ ] 数据验证脚本无高优问题（见 §5）
- [ ] 全量回归测试通过（§14）

## 2. 数据库备份

```bash
# 登录生产服务器
ssh -i loginkey.pem root@8.163.56.109

# 备份 PostgreSQL
cd /opt/2240ai-v2
docker compose exec -T postgres pg_dump -U pguser 2240ai > /tmp/2240ai_backup_$(date +%Y%m%d_%H%M%S).sql

# 验证备份文件大小
ls -lh /tmp/2240ai_backup_*.sql

# 将备份复制到安全位置
# 保留至少到回填完成并验证后
```

## 3. 代码部署顺序

```
1. 后端（app）   → 兼容新旧格式，先部署
2. 管理端（admin）→ 部署在后台之后
3. 小程序        → 可在后端部署后随时发布（需微信审核）
4. 回填脚本      → 代码部署后单独运行（见 §6-10）
```

### 后端部署

```bash
rsync -az --exclude-from=".deployignore" \
  -e "ssh -i loginkey.pem" \
  ./ root@8.163.56.109:/opt/2240ai-v2/

ssh root@8.163.56.109 \
  "cd /opt/2240ai-v2 && bash deploy/scripts/deploy.sh update"
```

### 管理端部署

```bash
# 构建
cd admin-frontend && npm run build

# 部署（dist/ 通过 rsync 同步到服务器 nginx 目录）
# 或随后端 rsync 一并部署
```

## 4. Alembic 迁移

多空选择题不需要数据库 schema 变更（数据存储在已有的 `parsed_content` / `content` JSON 字段中）。

```bash
# 如果你确认需要执行迁移（通常不需要）
ssh root@8.163.56.109 \
  "cd /opt/2240ai-v2 && bash deploy/scripts/deploy.sh migrate"
```

验证迁移状态：
```bash
ssh root@8.163.56.109 \
  "cd /opt/2240ai-v2 && docker compose exec -T app alembic current"
```

## 5. 数据验证（只读）

```bash
# 在生产环境执行只读验证
ssh root@8.163.56.109 \
  "cd /opt/2240ai-v2 && docker compose exec -T app python -m scripts.verify_multi_blank_choice_data --report-json /tmp/verify_report.json"

# 查看报告
ssh root@8.163.56.109 "cat /tmp/verify_report.json"

# 确认：
# - 无 high 级别问题
# - suspected_misclassified 列表可审查
```

## 6. 回填 — 首次 Dry-Run

```bash
# 在生产环境执行 dry-run（只读扫描）
ssh root@8.163.56.109 \
  "cd /opt/2240ai-v2 && docker compose exec -T app python -m scripts.backfill_multi_blank_choice --dry-run --report-json /tmp/backfill_dry_run.json"
```

## 7. 审查 JSON 报告

检查 dry-run 报告：
- `summary.candidates_imports`：导入表中待转换的候选数
- `summary.candidates_questions`：正式题目中待转换的候选数
- `summary.ambiguous_imports`：导入表中歧义记录（需人工审查）
- `summary.ambiguous_questions`：正式题目中歧义记录（需人工审查）
- `candidates`：每个候选的详情（table, id, type, slots, answer）
- `ambiguous`：歧义记录的原因

重点关注：
- 歧义记录为什么被跳过，需要人工处理
- 候选记录是否确实需要回填（查看具体 stem 和 answer）
- 是否存在意外匹配（false positive）

## 8. 小批量 apply（验证用）

```bash
# 先对少量明确 ID 执行 apply
ssh root@8.163.56.109 \
  "cd /opt/2240ai-v2 && docker compose exec -T app python -m scripts.backfill_multi_blank_choice --apply --import-id 1 --import-id 2 --question-id 3 --question-id 4 --yes"
```

小批量验证：
- 检查题目在管理端是否正确显示为多空选择题
- 在小程序中进行答题验证
- 检查判题是否正确

## 9. 全量安全回填

确认小批量验证通过后：

```bash
ssh root@8.163.56.109 \
  "cd /opt/2240ai-v2 && docker compose exec -T app python -m scripts.backfill_multi_blank_choice --apply --batch-size 200"
```

脚本会请求输入 `yes` 确认。建议先使用 `--limit 500` 限制范围，再扩展到全量。

## 10. Apply 后验证

```bash
# 验证无新增问题
ssh root@8.163.56.109 \
  "cd /opt/2240ai-v2 && docker compose exec -T app python -m scripts.verify_multi_blank_choice_data --report-json /tmp/verify_after_apply.json"

# 再次执行 dry-run，确认幂等（无新候选）
ssh root@8.163.56.109 \
  "cd /opt/2240ai-v2 && docker compose exec -T app python -m scripts.backfill_multi_blank_choice --dry-run --report-json /tmp/backfill_after_apply.json"

# 验证第二次 dry-run 的 total_candidates == 0
```

## 11. API Smoke Test

```bash
# 获取多空选择题
curl -s "https://xzshub.top/api/v1/questions?subject=math2&page_size=5" | python3 -m json.tool | grep -c "multi_blank_choice"

# 判题验证
curl -s -X POST "https://xzshub.top/api/v1/practice/submit" \
  -H "Content-Type: application/json" \
  -d '{"question_id": <ID>, "answer": "①:B;②:D", "question_type": "multi_blank_choice"}' | python3 -m json.tool
```

## 12. 小程序人工验收

使用开发者工具或真机预览，确认：

1. **刷题页**
   - 多空选择题显示逐空选项按钮
   - 每空可在自己的选项列表中选择
   - 部分作答后不会误标为已答完
   - 全答完后可正常提交

2. **结果页**（practice-result）
   - 逐空显示：空位 ID、用户选择、正确答案
   - 选错 → 显示用户选项（错误状态）+ 正确选项（正确状态）
   - 未作答 → 显示"未作答"+ 正确答案
   - 整题正确 → 显示"全部正确"

3. **错题详情页**（wrong-detail）
   - 逐空高亮显示
   - 正确空与错误空用不同颜色

4. **兼容性**
   - 旧题型（单选/多选/判断/填空）无回归
   - 公式和富文本选项正确渲染

## 13. 监控指标

部署后 1 小时内关注：

| 指标 | 观察点 |
|------|--------|
| API 错误率 | `POST /practice/submit` 4xx/5xx 增加？ |
| 判题准确率 | `isAnswerCorrect` 对多空选择题返回 null？ |
| 管理端错误 | 审核页加载失败？保存报错？ |
| 回填脚本退出码 | apply 是否全部成功？ |

## 14. 回归测试（本地执行）

```bash
# 后端（使用本地开发数据库）
cd backend
python3 -m pytest tests/test_services/test_multi_blank_choice.py -v
python3 -m pytest tests/test_services/ -q
python3 -m pytest tests/test_api/ -q
python3 -m pytest tests/test_features/ -q

# 小程序
cd miniprogram
node tests/test-multi-blank-answer.js
node tests/test-answer.js

# 管理端
cd admin-frontend
npx tsc --noEmit   # TypeScript typecheck
npm run lint
npm run build
```

## 15. 回滚条件

满足以下任意条件时应执行回滚：

- API 错误率较基线上升超过 5%
- `POST /practice/submit` 出现大量 500 错误
- 多空选择题判题结果明显错误（人工抽查 20 题）
- 小程序闪退或白屏率上升
- 数据验证脚本检测到新的高优问题

## 16. 回滚步骤

### 代码回滚

```bash
# 回滚后端
ssh root@8.163.56.109 \
  "cd /opt/2240ai-v2 && git revert HEAD --no-edit && bash deploy/scripts/deploy.sh update"
```

### 数据回滚

> 仅当回填脚本已经执行且需要撤销时才需要。

```bash
# 如果有备份，使用备份恢复
ssh root@8.163.56.109 \
  "cd /opt/2240ai-v2 && cat /tmp/2240ai_backup_*.sql | docker compose exec -T postgres psql -U pguser 2240ai"

# 没有备份时，逐个表格手动修复：
# 1. question_imports:  将 question_type 改回原值，恢复 parsed_options, parsed_content, parsed_answer
# 2. questions:         将 question_type 改回原值，恢复 options, content, answer
```

## 17. 不允许执行的危险命令

```bash
# ❌ 禁止 — 会删除所有容器和数据
docker compose down

# ❌ 禁止 — 会重置数据库
docker compose down -v

# ❌ 禁止 — 会覆盖生产配置文件
cp .env.prod.local .env

# ❌ 禁止 — 无备份时直接执行 apply
python -m scripts.backfill_multi_blank_choice --apply

# ❌ 禁止 — 跳过确认
python -m scripts.backfill_multi_blank_choice --apply --yes
```

## 发布检查清单

```markdown
□ 数据库备份完成
□ 验证脚本通过（verify_multi_blank_choice_data 无 high 问题）
□ 回填 dry-run 报告审查通过
□ 小批量 apply 验证通过
□ 全量回填 apply 完成（或分批）
□ apply 后验证通过
□ 第二次 dry-run 确认幂等
□ API smoke test 通过
□ 小程序人工验收通过
□ 监控无异常
```
