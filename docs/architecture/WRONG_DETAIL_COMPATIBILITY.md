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
