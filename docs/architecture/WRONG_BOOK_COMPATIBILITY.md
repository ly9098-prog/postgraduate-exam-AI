# 错题本页面兼容边界

核对日期：2026-10-29。覆盖小程序错题本页面的值格式化、题目装饰、任务分组、统计分析投影、加载请求、选择交互、批量请求/撤销、生命周期、导航/导出及 AI 状态/缓存/设置/请求/交互编排，不表示错题学习闭环或真实客户端验收完成。

## 1. 职责与动态端口

- 页面 `miniprogram/subpackages/study/wrong-book/wrong-book.js` 从 1547→1306 行，保留生命周期、API/缓存/存储、日期筛选、列表请求序列、批量选择、撤销、AI 请求和视图回写。
- 27 个投影方法迁入同页 `utils/wrong-book-{value,item,analysis}-view.js`，原页面方法保留名称、参数、默认值与单次返回委托。外部静态 helper 按原页面导入顺序注入；投影模块不直接访问平台、网络或存储。
- `wrong-book-view-page-adapter.js` 通过 getter 在读取时取得页面当前 helper 并绑定页面。保留页面实例隔离、方法替换与 callback `.bind(this)` 的接收者语义，未引入共享可变状态。
- `wrong-book-boundaries.js` 登记四个新模块，检查 300/50 预算、页面 1306 行上限、27 路委托、模块依赖/平台端口限制和新增/缺失模块。该目录由独立门禁覆盖，不属于既有七个 controller 目录。

## 2. 既有显示口径

- 题目先解析错题次数、复盘次数、掌握进度、复习日期与最近新增状态，再装饰显示字段；不改原题目对象。`review_record_count=0` 优先于 `review_count`；`mastery_progress=0` 的既有 truthy fallback 保留。
- 任务分组按今日到期、高频、最近新增、待巩固、已掌握依次占用 ID，各组保留原排序和最多 3 条预览；`ungroupedCount` 仍以原列表长度减预览条数计算。
- 分析优先使用服务端错因/科目统计，缺失时从当前列表计数。过滤后的列表与全局统计分离继续由页面请求编排负责。
- 状态、中文标签、雷达图比例、默认文案、日期解释、文本清洗与输入缺省值均保留；WXML/WXSS/资源不变。

## 3. 验证与限制

- 拆分前新增 6 项投影刻画和既有日期筛选测试通过；拆分后新增动态 helper 绑定用例及 6 项架构负向/扫描测试，共 13 项定向通过。
- 全量 `node --test tests/*.js`：2141 passed；渲染回归：5 fixtures、31 passed；七条页面/学习/controller 架构门禁通过。CI 显式加入错题本门禁和两条新测试路径。
- 原实现/当前实现对照：27 个迁移方法体归一化后相同，其余 107 个页面属性保持；9,944 次确定性投影比较一致。独立只读 review 的 1 项 P3（`new Function` 动态执行门禁绕过）已修复并复核，额外 3,007 次差分一致。
- 未执行微信开发者工具编译、模拟器/真机、真实网络/AI、弱网刷新或批量撤销交互验收。临时证据位于 `/tmp/wrong-book-view-batch/`，不能代替长期测试或真实环境验收。

## 4. 加载请求编排

- 页面由 1306→1141 行；筛选重载、页面加载、统计、列表、任务流与科目六个方法迁至 `utils/wrong-book-request-flow.js`（191 行、函数≤50 行）。原页面方法保留参数、默认值、async 与单次返回委托，API 对象从原页面注入；其余 128 个 Page 属性原文不变。
- 筛选重载先递增列表/任务流序号，再应用可覆盖默认字段的 patch，更新筛选计数并非等待地加载列表。页面加载仍按统计、列表顺序启动 `Promise.all`，完成后检查销毁状态，再等待当前 AI 诊断方法。
- 列表日期同步位于 try 外，日期变化强制 reset 并使旧任务流失效。保留两次序号/存活守卫、await 后的当前装饰与投影 helper、追加列表/分页/字段顺序、全局高频数值优先口径，以及 reset 后非等待的任务流加载。错误始终记录，仅当前且存活的请求写回错误。
- 统计和科目成功检查销毁/序号，未新增 alive 守卫；科目保留 loading 去重及当前 flatten helper。任务流参数仍在 try 外构造，成功同时检查销毁/存活/序号，catch 仅检查销毁/序号；分组 fallback、全局/筛选统计口径和选择状态同步保持。
- 新增 14 项契约在原页面与当前页面均通过；四组定向 28 项、全量 Node 2326 项、渲染 5 fixtures/31 项、八条架构门禁、JS 语法、既有 visual/math 源检查与 CI YAML 解析通过。六方法体仅替换接收者/API 端口，1200 组六入口返回值、状态、调用轨迹与字段顺序差分一致。
- 门禁收紧至页面 1141 行、5 模块/33 委托，CI 注册请求契约。独立实现 review 无 P0–P3；临时证据 `/tmp/wrong-book-request-batch/`。生命周期、批量选择/操作、撤销与 AI 编排继续待治理；真实客户端、网络和完整闭环仍未验收。

## 5. 选择状态与批量工具条

- 页面由 1141→1028 行；视图切换、批量模式、交互/滚动、工具条计时、点击/长按、选择切换/全选/有效键同步与徽标反馈共 16 个方法迁至 `utils/wrong-book-selection-flow.js`（179 行、函数≤50 行）。原入口参数与单次返回委托保持，其余 118 个 Page 属性原文不变；详情导航、批量请求与撤销未在本批迁移。
- 选择切换复制 map 并按旧值 truthy 判定，再同步有效键，新增选择才触发徽标。有效键来自列表与任务分组，保留有效键时仍忽略旧值真假；全选只改当前可见键，保留屏外键，未新增同步步骤。列表视图保留重复字符串 ID，任务视图按遇见顺序去重。
- 批量模式退出先清工具条 timer，进入仅在 setData callback 中调用当前显示方法；原筛选收起和选择字段重置保持。工具条仍在 5000ms 后按当前 alive/mode/visible 判定隐藏，先清 timer 再判断是否调度；徽标保留未跟踪的首段 16ms timer、后续 260ms timer 和两段存活检查。
- 点击保留严格小于抑制时间的判断；长按写入当前时间+700ms，进入模式后在原 try 内动态读取平台并保留 receiver，平台缺失/振动异常仍吞掉后继续选择。延迟 callback 中当前 helper 的解析、异常传播和部分写回顺序保持。
- 新增 15 项契约在原页面与当前页面均通过；五组定向 43 项、全量 Node 2341 项、渲染 5 fixtures/31 项、八条架构门禁、JS 语法、visual/math 与 CI YAML 解析通过。16 个迁移方法体仅替换接收者/常量/平台端口，1600 组入口、状态、timer、轨迹与字段顺序差分一致；独立实现 review 无 P0–P3。
- 门禁收紧至页面 1028 行、6 模块/49 委托，CI 注册选择契约；临时证据 `/tmp/wrong-book-selection-batch/`。生命周期、批量请求/撤销、AI 与真实客户端/网络/完整学习闭环验收仍待完成。

## 6. 批量请求与掌握撤销

- 页面由 1028→894 行；批量菜单/确认、ID 解析、动作规则、请求/成功/错误/缺失接口与重载共 12 个方法迁至 `utils/wrong-book-batch-flow.js`（131 行），掌握结果/撤销/清理 3 个方法迁至 `utils/wrong-book-batch-undo.js`（67 行），函数均≤50 行。原签名、async 与单次返回委托保持，其余 119 个 Page 属性原文不变；三个无页面依赖的规则函数不接收页面。
- 确认前捕获 ID 和标签，ID 只在数值转换与字符串往返相等时转为数字。取消确认不提交，确认与 showLoading 异常仍在请求 try 外；响应后先 hideLoading，再判断销毁状态，随后读取当前处理方法。更多菜单/错误缺失接口展示仍不等待后续动作，普通成功才等待当前重载。
- 掌握结果优先用 skipped_ids 排除撤销 ID；缺少 skipped_ids 且报告数不是全部时不开放撤销。保留副本、计数口径、字段顺序、5000ms 窗口及 callback 执行时读取清理方法。撤销入口仍返回 undefined，成功/失败沿原 then/catch 链处理，重载不等待，失败保留 ID 并重开窗口；API、平台 receiver 和 await 后动态读取保持。
- 新刻画并保留既有缺陷：普通成功响应缺少 updated_count 时，`_handleBatchSuccess` 的 fallback 引用未定义的 ids，抛出 ReferenceError；通过动作入口调用时仍进入原错误处理。撤销 timer 清理或 showLoading 等请求前异常仍可保留 inFlight 标记，成功处理异常仍进入原重试 catch。本批未夹带修复。
- 新增 18 项契约在原页面与当前页面均通过；六组定向 61 项、全量 Node 2359 项、渲染 5 fixtures/31 项、八条架构门禁、JS 语法、visual/math 与 CI YAML 解析通过。15 个迁移方法体仅替换接收者/API/平台端口，1500 组入口、返回值、状态、timer、轨迹与字段顺序差分一致；独立实现 review 无 P0–P3。
- 门禁收紧至页面 894 行、8 模块/64 委托，CI 注册批量契约；临时证据 `/tmp/wrong-book-batch-actions/`。生命周期、导航/导出、AI 以及真实客户端/网络/完整学习闭环验收仍待完成。

## 7. 生命周期与导航/导出

- 页面由 894→783 行；load/ready/show/hide/unload 五个方法迁至 `utils/wrong-book-lifecycle.js`（67 行），导出能力、返回、详情导航、导出入口/记录与详情事件六个方法迁至 `utils/wrong-book-navigation-flow.js`（92 行），函数均≤50 行。原签名、async 与单次委托保持，其余 123 个 Page 属性原文不变。
- load 保留销毁/统计/科目/任务流序号与撤销状态重置、数学配置、日期同步、query 转换和 helper 顺序，未新增 alive/ready/list 序号重置。ready 不等待科目加载；show 先标记存活/同步日期/恢复工具条，再检查 ready，随后非等待地启动统计/列表，完成后读取当前诊断方法，未新增销毁守卫。
- unload 先标记失活/销毁并递增六个序号，再按工具条、徽标、自动开关、撤销的原顺序清理；timer 清理异常仍中断后续动作并保留原部分状态。导出能力仍只接受配置和能力字段的严格 true，保留初始 patch 在 try 外、requestId 守卫、当前 formatter 与异常边界，未新增 alive/destroyed 守卫。
- 详情导航保留任务 ID 数组引用、缺失 ID 前插、原始列表 ID、首个匹配索引及 ids/ts 存储 shape；存储失败先记录再导航。导出 ID 仍按有限数值且非零过滤，允许负数/小数，最多 100 项；先写原全局字段再跳转。返回 fallback、平台/app getter 与 receiver 保持执行时解析，导出配置和记录路由原值不变。
- 新增 17 项契约在原页面与当前页面均通过；七组定向 78 项、全量 Node 2376 项、渲染 5 fixtures/31 项、八条架构门禁、JS 语法、visual/math 与 CI YAML 解析通过。11 个方法体按 AST token 校验，仅替换接收者/注入端口，1100 组入口、返回、状态、导航、轨迹与字段顺序差分一致；独立实现 review 无 P0–P3。
- 门禁收紧至页面 783 行、10 模块/75 委托，CI 注册生命周期契约；临时证据 `/tmp/wrong-book-lifecycle-batch/`。筛选与 AI 剩余编排继续待治理，真实客户端/网络/完整学习闭环仍未验收。

## 8. AI 状态、缓存与自动分析设置

- 页面由 783→652 行；空闲文案/归一化/内容判定/生成状态判定/详情投影五个方法迁至 `utils/wrong-book-ai-state.js`（80 行），用户/设置键/设置恢复/自动开关/缓存恢复/来源签名/缓存提交八个方法迁至 `utils/wrong-book-ai-persistence.js`（107 行），函数均≤50 行。原签名与单次返回委托保持，其余 121 个 Page 属性原文不变。
- 归一化保留 JSON 深拷贝、数组缺省、知识点过滤、accuracy 的 0–1/百分数混合口径、建议过滤及字段顺序；详情保留前三项、显式百分比优先和既有强制转换。内容判定仍读取当前归一化 helper；生成状态保持 status/state/generation_status 与 message/detail/summary 的 truthy 优先级、严格 generating=true 和原文本模式。
- 用户 ID 保留 id/user_id/openid 的 truthy 优先级，存储读取异常仍返回 null；自动设置键保持原前缀，只接受存储值严格 true。来源签名仍读取当前 stats/list 与原 firstItem，缓存恢复/提交保留原对象身份、当前 helper、字段顺序及原始 summary 文案来源；提交先记录当前时间再 save，save 后才读取当前详情 helper，失败保留原部分状态。
- 自动开关保持存储→旧 timer 清理→patch→420ms timer→toast→自动启动顺序。关闭时仅已有加载/刷新使请求序号失效；开启仍要求统计已加载且总数>0，已有 Promise 时沿原 finally 注册启动，callback 执行时读取当前 alive/开关/分析方法，不等待分析请求。timer 失活时仍清空私有句柄，不新增 Promise 链接管或异常吞掉。
- 新增 15 项契约在原页面与当前页面均通过；八组定向 93 项、全量 Node 2391 项、渲染 5 fixtures/31 项、八条架构门禁、JS 语法、visual/math 与 CI YAML 解析通过。13 个方法体按 AST token 校验，仅替换接收者/注入端口，1300 组入口、返回、状态、缓存、timer、轨迹与字段顺序差分一致；独立实现 review 无 P0–P3。
- 门禁收紧至页面 652 行、12 模块/88 委托，CI 注册 AI 状态契约；临时证据 `/tmp/wrong-book-ai-state-batch/`。筛选、AI 请求/轮询/结果分流及交互剩余编排继续待治理，真实客户端/外部 AI/完整学习闭环仍未验收。

## 9. AI 请求、轮询与结果交互

- 页面由 652→504 行；诊断检查/延迟/轮询/ensure/请求装配/执行/fetch/结果分流/错误处理九个方法迁至 `utils/wrong-book-ai-request-flow.js`（147 行），洞察展开/手动刷新/反馈三个方法迁至 `utils/wrong-book-ai-interaction.js`（53 行），函数均≤50 行。原参数、async 与单次委托保持，其余 122 个 Page 属性原文不变。
- 诊断检查保留 destroyed/统计就绪/严格 total=0/自动开关的原顺序与清缓存规则。ensure 保留严格零先于 Promise 去重、已有请求先于 force、前台已有数据直接返回、缓存陈旧与来源变化/冷却条件的优先级；请求装配先递增序号并写 loading/refreshing，再保存当前 executor 返回值。
- 请求保持 55000ms timeout、force/refresh 才传 refresh=true；pending 时读取当前 poll helper。轮询最多四次，延迟 1200/1550/1900/2250ms，每次延迟后检查请求序号/alive，再读取当前 API 方法；第四次响应后仍直接返回，无新增最终守卫。仍 pending 时保留 detail/message/默认错误的优先级。
- executor 保留 await 后序号/alive 守卫、当前结果/错误 helper、原 return 而非 return-await 和 catch/finally 范围。新刻画并保留既有并发限制：finally 无条件清空当前 Promise 字段，旧执行结束可能清除较新字段；本批未加入身份检查。结果分流、错误日志先于守卫、保留旧数据及强制刷新才 toast 的口径不变。
- 洞察展开保留先收起再忙碌判断、showLoading 位于 try 外、finally 中读取当前 hideLoading、响应后无新增存活守卫；手动刷新仍不等待 ensure。反馈保留选项 fallback、source/feedback_type 字段和 API receiver，成功 toast 仍处于原 catch 范围。
- 新增 20 项契约在原页面与当前页面均通过；九组定向 113 项、全量 Node 2411 项、渲染 5 fixtures/31 项、八条架构门禁、JS 语法、visual/math 与 CI YAML 解析通过。12 个方法体按 AST token 校验，仅替换接收者/注入端口，1200 组入口、返回、状态、请求/轮询、轨迹与字段顺序差分一致；独立实现 review 无 P0–P3。
- 门禁收紧至页面 504 行、14 模块/100 委托，CI 注册 AI 请求契约；临时证据 `/tmp/wrong-book-ai-request-batch/`。筛选剩余编排与页面完整入口门禁继续待治理，真实客户端/外部 AI/完整学习闭环仍未验收。
