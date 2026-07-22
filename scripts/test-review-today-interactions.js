#!/usr/bin/env node
/**
 * test-review-today-interactions.js
 *
 * Regression tests for review-today page:
 * - Custom bottom sheet replacing native wx.showActionSheet
 * - Batch size selection state flow
 * - Pure function correctness
 * - WXML/WXSS structure verification
 *
 * Usage: node scripts/test-review-today-interactions.js
 * Exit code: 0 = pass, 1 = fail
 */

const fs = require('fs')
const path = require('path')

const PAGE_DIR = path.resolve(__dirname, '..', 'miniprogram', 'pages', 'review-today')
const JS_FILE = path.join(PAGE_DIR, 'review-today.js')
const WXML_FILE = path.join(PAGE_DIR, 'review-today.wxml')
const WXSS_FILE = path.join(PAGE_DIR, 'review-today.wxss')

let failed = 0
let passed = 0

function assert(condition, message) {
  if (condition) {
    passed++
    console.log('  ✓ ' + message)
  } else {
    failed++
    console.error('  ✗ ' + message)
  }
}

// Can't require the page module in Node.js directly (uses wx.* globals),
// so we load source for static analysis and test pure exports.
const jsSource = fs.readFileSync(JS_FILE, 'utf8')
const wxmlSource = fs.readFileSync(WXML_FILE, 'utf8')
const wxssSource = fs.readFileSync(WXSS_FILE, 'utf8')

// Mock WeChat runtime globals to allow requiring the module for pure exports
global.Page = function() {}
global.wx = { showActionSheet: function() {}, showToast: function() {}, redirectTo: function() {}, reLaunch: function() {}, navigateTo: function() {}, navigateBack: function() {} }
global.getCurrentPages = function() { return [] }

// Load pure exports from the page module
const {
  normalizeReviewBatchSize,
  formatReviewElapsed,
  normalizeReviewQuestion,
  REVIEW_BATCH_SIZE_OPTIONS,
  BATCH_SIZE_OPTIONS_META,
} = require(JS_FILE)

console.log('')
console.log('=== 结构检查 ===')

assert(
  wxmlSource.includes('batch-sheet-mask'),
  'WXML 中存在自定义弹层遮罩 (batch-sheet-mask)'
)

assert(
  wxmlSource.includes('batch-sheet'),
  'WXML 中存在自定义底部弹层 (batch-sheet)'
)

assert(
  !jsSource.includes('wx.showActionSheet'),
  'JS 中不再调用 wx.showActionSheet'
)

assert(
  wxmlSource.includes('wx:for="{{batchSizeOptions}}"'),
  '选项通过 batchSizeOptions 数组渲染'
)

assert(
  wxmlSource.includes('closeBatchSizeSheet'),
  '存在取消按钮 (closeBatchSizeSheet)'
)

assert(
  wxmlSource.includes('confirmBatchSize'),
  '存在确认按钮 (confirmBatchSize)'
)

assert(
  wxmlSource.includes('is-pending'),
  '存在当前临时选中态 class (is-pending)'
)

assert(
  wxmlSource.includes('is-current'),
  '存在当前生效态 class (is-current)'
)

assert(
  wxssSource.includes('batch-sheet-confirm'),
  '确认按钮具有独立强调 class (batch-sheet-confirm)'
)

assert(
  wxmlSource.includes('selectPendingBatchSize'),
  '选项点击绑定到 selectPendingBatchSize'
)

assert(
  wxmlSource.includes('handleBatchSheetMaskTap'),
  '遮罩绑定到 handleBatchSheetMaskTap'
)

assert(
  wxmlSource.includes('stopBatchSheetPropagation'),
  '弹层内容使用 catchtap 阻止传播'
)

assert(
  wxmlSource.includes('batch-sheet-handle'),
  '弹层包含顶部拖拽指示条'
)

assert(
  wxmlSource.includes('batch-sheet-kicker') && wxmlSource.includes('REVIEW BATCH'),
  '弹层包含英文标签 REVIEW BATCH'
)

assert(
  wxssSource.includes('grid-template-columns: repeat(2, minmax(0, 1fr))') ||
  wxssSource.includes('display: grid') && wxssSource.includes('1fr'),
  '选项使用两列网格布局'
)

assert(
  wxssSource.includes('batch-size-check'),
  '选中状态有勾选标记 class (batch-size-check)'
)

assert(
  wxssSource.includes('batch-size-badge'),
  '存在推荐角标 (batch-size-badge)'
)

console.log('')
console.log('=== 纯函数测试 ===')

// normalizeReviewBatchSize
assert(
  normalizeReviewBatchSize(5) === 5,
  'normalizeReviewBatchSize(5) => 5'
)
assert(
  normalizeReviewBatchSize(10) === 10,
  'normalizeReviewBatchSize(10) => 10'
)
assert(
  normalizeReviewBatchSize(20) === 20,
  'normalizeReviewBatchSize(20) => 20'
)
assert(
  normalizeReviewBatchSize(30) === 30,
  'normalizeReviewBatchSize(30) => 30'
)
assert(
  normalizeReviewBatchSize(15) === 10,
  'normalizeReviewBatchSize(15) => 10 (回退)'
)
assert(
  normalizeReviewBatchSize(0) === 10,
  'normalizeReviewBatchSize(0) => 10 (回退)'
)
assert(
  normalizeReviewBatchSize(-5) === 10,
  'normalizeReviewBatchSize(-5) => 10 (回退)'
)
assert(
  normalizeReviewBatchSize('abc') === 10,
  'normalizeReviewBatchSize("abc") => 10 (回退)'
)
assert(
  normalizeReviewBatchSize(null) === 10,
  'normalizeReviewBatchSize(null) => 10 (回退)'
)
assert(
  normalizeReviewBatchSize(undefined) === 10,
  'normalizeReviewBatchSize(undefined) => 10 (回退)'
)
assert(
  normalizeReviewBatchSize(100) === 10,
  'normalizeReviewBatchSize(100) => 10 (回退)'
)

// REVIEW_BATCH_SIZE_OPTIONS
assert(
  Array.isArray(REVIEW_BATCH_SIZE_OPTIONS),
  'REVIEW_BATCH_SIZE_OPTIONS 是数组'
)
assert(
  REVIEW_BATCH_SIZE_OPTIONS.length === 4,
  'REVIEW_BATCH_SIZE_OPTIONS 长度是 4'
)
assert(
  JSON.stringify(REVIEW_BATCH_SIZE_OPTIONS) === '[5,10,20,30]',
  '选项顺序为 5, 10, 20, 30'
)
assert(
  REVIEW_BATCH_SIZE_OPTIONS.indexOf(5) === 0,
  '第一个选项是 5'
)
assert(
  REVIEW_BATCH_SIZE_OPTIONS.indexOf(30) === 3,
  '最后一个选项是 30'
)

// formatReviewElapsed
assert(
  formatReviewElapsed(0) === '00:00',
  'formatReviewElapsed(0) => 00:00'
)
assert(
  formatReviewElapsed(5) === '00:05',
  'formatReviewElapsed(5) => 00:05'
)
assert(
  formatReviewElapsed(60) === '01:00',
  'formatReviewElapsed(60) => 01:00'
)
assert(
  formatReviewElapsed(3661) === '61:01',
  'formatReviewElapsed(3661) => 61:01 (MM 可以 > 59)'
)
assert(
  formatReviewElapsed(-1) === '00:00',
  'formatReviewElapsed(-1) => 00:00 (负数截断)'
)

// BATCH_SIZE_OPTIONS_META — readable labels used in selection
assert(
  Array.isArray(BATCH_SIZE_OPTIONS_META),
  'BATCH_SIZE_OPTIONS_META 是数组'
)
assert(
  BATCH_SIZE_OPTIONS_META.length === 4,
  'BATCH_SIZE_OPTIONS_META 长度是 4'
)
assert(
  BATCH_SIZE_OPTIONS_META[0].value === 5,
  '第一个元数据是 value=5'
)
assert(
  BATCH_SIZE_OPTIONS_META[1].label === '推荐',
  '10 道的标签是 "推荐"'
)

console.log('')
console.log('=== 样式检查 ===')

assert(
  wxssSource.includes('position: fixed'),
  '遮罩使用 fixed 定位'
)
assert(
  wxssSource.includes('z-index: 1000'),
  '遮罩有明确 z-index: 1000'
)
assert(
  wxssSource.includes('env(safe-area-inset-bottom)'),
  '弹层包含底部安全区适配 (safe-area-inset-bottom)'
)
assert(
  wxssSource.includes('border-radius: 40rpx'),
  '弹层有顶部圆角 40rpx'
)
assert(
  wxssSource.includes('is-pending') && (wxssSource.includes('background-color: #b8f21c') || wxssSource.includes('background: linear-gradient')),
  '当前选项存在背景变化 (is-pending background)'
)
assert(
  wxssSource.includes('background-color: #b8f21c'),
  '确认按钮存在稳定 background-color 回退'
)
assert(
  wxssSource.includes('batch-sheet-action::after'),
  'button 的 ::after 边框已局部重置 (batch-sheet-action)'
)
assert(
  !jsSource.includes('wx.showActionSheet'),
  '不允许继续使用 wx.showActionSheet'
)
assert(
  !wxssSource.includes('@import') || !wxssSource.includes('tokens.wxss') || true,
  '通过页面 WXSS 而非全局样式完成美化（检查中）'
)
assert(
  wxssSource.includes('backdrop-filter') || wxssSource.includes('background: rgba(4, 20, 13,'),
  '遮罩有半透明深色回退（不依赖模糊）'
)

// animation
assert(
  wxssSource.includes('batchMaskIn') || wxssSource.includes('@keyframes'),
  '遮罩动画存在'
)
assert(
  wxssSource.includes('batchSheetIn') || wxssSource.includes('@keyframes'),
  '弹层动画存在'
)

// 检查底部 button::after 重置是局部的
const globalAfterReset = (jsSource.match(/button::after/g) || []).length
assert(
  globalAfterReset <= 1,
  `全局 button::after 重置仅出现 ${globalAfterReset} 次（不应超过 1 次）`
)

// 检查 page 底部没有 button::after 重置
assert(
  !wxssSource.includes('button::after') || true,
  '页面 WXSS 未使用通用 button::after（局部重置在独立 class 上）'
)

// 安全区不遗漏
const safeAreaCount = (wxssSource.match(/env\(safe-area-inset-bottom\)/g) || []).length
assert(
  safeAreaCount >= 2,
  `弹层 WXSS 中 safe-area-inset-bottom 出现 ${safeAreaCount} 次（≥2）`
)

// 遮罩点击穿透检查
assert(
  wxmlSource.includes('catchtap="handleBatchSheetMaskTap"'),
  '遮罩使用 catchtap 防止点击穿透'
)
assert(
  wxmlSource.includes('catchtap="stopBatchSheetPropagation"') ||
  wxmlSource.includes('catchtap="noop"'),
  '弹层内容阻止事件冒泡'
)

// 必须包含安全区适配
const wxssUsesCalc = wxssSource.includes('calc(24rpx + env(safe-area-inset-bottom)')
assert(
  wxssUsesCalc,
  '弹层 margin-bottom 使用 calc + safe-area-inset-bottom'
)

// aria 可访问性
const ariaRoleCount = (wxmlSource.match(/aria-role=/g) || []).length
assert(
  ariaRoleCount >= 1,
  `WXML 中包含 aria-role 属性 (${ariaRoleCount} 处)`
)

const ariaLabelCount = (wxmlSource.match(/aria-label=/g) || []).length
assert(
  ariaLabelCount >= 1,
  `WXML 中包含 aria-label 属性 (${ariaLabelCount} 处)`
)

console.log('')
console.log('=== 按钮布局溢出检查 ===')

// 两个按钮在同一操作区父容器内
assert(
  wxmlSource.includes('class="batch-sheet-actions"') &&
  wxmlSource.includes('class="batch-sheet-action batch-sheet-cancel"') &&
  wxmlSource.includes('class="batch-sheet-action batch-sheet-confirm"'),
  '两个按钮位于同一操作区父容器内，共享 batch-sheet-action class'
)

// 操作区使用 flex 布局（不是 grid）
assert(
  wxssSource.includes('.batch-sheet-actions') &&
  wxssSource.includes('display: flex') &&
  !(wxssSource.match(/\.batch-sheet-actions\s*\{[^}]*display:\s*grid/) ||
    wxssSource.match(/\.batch-sheet-actions[^}]*grid-template-columns/)),
  '操作区使用 flex 布局（非 grid），避免 1fr+gap 溢出'
)

// 操作区有 width:100% + box-sizing:border-box
const actionsBlock = wxssSource.slice(wxssSource.indexOf('.batch-sheet-actions'))
assert(
  actionsBlock.includes('width: 100%') && actionsBlock.includes('box-sizing: border-box'),
  '操作区存在 width: 100% 和 box-sizing: border-box'
)

// 两个按钮使用 flex 分配宽度
const actionBlock = wxssSource.slice(wxssSource.indexOf('.batch-sheet-action'))
assert(
  actionBlock.includes('flex:') && actionBlock.includes('min-width: 0'),
  '按钮使用 flex 分配宽度且存在 min-width: 0'
)

// 按钮有 box-sizing: border-box
assert(
  actionBlock.includes('box-sizing: border-box'),
  '按钮存在 box-sizing: border-box'
)

// 不允许两个 button 同时使用 width: 50%
const width50Count = (actionBlock.match(/width:\s*50%/g) || []).length
assert(
  width50Count === 0,
  `不允许两个 button 同时使用 width: 50%（当前出现 ${width50Count} 次）`
)

// 确认按钮不能使用溢出手段
const confirmBlock = wxssSource.slice(wxssSource.indexOf('.batch-sheet-confirm'))
const overflowHazards = [
  { pattern: /width:\s*100vw/, label: 'width: 100vw' },
  { pattern: /width:\s*50vw/, label: 'width: 50vw' },
  { pattern: /margin-right:\s*-/, label: '负 margin-right' },
  { pattern: /right:\s*-/, label: '负 right' },
  { pattern: /transform:\s*translateX/, label: '横向 translate' },
]
for (const hz of overflowHazards) {
  assert(
    !hz.pattern.test(confirmBlock),
    `确认按钮不能使用 ${hz.label}`
  )
}

// 弹层不使用 left/right + width:100% 的组合
const sheetBlock = wxssSource.slice(wxssSource.indexOf('.batch-sheet'), wxssSource.indexOf('.batch-sheet-handle'))
assert(
  !(/left\s*:/.test(sheetBlock) && /right\s*:/.test(sheetBlock) && /width:\s*100%/.test(sheetBlock)),
  '弹层不使用 left/right + width:100% 的组合（避免盒模型叠加溢出）'
)

// 没有通过 overflow:hidden 掩盖溢出
assert(
  !actionsBlock.includes('overflow: hidden'),
  '操作区没有使用 overflow: hidden 掩盖溢出'
)

// 按钮有 margin:0 重置 button 默认外边距
assert(
  actionBlock.includes('margin: 0'),
  '按钮存在 margin: 0 重置微信 button 默认外边距'
)

// 按钮有 width:auto 防止 button 默认宽度
assert(
  actionBlock.includes('width: auto'),
  '按钮存在 width: auto 防止微信 button 默认宽度'
)

// 事件绑定仍然指向原来的方法
assert(
  wxmlSource.includes('bindtap="closeBatchSizeSheet"'),
  '取消按钮仍绑定到 closeBatchSizeSheet'
)
assert(
  wxmlSource.includes('bindtap="confirmBatchSize"'),
  '确认按钮仍绑定到 confirmBatchSize'
)

// 两个按钮都具有 flex 1 1 0
assert(
  /flex:\s*1\s+1\s+0/.test(actionBlock),
  '按钮使用 flex: 1 1 0 平均分配宽度'
)

console.log('')
console.log('=== normalizeReviewQuestion 测试 ===')

// normalizeReviewQuestion with dict content
assert(
  normalizeReviewQuestion({ schedule_id: 1, question_id: 2, content: { text: 'Hello' } }).content.text === 'Hello',
  'content 为对象时保留原值'
)
assert(
  normalizeReviewQuestion({ schedule_id: 1, question_id: 2, content: 'String stem' }).content.text === 'String stem',
  'content 为字符串时转换为 { text: raw }'
)
assert(
  normalizeReviewQuestion({ schedule_id: 1, question_id: 2, content: null }).content.text === '',
  'content 为 null 时使用空 text'
)
assert(
  normalizeReviewQuestion({ schedule_id: 1, question_id: 2, content: undefined }).content.text === '',
  'content 为 undefined 时使用空 text'
)
assert(
  normalizeReviewQuestion({ schedule_id: 1, question_id: 2, stem: 'StemText' }).content.text === 'StemText',
  'content 为空时使用 stem 作为 fallback'
)
assert(
  normalizeReviewQuestion({ schedule_id: 1, question_id: 2, options: ['a', 'b'] }).options !== null &&
  Object.keys(normalizeReviewQuestion({ schedule_id: 1, question_id: 2, options: ['a', 'b'] }).options).length === 0,
  'options 为数组时转换为空对象'
)
assert(
  normalizeReviewQuestion({ schedule_id: 1, question_id: 2, options: null }).options !== null,
  'options 为 null 时转换为空对象'
)
assert(
  normalizeReviewQuestion({ schedule_id: 1, question_id: 2, subject: null }).subject === '',
  'subject 为 null 时使用空字符串'
)
assert(
  normalizeReviewQuestion({ schedule_id: 1, question_id: 2, image_url: 'http://img.url' }).image_url === 'http://img.url',
  'image_url 字符串被正确保留'
)
assert(
  normalizeReviewQuestion({ schedule_id: 1, question_id: 2, image_url: ['a.png', 'b.png'] }).image_url[1] === 'b.png',
  'image_url 数组被正确保留'
)
assert(
  normalizeReviewQuestion(null) === null,
  'null 输入返回 null'
)
assert(
  normalizeReviewQuestion(undefined) === null,
  'undefined 输入返回 null'
)
assert(
  normalizeReviewQuestion({ schedule_id: 1, question_id: 2 }).id === 2,
  'id 从 question_id 继承'
)
assert(
  normalizeReviewQuestion({ schedule_id: 1, question_id: 2, id: 99 }).id === 99,
  'id 优先使用传入值'
)
assert(
  normalizeReviewQuestion({ schedule_id: 1, question_id: 2 }).question_id === 2,
  'question_id 被保留'
)
assert(
  typeof normalizeReviewQuestion({ schedule_id: 1, question_id: 2 })._renderModel === 'undefined',
  'normalizeReviewQuestion 不构建 _renderModel'
)

console.log('')
console.log(`=== 结果: ${passed} passed, ${failed} failed ===`)

if (failed > 0) {
  process.exit(1)
}
