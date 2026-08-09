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
 *   9. 提交失败后恢复计时，requestId 复用（重试不会产生重复 session 上报）
 *
 * Usage: node scripts/test-pomodoro-practice-stats.js
 * Exit code: 0 = pass, 1 = fail
 */
/* eslint-disable no-console */
const assert = require('assert')
const path = require('path')
const fs = require('fs')

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
require.cache[storageMockPath] = { exports: { KEYS: {}, get: () => null, set() {} } }
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

console.log('\n=== practice.js: session 上报 / 时长锁定 / 失败恢复 ===')

const js = fs.readFileSync(path.join(__dirname, '../subpackages/study/practice/practice.js'), 'utf8')

t('doSubmit 把 session 元数据发给 /practice/batch-submit', () => {
  const doSubmit = extractMethod(js, 'doSubmit')
  assert.ok(doSubmit.indexOf("'/practice/batch-submit'") >= 0, '必须 POST 到 batch-submit')
  assert.ok(doSubmit.indexOf('session,') >= 0, '请求体必须携带 session')
  assert.ok(doSubmit.indexOf('request_id: requestId') >= 0, 'session.request_id')
  assert.ok(doSubmit.indexOf('subject_id: selectedSubjectId') >= 0, 'session.subject_id')
  assert.ok(doSubmit.indexOf('mode: this.data.selectedMode') >= 0, 'session.mode')
  assert.ok(doSubmit.indexOf('started_at: new Date(startTime).toISOString()') >= 0, 'session.started_at 用 ISO')
  assert.ok(doSubmit.indexOf('finished_at: new Date(finishedAt).toISOString()') >= 0, 'session.finished_at 用 ISO')
  assert.ok(doSubmit.indexOf('duration_sec: duration') >= 0, 'session.duration_sec')
})

t('duration 在发请求之前锁定（不包含提交接口网络耗时）', () => {
  const doSubmit = extractMethod(js, 'doSubmit')
  // duration 用 finishedAt 冻结，并扣除切后台/跳转他页的 backgroundMs（仅前台计时）
  const durIdx = doSubmit.indexOf('const duration = Math.max(0, Math.floor(')
  const bgIdx = doSubmit.indexOf('(finishedAt - startTime - (this._practiceSession.backgroundMs || 0)) / 1000')
  const postIdx = doSubmit.indexOf("api.post('/practice/batch-submit'")
  const finishedAtIdx = doSubmit.indexOf('const finishedAt = Date.now()')
  assert.ok(durIdx >= 0, '必须用 finishedAt 冻结时长')
  assert.ok(finishedAtIdx >= 0 && durIdx > finishedAtIdx, 'finishedAt 在 duration 之前')
  assert.ok(bgIdx > durIdx, 'duration 需扣除后台挂起时间（只统计前台学习时长）')
  assert.ok(durIdx >= 0 && postIdx >= 0 && durIdx < postIdx, 'duration 必须早于 api.post（网络耗时不计入）')
})

t('不再在提交成功后用 Date.now() 重算 duration', () => {
  const doSubmit = extractMethod(js, 'doSubmit')
  // 旧实现：duration = Math.floor((Date.now() - startTime) / 1000) 出现在提交成功之后
  const reassignIdx = doSubmit.indexOf('duration = Math.floor((Date.now() - startTime) / 1000)')
  assert.strictEqual(reassignIdx, -1, '不应在提交成功后重算 duration（会混入网络耗时）')
})

t('提交失败恢复计时 + requestId 复用', () => {
  const doSubmit = extractMethod(js, 'doSubmit')
  assert.ok(doSubmit.indexOf('this._startTimer()') >= 0, '失败后恢复计时器')
  assert.ok(doSubmit.indexOf('this.setData({ submitting: false })') >= 0, '失败后解除 submitting')
  assert.ok(doSubmit.indexOf('this._practiceSession.requestId = requestId') >= 0, 'requestId 持久化供重试复用')
})

t('切后台/跳转他页的时长不计入刷题时长（onHide/onShow 前台计时）', () => {
  const onHide = extractMethod(js, 'onHide')
  const onShow = extractMethod(js, 'onShow')
  assert.ok(onHide.indexOf('_bgStartAt = Date.now()') >= 0, 'onHide 记录离开时间点')
  assert.ok(onShow.indexOf('s.backgroundMs') >= 0, 'onShow 结算 backgroundMs')
  assert.ok(onShow.indexOf('_bgStartAt = null') >= 0, '结算后清空离开标记')
  // 只统计前台：startTime 未开始（0）时不记录离开，避免首帧误扣
  assert.ok(onHide.indexOf('s.startTime') >= 0 && onShow.indexOf('s.startTime') >= 0, '未开始时忽略，避免误扣')
})

console.log('\n==============================')
console.log('Passed:', passed, ' Failed:', failed)
console.log('==============================\n')
if (failed > 0) process.exit(1)

// ── Helper: extract a method body from Page({...}) by name ──
function extractMethod(src, name) {
  const patterns = [
    new RegExp('(?:^|,)\\s*(?:async\\s+)?' + name + '\\s*\\(', 'm'),
    new RegExp('(?:^|\\s)' + name + '\\s*:\\s*function\\s*\\(', 'm'),
  ]
  let startMatch = null
  for (let i = 0; i < patterns.length; i++) {
    startMatch = src.match(patterns[i])
    if (startMatch) break
  }
  if (!startMatch) return ''
  let j = startMatch.index + startMatch[0].length
  while (j < src.length && src[j] !== '{') j++
  if (j >= src.length) return ''
  j++
  let braceCount = 1
  let result = src.substring(startMatch.index, j)
  while (j < src.length && braceCount > 0) {
    const ch = src[j]
    result += ch
    if (ch === '{') braceCount++
    else if (ch === '}') braceCount--
    j++
  }
  return result
}
