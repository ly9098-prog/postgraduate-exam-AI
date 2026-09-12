# 数据结构题库题图补图 — 生产执行手册

> 版本: 1.0 | 日期: 2026-07-16

---

## 1. 执行前检查

### 1.1 文件完整性

```bash
# PDF — 513页扫描版真题
ls -lh artifacts/data-structure-import/source/ds_sc.pdf
# 期望: 约 50MB, SHA256 可验证

# Manifest — 19题人工确认 bbox
cat artifacts/data-structure-import/question-image-regions.json | python3 -m json.tool > /dev/null
echo "Manifest valid: $?"

# 确认 manifest 中所有19条 verified=true
python3 -c "
import json
with open('artifacts/data-structure-import/question-image-regions.json') as f:
    m = json.load(f)
for k, v in m.items():
    if not v.get('verified'):
        print(f'WARN: {k} not verified')
print('All verified:', all(v.get('verified') for v in m.values()))
"
```

### 1.2 数据库状态

```bash
# 记录原始状态
sqlite3 backend/postgraduate.db "
SELECT 'question_imports_total', COUNT(*) FROM question_imports
UNION ALL SELECT 'pending_count', COUNT(*) FROM question_imports WHERE status='pending'
UNION ALL SELECT 'linked_count', COUNT(*) FROM question_imports WHERE question_id IS NOT NULL
UNION ALL SELECT 'empty_source_page_start', COUNT(*) FROM question_imports WHERE source_page_start IS NULL
UNION ALL SELECT 'questions_total', COUNT(*) FROM questions;
"
```

### 1.3 数据库备份

```bash
# 备份到安全位置
cp backend/postgraduate.db backend/postgraduate.db.backup.$(date +%Y%m%d_%H%M%S)
ls -lh backend/postgraduate.db.backup.*
```

---

## 2. PDF 校验和验证

```bash
sha256sum artifacts/data-structure-import/source/ds_sc.pdf
# 记录此值，与原始文件对比确认未损坏
```

---

## 3. Manifest 校验和验证

```bash
sha256sum artifacts/data-structure-import/question-image-regions.json
# 记录此值，与开发环境中的 manifest 对比
```

---

## 4. Dry-run 执行

```bash
cd /path/to/project

python scripts/backfill_question_images.py \
  --db sqlite+aiosqlite:///./backend/postgraduate.db \
  --pdf artifacts/data-structure-import/source/ds_sc.pdf \
  --ids 229,369,371,380,388,395,397,400,402,405,407,411,412,451,457,460,461,472,480 \
  --region-manifest artifacts/data-structure-import/question-image-regions.json \
  --replace-existing-images \
  --backfill-all-pages \
  --dry-run \
  --output-report /tmp/backfill_production_dry_run.json
```

### Dry-run 验收条件

检查输出报告:

```bash
python3 -c "
import json
with open('/tmp/backfill_production_dry_run.json') as f:
    r = json.load(f)
s = r['summary']
assert s['success'] == 19, f'Expected 19 success, got {s[\"success\"]}'
assert s['failed'] == 0, f'Expected 0 failed, got {s[\"failed\"]}'
# Verify all are manual_bbox
for item in r['items']:
    assert item['crop_mode'] == 'manual_bbox', f'Item {item[\"import_id\"]} has mode {item[\"crop_mode\"]}'
print('Dry-run validation passed')
"
```

同时确认:

```bash
# 数据库未被修改
sqlite3 backend/postgraduate.db "SELECT COUNT(*) FROM question_imports WHERE source_page_start IS NULL;"
# 应该输出 0（因为 --backfill-all-pages 在 dry-run 下不应修改）

# 检查数据库文件 checksum 与备份一致
md5sum backend/postgraduate.db
```

---

## 5. 正式执行

```bash
python scripts/backfill_question_images.py \
  --db sqlite+aiosqlite:///./backend/postgraduate.db \
  --pdf artifacts/data-structure-import/source/ds_sc.pdf \
  --ids 229,369,371,380,388,395,397,400,402,405,407,411,412,451,457,460,461,472,480 \
  --region-manifest artifacts/data-structure-import/question-image-regions.json \
  --replace-existing-images \
  --backfill-all-pages \
  --no-dry-run \
  --output-report /tmp/backfill_production_live_run.json \
  --backup-dir artifacts/data-structure-import/backups
```

⚠️ 备份到 `artifacts/data-structure-import/backups/` 的数据库备份 `postgraduate_backup_*.db` **请立即复制到安全存储**。

---

## 6. 执行后检查

### 6.1 SQL 检查

```bash
sqlite3 backend/postgraduate.db "
SELECT '--- question_imports 总数 ---';
SELECT COUNT(*) FROM question_imports;

SELECT '--- pending 状态 ---';
SELECT COUNT(*) FROM question_imports WHERE status = 'pending';

SELECT '--- 已关联 question_id ---';
SELECT COUNT(*) FROM question_imports WHERE question_id IS NOT NULL;

SELECT '--- questions 表总数 ---';
SELECT COUNT(*) FROM questions;

SELECT '--- source_page_start 为空 ---';
SELECT COUNT(*) FROM question_imports WHERE source_page_start IS NULL;

SELECT '--- 页码范围 ---';
SELECT MIN(source_page_start), MAX(source_page_start) FROM question_imports;
"
```

所有不变量必须满足:

| 指标 | 期望值 |
|------|--------|
| question_imports 总数 | 513 |
| pending | 513 |
| linked questions | 0 |
| questions 表 | 0 |
| source_page_start 为空 | 0 |
| 最小页码 | 1 |
| 最大页码 | 513 |

### 6.2 图片 URL 检查

```bash
# 检查图片文件已创建
ls -la static/question-assets/202607/ds_sc/*.png
echo "文件数: $(ls static/question-assets/202607/ds_sc/*.png 2>/dev/null | wc -l)"
# 期望: 19 个文件

# 检查图片大小（不应为空）
find static/question-assets/202607/ds_sc/ -name "*.png" -size 0
# 期望: 无输出（无空文件）
```

### 6.3 19 道题 segment 验证

```bash
python3 -c "
import sqlite3, json
conn = sqlite3.connect('backend/postgraduate.db')
cur = conn.cursor()
for qid in [229,369,371,380,388,395,397,400,402,405,407,411,412,451,457,460,461,472,480]:
    row = cur.execute('SELECT parsed_content,source_page_start FROM question_imports WHERE id=?', (qid,)).fetchone()
    if not row:
        print(f'#{qid}: NOT FOUND')
        continue
    pc = json.loads(row[0]) if row[0] else {}
    segs = pc.get('segments', [])
    img_segs = [s for s in segs if isinstance(s,dict) and s.get('type')=='image']
    mode = img_segs[0].get('crop_mode','?') if img_segs else 'NONE'
    cs = (img_segs[0].get('checksum','')[:12]) if img_segs else 'NONE'
    print(f'#{qid}: page={row[1]} segments={len(segs)} images={len(img_segs)} mode={mode} cs={cs}')
"
```

### 6.4 幂等性验证

```bash
# 再执行一次，确认 19 道全部跳过
python scripts/backfill_question_images.py \
  --db sqlite+aiosqlite:///./backend/postgraduate.db \
  --pdf artifacts/data-structure-import/source/ds_sc.pdf \
  --ids 229,369,371,380,388,395,397,400,402,405,407,411,412,451,457,460,461,472,480 \
  --region-manifest artifacts/data-structure-import/question-image-regions.json \
  --replace-existing-images \
  --backfill-all-pages \
  --no-dry-run \
  --output-report /tmp/backfill_production_idempotent_run.json \
  --skip-backup

python3 -c "
import json
with open('/tmp/backfill_production_idempotent_run.json') as f:
    r = json.load(f)
s = r['summary']
assert s['success'] == 0, f'Expected 0 new, got {s[\"success\"]}'
assert s['skipped'] == 19, f'Expected 19 skipped, got {s[\"skipped\"]}'
print('Idempotent: PASS')
"
```

---

## 7. 回滚步骤

### 7.1 从数据库备份恢复

```bash
# 找到数据库备份
ls -la artifacts/data-structure-import/backups/postgraduate_backup_*.db

# 停止应用
sudo systemctl stop postgraduate-ai

# 恢复数据库
cp artifacts/data-structure-import/backups/postgraduate_backup_20260716_*.db backend/postgraduate.db

# 重新启动
sudo systemctl start postgraduate-ai
```

### 7.2 删除新增图片

```bash
# 列出新创建的图片（按文件名中的 import ID 筛选）
rm -v static/question-assets/202607/ds_sc/q_*_p*_*.png

# 确认已删除
ls static/question-assets/202607/ds_sc/
# 期望: 无 png 文件
```

### 7.3 恢复 source_page_start

```bash
# 将 source_page_start 清空（仅在需要时执行）
sqlite3 backend/postgraduate.db "
UPDATE question_imports SET source_page_start = NULL, source_page_end = NULL;
"
```

### 7.4 恢复 parsed_content segments

```bash
# 以下操作会回滚 parsed_content 到无 segments 状态
python3 -c "
import sqlite3, json
conn = sqlite3.connect('backend/postgraduate.db')
cur = conn.cursor()

# 备份当前 parsed_content（可选）
# cur.execute('CREATE TABLE question_imports_bak AS SELECT id, parsed_content FROM question_imports')

# 回滚：从 parsed_content 中移除 image segments
for qid in [229,369,371,380,388,395,397,400,402,405,407,411,412,451,457,460,461,472,480]:
    row = cur.execute('SELECT parsed_content FROM question_imports WHERE id=?', (qid,)).fetchone()
    if not row: continue
    pc = json.loads(row[0]) if row[0] else {}
    if 'segments' in pc:
        # Keep only non-image segments
        segs = [s for s in pc.get('segments', []) if not (isinstance(s,dict) and s.get('type')=='image' and s.get('asset_kind')=='question_figure')]
        pc['segments'] = segs
        cur.execute('UPDATE question_imports SET parsed_content=? WHERE id=?', (json.dumps(pc, ensure_ascii=False), qid))
conn.commit()
print('Rolled back image segments for 19 questions')
"
```

---

## 8. 禁止操作

以下操作在本轮流程中**严禁执行**:

| 操作 | 原因 |
|------|------|
| `publish_questions()` API 调用 | 19 道题虽然补充了图片但答案未经确认 |
| `approve_import_batch` | 同上 |
| 批量审核通过 513 条记录 | 大部分题目仅补充了页码，未做内容审核 |
| 直接修改 `questions` 表 | 应当只通过发布流程写入 |
| 删除数据库备份文件 | 备份是唯一的回滚保障 |
| 反向迁移 (`alembic downgrade`) | 补图不涉及 schema 变更 |

---

## 9. 执行后建议

1. 在管理端逐题人工审核 19 道题图片是否完整；
2. 确认图片 URL 能够被刷题小程序加载；
3. 如发现裁剪图不完整，更新 manifest 中 bbox 后重新执行；
4. 集成测试通过后，将 19 道题纳入审核发布流程。

---

## 10. 快速回滚（1 行命令）

```bash
cp artifacts/data-structure-import/backups/postgraduate_backup_20260716_*.db backend/postgraduate.db
```
