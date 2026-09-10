请基于我提供的 `data_structure_hierarchy_2026.csv`，把“数据结构”知识点层级导入现有数据库。

> 导入目标只涉及两张表：
>
> 1. `knowledge_edges`
> 2. `syllabus_knowledge_points`
>
> 不要直接覆盖或删除 `knowledge_points` 中的知识点数据。
>
> 具体要求如下：
>
> - 数据结构对应 `subject_id = 7`
> - 当前大纲版本对应 `syllabus_version_id = 1`
>
> 对 `knowledge_edges`：
>
> - 先备份相关数据
>
> - 删除：
>
>   ```sql
>   DELETE FROM knowledge_edges
>   WHERE subject_id = 7
>     AND relation_type = 'parent';
>   ```
>
> - 不要删除 `prerequisite`、`related` 等其他关系
>
> - 对 CSV 中 `parent_knowledge_point_id` 非空的记录重新创建父子边
>
> - 字段映射：
>
>   ```text
>   subject_id                  = 7
>   source_knowledge_point_id   = parent_knowledge_point_id
>   target_knowledge_point_id   = knowledge_point_id
>   relation_type               = 'parent'
>   source                      = 'manual'
>   confidence                  = 1.0
>   weight                      = 1.0
>   is_active                   = 1
>   ```
>
> - CSV 中根节点没有 parent，不要为根节点插入 parent edge
>
> 对 `syllabus_knowledge_points`：
>
> - 通过：
>
>   ```text
>   syllabus_version_id = 1
>   subject_id = 7
>   knowledge_point_id = CSV.knowledge_point_id
>   ```
>
>   匹配现有数据
>
> - 只更新：
>
>   ```text
>   sort_order = CSV.tree_sort_order
>   ```
>
> - 不要修改 snapshot、difficulty、description 等其他字段
>
> 关于 CSV 里的重复知识点治理字段：
>
> - `canonical_knowledge_point_id`
> - `canonical_name`
> - `merge_candidate_group`
> - `data_quality_note`
>
> 本次只作为参考，不要执行 merge/delete，也不要修改任何知识点 ID 或题目关联。
>
> 请使用事务执行整个导入流程，如果中途失败则 rollback。
>
> 导入完成后请做以下校验并输出结果：
>
> 1. `subject_id=7` 的 `parent` 边总数
> 2. 数据结构根节点数量
> 3. 是否存在一个知识点拥有多个 `parent` 父级
> 4. 是否存在 parent edge 指向不存在的 knowledge_point
> 5. `线性表 -> 顺序表`
> 6. `线性表 -> 链表`
> 7. `链表 -> 单链表`
> 8. `链表 -> 双链表`
> 9. `链表 -> 循环链表`
> 10. `B树 -> B+树`
> 11. `syllabus_knowledge_points.sort_order` 是否已按 CSV 更新
>
> 另外请在真正写入数据库之前，先读取当前数据库 schema，确认 `knowledge_edges` 和 `syllabus_knowledge_points` 的实际字段名、唯一约束和外键约束。如果字段名与上述描述不完全一致，请按实际 schema 适配，不要盲目执行 SQL。
>
> 最后请给我：
>
> - 实际执行的迁移脚本
> - 导入日志
> - 校验结果
> - 如有异常，列出未导入或冲突的数据，不要自动删除现有业务数据。



> **先 dry-run，确认将新增/删除/更新多少条数据后，再正式执行。**

