#!/usr/bin/env node
/**
 * test-pomodoro-practice-stats.js
 *
 * 刷题时长纳入番茄钟学习统计的前端回归测试：
 *   1. _formatSession() 正确识别 practice（record_type === 'practice'）
 *   2. 刷题显示「刷题 · 科目」，状态「刷题」，class status-done
 *   3. 刷题时长格式化正确（18分钟 / X时Y分）
 *   4. mixed history（番茄 + 刷题混排）能正常格式化渲染
 *   5. record_key 跨来源不冲突（pomodoro:10 vs practice:10）
 *   6. 空状态文案已改为「开始专注或刷一组题吧」，history 使用 wx:key="record_key"
 *   7. practice.js doSubmit 确实把 session metadata 发给 /practice/batch-submit
 *   8. duration 在发请求之前锁定（finishedAt/duration 早于 api.post），
 *      不包含提交接口网络耗时
 *   9. 提交失败后冻结首次交卷快照，requestId / 答案 / 时长原样复用
 *  10. 待确认交卷持久化到本地，进程重启后可恢复同一 requestId
 *  11. 400/409 确定性拒绝停止无意义重试，结果页跳转失败不重新交卷
 *  12. 结果页正确率按已作答题计算，完成率冗余展示已移除，未完成题仍可识别
 *  13. 刷题页使用 page-container 消费真机侧滑/Android Back，并复用自定义退出确认
 *
 * Usage: node scripts/test-pomodoro-practice-stats.js
 * Exit code: 0 = pass, 1 = fail
 */
/* eslint-disable no-console */
const assert = require('assert')
const path = require('path')
const fs = require('fs')
const { spawnSync } = require('node:child_process')

let failed = 0
let passed = 0
function t(desc, fn) {
  try {
    fn()
    passed++
    console.log('  ✓ ' + desc)
  } catch (e) {
    failed++
    console.error('  ✗ ' + desc + ' - ' + e.message)
  }
}
function assertEqual(actual, expected, desc) {
  t(desc, () => assert.strictEqual(actual, expected))
}

// ── 加载 pomodoro-stats 页面模块 ────────────────────────────────────
global.wx = global.wx || {
  getWindowInfo() { return { windowWidth: 375, pixelRatio: 2 } },
  getDeviceInfo() { return { system: 'Node.js regression test' } },
  setNavigationBarColor() {},
  getStorageSync() { return null },
  setStorageSync() {},
  showLoading() {},
  hideLoading() {},
  showToast() {},
  createSelectorQuery() {
    return {
      in() { return this }, select() { return this },
      fields() { return this }, exec(cb) { cb && cb([]) },
    }
  },
}
const apiMockPath = path.resolve(__dirname, '../utils/api.js')
const storageMockPath = path.resolve(__dirname, '../utils/storage.js')
const configMockPath = path.resolve(__dirname, '../config.js')
const debugMockPath = path.resolve(__dirname, '../utils/debug.js')
require.cache = require.cache || {}
require.cache[apiMockPath] = { exports: { get: () => Promise.resolve({}), put: () => Promise.resolve({}) } }
require.cache[storageMockPath] = { exports: { KEYS: {}, get: () => null, set() {}, pomodoroTaskTypes: { labelForSession() { return '' } } } }
require.cache[configMockPath] = { exports: {} }
require.cache[debugMockPath] = { exports: { debugLog() {}, isDebugMode: () => false, saveDebugSnapshot() {} } }

let pageConfig = null
global.Page = function (cfg) { pageConfig = cfg }

const pagePath = path.join(__dirname, '../subpackages/productivity/pomodoro-stats/index.js')
require(pagePath)

function createInstance() {
  const inst = {}
  inst.data = JSON.parse(JSON.stringify(pageConfig.data))
  inst.setData = function (patch, cb) {
    Object.keys(patch).forEach(k => { inst.data[k] = patch[k] })
    if (typeof cb === 'function') cb.call(inst)
  }
  Object.keys(pageConfig).forEach(k => {
    if (k !== 'data' && k !== 'setData') inst[k] = pageConfig[k]
  })
  return inst
}

const inst = createInstance()
inst.data.themeMode = 'light'

console.log('\n=== _formatSession: practice 识别 ===')

const practiceSession = {
  record_key: 'practice:123',
  record_type: 'practice',
  id: 123,
  start_time: '2026-08-08T01:20:00', // 中国 09:20
  actual_duration: 1080,
  subject_name: '高等数学',
  subject_code: 'math2',
  subject_id: 1,
  status: 'completed',
}
const fmt = inst._formatSession(practiceSession)
assertEqual(fmt._subjectLabel, '刷题 · 高等数学', '刷题标签为「刷题 · 科目」')
assertEqual(fmt._statusLabel, '刷题', '刷题状态为「刷题」')
assertEqual(fmt._statusClass, 'status-done', '刷题状态 class 为 status-done')
assertEqual(fmt._time, '09:20', '刷题时间按中国时间显示')
assertEqual(fmt._duration, '18分钟', '刷题时长 1080s -> 18分钟')
assertEqual(fmt.record_key, 'practice:123', 'record_key 保留')

console.log('\n=== _formatSession: 番茄钟保持不变 ===')

const pomoSession = {
  record_key: 'pomodoro:1',
  record_type: 'pomodoro',
  id: 1,
  start_time: '2026-08-08T00:30:00', // 中国 08:30
  actual_duration: 1500,
  subject_name: '英语',
  subject_code: 'eng',
  subject_id: 2,
  preset: 'standard',
  status: 'completed',
}
const fmt2 = inst._formatSession(pomoSession)
assertEqual(fmt2._subjectLabel, '英语', '标准番茄标签为科目名')
assertEqual(fmt2._statusLabel, '完成', '标准番茄状态为「完成」')
assertEqual(fmt2._time, '08:30', '番茄时间按中国时间显示')
assertEqual(fmt2._duration, '25分钟', '番茄时长 1500s -> 25分钟')

const freeSession = {
  record_key: 'pomodoro:2',
  record_type: 'pomodoro',
  id: 2,
  start_time: '2026-08-08T00:30:00',
  actual_duration: 2520,
  subject_name: '政治',
  subject_id: 3,
  preset: 'free',
  status: 'completed',
}
const fmtFree = inst._formatSession(freeSession)
assertEqual(fmtFree._subjectLabel, '自由计时 · 政治', '自由计时标签保持「自由计时 · 科目」')

console.log('\n=== mixed history 渲染 ===')

const mixed = [practiceSession, pomoSession, freeSession].map(s => inst._formatSession(s))
assertEqual(mixed.length, 3, '混排 3 条')
assertEqual(mixed[0]._subjectLabel, '刷题 · 高等数学', '刷题在最前')
assertEqual(mixed[0]._statusLabel, '刷题', '刷题状态')
assertEqual(mixed[1]._statusLabel, '完成', '番茄状态')

console.log('\n=== _formatSession: 今日复习计入刷题时长 ===')

const fmtReview = inst._formatSession({
  record_key: 'review:7',
  record_type: 'review',
  id: 7,
  start_time: '2026-08-08T02:00:00', // 中国 10:00
  actual_duration: 600,
  subject_name: '数据结构',
  subject_id: 4,
  status: 'completed',
})
assertEqual(fmtReview._subjectLabel, '复习 · 数据结构', '复习标签为「复习 · 科目」')
assertEqual(fmtReview._statusLabel, '复习', '复习状态为「复习」')
assertEqual(fmtReview._statusClass, 'status-done', '复习状态 class 为 status-done')
assertEqual(fmtReview._iconType, 'practice', '复习沿用刷题图标')
assertEqual(fmtReview._duration, '10分钟', '复习时长 600s -> 10分钟')

console.log('\n=== record_key 不冲突 ===')

const k1 = inst._formatSession({ record_key: 'pomodoro:10', record_type: 'pomodoro', id: 10, start_time: '2026-08-08T01:00:00', actual_duration: 600, subject_name: '数学', subject_id: 1, preset: 'standard', status: 'completed' })
const k2 = inst._formatSession({ record_key: 'practice:10', record_type: 'practice', id: 10, start_time: '2026-08-08T01:00:00', actual_duration: 600, subject_name: '数学', subject_id: 1, status: 'completed' })
t('两张表相同 id 的 record_key 不同', () => assert.notStrictEqual(k1.record_key, k2.record_key))
t('record_key 采用来源前缀，包含 id', () => {
  assert.strictEqual(k1.record_key, 'pomodoro:10')
  assert.strictEqual(k2.record_key, 'practice:10')
})

console.log('\n=== WXML 文案与 key ===')

const wxml = fs.readFileSync(path.join(__dirname, '../subpackages/productivity/pomodoro-stats/index.wxml'), 'utf8')
t('history 循环使用 wx:key="record_key"', () => {
  assert.ok(wxml.indexOf('wx:key="record_key"') >= 0, 'WXML 必须用 record_key 作为 wx:key')
  assert.ok(wxml.indexOf('wx:key="id"') === -1, 'WXML 不得再使用 wx:key="id"（两表 id 冲突）')
})
t('空状态文案已通用化（不再只提番茄钟）', () => {
  assert.ok(wxml.indexOf('开始专注或刷一组题吧') >= 0, '空状态应提示专注或刷题')
  assert.ok(wxml.indexOf('开始一个番茄钟吧') === -1, '空状态不应只建议开始番茄钟')
})
t('跨统计日提示不再特指「专注」', () => {
  assert.ok(wxml.indexOf('部分时长来自跨统计日（前一统计日开始）') >= 0)
  assert.ok(wxml.indexOf('部分时长来自跨统计日的专注') === -1)
})

console.log('\n=== 刷题提交、计时、恢复与结果的当前行为契约 ===')

// These behaviors now span controllers and adapters; exercise their contracts
// instead of requiring their implementation text to remain inside practice.js.
const practiceContractFiles = [
  '../tests/test-practice-page-contracts.js',
  '../tests/test-practice-module-boundaries.js',
  '../tests/test-practice-submit-adapter-integration.js',
  '../tests/test-practice-submit-entry-controller.js',
  '../tests/test-practice-submit-flow-controller.js',
  '../tests/test-practice-submit-error-controller.js',
  '../tests/test-practice-submit-success-controller.js',
  '../tests/test-practice-session-timer-controller.js',
  '../tests/test-practice-monotonic-clock.js',
  '../tests/test-practice-lifecycle-controller.js',
  '../tests/test-practice-pending-submission-controller.js',
  '../tests/test-practice-submit-session-builder.js',
  '../tests/test-practice-submit-payload-builder.js',
  '../tests/test-practice-submission-snapshot-builder.js',
  '../tests/test-practice-question-load-state.js',
  '../tests/test-practice-question-load-wiring.js',
  '../tests/test-practice-answer-classification.js',
  '../tests/test-practice-result-counts.js',
  '../tests/test-practice-payload-mapper.js',
  '../tests/test-practice-result-recovered-payload.js',
  '../tests/test-practice-result-tips.js',
  '../tests/test-practice-result-url-builder.js',
  '../tests/test-practice-exit-guard-controller.js',
  '../tests/test-practice-exit-request-controller.js',
  '../tests/test-storage-facade-contract.js',
].map(filename => path.resolve(__dirname, filename))
t('当前刷题职责与页面连接的行为回归', () => {
  const result = spawnSync(process.execPath, ['--test', ...practiceContractFiles], {
    cwd: path.resolve(__dirname, '..'),
    stdio: 'inherit',
  })
  if (result.error) throw result.error
  assert.strictEqual(result.status, 0, `刷题行为回归失败，signal=${result.signal || ''}`)
})

const resultJs = fs.readFileSync(path.join(__dirname, '../subpackages/study/practice-result/index.js'), 'utf8')
const resultWxml = fs.readFileSync(path.join(__dirname, '../subpackages/study/practice-result/index.wxml'), 'utf8')
const recoveryQuestionsBuilder = fs.readFileSync(path.join(__dirname, '../subpackages/study/practice/utils/recovery-questions-builder.js'), 'utf8')

t('结果模板区分未完成并移除冗余完成率', () => {
  assert.ok(resultWxml.includes('未完成'))
  assert.ok(!resultWxml.includes('完成率 {{completionPct}}%'))
})

t('刷题模板将系统返回交给页面退出守卫', () => {
  const template = fs.readFileSync(path.join(__dirname, '../subpackages/study/practice/practice.wxml'), 'utf8')
  assert.ok(template.includes('<page-container'))
  assert.ok(template.includes('show="{{practiceExitGuardVisible}}"'))
  assert.ok(template.includes('bind:afterleave="onPracticeExitGuardLeave"'))
})

t('趋势接口失败不伪造历史 0 数据，未完成题不显示全部答对', () => {
  assert.strictEqual(resultJs.indexOf('buildFallbackTrend'), -1, '不得生成虚假的历史趋势 fallback')
  assert.ok(resultJs.indexOf('trendAvailable: false') >= 0, '趋势不可用需有明确状态')
  assert.ok(resultWxml.indexOf('趋势暂不可用') === -1 || resultJs.indexOf('趋势暂不可用') >= 0, '趋势失败需明确提示不可用')
  assert.ok(resultWxml.indexOf('partialCount > 0') >= 0, '未完成题存在时不得显示本组全部答对')
})

t('结果缓存失败可通过同一 requestId 重放 canonical response 恢复', () => {
  const resultUrlBuilder = fs.readFileSync(path.join(__dirname, '../subpackages/study/practice/utils/result-url-builder.js'), 'utf8')
  assert.ok(resultUrlBuilder.indexOf('_recover=${resultCacheStored') >= 0 || resultUrlBuilder.indexOf('_recover=') >= 0, '缓存失败结果页需带恢复标记')
  assert.ok(resultJs.indexOf('recoverSubmittedResult') >= 0, '结果页需支持恢复已提交结果')
  assert.ok(resultJs.indexOf("api.post('/practice/batch-submit'") >= 0, '结果恢复需重放同一 batch-submit')
  assert.ok(resultJs.indexOf('submission.batchToken') >= 0, '结果恢复需复用原 batch_token')
})


t('结果恢复保留完整题目展示字段', () => {
  const recoveredPayloadBuilder = fs.readFileSync(
    path.join(__dirname, '../subpackages/study/practice-result/utils/recovered-payload-builder.js'),
    'utf8'
  )
  assert.ok(recoveryQuestionsBuilder.indexOf('content: (q && q.content) || {}') >= 0, 'pending snapshot 需保留完整题目 content')
  assert.ok(recoveryQuestionsBuilder.indexOf('options: (q && q.options) || null') >= 0, 'pending snapshot 需保留选择题选项')
  assert.ok(recoveryQuestionsBuilder.indexOf('image_url: (q && q.image_url) || null') >= 0, 'pending snapshot 需保留题目图片')
  assert.ok(recoveredPayloadBuilder.indexOf('content: q.content ||') >= 0, '结果恢复需重建 content')
  assert.ok(recoveredPayloadBuilder.indexOf('options: q.options || null') >= 0, '结果恢复需重建 options')
})

console.log('\n==============================')
console.log('Passed:', passed, ' Failed:', failed)
console.log('==============================\n')
if (failed > 0) process.exit(1)
