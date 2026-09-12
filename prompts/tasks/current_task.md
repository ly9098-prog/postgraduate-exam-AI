你正在本地代码仓库中（\artifacts\db_data_fix）执行408知识图谱破坏式重构后的收尾迁移任务。

目标：
1. 修正 questions.subject_id 和 question_versions.subject_id，使其与新的 knowledge_points 体系一致。
2. 清理 practice_sessions 中依赖旧知识点体系的 scope 数据。

执行要求：

一、修改前备份
- 必须先备份数据库。
- 备份失败禁止继续。
- 保存时间戳。

二、question subject 修正
数据来源：
\artifacts\db_data_fix或本次提供的 subject repair CSV。

原则：
- 新知识图谱中的 knowledge_subject_id 是权威来源。
- 不根据旧 questions.subject_id 判断。
- questions.subject_id 和对应 active/current question_versions.subject_id 必须同步。

执行前：
- 输出受影响数量。
- 检查是否存在一个 question_id 对应多个新 subject_id。
- 如果存在冲突，停止并报告。

执行：
- 更新 questions.subject_id。
- 更新 question_versions.subject_id。

三、practice_sessions处理

practice_sessions中以下字段依赖旧知识点体系：
- scope_root_knowledge_point_id
- scope_snapshot

由于knowledge_point_id已经全量重建：
不要尝试旧ID映射。

处理策略：
- 保留答题记录、时间、统计数据。
- 清空旧scope字段：
  scope_root_knowledge_point_id=NULL
  scope_snapshot=NULL
- 如果业务允许，也可以标记scope_version废弃。

不要删除practice_sessions主体。

四、事务

尽量使用transaction。

失败：
ROLLBACK。

成功：
COMMIT。

五、验证

验证：
1. questions.subject_id与最新question_version知识点科目一致。
2. question_versions.subject_id一致。
3. practice_sessions没有残留旧scope_root_knowledge_point_id。
4. 没有影响答题历史。

六、输出报告：
- backup路径
- 修改行数
- 清理scope数量
- SQL/migration文件
- 验证结果
