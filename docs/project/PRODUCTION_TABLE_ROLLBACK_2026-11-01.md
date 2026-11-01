# 生产空表删除与恢复记录（2026-11-01）

最终状态：用户撤回删除要求后，已恢复本轮删除的全部 17 张空表。恢复事务已提交，2026-11-01 13:24:45（Asia/Shanghai）完成校验。未覆盖其他 64 张表的数据，没有修改 Alembic 版本或重启服务。本记录不代表 ENV-06 最终验收通过。

## 范围与过程

按 `DEPLOY_PLAN.md` 连接生产库 `postgraduate`。用户明确授权删除空表并禁止删除非空表，再次要求执行后，先生成完整备份及 schema 快照；同一事务对下列 17 表取得 `ACCESS EXCLUSIVE` 锁，逐表确认 `COUNT(*)=0`，使用一条显式 `RESTRICT` 的多表 DROP，2026-11-01 13:16:22 提交。清单外 64 张表的名称、schema 和 OID 全部保留。

用户随后要求“算了，回滚那些表”。从本次备份提取限定对象，在单一事务内恢复表、序列、默认值、索引和约束；恢复前确认目标均不存在，提交前确认 17 表全部为空、其他 64 表身份不变及迁移标记不变。未进行全库恢复、业务行回灌、删除或清空其他表。

恢复清单：

```text
admin_ai_settings
admin_ai_usage_monthly
ai_feedback_logs
export_snapshots
formula_graph_previews
formula_import_items
formula_import_jobs
import_pipeline_chunks
import_pipelines
ocr_jobs
recommendation_experiment_assignments
sequential_reservations
syllabus_knowledge_point_mappings
tags
user_recommend_preference
watermark_rules
worker_credentials
```

## 备份与验证

服务器证据目录：

```text
/data/backups/postgres/pre_drop_empty_20261101T051459Z_jondm9/
```

- `postgraduate.dump`：23,185,496 字节，SHA256 `f1111caf88052f0b5f65138ec9e591528427233f04102dafdde015c40817760a`。
- `schema_before.sql`：248,938 字节，SHA256 `8fff89c813c6b2121293fd865e1a01213494e64aac10fc326c5ede2e1148e021`。
- 目录创建权限 700，备份文件 600；TOC 可读、完整归档解码及 SHA256 复核通过。未执行含过期备份清理的脚本。
- `drop_empty_tables.sql` / `drop_result.txt` 保存实际删除事务和结果；`restore_17_transaction.sql` / `restore_result.txt` 保存实际恢复事务和结果。
- `schema_after_restore.sql` / `schema_restore_verification.json` 保存恢复后比对及健康结果。没有把生产备份、SQL 数据或原始运行日志加入 Git。

恢复验证：

| 检查 | 结果 |
| --- | --- |
| 表 | 17 张恢复成功，提交前逐表为 0 行；其他 64 张表名称、schema、OID 保留 |
| 序列 | 12 个序列的 `last_value` / `is_called` 与本次备份一致 |
| 关联对象 | 恢复 12 个默认值、23 个主键/唯一约束、28 个独立索引、19 个外键及 12 项序列归属 |
| 完整 schema | 前后均为 830 个 pg_dump 对象段，无缺失或新增；829 段逐字相同 |
| 等价文本变化 | `ck_syllabus_kp_mapping_type` 的数组到 text 转换被 PostgreSQL 解析器格式化；其他内容相同。7 个允许值、非法值、空字符串、NULL 共 10 种判定一致，约束保持 validated |
| Alembic | 保持 `v19_pomodoro_subject_allocations` |
| 公网 | `/health/live`、`/health`、首页均 HTTP 200 |
| 容器 | app / PostgreSQL / Redis healthy；Admin / worker / scheduler / nginx 保持运行 |

上述验证是本轮限定表恢复及入口存活检查，没有新增真实用户业务操作，也没有执行全库数据恢复、Redis 恢复、生产完整刷题或导入验收。

## 代码同步边界

本轮服务器代码检查仅为 rsync checksum dry-run，没有执行文件同步、镜像构建、容器替换或 nginx reload。发现两个后端运行文件 `admin_auth.py` / `admin_imports.py` 和两个 Admin 运行文件 `batch-image/page.tsx` / `action-labels.ts` 与服务器源文件不同；另有测试、离线脚本及未部署材料差异，不能整份 dry-run 清单直接上传。按用户最新指令先完成表恢复，代码同步仍待处理，不能继续沿用上一轮“没有新代码”的结论。

本地保留已确认的 `11332141` 和全部既有工作区变化；无业务源码改动或推送。最终 ENV 状态保持不变，生产后续操作仍以具体用户授权为边界。
