# 错题详情状态与专项老师端口兼容边界

核对日期：2026-10-29。本批覆盖状态规则、题目视图投影及既有专项老师 controller 的端口装配；错题详情完整编排和真实客户端验收仍未完成。

## 1. 职责边界

- `miniprogram/subpackages/study/wrong-detail/wrong-detail.js` 从 1653→1533 行。页面保留原私有 helper 名称与调用入口；生命周期、导航、AI 生成/恢复/重新生成、错因编排仍在页面。
- `utils/wrong-detail-ai-state.js`（88 行）承接八个原 helper：轮询间隔、超时识别、生成标记、失败文案、掌握状态、AI 结果显示、已有分析判断和优先分析选择。
- `utils/wrong-detail-question-view.js`（28 行）承接题目装饰。渲染工具、配置和平台相关依赖仍从页面按原引用注入，保留实时配置读取。
- `utils/wrong-detail-teacher-page-adapter.js`（37 行）承接既有 controller 的 22 个端口；API、专项老师工具、结果展示和超时值由页面注入。controller 实现未改；页面继续惰性创建和缓存实例，端口按调用时读取页面状态及全局 `wx`。

## 2. 保留语义

- AI 分析状态为空或 ready 且有内容时优先使用 AI；否则使用题库解析。字符串空值/布尔/数字/空容器判断、对象与数组规则、默认文案和轮询阈值保持。
- 原八个状态 helper 和题目投影方法体保持；其余 118 个页面属性未改。专项老师端口对象仅将接收者 `this.` 改为 `page.`，键集合与顺序保持。
- 缓存键、反馈恢复、请求序号、inflight promise 身份、迟响应与卸载拒绝逻辑保持；未新增共享状态、网络入口或存储键，WXML/WXSS/资源不变。
- `scripts/architecture/wrong-detail-boundaries.js` 固化页面 1533 行、四个受治理 utils 的 300/50 预算、迁移方法归属、页面委托模板和 22 个端口，禁止规则/适配模块增加导入或动态执行。

## 3. 验证和已知限制

- 八项行为契约均在原页面重放通过；当前八项契约及七项边界测试共 15 passed。原新对照包含方法体/页面属性/端口审计与 9,000 次确定性比较。
- 全量 `node --test tests/*.js`：2156 passed；渲染回归：5 fixtures、31 passed；八条架构门禁、JavaScript 语法、CI YAML 解析与 diff check 通过。CI 增加详情页门禁及两条测试路径。
- `test-wrong-detail-ai-visual.js` 与 `test-wrong-detail-ai-math.js` 通过。视觉脚本的优先分析规则断言改指规则模块并校验页面委托。
- `test-408-ai-teacher.js` 的错题详情 API/context 断言改指适配器/controller；脚本仍停在 practice-result 的既有 API 源断言，原页面重放有相同失败。`test-error-diagnosis.js` 未改，仍有 practice-result occurrence diagnosis_id 的既有失败，原页面重放同样失败。不能据此声称这些脚本全部通过。
- 独立只读 review 覆盖生产代码、契约、门禁及源断言归属；提交前关闭所有已发现问题。临时证据在 `/tmp/wrong-detail-state-batch/`。
- 未执行微信开发者工具编译、模拟器/真机、真实 AI 请求、弱网/取消或完整错题学习闭环验收；Node 契约不替代这些验收。

## 4. 切题动画、滑动与看门狗（2026-10-29 后续批次）

- 本批页面由 1533→1454 行；10 个滑动/切题动画/看门狗方法迁入 `utils/wrong-detail-content-transition.js`（132 行），函数均 ≤50 行。页面保留方法名、参数和 async 标记，传入所属页面以及原页面的出场/入场/看门狗常量与 `_sleep`。不新增 controller 实例或共享状态。
- 迁移方法体仅替换接收者 `this`→`page`，其余 109 个页面属性不变。全局时钟/计时器、页面方法在执行时解析，定时回调继续访问当前页面方法与状态。
- 保留 56px 横滑阈值及横向距离须超过纵向 1.2 倍、索引边界、方向映射；出场等待默认/上限 150ms 并扣除已过时长，入场 170ms；默认看门狗 35000ms，实际导航提交的动画看门狗仍为 5000ms。
- 强制复位继续增加 navigation 序号并清理动画/遮罩/看门狗；卸载清理保持在原页面。原有无效导航、网络请求、缓存、诊断刷新及 `setData` 回调编排未改，不借此修复或调整既有边界行为。
- 拆分前 9 项契约通过，最终扩展 11 项全部在原页面重放通过；当前含状态/边界测试共 26 passed。另有 6,000 次确定性状态/计时器/视图 patch 对照一致。
- 全量 Node 2167 passed、渲染 5 fixtures/31 passed、八条架构门禁、语法、视觉/KaTeX、CI YAML 与 diff check 通过。详情门禁扩展为五个模块和 15 条委托模板，页面预算下调至 1454；CI 增加切题契约路径。
- 本批临时证据 `/tmp/wrong-detail-transition-batch/`；前述两条 legacy 脚本既有失败和真实环境验收限制仍然有效。

## 5. 错题切换与导航列表（2026-10-29 后续批次）

- 本批页面由 1454→1355 行。六个导航数据准备/视图构造/切换提交/列表移除/错误处理入口迁入 `utils/wrong-detail-navigation-data.js`（51 行）与 `utils/wrong-detail-navigation-flow.js`（76 行）；页面保留名称、参数、异步声明和单次委托。
- 保持 live API 读取及 await 后的页面 renderer/helper 查找、请求序号/存活检查先于缓存写入、缓存对象与时间戳、AI 优先/题目解析 fallback、字段顺序与重复诊断归一化调用。
- 切换提交仍先等待出场动画，然后做序号与卸载检查，再更新页面私有 ID/AI 结果，依次清遮罩 timer、启动 5000ms watchdog、setData、检查渲染不变式；setData 回调中动画收尾先于服务端诊断刷新。
- 保留无效索引时的原锁状态、404/410 通过旧 sentinel `drop(0)` 更新列表、存储异常吞掉与现有 toast。此轮不改变这些业务口径。
- 拆分前 11 项导航契约通过；扩展后 13 项原页面重放通过。当前状态、模块边界、动画与导航定向共 39 passed；另有 800 次确定性 response/state/field-order 对照一致。
- CI 增加导航契约；详情页门禁登记七个模块、21 条页面委托模板、1355 行 ceiling。全量 Node、渲染与八条门禁于提交前复验。原始证据 `/tmp/wrong-detail-navigation-batch/`。

## 6. AI 持久化轮询与恢复应用（2026-10-29 后续批次）

- 本批页面由 1355→1302 行。请求身份判断、持久化状态轮询、恢复结果应用三个方法迁入 `utils/wrong-detail-ai-recovery.js`（64 行，函数均 ≤50 行）；原页面方法名、参数及 async 标记保持，单次委托传入所属页面和既有依赖。生成、重新生成及后台恢复任务的其他编排仍待治理。
- 轮询保持 44 次请求与 43 次等待；前五次等待为 2000ms、第六至十五次为 3000ms，其后为 5000ms。请求前、等待后和响应后的身份/存活/当前题守卫保持；falsey 基准标记归一化、新一代标记过滤和空结果跳过保持。
- status 请求仍在每轮执行时读取当前 `api.get`，保留 API receiver、路径及超时/静默选项；归一化和内容判断仍在 await 后调用页面闭包 helper。status/归一化异常继续由原 catch 吞掉，等待仍在 catch 外，定时器仍在调用时读取。
- 恢复应用保持 reset → 私有结果与生成标记 → 缓存写入 → 卡片构造/setData 顺序；保留最新题目对象引用、marker 回退、缺失恢复结果返回 false、重新生成来源标志、字段和值。其余 116 个 Page 属性原文不变。
- 12 项恢复契约在原页面与当前页面全部通过，覆盖等待期间取消、响应后取消、重试时 API 替换、异常状态、耗尽、写回顺序及来源标志；状态/动画/导航/恢复/模块门禁合计 51 项通过。800 组确定性轮询与恢复结果、状态和调用轨迹对照一致。
- 全量 Node 2192 passed、渲染 5 fixtures/31 passed、八条架构门禁及视觉/KaTeX检查通过。CI 增加恢复契约；详情门禁登记八个模块、24 条委托模板，页面 ceiling 为 1302。独立只读审查无 P0–P3 可操作发现；证据 `/tmp/wrong-detail-ai-recovery-batch/`。
- 前述两条 legacy 源断言既有失败仍单独记录；真实微信工具/模拟器/真机、外部 AI、弱网与完整错题学习闭环未验收，本批 Node 契约不替代这些验证。

## 7. 普通 AI 生成编排（2026-10-29 后续批次）

- 本批页面由 1302→1245 行。普通生成入口、结果分流、成功写回与错误恢复四个方法迁入 `utils/wrong-detail-ai-generation.js`（75 行，函数均 ≤50 行）；页面保留原参数、async 标记和单次委托。生成请求协议、重新生成及后台恢复任务的其余编排仍在页面。
- 四个方法体仅把接收者 `this` 改为 `page`；其余 115 个 Page 属性原文保持。生成前的 guard、baseline 捕获、请求序号递增、loading patch 与请求顺序保持；响应后才读取当前页面结果处理方法，迟响应仍复位 loading。
- 结果继续按 generating → fallback → 空内容 → success 分流；generating 优先轮询恢复，耗尽后仅为当前请求写错误。fallback helper 的 receiver 和 patch 覆盖顺序、成功时 reset/私有字段/缓存/卡片/setData 顺序及 falsey marker 回退保持。
- 错误处理继续先记录日志，再为当前请求写 notice、不等待地 enqueue、await 轮询；恢复应用优先于最终身份检查与错误展示。请求或结果应用异常仍 await 当前错误处理方法；错误处理自身的失败继续传播。页面方法及全局 console 保留运行时读取。
- 12 项新契约在原页面与当前页面全部通过；状态/动画/导航/恢复/生成/模块门禁合计 63 项通过。800 组四入口的生成、分流、成功与错误状态/调用轨迹/字段顺序对照一致；独立只读审查无 P0–P3 可操作发现。
- 全量 Node 2204 passed、渲染 5 fixtures/31 passed、八条架构门禁及视觉/KaTeX检查通过。CI 增加生成契约；详情门禁登记九个模块、28 条委托模板，页面 ceiling 为 1245。证据 `/tmp/wrong-detail-ai-generation-batch/`；前述既有失败及真实环境验收限制继续有效。

## 8. AI 重新生成编排（2026-10-29 后续批次）

- 本批页面由 1245→1143 行。重新生成入口、结果分流、生成中恢复、缓存保留、fallback、空内容、成功、错误分派、错误恢复和超时处理十个方法迁入 `utils/wrong-detail-ai-regeneration.js`（144 行，函数均 ≤50 行）。页面保留原方法名、参数和 async 标记，以单次委托传入页面与既有 helper/toast 端口。
- 十个方法体只替换接收者 `this`→`page` 及 toast 端口调用；其余 109 个 Page 属性原文不变。旧题目 ID、oldCards/oldResult/baseline 捕获、序号递增与 loading patch 顺序保持，await 后仍读取当前页面方法。
- 结果继续按 generating → 有内容的 cache-preserved → fallback → 空内容 → success 分流。历史卡片/结果的保留条件、falsey marker 回退、regeneration 来源标志、缓存写回及 reset/视图/toast 顺序保持；toast 在实际执行时读取当前全局 `wx` 并保留 receiver。
- 请求或结果应用异常继续调用但不 await 错误分派；错误分派也不返回恢复 Promise。后台 enqueue 仍不等待，随后 await 轮询、应用恢复结果，最后再判断当前请求是否可写入超时状态；不把这些现有等待差异改成普通生成的行为。
- 15 项契约在原页面与当前页面全部通过；状态/动画/导航/恢复/生成/重新生成/模块门禁合计 78 项通过。1200 组十入口状态、调用轨迹及字段顺序对照一致；独立只读审查无 P0–P3 可操作发现。
- 全量 Node 2219 passed、渲染 5 fixtures/31 passed、八条架构门禁及视觉/KaTeX检查通过。CI 增加重新生成契约；详情门禁登记十个模块、38 条委托模板，页面 ceiling 为 1143。证据 `/tmp/wrong-detail-ai-regeneration-batch/`；AI 请求协议/后台恢复任务入队、缓存写回及错因剩余编排仍待治理，既有失败及真实环境限制继续有效。

## 9. AI 请求与缓存支持（2026-10-29 后续批次）

- 本批页面由 1143→1101 行。loading 复位、缓存写回、生成请求、后台恢复入队、失败状态及点击入口六个方法迁入 `utils/wrong-detail-ai-request.js`（68 行，函数均 ≤50 行）；页面保留原方法名、参数、async 和单次委托。无页面状态依赖的三个函数不接收页面，其余三个接收显式 page。
- 六个方法体仅改变接收者及网络/toast 端口调用；其余 113 个 Page 属性原文不变。网络端口每次调用都读取当前 `api.post` 并保留 receiver；生成请求继续使用 55000ms 超时，恢复入队为 10000ms，均静默网络 toast。force 布尔化、仅强制入队时添加 baseline、字段顺序和返回值保持。
- 普通请求同步错误/异步拒绝继续传播；enqueue 的 baseline 转换、请求与响应属性异常仍进入原 catch，记录当前 console.warn 并返回 false。reset 仅写原四个 loading 字段；点击入口保留忙碌守卫、私有 ID 优先、当前 loader 调用、不返回 Promise 和缺失 ID toast。
- 缓存写回仅替换 entry.data，保留 cache/entry 身份、timestamp、旧 status 与无关字段；normalized 引用保持。generatedAt 为 undefined 时不写 marker，其他 falsey 值写空字符串；不增加 ready 状态或改变失效规则。
- 13 项契约在原页面与当前页面全部通过；八组定向共 91 项通过。900 组六入口返回值、状态、调用轨迹及字段顺序对照一致；独立只读审查无 P0–P3 可操作发现。夹具额外暴露真实 Page definition，确保 reset/cache 契约执行真实方法而非既有 mock。
- 全量 Node 2232 passed、渲染 5 fixtures/31 passed、八条架构门禁及视觉/KaTeX检查通过。CI 增加请求支持契约；详情门禁登记十一个模块、44 条委托模板，页面 ceiling 为 1101。证据 `/tmp/wrong-detail-ai-request-batch/`；错因、详情加载、掌握/撤销及其他剩余页面职责和真实环境验收仍待继续。

## 10. 错因选择、保存与持久化刷新（2026-10-29 后续批次）

- 本批页面由 1101→963 行。诊断弹层打开/关闭、主次错因选择、保存、后续行动路由及服务端刷新七个方法迁入 `utils/wrong-detail-diagnosis-flow.js`（168 行，函数均 ≤50 行）；页面方法名、参数、async 和单次委托保持。七个方法体仅替换接收者及注入端口访问，其余 112 个 Page 属性原文不变。
- API 与 diagnosis 工具对象显式注入，保留方法 receiver、API 方法在 payload 前求值，以及 await 后当前 helper、occurrence ID、视图和时钟读取；平台 getter 每次读取当前全局 wx。错误 toast 方法仍在错误 formatter 之前取得，保存/cache/setData/toast 顺序不变。
- 次级错因仍最多三个，切换主因时复制并移除同名次因；路由过滤 null/undefined/空字符串而保留 0/false，按原键序编码。保存捕获原选择，在响应后读取当前 occurrence ID，写入本地确认事实并保留服务端 ID；缓存 entry 替换与视图引用关系保持。
- 刷新先展示 embedded fallback，再请求 occurrence 级 diagnosis；序号/存活/题目守卫、confirmed fallback 对滞后聚合结果的保护、视图与缓存分别合并、finally 仅检查序号与存活的既有差异保持。失败不弹 toast，保留 fallback。
- 新增基线限制：save 响应若为 `data` 包装，本地 raw 顶层虽写入用户选择及 `user_confirmed=true`，后续 normalizer 仍优先读取保留的内层 `data`，normalized primary/confirmed 可能保留旧值；直接响应与 `diagnosis` 包装不出现该差异。该行为在原页面重放确认，本批刻画并保留，未作为兼容重构中的业务修复。
- 15 项契约在原页面与当前页面通过；九组定向共 106 项通过，1120 组七入口状态/调用轨迹/字段顺序对照一致；独立只读审查无 P0–P3 可操作发现。全量 Node 2247 passed，渲染 5 fixtures/31 passed，八条门禁与视觉/KaTeX通过。
- CI 增加诊断契约；详情门禁为十二个模块、51 条委托，页面 ceiling 为 963。legacy diagnosis 脚本的错题详情断言改指新归属并单独验证通过，完整脚本在原版/当前均复现 practice-result occurrence diagnosis_id 的既有失败；未修改该失败。证据 `/tmp/wrong-detail-diagnosis-batch/`；真实微信/AI与完整闭环等验收限制继续有效。
