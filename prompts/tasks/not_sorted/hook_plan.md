# 🧩 一、最终推荐架构（精简但专业版）

```
Claude Code Automation Stack

Level 1 - Safety（必须）
  PreToolUse → 敏感文件保护

Level 2 - Fast Feedback（hooks）
  PostToolUse → 轻量测试 + lint

Level 3 - Intelligence（agents）
  OCR pipeline reviewer
  DB migration reviewer

Level 4 - CI（GitHub Actions）
  full pytest + OCR regression + migration check

Level 5 - MCP（能力增强）
  context7
```

------

# 🛡️ 二、Level 1：PreToolUse（安全层，强烈建议）

📌 文件：`.claude/settings.local.json`

```json
{
  "hooks": {
    "PreToolUse": {
      "protect-sensitive-files": {
        "glob": "{backend/.env,**/*.pem,**/*.key,**/*.crt,**/*.db,backend/.venv/**}",
        "command": "echo '⛔ Blocked: sensitive file modification detected (.env/db/key)' && exit 1"
      }
    }
  }
}
```

### ✔ 我帮你优化点：

- 不只是 .env
- 加了：
  - key / cert
  - db
  - venv
- 防止 OCR 数据库误删

------

# ⚡ 三、Level 2：PostToolUse（关键优化版）

## ❌ 你原来的问题：

- 每次改 Python → 跑全量 pytest ❌（太慢）

------

## ✔ 我给你的版本（智能分流）

```json
{
  "hooks": {
    "PostToolUse": {
      "smart-test-runner": {
        "glob": "backend/**/*.py",
        "command": "bash .claude/scripts/smart_test_runner.sh"
      }
    }
  }
}
```

------

## 🧠 新增脚本：`.claude/scripts/smart_test_runner.sh`

```bash
#!/bin/bash

FILE_CHANGED=$1

echo "🧪 Detecting change: $FILE_CHANGED"

# 1. OCR pipeline 改动 → 跑重测试
if echo "$FILE_CHANGED" | grep -E "ocr|parser|qwen|paddle"; then
  echo "🔥 OCR pipeline detected → running full OCR regression tests"
  pytest backend/tests/ocr -q
  exit 0
fi

# 2. migration 改动 → 跑 DB 测试
if echo "$FILE_CHANGED" | grep -E "alembic|migration|models"; then
  echo "🧱 DB layer change → running migration tests"
  pytest backend/tests/db -q
  exit 0
fi

# 3. 普通 API → 轻量测试
echo "⚡ running unit tests only"
pytest backend/tests/unit -q
```

------

### ✔ 这个版本的优点：

- 不拖慢 Claude Code
- OCR 改动才跑重测试
- API 改动只跑 unit
- migration 自动保护

------

# 🧠 四、Level 3：Agents（重点优化你项目）

## 1. OCR Pipeline Reviewer（强烈建议）

📄 `.claude/agents/ocr-pipeline-reviewer.md`

核心职责：

- 检查 OCR 输出结构是否变化
- 检查 Qwen / PaddleOCR 输出一致性
- 检查 JSON schema 是否破坏
- 检查 LaTeX / 数学公式误修复

### 它要重点盯：

✔ OCRFixRouter
✔ AI纠错层
✔ qwen-vl / qwen3.5-ocr
✔ normalization pipeline

------

## 2. DB Migration Reviewer（增强版）

比原来的更严格：

检查：

- downgrade 是否实现
- revision chain 是否断裂
- OCR JSON schema 是否变化
- nullable / default 是否安全
- 是否影响 production table

------

# 🧪 五、Level 4：CI（GitHub Actions）

你必须保留 CI 做：

- 全量 pytest
- OCR regression dataset
- migration validation

👉 原则：

> hooks = 快
> CI = 全

------

# 🔌 六、Level 5：MCP（推荐）

## ✔ context7（可以加）

适合你：

- FastAPI
- SQLAlchemy
- Pydantic
- OCR pipeline design

安装：

```bash
claude mcp add context7
```

------

# 🧠 七、我帮你总结“最关键的优化点”

你现在这个项目真正核心是：

> 🧾 OCR + AI纠错链路（不是普通 CRUD）

所以关键优化应该是：

### ❌ 不要：

- 全量 pytest hook
- 过多自动化噪音

### ✔ 要：

- OCR 改动单独触发重测
- schema / AI输出严格守护
- migration 单独保护
- CI 做最终裁判

------

