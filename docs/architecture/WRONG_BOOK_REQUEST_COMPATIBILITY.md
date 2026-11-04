# 小程序错题 Public API 请求兼容边界

2026-10-30 按“小程序接口 > 后台管理系统接口 > OCR 接口”优先级，以错题本、
错题详情及诊断消费的请求链路为一个批次。实际调用方包括 wrong-book 的列表/
统计/任务流/批量操作、wrong-detail 的加载/诊断/掌握与移出、dashboard 和考试/
刷题结果页的诊断入口。原小程序页面及底层业务 service 保持原实现。

## 职责与接口

`backend/app/api/v1/wrong_questions.py` 保留全部路径、方法、鉴权、Query 默认值/
范围/描述、类型注解、response_model 和原 docstring；统计、诊断分类和诊断统计
三个已薄入口保留。20 个原请求/helper 委托至六个职责模块：

- `wrong_book_sanitization`：代码识别、OCR 断行修复、正文与选项的不同清洗规则。
- `wrong_book_projection`：AI 内容/status/原生成标记、关联题目及扩展响应字段。
- `wrong_book_queries`：产品科目范围、当前题目、详情 join、复习聚合及日期校验。
- `wrong_book_reading`：列表/任务流逐项清洗、详情诊断及 AI 缓存状态装配。
- `wrong_book_mutations`：更新/批量请求与缓存失效。
- `wrong_book_diagnosis`：诊断读取/兼容旧记录、确认及 AI 建议请求。

新模块导入不加载路由、FastAPI、ORM、配置或数据库资源；既有函数内惰性导入
继续在原使用位置执行。路由依赖、内建函数、schema、查询构造器和
缓存等通过使用时读取的原端口解析；await 后的当前辅助函数/对象读取保持。
不新增底层业务 service、数据库结构、事务容器、依赖或跨请求状态。响应投影的
注入端口使用位置专用参数，保持原 `**extra` 可接受名为 ports 的扩展字段。

全部路径前缀为 `/api/v1/wrong-questions`，保持原用户鉴权：

| 路径 | 方法 | 保留协议 |
| --- | --- | --- |
| 空路径 | GET | 科目/错因/主题/产品/自然日筛选，page≥1、page_size≤100 |
| `/stats` | GET | 原产品科目范围及统计响应 |
| `/task-flow` | GET | 原筛选与任务流结构，preview_size 为 1–10 |
| `/diagnosis/taxonomy` | GET | 原诊断分类 |
| `/diagnosis/stats` | GET | window_days 为 7–365，原科目/知识点筛选 |
| `/{wq_id}` | GET / PUT | 详情、AI缓存投影及原错因更新 |
| `/{wq_id}/diagnosis` | GET / PUT | 诊断读取与确认 |
| `/{wq_id}/diagnosis/suggest` | POST | 原建议队列交接和 queued/diagnosis 响应 |
| `/batch` | POST | 原 action、1–100 ID 上限及去重，原成功/跳过响应 |

重构前后实际 FastAPI OpenAPI 对象相等，包含路由顺序之外的完整 schema 对照；
原声明/路由顺序由结构检查验证。真实微信登录、网关、数据库隔离仍需独立验收。

## 展示、查询与 AI

- 普通正文先统一 CR/LF；代码识别沿用原 signals/数据结构词/控制关键字权重，
  score≥3 时只合并运算符断行，保留缩进和重复代码。普通文本继续先去重、再
  roman 子项拆分、最后合并运算符断行。正则读取包含生成式里的使用位置。
- content 字符串先包为 text，对象浅拷贝后按 text→stem 清洗，再 reconcile，
  移除 source_snapshot/visual 管理字段，最后剥离学生不可见段元数据。嵌套引用
  与原输入不变性保持。非 dict/string content 返回 None。
- 选项浅拷贝；rich 值保持原 text 为空时回退 value 的条件，只更新副本 text。
  选项不做正文去重或 roman 拆分；断行合并后将连续换行替为空格并 trim。
- 产品 scope 继续 str/strip/lower，空值不过滤，只有 exam408 合法；非法值先
  返回原 400。日期先于 scope/数据库查询校验，保留“开始日期不能晚于结束日期”
  的 422 和既有北京时间自然日 service 过滤。
- 展示读取当前 Question.id，不将历史 question_version_id 换成最新版本。历史
  version 继续用于 ReviewRecord/ReviewSchedule 的用户隔离聚合；详情仍是
  WrongQuestion/Question outer join 加独立批量知识点查询。缺失错题为404，
  已硬删除题目的错题仍可展示，knowledge_points=None；存活题无知识点为[]。
- 复习富化仍只有一个聚合 round trip，review_record_count 子查询按题目/版本/
  用户，schedule 同时限定 active；原 count/repetitions 的默认0、掌握优先、
  mastery百分比与4位round规则保持。调度器 helper 仍在查询成功之后惰性导入。
- 详情顺序为当前题目/知识点→复习富化→最新诊断→仅对存在题目评估AI缓存→
  当前响应 helper。analysis/status override 继续按 key 存在与 None 判断，
  generated_at 仍来自原 wq.ai_analysis._meta，而不是被替换的分析。保留字段
  构造顺序、默认值和 Pydantic 序列化。AI评估失败/取消不新增兜底或提交。
- 列表和任务流仍在 service 返回的原 item 对象上按 content→options 修改；
  不统一响应 envelope、不深拷贝、不增加缺失 group/items 的其他保护。

## 事务、缓存与错误

- 更新 service 成功后依次删除 wrong_questions、stats 缓存，再读当前题目和
  复习富化并投影；缺失记录时不清缓存。更新响应仍不额外执行详情AI评估。
- 批量操作的归属/动作/去重及实际数据库写入由原 service 执行；success falsy
  时原400，成功后按 wrong_questions→stats→review→dashboard 清缓存并返回原
  result 对象。缓存失败仍传播，保留前面已执行的service副作用与部分缓存失效。
- 诊断读取先校验错题归属，有现成诊断不提交；只有缺失诊断的 legacy 创建路径
  持有原 commit→refresh。确认/建议不增加提交，继续由原service负责原事务。
  确认成功后按原三个pattern清缓存，再读取当前serializer；缺失记录为原404。
- 所有普通错误、HTTP 状态、错误文案和 CancelledError 传播保持；没有顺手
  修复既有并发、部分清洗/缓存或AI可用性问题。

## 验证与限制

命令、测试数量、逆展开、种子差分、OpenAPI hash、模块预算和源码hash集中在
`refactor-results/miniprogram-wrong-interface-2026-10-30.json`。证据包括原实现/
当前直接契约、已有API/SQLite临时夹具、逐语句逆展开、SQL/响应/状态/缓存轨迹
比较、原路由声明门禁、模块预算及无运行时副作用导入检查。

测试使用假session/服务或既有隔离SQLite夹具，不访问开发或生产用户数据。
未执行真实微信编译/设备/登录、真实AI模型、生产PostgreSQL/Redis或完整学习
闭环验收；本批不代表全部小程序接口或全栈目标已完成。

---

## 相关链接

- [[docs/architecture/SYSTEM_ARCHITECTURE.md|SYSTEM_ARCHITECTURE]] — 系统架构
- [[docs/architecture/PRODUCTION_ARCH.md|PRODUCTION_ARCH]] — 生产架构
- [[docs/architecture/API_ROUTER_STRUCTURE.md|API_ROUTER_STRUCTURE]] — 路由结构
- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
