# 小程序导出请求生命周期兼容边界

2026-10-30 按“小程序接口 > 后台管理系统接口 > OCR 接口”优先级，以完整导出
请求生命周期为一个批次收敛。实际消费者包括小程序 export 子包的 API service、
文件 URL 和状态同步管理器，以及 study 子包的导出能力检查。

## 职责

`backend/app/api/v1/exports.py` 保留路由、默认值、Query/Depends、鉴权、响应模型、
类型注解和原描述；原健康/能力入口与本地处理器唤醒薄实现保留，其他历史入口
委托到 `backend/app/services/export/` 下七个职责模块：

- `api_queries`：预览、列表、详情、用户归属/行锁、配置和幂等查询/键。
- `api_creation`：创建校验、用户容量锁及唯一键冲突恢复与提交。
- `api_downloads`：下载元信息、签名 URL/显式本地 fallback、文件响应及路径保护。
- `api_deletion`：快照引用检查、文件移除及数据库记录删除顺序。
- `api_regeneration`：失败任务重试、原记录重导出和旧文件保留条件。
- `api_projection`：等待原因、超时提示和任务响应字段投影。
- `api_websocket`：关联上下文、鉴权及状态推送服务交接。

模块导入不加载路由、FastAPI、数据库、模型或运行时配置；保留原函数内惰性
导入和使用时读取的路由端口。异常构造器、模型、时钟、存储和辅助入口仍在原
使用位置解析，await 后替换 helper 的语义保持。没有新增事务容器或共享状态。
底层生成器、快照实现、processor/push service、worker 和调度协议不在本批改写。

## 外部接口

下表前缀为 `/api/v1/exports`；除公开健康探针外，HTTP 消费者保持用户鉴权，
WebSocket 保持独立 token 校验。

| 路径 | 方法 | 保留边界 |
| --- | --- | --- |
| `/health` | GET | 公开最小健康探针 |
| `/capabilities` | GET | 全局格式和运行限制，原 DOCX 开关 |
| `/preview-count` | POST | 原范围/筛选/选择 ID，只有 ValueError 映射 400 |
| 空路径 | POST | 创建、幂等、用户容量限制和异步生成交接 |
| 空路径 | GET | 用户隔离，page≥1、page_size≤50 |
| `/{task_id}` | GET | 用户归属、原任务投影 |
| `/{task_id}/download` | GET | 本地 stream 或 COS 短期签名地址 |
| `/{task_id}/file` | GET | 鉴权文件流、inline header 与禁止缓存 |
| `/{task_id}` | DELETE | 原快照/文件/记录失败边界 |
| `/{task_id}/retry` | POST | 只允许失败任务，创建新任务并保留来源 |
| `/{task_id}/re-export` | POST | 原记录和可用旧文件复用 |
| `/ws` | WebSocket | 子协议 token、受控旧 query token、finally 清理上下文 |

重构前后实际 FastAPI OpenAPI 对象相等；OpenAPI 不表达 WebSocket 协议，后者由
直接入口契约及原语句逆展开分别验证。此结果不等于生产网关或真实登录验收。

## 事务、状态与文件

- 创建先进行 DOCX 校验、范围预览/校验、幂等查询，再对当前用户未完成任务
  查询加行锁并检查容量。已有幂等任务返回前仍唤醒本进程处理器，不新增提交。
  SQLite 忽略 FOR UPDATE 的原竞争限制保持，没有借重构更换并发机制。
- 唯一键冲突仍 rollback 后以提前捕获的 user ID 查找，避免访问失效 ORM 用户。
  两级恢复都找不到时保留原 409；恢复成功路径不新增唤醒/commit。正常创建仍是
  commit→refresh→wake→log→当前投影。异常及取消的传播保持。
- 列表仍先取所有匹配 ID 计数，再按 created_at desc 分页；不顺手改为 COUNT、
  增加排序键或改变每条记录投影时读取当前 helper 的行为。
- 删除先锁定当前用户任务，拒绝 pending/processing。快照无其他状态非 expired 的引用时
  先暂存快照删除，再删除外部文件，最后删除记录并 commit。快照普通错误、
  文件普通错误或 false 仍 rollback 并返回原结构化 503；取消继续直接传播。
  文件已移除后的数据库提交失败没有补偿逻辑，本批保留该既有边界。
- 重试保留两次配置读取：预览前读取，容量检查 await 后再读取。新任务保留
  source_task_id、retry_count 和预览数量；不改变事务所有者。
- 原记录重导出先检查格式/状态/容量，尝试复用属于当前用户的快照；缺失才重新
  预览/校验，校验成功后清 snapshot_id。仅当旧文件存在、曾完成且未过期时
  保留旧 file_key/size/completed_at/expires_at，随后重置处理字段、版本和幂等键，
  保留记录 ID，使用原 generator_version 配置。
- 下载允许 completed/pending/processing/failed 且有文件的记录；文件不存在、
  状态不允许、过期的原错误文本和优先级保持。COS 签名仍为 3600 秒，只有显式
  开启 fallback 才尝试本地流。文件流保持 inline 编码和 private/no-store header。
  路径仍从统一 export storage root 解析 realpath 并检查目录前缀，防止路径穿越。
- 时间相等时的既有差异保持：下载仅在 expires_at<now 时拒绝，响应投影将
  completed 且 expires_at≤now 显示为 expired；旧文件复用要求 expires_at>now。
  不借重构统一这些业务规则。
- pending 投影仍先取处理器健康和等待时长，再读取路由时钟判定文件/状态；
  处理器健康普通异常吞掉，等待时长读取错误不新增 catch。字段顺序、UTC 序列化、
  旧文件可用、重导出/失败标记保持。

## WebSocket 和验证限制

先绑定 trace/request 上下文，再检查开关与 token。`bearer` 子协议优先；
query token 仅在本地环境或显式旧兼容开关时使用。用户会话退出后才读取 user.id，
鉴权普通失败保持 4001；取消传播。用户上下文绑定、日志及推送仍在同一
try/finally 中，始终按原 tokens 列表清理；绑定自身失败的原边界保持。

命令、测试数量、逆展开、差分、OpenAPI hash、预算和源码 hash 集中记录于
`refactor-results/miniprogram-export-interface-2026-10-30.json`。直接契约使用
假 session/storage，未删除真实文件；旧源码字符串断言改为行为验证。

未执行真实微信编译/设备/登录、生产鉴权/数据库、真实 COS/本地文件生命周期、
真实多进程并发或 WebSocket 网关连接；本批不代表整个导出生成器、全部小程序
接口或全栈重构已经验收。
