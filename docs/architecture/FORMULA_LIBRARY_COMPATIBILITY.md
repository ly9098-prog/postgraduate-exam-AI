# 小程序公式库接口兼容边界

2026-10-29 按用户确认的“小程序接口 > 后台管理系统接口 > OCR 接口”优先级，
以完整公式库消费链路为一个批次治理；不改管理端公式治理或 OCR 实现。

## 范围与职责

`backend/app/api/v1/formulas.py` 保留原路由顺序、路径、方法、参数默认值、Query
别名/范围、鉴权依赖、类型注解和描述；19 个原入口委托到五个职责模块。
`get_formula_card_types` 已是薄入口，保留现状。

- `formula_library_catalog`：目录树、计数聚合、学科折叠与标签读取。
- `formula_library_filters`：考试范围、题卡类型、图像库、章节及组合筛选。
- `formula_library_listing`：普通/收藏列表输入与唯一批量分页装配。
- `formula_library_projection`：卡片、图像资源、标签及多图规格的响应投影。
- `formula_library_access`：详情、随机读取与用户收藏的幂等写入。

服务模块不在导入时加载路由、FastAPI、模型、SQLAlchemy 或配置/数据库运行时。
协议异常构造器、模型、查询构造器和既有辅助入口通过路由侧的动态端口注入；
依赖在原使用位置读取，保留 await 后 helper 被替换时的行为。新增模块没有请求
级共享状态、第二套鉴权或事务工厂。

## 外部接口

| 路径（前缀 `/api/v1/formulas`） | 方法 | 原有边界 |
| --- | --- | --- |
| `/catalog` | GET | 当前用户依赖；支持范围、库类型、题卡类型及收藏过滤 |
| `/card-types` | GET | 原公开题卡分类入口 |
| `/tags` | GET | 原公开标签读取入口 |
| 空路径 | GET | 当前用户依赖；page_size 为 1–100 |
| `/{formula_id}` | GET | 原公开已发布卡片详情；未找到为 404 |
| `/favorites/list` | GET | 当前用户依赖；page_size 为 1–200 |
| `/random/next` | GET | 当前用户依赖；排除池耗尽时清除排除条件重试一次 |
| `/{formula_id}/favorite` | PUT / DELETE | 当前用户依赖；幂等添加/移除收藏 |

重构前后的实际 FastAPI OpenAPI 对象相等，包含描述与鉴权声明。此证据来自本地
构建 schema，不代表真实微信登录、网关或生产 API 验收。

## 查询、投影与事务

- 考试范围继续 trim/lower，旧别名不自动映射为其他数据集；逻辑 math/408 科目
  范围仍由既有 `formula_subject_scope` 实现，不在本批重写。发布状态、软删除、
  当前用户收藏及组合过滤条件保持。章节校验仍只在普通列表调用；收藏与随机入口
  不新增校验。错误优先级、HTTP 状态和原 detail 文本保持。
- 目录按原顺序加载分类、建立树、查询每分类计数、递归汇总、剪除一级空章节，
  再执行逻辑科目折叠。重复分类 ID、孤儿节点和 sort_order 同值的顺序保持。
- 普通/收藏分页共用同一执行函数：先 count，再按 sort_order/id 排序分页，再按
  assets → tags → specs 顺序批量读取，最后逐卡片选资源并投影。保留 map、数组
  及卡片字段的浅引用；不顺手改变空 batch map 未命中时的逐卡片 fallback 查询。
- 卡片投影仍先处理标签，再处理资源及 image/thumbnail/original SVG URL，最后
  读取规格并形成原字段序。显式空标签/规格列表不触发补查；资源 fallback 在调用
  内延迟导入。`is_function_graph` 仍接收原传入 graph_asset，即使之后查到 fallback
  资源也不替换该实参。URL 归一化失败前已发生的对象修改仍保留，异常原样传播。
- 随机排除 ID 保持全串解析：任一值无法转 int 时整组排除不生效。count 为零且
  exclude_ids truthy 时调用当前随机入口重试一次，将 exclude_ids 置 None、空 tags
  置 None，保留 db/用户引用。正常选择仍按 id 排序并使用原 random.randint 偏移；
  无候选或随机查询无记录时保留原 404。
- 添加收藏仍先检查已发布且未软删除卡片，再检查用户收藏；只在新增时 add/commit。
  移除只在存在记录时 delete/commit。保留 caller session 与原提交时点，不新增
  flush/refresh/rollback；查询或提交的普通异常、取消继续原样传播。

## 验证与限制

命令、结果数量、OpenAPI hash、模块预算及源码 hash 集中于
`refactor-results/miniprogram-formula-interface-2026-10-29.json`。证据包括迁移前后
接口测试、直接入口契约、逆展开 AST、种子 SQL/响应/事务轨迹差分、实际 OpenAPI
对照、导入隔离/职责预算/能力门禁以及固定 CI 清单本地重放。

未执行真实微信编译/设备访问、生产鉴权与数据库、外部图像网络请求或管理端页面
交互；本批不代表全部小程序接口、全栈重构或 OCR 验收完成。

---

## 相关链接

- [[docs/architecture/SYSTEM_ARCHITECTURE.md|SYSTEM_ARCHITECTURE]] — 系统架构
- [[docs/architecture/PRODUCTION_ARCH.md|PRODUCTION_ARCH]] — 生产架构
- [[docs/architecture/API_ROUTER_STRUCTURE.md|API_ROUTER_STRUCTURE]] — 路由结构
- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
- [[docs/frontend/FORMULA_READER_UI.md|FORMULA_READER_UI]] — 公式阅读 UI
