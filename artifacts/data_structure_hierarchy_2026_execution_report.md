# 数据结构层级导入执行报告

执行时间：2026-09-10（生产服务器 `101.33.231.186`）

数据库：PostgreSQL `postgraduate`，容器 `deploy-postgres-1`
CSV：`artifacts/data_structure_hierarchy_2026.csv`

## 备份

- `/backups/data_structure_hierarchy_20260910_092316.sql`
- SHA-256：`71936f3f1a87bdeca8939285a092a6021b4c5697445e7a9276296dad3b2c2a3d`
- 内容：`knowledge_edges`、`syllabus_knowledge_points` 数据备份

## Dry-run

| 指标 | 数量 |
| --- | ---: |
| CSV 行数 | 184 |
| CSV 父边 | 174 |
| 现有 subject=7 parent 边 | 101 |
| 现有 subject=7 非 parent 边 | 236 |
| 现有 syllabus 成员 | 172 |
| 缺失知识点/父知识点 | 0 / 0 |
| 缺失 syllabus 成员 | 12 |
| sort_order 不一致 | 169 |
| 已存在的目标父边 | 83 |

## 实际写入

- 在单一事务中锁定两张目标表。
- 删除 subject 7 的 101 条 `parent` 边。
- 按 CSV 插入 174 条 `parent` 边（`source=manual`、`confidence=1.0`、`weight=1.0`、`is_active=true`）。
- 仅更新匹配成员的 `syllabus_knowledge_points.sort_order`，更新 169 条。
- 未新增 syllabus 成员，未修改 `knowledge_points` 或其他关系类型。

## 校验

| 检查项 | 结果 |
| --- | ---: |
| subject=7 parent 边总数 | 174 |
| 数据结构根节点数 | 10 |
| 多 parent 节点数 | 0 |
| 悬空 parent 边 | 0 |
| `线性表 -> 顺序表` | 1 |
| `线性表 -> 链表` | 1 |
| `链表 -> 单链表` | 1 |
| `链表 -> 双链表` | 1 |
| `链表 -> 循环链表` | 1 |
| `B树 -> B+树` | 1 |
| sort_order 不一致（已匹配成员） | 0 |
| CSV 父边集合与数据库差异 | 0 / 0 |

未匹配的 12 个 syllabus 成员均为此前重复治理停用的 duplicate ID：
`90, 164, 120, 150, 151, 179, 148, 161, 153, 154, 272, 149`。
按任务要求未自动新增或删除任何成员。

执行脚本：`artifacts/data_structure_hierarchy_2026_execute.sql`

Dry-run 脚本：`artifacts/data_structure_hierarchy_2026_dry_run.sql`
