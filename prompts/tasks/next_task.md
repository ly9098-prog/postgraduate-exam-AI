你是一名资深微信小程序前端性能优化和样式架构工程师。请继续在当前项目上完成第四阶段修复。

前三阶段已经完成：

- 高频 `setData` 优化；
- 页面运行态从 `data` 迁移至实例变量；
- Wrong Detail AI 请求防串；
- 大部分 `:active` 替换为 `hover-class`；
- 点击热区、惯性滚动、颜色对比度修复；
- 定时器与异步请求生命周期检查。

本阶段只处理：

1. `.year-day:active .year-day-tip`；
2. 16 个 orphan pressed 样式；
3. 未使用 WXSS 的安全清理；
4. 全局样式和页面样式的职责调整；
5. 样式引用完整性检查；
6. 包体积和主包资源检查；
7. 生成开发者工具最终审计所需的验证清单。

不得进行无关业务重构，不得修改接口、路由、答题逻辑、计时逻辑或 AI 请求协议。

不要只输出建议，请直接修改源码。

# 一、修改前检查

开始前必须执行：

1. 查看当前 Git diff。
2. 确认实际源码根目录为 `miniprogram/`。
3. 确认 `project.config.json` 中的 `miniprogramRoot`。
4. 记录当前所有未提交修改。
5. 搜索以下内容：

```bash
grep -RInE ":active|hover-class|-pressed|year-day-tip" \
  miniprogram \
  --include="*.wxss" \
  --include="*.wxml"
```

1. 搜索所有 WXSS：

```bash
find miniprogram -name "*.wxss" -type f
```

1. 记录重点 WXSS 文件修改前字节数。

禁止执行：

```bash
git reset --hard
git checkout .
git clean -fd
```

不得覆盖前三阶段修改。

# 二、P0：彻底移除 `.year-day:active`

当前项目仍存在：

```css
.year-day:active .year-day-tip
```

虽然此前报告认为它属于 tooltip 显示，但它仍然使用 CSS `:active`，不能继续声称项目自有 WXSS 已经完全移除 `:active`。

请检查：

- `.year-day` 对应 WXML；
- 是否存在 `bindtap`、`bindtouchstart`、`bindtouchend`；
- tooltip 是短按显示、点击切换，还是仅桌面端 hover 行为；
- tooltip 是否会被其他元素遮挡；
- 滚动时是否会误触。

## 2.1 推荐实现

使用显式状态控制 tooltip，不使用 CSS `:active`。

WXML 示例：

```xml
<view
  class="year-day"
  data-index="{{index}}"
  bindtap="onToggleYearDayTip"
>
  <view
    wx:if="{{activeYearDayIndex === index}}"
    class="year-day-tip"
  >
    {{item.tipText}}
  </view>
</view>
```

JS 示例：

```js
onToggleYearDayTip(event) {
  const index = Number(event.currentTarget.dataset.index)

  this.setData({
    activeYearDayIndex:
      this.data.activeYearDayIndex === index ? -1 : index
  })
}
```

如果只允许一次显示，可点击其他区域关闭。

如果 tooltip 只需在按压期间显示，也可以使用：

```xml
hover-class="year-day-pressed"
```

以及：

```css
.year-day-pressed .year-day-tip {
  opacity: 1;
  visibility: visible;
}
```

但必须确认 `hover-class` 能满足当前产品交互。

## 2.2 状态要求

若新增 `activeYearDayIndex`：

1. 必须绑定 WXML；
2. 默认值设为 `-1`；
3. 切换统计年份时重置；
4. 页面隐藏时根据产品逻辑决定是否关闭；
5. 不得新增未绑定 `setData` 字段；
6. 不得使用模块级全局变量共享 tooltip 状态。

## 2.3 验收

完成后执行：

```bash
grep -RIn ":active" \
  miniprogram \
  --include="*.wxss"
```

目标：项目自有 WXSS 中结果为 0。

如果第三方组件仍存在 `:active`，逐条列出，并说明是否位于实际打包路径。

# 三、P0：清理 16 个 orphan pressed 样式

此前报告发现 16 个没有直接 WXML 引用的 `*-pressed` 样式，分类为：

- 共享组件样式；
- 使用替代 hover-class 的样式；
- 死样式；
- picker 等边缘场景。

不要直接全部删除。请为每个样式建立引用证据表：

| 选择器 | 所在文件 | WXML 直接引用 | JS 动态引用 | externalClasses | 替代类 | 结论 |
| ------ | -------- | ------------- | ----------- | --------------- | ------ | ---- |
|        |          |               |             |                 |        |      |

## 3.1 判定规则

### 可以删除

同时满足：

1. WXML 没有 `hover-class` 引用；
2. WXML 没有普通 class 引用；
3. JS 没有动态拼接；
4. 组件没有 `externalClasses`；
5. 不属于全局复用类；
6. 没有被其他 WXSS 组合选择器依赖；
7. 不属于 picker、button、navigator 等原生组件状态兼容样式；
8. 不属于第三方组件；
9. 没有未来配置项或条件渲染引用。

### 应保留

满足任意一项：

- 属于组件公开样式契约；
- 通过 `externalClasses` 传入；
- 被 JS 动态拼接；
- 被多个页面复用；
- 是设计系统通用 pressed token；
- 由 picker、表单或原生组件结构间接使用；
- 当前无法确定安全性。

### 应修复引用

如果样式本来应当使用，但 WXML 漏写 `hover-class`，则补齐 WXML，不要删除样式。

## 3.2 删除后检查

删除 orphan pressed 样式后再次搜索：

```bash
grep -RInE "[A-Za-z0-9_-]+-pressed" \
  miniprogram \
  --include="*.wxss" \
  --include="*.wxml"
```

确保：

1. 每个 WXSS pressed 类都有 WXML 引用；
2. 每个 WXML hover-class 都有对应 WXSS 定义；
3. 没有拼写不一致；
4. 没有只定义未使用；
5. 没有只使用未定义。

# 四、P1：安全清理未使用 WXSS

旧审计曾提示约可节省 161 KB，但该数据来自特定页面访问轨迹，可能把条件样式和第三方样式误判为未使用。

重点文件：

- `miniprogram/app.wxss`
- `miniprogram/pages/practice/practice.wxss`
- `miniprogram/components/AnimatedView/AnimatedView.wxss`
- `miniprogram/components/mp-html/index.wxss`
- `miniprogram/components/quiz-runner/quiz-runner.wxss`
- `miniprogram/pages/wrong-detail/wrong-detail.wxss`
- `miniprogram/pages/wrong-book/wrong-book.wxss`
- `miniprogram/pages/dashboard/dashboard.wxss`
- `miniprogram/pages/pomodoro-stats/pomodoro-stats.wxss`

## 4.1 一次只处理一个文件

必须按以下顺序处理：

1. `pomodoro-stats.wxss`
2. `quiz-runner.wxss`
3. `wrong-detail.wxss`
4. `wrong-book.wxss`
5. `dashboard.wxss`
6. `practice.wxss`
7. `AnimatedView.wxss`
8. `app.wxss`
9. `mp-html/index.wxss`

每个文件处理完成并检查后，才能进入下一个。

## 4.2 为每个选择器建立引用映射

检查：

- 当前页面 WXML；
- 当前组件 WXML；
- 所有 JS 动态 class；
- `hover-class`；
- `externalClasses`；
- 父组件传入样式；
- 插槽内容；
- `wx:if` 条件分支；
- 空状态；
- 加载状态；
- 请求失败状态；
- 禁用状态；
- 选中状态；
- 正确、错误状态；
- 动画进入和退出状态；
- 模态框；
- 管理员或开发状态；
- 媒体查询；
- 伪元素；
- 组合选择器；
- 全局样式继承。

## 4.3 删除条件

仅删除同时满足以下条件的选择器：

1. 没有 WXML 静态引用；
2. 没有 JS 动态引用；
3. 没有 hover-class 引用；
4. 没有 externalClasses 引用；
5. 不属于插槽内容样式；
6. 不属于条件渲染状态；
7. 不属于动画状态；
8. 不属于第三方组件基础样式；
9. 不属于全局设计系统；
10. 不被其他选择器依赖。

## 4.4 动态类检查

必须搜索类似代码：

```js
`class-a ${active ? 'active' : ''}`
```

以及：

```js
[className, stateClass].join(' ')
```

还要检查 WXML：

```xml
class="card {{selected ? 'selected' : ''}}"
```

不得因为不存在完整字符串 `.card.selected` 就判断未使用。

# 五、各重点文件处理要求

## 5.1 pomodoro-stats.wxss

优先清理：

- 已确认没有点击事件的 pressed 样式；
- 已废弃历史卡片样式；
- 重复布局类；
- 页面已不存在的旧空状态样式。

必须保留：

- 图表；
- 历史记录；
- 周统计；
- 空状态；
- 加载状态；
- 惯性滚动相关样式；
- 底部安全区。

## 5.2 quiz-runner.wxss

必须保留：

- 单选、多选、填空题状态；
- 正确、错误、已提交状态；
- 当前题和已答题圆点；
- 80rpx 点击热区；
- 上一题、下一题禁用状态；
- hover-class pressed 状态；
- 题目内容富文本样式；
- 横向导航滚动。

删除前检查组件 properties 和动态 class。

## 5.3 wrong-detail.wxss

必须保留：

- 错误类型；
- 正确答案；
- 用户答案；
- 知识点；
- AI loading；
- AI empty；
- AI error；
- AI cards；
- 重新生成按钮；
- 切题遮罩；
- 上一题、下一题。

不得删除当前测试中不容易触发的 AI 失败和降级样式。

## 5.4 wrong-book.wxss

必须保留：

- 筛选项；
- 错题列表；
- 空状态；
- 加载状态；
- 科目标签；
- 错误类型；
- 分页或加载更多；
- pressed 状态。

## 5.5 dashboard.wxss

必须保留：

- 英雄统计区；
- 趋势图；
- 学科统计；
- 掌握率；
- 成长数据；
- 自适应建议；
- 加载状态；
- 错误状态；
- 年度记录 tooltip；
- 弱项卡片；
- 空状态。

## 5.6 practice.wxss

这是高风险文件。

必须覆盖：

- 单选；
- 多选；
- 填空；
- 题目加载；
- 安全模式；
- 网络错误；
- 提交状态；
- 结果跳转；
- 底部导航；
- 键盘弹出；
- 横屏或小屏适配；
- pressed 状态。

每次删除后必须确认 WXML 所有 class 仍有定义。

## 5.7 AnimatedView.wxss

检查组件：

- properties；
- observers；
- JS 状态；
- 动画方向；
- 动画时间；
- 延迟；
- enter/leave；
- fade/slide/scale；
- disabled motion。

如果无法完整证明某个动画类型未使用，则保留。

## 5.8 app.wxss

禁止大规模删除。

优先识别：

- 页面专属样式误放全局；
- 重复工具类；
- 已废弃调试类；
- 从未引用的旧主题类。

通用类应保留，包括：

- 页面容器；
- 安全区域；
- 卡片；
- 主按钮；
- 次按钮；
- 文本色；
- 间距；
- Flex 布局；
- 加载和空状态；
- pressed 通用类。

如果某全局类只被单个页面使用，可迁移到页面 WXSS，但迁移前后视觉必须一致。

## 5.9 mp-html/index.wxss

默认不做核心样式裁剪。

只能删除：

- 项目自行添加且已经废弃的覆盖样式；
- 能明确证明无任何引用的扩展样式。

必须保留：

- 文本；
- 标题；
- 图片；
- 表格；
- 列表；
- 引用；
- 链接；
- 代码；
- 数学公式；
- 上下标；
- 视频或媒体占位；
- 长文本换行。

无法完成富文本全场景测试时，不得大范围修改该文件。

# 六、P1：重复与冲突样式检查

检查以下问题：

1. 同一选择器在同一文件重复定义；
2. 同一组件状态存在多个 pressed 类；
3. 页面 WXSS 与 `app.wxss` 定义相同类但值不同；
4. 无效嵌套选择器；
5. 永远无法匹配的选择器；
6. 拼写错误；
7. 不存在的父级 class；
8. 已删除 WXML 元素对应的旧样式；
9. 重复动画 keyframes；
10. 无引用 CSS 变量；
11. 重复安全区处理；
12. 重复字体和颜色 token。

对冲突样式：

- 明确最终生效来源；
- 保留语义最清晰的一处；
- 不得通过增加 `!important` 掩盖问题。

# 七、P1：资源与包体积检查

检查 `miniprogram/` 内：

- 未引用图片；
- 重复图片；
- 超大 PNG/JPG；
- 临时截图；
- 备份文件；
- `.bak`；
- `.old`；
- `.copy`；
- 编辑器临时文件；
- 测试数据；
- 日志文件；
- 旧审计文件；
- 开发专用文件。

## 7.1 资源引用

对每个候选图片搜索：

- WXML；
- WXSS；
- JS；
- JSON；
- 动态路径；
- 配置文件。

只有确认没有动态路径引用后才允许删除。

## 7.2 packOptions.ignore

检查 `project.config.json` 是否适合忽略：

- 文档；
- 审计导出；
- 临时文件；
- 测试脚本；
- 不参与运行的设计稿；
- 本地开发说明。

不得忽略运行所需文件。

## 7.3 结果记录

记录：

- 修改前 WXSS 总字节数；
- 修改后 WXSS 总字节数；
- 删除资源数；
- 删除资源总大小；
- 是否修改 `packOptions.ignore`；
- 是否能够获得真实主包体积。

如果无法从 CLI 获得真实上传包体积，明确写“待微信开发者工具确认”，不得估算。

# 八、静态完整性检查

修改完成后执行以下检查。

## 8.1 :active

```bash
grep -RIn ":active" \
  miniprogram \
  --include="*.wxss"
```

项目自有代码目标为 0。

## 8.2 hover-class 定义与引用

输出：

- WXML 使用的 hover-class 集合；
- WXSS 定义的 pressed 类集合；
- 使用但未定义；
- 定义但未使用。

## 8.3 WXML class 与 WXSS

检查所有页面和组件：

- WXML class 是否有样式定义；
- 动态 class 是否有定义；
- 已删除样式是否仍被引用；
- 同名类是否错误依赖全局。

注意：不是所有 WXML class 都必须有样式，有些可能用于测试或数据定位。对此要注明，不得自动添加空样式。

## 8.4 WXSS 语法

检查：

- 花括号闭合；
- 注释闭合；
- `@import` 路径；
- `@keyframes`；
- CSS 变量；
- 无效属性；
- 重复属性；
- 错误选择器。

## 8.5 JS 和 WXML

确认样式清理未改坏：

- WXML 标签闭合；
- 动态表达式；
- JS class 字符串；
- hover-class 条件表达式；
- 禁用状态。

# 九、回归测试要求

至少逐页验证：

## Login

- 微信登录按钮；
- loading 禁用态；
- 协议链接；
- 开发入口。

## Home

- 数字动画；
- 目标配置；
- 功能入口；
- 卡片点击态。

## Practice

- 单选；
- 多选；
- 填空；
- 上下题；
- 题号导航；
- 提交；
- 错误状态；
- 安全模式。

## Practice Result

- 主按钮；
- 次按钮；
- 成长徽章；
- 返回首页。

## Wrong Book

- 筛选；
- 列表点击；
- 空状态；
- 加载更多。

## Wrong Detail

- 错误类型；
- AI loading；
- AI 成功；
- AI 失败；
- AI 重新生成；
- 上下题；
- 快速切题。

## Dashboard

- 全部统计区块；
- 趋势切换；
- 年度 tooltip；
- 弱项卡片；
- 空状态；
- 错误状态。

## Pomodoro

- 模式选择；
- 科目卡片；
- 启动；
- 暂停；
- 恢复；
- 结束；
- 字体大小；
- 统计入口。

## Pomodoro Stats

- 图表；
- 历史记录；
- 今日入口；
- 空状态；
- 页面滚动。

## Review Today

- 空状态；
- 加载失败；
- 开始复习；
- 题组完成；
- 最终结果；
- 确认弹窗；
- 取消按钮；
- 主次操作按钮。

## 富文本

- 标题；
- 正文；
- 列表；
- 图片；
- 表格；
- 代码；
- 数学公式；
- 长文本。

# 十、微信开发者工具最终审计

代码修改完成后，不得直接宣布最终通过。

请输出人工操作要求：

1. 清除缓存。
2. 重新编译。
3. 登录测试账号。
4. 完整访问全部页面。
5. 完成每个页面核心交互。
6. 运行自动审计。
7. 导出新的 `audits.json`。
8. 将新审计结果与旧分数对比。

重点确认：

- `unused-css`
- `ele-active-state`
- `set-data-freq`
- `set-data-no-binding`
- `small-response-area`
- `overflow-scroll`
- `color-contrast`
- `js-exception`
- 首屏时间；
- 包体积。

如果当前环境不能运行 GUI，必须明确写：

“未执行微信开发者工具 GUI 审计，本阶段仅完成代码和静态引用检查。”

# 十一、最终输出格式

严格按以下格式输出：

## 1. 修改摘要

说明本阶段真实完成内容。

## 2. `.year-day:active` 处理

说明：

- 原交互；
- 新交互；
- 使用的状态；
- 是否仍有 `:active`。

## 3. Orphan pressed 样式

提供完整表格：

| 选择器 | 文件 | 原因 | 处理 |
| ------ | ---- | ---- | ---- |
|        |      |      |      |

## 4. WXSS 清理结果

逐文件提供：

| 文件 | 修改前字节 | 修改后字节 | 删除选择器数 | 保留风险项 |
| ---- | ---------- | ---------- | ------------ | ---------- |
|      |            |            |              |            |

## 5. 总体积变化

提供：

- WXSS 修改前总大小；
- WXSS 修改后总大小；
- 节省大小；
- 删除资源大小；
- 是否修改 `packOptions.ignore`；
- 主包真实大小是否已获取。

## 6. 样式引用完整性

提供：

- hover-class 使用但未定义数量；
- pressed 定义但未使用数量；
- WXML 引用已删除样式数量；
- 剩余 `:active` 数量。

## 7. 资源清理

列出删除和保留资源。

## 8. 回归测试

逐项标注：

- 通过；
- 失败；
- 未执行。

静态检索不得写为功能测试通过。

## 9. 审计结果

如果执行了开发者工具审计，填写：

- 总分；
- 性能；
- 体验；
- 最佳实践；
- 剩余失败项。

如果未执行，明确说明未执行。

## 10. 未完成事项

列出原因和下一步。

# 十二、禁止事项

1. 不得回滚前三阶段修改。
2. 不得批量正则删除 WXSS。
3. 不得根据审计覆盖率直接删除样式。
4. 不得大规模裁剪 `mp-html`。
5. 不得删除条件状态样式。
6. 不得删除错误、空状态和 loading 样式。
7. 不得删除动画状态而保留 JS 引用。
8. 不得删除动态路径资源。
9. 不得伪造包体积。
10. 不得伪造审计分数。
11. 不得声称执行了未执行的测试。
12. 不得使用 `:active` 实现点击态。
13. 不得新增无引用 pressed 样式。
14. 不得使用 `!important` 掩盖样式冲突。
15. 不得修改接口、路由和业务逻辑。
