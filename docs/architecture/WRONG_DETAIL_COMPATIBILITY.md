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

## 11. 详情加载、投影与预取（2026-10-29 后续批次）

- 本批页面由 963→867 行。加载入口、初始 patch、加载投影/字段、优先解析写回、渲染检查、加载错误和题目预取八个方法迁入 `utils/wrong-detail-load-flow.js`（130 行，函数均 ≤50 行）；纯初始 patch 无需 page，其余按原依赖注入。页面签名、async 与单次委托保持，八个方法体仅改变接收者及 API 对象名，其余 111 个 Page 属性原文不变。
- 加载保持 request 序号、reset/初始 patch/诊断和 teacher 序号、await 请求与迟响应守卫次序；先写原响应到缓存，再构造投影。投影为 null 时保留已写缓存；诊断刷新不等待，随后执行渲染检查；请求/投影/同步副作用异常仍交当前错误处理方法。
- 投影保持 raw/原题目引用关系、占位题循环、当前 ID/序号/label/生成标记等私有字段的写入及最终 guard 位置；不把最终检查前的副作用提前取消。字段顺序、重复两次 diagnosis.normalize、AI/题库解析来源、空内容/格式异常与卡片文案不变；renderer/优先解析/helper 按调用时读取。
- 渲染检查仍先执行 invariant，再读取当前 trace 方法和 trace 字段。预取沿用 300000ms 缓存边界，在请求开始记录时间，拒绝覆盖时间戳大于或等于开始时间的缓存；结果还须页面存活和缓存存在。预取不返回 Promise，Promise 拒绝吞掉，同步请求异常仍传播。
- 15 项加载契约在原页面与当前页面全部通过；十组定向共 121 项通过，1000 组八入口返回值/状态/调用轨迹/字段顺序对照一致。全量 Node 2262 passed，渲染 5 fixtures/31 passed，八条架构门禁及视觉/KaTeX通过。
- 独立实现只读审查无 P0–P3 可操作发现，独立运行 121 项定向与详情门禁通过。CI 增加加载契约；详情门禁为十三个模块、59 条委托，页面 ceiling 为 867。证据 `/tmp/wrong-detail-load-batch/`；生命周期、掌握/撤销、删除及其他剩余页面职责继续核查，前述 data envelope 限制、legacy 源断言失败和真实环境验收限制保持。


## 12. 生命周期、导航来源与底部操作栏（2026-10-29 后续批次）

- 本批页面由 867→771 行。加载入口/状态初始化/参数初始化/导航来源、show/hide/滚动/交互、底部操作栏 timer/调度/展示和卸载十二方法迁入 `utils/wrong-detail-lifecycle.js`（146 行，函数均 ≤50 行）。页面方法名、参数、async 和单次委托保持；无页面状态依赖的导航来源函数不接收 page。十二方法体仅改变接收者及 platform 访问，其余 107 个 Page 属性原文不变。
- 初始化保留 render guard 先于状态赋值、null 原型 teacher 缓存、每次初始化的新对象、data 与既有 controller 身份；参数初始化保留 ID 校验、列表身份/重复 ID 与 index fallback、非等待 load 后才展示操作栏。同步 load 异常继续阻止后续展示。
- 导航来源每次实际访问 storage 时读取当前 wx，保留 receiver、source 过滤与严格小于 30 分钟 TTL。仍只过滤非有限值，保留重复项/零/负数、未来时间戳与无 source 记录的既有规则；异常和当前 ID 缺失回退单题列表。
- 操作栏继续使用单一定时器与 3000ms 空闲阈值，交互更新时间、到期后重新计算剩余等待、当前时钟/timer 与页面存活守卫保持。卸载按序失效 AI/teacher/diagnosis 序号、清理切题和返回 timer、调用当前 bottom/undo hook、清缓存与 marker、reset render guard；hook 异常仍保留部分清理并传播。
- 14 项契约原页重放与当前均通过；十一组定向 135 项、全量 Node 2276 项、渲染 5 fixtures/31 项、八条架构门禁与视觉/KaTeX检查通过。1000 组生命周期/导航/timer/卸载状态及调用轨迹对照一致；独立实现只读审查无 P0–P3 可操作发现。
- CI 增加生命周期契约；详情门禁为十四模块、71 条委托，页面 ceiling 为 771。证据 `/tmp/wrong-detail-lifecycle-batch/`；掌握/撤销、删除、渲染安全等剩余页面职责继续核查，既有 data envelope/legacy 源断言和真实环境限制保持。


## 13. 掌握、重新加入复习与撤销（2026-10-29 后续批次）

- 本批页面由 771→620 行。掌握确认/取消弹层、动作分派、掌握请求/结果/写回及重新加入复习九方法迁入 `utils/wrong-detail-master-flow.js`（130 行）；撤销入口/计时器/请求/错误/提交/到期清理八方法迁入 `utils/wrong-detail-master-undo.js`（93 行）。新模块函数均 ≤50 行，页面签名/async/单次委托保持；十七方法体仅改变接收者和 API/platform 访问，其余 102 个 Page 属性原文不变。
- 请求保留私有 ID 优先与 busy 守卫、patch 在请求前写入、await 后存活守卫与当前 handler；skipped_ids 按 String 比较、updated_count 非 null 时数值≤0的同步分支，以及缺失/NaN等既有判定均保持。API/wx receiver 与平台调用时读取保持。
- 掌握写回保留 entry 元数据与原对象、分离的 cache/view 副本、undo snapshot 和当前题判断，先清旧 undo、写回、开启 5000ms 撤销，再注册 120ms 自动前进。前进 callback 继续读取执行时 currentIdx，仍不新增存活守卫；重新加入复习的成功/同步/错误 toast 与掌握错误不 toast 的差异保持。
- 撤销保留原 pending 对象、inflight 拦截、timer 清理先于 try/finally、await 后当前 hook、按当前列表/视图选择 navigate/setData/load、失败仅对相同 pending 重开 5000ms 窗口以及 finally 解锁。timer 句柄 truthy 判断、默认窗口和卸载后不写视图保持。
- 新刻画并保留两处原限制：撤销 API 的 404/410 虽被处理为清 undo/移除导航/提示无法撤销，后续仍执行本地 commit 并显示成功 toast；timer 清理在 try/finally 外若抛错，inflight 会保持 true。15 项契约在原页重放证实，本批不夹带业务修复。
- 15 项契约原页与当前通过；十二组定向 150 项、全量 Node 2291 项、渲染 5 fixtures/31 项、八门禁和视觉/KaTeX通过。1360 组十七入口返回值/状态/调用轨迹/字段顺序对照一致；独立实现只读审查无 P0–P3 可操作发现。CI 增加掌握契约；详情门禁为十六模块、88 条委托，页面 ceiling 为 620。证据 `/tmp/wrong-detail-master-batch/`；删除、渲染安全及其他剩余职责继续核查，既有真实环境限制保持。


## 14. 移出错题本与返回计时（2026-10-29 后续批次）

- 本批页面由 620→579 行。更多菜单/移除确认的开关和移出错题本五方法迁入 `utils/wrong-detail-remove-flow.js`（63 行，函数均 ≤50 行）；页面签名/async/单次委托保持。五方法体仅改变接收者与 API/platform 访问，其余 114 个 Page 属性原文不变。
- 保留私有 ID 优先与 busy 守卫、try 外清 undo 与初始 patch；API 返回后先存活守卫，再读取当前列表与索引，按 String 过滤全部同 ID 项、仅移除对应 cache entry，并写原 ids/ts 存储形状和字段顺序。存储异常继续吞掉，响应 skipped/count 字段仍不参与本地移除判定。
- 空列表继续先 toast、清原返回 timer、注册 220ms 回退；callback 先清句柄，再判断存活并调用当前 goBack。非空分支保留索引 clamp、await 当前 loadData 后直接 toast，不补第二次存活判断；load/同步副作用失败仍进入原 catch，已完成的列表/cache/存储写入不回滚。
- 9 项契约原页重放与当前通过；十三组定向 159 项、全量 Node 2300 项、渲染 5 fixtures/31 项、八门禁及视觉/KaTeX通过。1000 组五入口返回值/状态/调用轨迹/字段顺序对照一致；独立实现只读审查无 P0–P3 可操作发现。
- CI 增加移除契约；详情门禁为十七模块、93 条委托，页面 ceiling 为 579。证据 `/tmp/wrong-detail-remove-batch/`；渲染安全、专项老师反馈等剩余页面职责继续核查，前述既有行为和真实环境验收限制保持。


## 15. 渲染安全与专项老师交互收敛（2026-10-29 后续批次）

- 本批页面由 579→502 行。CODE/MIXED 渲染检查、trace 与安全模式重渲染三方法迁入 `utils/wrong-detail-render-safety.js`（63 行）；老师动作开合、六字段缓存键、结果弹层关闭和反馈四方法迁入 `utils/wrong-detail-teacher-interaction.js`（46 行）。新模块函数均 ≤50 行；缓存键纯函数不接收 page，页面签名/async/单次委托保持。七方法体仅改变接收者与依赖访问，其余 112 个 Page 属性原文不变。
- CODE 检查仍受 rawText truthy 条件限制，按原实体正则和 html/richTextNodes 判定记录日志后再调用当前自愈方法；MIXED 保留空 blocks 和逐块日志，不触发自愈。trace 读取当前 config.debug，保留数组守卫、末 20 项与对象引用。安全模式仍先 warn/写标志，再读取当前题和 renderer，保持字段/引用、blank groups.length 口径、错误传播与写回顺序。
- 老师 key 保留原六字段、数值/字符串转换、版本 ID 优先级及 falsey 口径。反馈保留 try 外参数验证和提交时 payload/result 捕获、helper/API receiver；await 后读取当前 active key/cache/platform，不新增存活或并发拦截。成功缓存对象身份/null 原型创建、反馈标志与 toast 顺序保持；失败仍先求值当前 toast 方法，再调用当前错误 formatter，formatter 抛错继续传播。
- 原 `run408TeacherAction` 仍直接委托既有 controller；该入口和另七个导航/重载/滚动/noop 薄入口原文保留。全部 104 个 Page 方法和四个页外 helper 包装共 108 个精确模板登记；门禁补充未知 callable 属性与 spread 的负例，阻止未登记业务方法回流。十九个同页 utils 模块继续受 300/50 预算与依赖约束覆盖，页面保留 data、实例惰性装配、依赖注入和薄入口。
- 11 项契约原页面重放与当前通过；十四组定向 171 项、全量 Node 2312 项、渲染 5 fixtures/31 项、八条架构门禁和视觉/KaTeX通过。1400 组七入口返回值/状态/调用轨迹/字段顺序对照一致；独立实现只读审查无 P0–P3 可操作发现。
- `reliability.yml` 注册新增小程序契约；已核对 `ci.yml` 的四个 job 仅覆盖后端/Docker/迁移，本批未新增其固定清单中的后端架构测试。详情门禁为十九模块、108 模板，页面 ceiling 为 502。证据 `/tmp/wrong-detail-remaining-batch/`；下一项为错题本请求/批量/AI 编排，既有基线问题和真实微信/外部 AI/完整闭环验收限制保持。

## 16. 错题 AI 可用性探测与禁用提示（2026-11-01）

- 新增 `utils/wrong-detail-ai-availability.js`，承接页面初始化、检查请求、5 秒前端
  超时、共享状态应用、自动重试、卸载清理和 503 availability detail 白名单读取。
  页面仅保留七个薄委托；现有 AI 状态、生成、重新生成、老师 controller 仍按原模块
  边界工作，没有把网络或计时器依赖下沉到纯状态模块。
- 详情加载完成后和页面重新 `onShow` 时触发 availability 检查。请求成功且模型可用时
  同时恢复 AI 分析、重新生成和 AI 老师；检查中或禁用时停止新的调用。检查动画最多
  5 秒，超时后显示“仍在检查”并按后端 `retry_after_ms` 自动重查；后端返回
  `checking` 时按 2 秒重查，传输层超时仍单独按 5 秒结束动画；成功探测结果由后端
  共享 30 秒。
- 生成、重新生成和老师动作都读取同一 `aiAvailabilityEnabled`。禁用状态不清除
  已有 AI 卡片、老师结果或题目解析，只在原内容附近显示短原因。生成失败时若响应或
  503 detail 携带 availability，页面立即应用；老师面板直接展示该原因，已有老师结果
  继续保留。没有结构化原因时才静默刷新状态。
- 生成/重新生成继续沿用 §15 的失败恢复边界：只有网络响应丢失或 HTTP 408/502/504
  启动持久化恢复；明确的可用性 503、额度或鉴权业务失败不进入 44 次轮询。
- `wrong-detail-boundaries.js` 现登记 20 个同页模块、26 个老师端口和新增七个页面
  委托。详情页仍为 502 行；AI 可用性模块、页面委托和端口接线均有静态门禁。
- 错题详情相关 Node 定向 202 项通过；全量 `node --test tests/*.js` 为
  `2557 passed`，5 个渲染 fixture 共 31 项通过。未执行微信开发者工具编译、
  模拟器/真机、真实弱网或真实上游模型验收，小程序由用户手动发布。

## 17. 共享健康租期与可用性生命周期收敛（2026-11-06）

- 后端共享成功状态租期由 §16 的 30 秒延长为 30 分钟，距上次成功超过 5 分钟
  按需后台刷新，刷新期间未过期成功状态仍可用；实际调用成功续期。后端口径见
  [[docs/architecture/AI_ANALYSIS_COMPATIBILITY.md|AI_ANALYSIS_COMPATIBILITY]] §20。
- 小程序可用性模块统一管理暂停、恢复、主动等待与重试计时器，页面生命周期只调用
  对应入口：隐藏时暂停检查并使在途响应失效，不让迟响应修改状态或重建后台轮询；
  返回后复用仍有效的成功缓存，命中失败缓存时按剩余冷却恢复重试，不重新延长
  完整冷却或一直保持禁用。
- 检查中用户主动点击「开始复盘 / 重试复盘」时保留一次生成意图，检查成功后延续
  执行一次并防重复点击；没有主动操作不自动生成。等待最多约 65 秒，切题、隐藏、
  卸载或请求序列变化后取消；已确认故障保持禁用。生成请求仅因 `checking` 被拒时
  可在健康恢复后续发一次原请求，其他生成失败不自动重放。交互细则见
  `docs/frontend/UI_RULES.md`。
- 验证：本批 Node 定向 66 项、全量 `2703 passed`、渲染 31/31；官方 WCC 与编译
  模板回归通过，CLI 预览编译成功。真实弱网、真机与真实题目生成仍待复验。

---

## 相关链接

- [[docs/architecture/SYSTEM_ARCHITECTURE.md|SYSTEM_ARCHITECTURE]] — 系统架构
- [[docs/architecture/PRODUCTION_ARCH.md|PRODUCTION_ARCH]] — 生产架构
- [[docs/architecture/API_ROUTER_STRUCTURE.md|API_ROUTER_STRUCTURE]] — 路由结构
- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
- [[docs/ai/AI_PIPELINE.md|AI_PIPELINE]] — AI 管线
