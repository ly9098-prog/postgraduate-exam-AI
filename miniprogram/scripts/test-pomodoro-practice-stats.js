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
 *  12. 结果页正确率按已作答题计算，并单独展示完成率/未完成题
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
  assert.ok(doSubmit.indexOf('mode: this._practiceSession.batchMode || this.data.selectedMode') >= 0, 'session.mode')
  assert.ok(doSubmit.indexOf('this._practiceSession.startedAtMs') >= 0, 'session.started_at 使用服务器时钟校准后的绝对时间')
  assert.ok(doSubmit.indexOf('finishedAtMs = api.now()') >= 0, 'session.finished_at 使用 api.now() 校准服务器时钟')
  assert.ok(doSubmit.indexOf('duration_sec: duration') >= 0, 'session.duration_sec')
})

t('duration 在发请求之前锁定（不包含提交接口网络耗时）', () => {
  const doSubmit = extractMethod(js, 'doSubmit')
  // duration 用 finishedAt 冻结，并扣除切后台/跳转他页的 backgroundMs（仅前台计时）
  const durIdx = doSubmit.indexOf('const duration = Math.max(0, Math.floor(')
  const bgIdx = doSubmit.indexOf('(finishedMonoMs - activeStartedMonoMs - (this._practiceSession.backgroundMs || 0)) / 1000')
  const postIdx = doSubmit.indexOf("api.post('/practice/batch-submit'")
  const finishedAtIdx = doSubmit.indexOf('const finishedMonoMs = _monotonicNow()')
  assert.ok(durIdx >= 0, '必须用单调时钟冻结时长')
  assert.ok(finishedAtIdx >= 0 && durIdx > finishedAtIdx, 'finishedMonoMs 在 duration 之前')
  assert.ok(bgIdx > durIdx, 'duration 需扣除后台挂起时间（只统计前台学习时长）')
  assert.ok(durIdx >= 0 && postIdx >= 0 && durIdx < postIdx, 'duration 必须早于 api.post（网络耗时不计入）')
})

t('练习耗时使用单调时钟，设备校时不改变 duration', () => {
  assert.ok(js.indexOf('wx.getPerformance') >= 0, '应优先使用微信单调 performance 时钟')
  const timer = extractMethod(js, '_startTimer')
  assert.ok(timer.indexOf('_monotonicNow()') >= 0, '总时长计时必须使用单调时钟')
  const settle = extractMethod(js, '_settleQuestionTime')
  assert.ok(settle.indexOf('_monotonicNow()') >= 0, '单题计时必须使用单调时钟')
})

t('不再在提交成功后用 Date.now() 重算 duration', () => {
  const doSubmit = extractMethod(js, 'doSubmit')
  // 旧实现：duration = Math.floor((Date.now() - startTime) / 1000) 出现在提交成功之后
  const reassignIdx = doSubmit.indexOf('duration = Math.floor((Date.now() - startTime) / 1000)')
  assert.strictEqual(reassignIdx, -1, '不应在提交成功后重算 duration（会混入网络耗时）')
})

t('提交失败冻结 submission snapshot + requestId 复用', () => {
  const doSubmit = extractMethod(js, 'doSubmit')
  assert.strictEqual(doSubmit.indexOf('this._startTimer()'), -1, '提交失败后不应恢复学习计时')
  assert.ok(doSubmit.indexOf('this._practiceSession.submissionSnapshot = submission') >= 0, '首次交卷必须冻结 submission snapshot')
  assert.ok(doSubmit.indexOf('answers: submission.answers') >= 0, '重试必须复用冻结答案')
  assert.ok(doSubmit.indexOf('session: submission.session') >= 0, '重试必须复用冻结会话时长')
  assert.ok(doSubmit.indexOf('this.setData({ submitting: false })') >= 0, '失败后仅解除 submitting 以允许重试')
  assert.ok(doSubmit.indexOf('this._practiceSession.requestId = requestId') >= 0, 'requestId 持久化供重试复用')
})

t('切后台/跳转他页的时长不计入刷题时长（onHide/onShow 前台计时）', () => {
  const onHide = extractMethod(js, 'onHide')
  const onShow = extractMethod(js, 'onShow')
  assert.ok(onHide.indexOf('_backgroundStartedMonoMs = _monotonicNow()') >= 0, 'onHide 用单调时钟记录离开时间点')
  assert.ok(onShow.indexOf('s.backgroundMs') >= 0, 'onShow 结算 backgroundMs')
  assert.ok(onShow.indexOf('_backgroundStartedMonoMs = null') >= 0, '结算后清空离开标记')
  // 只统计前台：startTime 未开始（0）时不记录离开，避免首帧误扣
  assert.ok(onHide.indexOf('s.activeStartedMonoMs') >= 0 && onShow.indexOf('s.activeStartedMonoMs') >= 0, '未开始时忽略，避免误扣')
})

t('待确认交卷持久化，支持进程重启后恢复同一 requestId', () => {
  assert.ok(js.indexOf('PRACTICE_PENDING_SUBMISSION_KEY_PREFIX') >= 0, '必须定义待确认交卷持久化 key')
  const doSubmit = extractMethod(js, 'doSubmit')
  assert.ok(doSubmit.indexOf("this._persistPendingSubmission(submission, 'pending'") >= 0, '请求前必须保存 pending snapshot')
  assert.ok(js.indexOf('_offerPendingSubmissionRecovery') >= 0, '页面需提供 pending submission 恢复流程')
  assert.ok(js.indexOf('submission.requestId') >= 0, '恢复记录必须保留 requestId')
})

t('确定性 400/409 停止重试，服务端成功后跳转失败只重开结果页', () => {
  const doSubmit = extractMethod(js, 'doSubmit')
  assert.ok(doSubmit.indexOf("errorCode === 'PRACTICE_SUBMISSION_CONFLICT'") >= 0, '需识别幂等冲突')
  assert.ok(doSubmit.indexOf("errorCode === 'PRACTICE_QUESTION_VERSION_CONFLICT'") >= 0, '需识别题目版本冲突')
  assert.ok(doSubmit.indexOf("errorCode === 'PRACTICE_BATCH_INVALID'") >= 0, '需识别题目批次失效')
  assert.ok(doSubmit.indexOf("errorCode === 'PRACTICE_PAYLOAD_INVALID'") >= 0, '需识别 payload 校验失败')
  assert.ok(doSubmit.indexOf('submission.retryBlocked = true') >= 0, '确定性拒绝必须锁定重试')
  assert.ok(doSubmit.indexOf('submission.serverAccepted = true') >= 0, '服务端成功必须标记已交卷')
  assert.ok(js.indexOf('_openSubmittedResult(resultUrl, submission)') >= 0, '结果页跳转应独立于再次交卷')
})

t('题目下发批次与交卷绑定，且存储失败不虚假承诺可跨进程恢复', () => {
  assert.ok(js.indexOf('this._practiceSession.batchToken = res.batch_token') >= 0, '需保存服务端下发的 batch_token')
  assert.ok(js.indexOf('res.submission_request_id') >= 0, '需使用服务端下发的 submission request id 作为幂等键')
  const doSubmit = extractMethod(js, 'doSubmit')
  assert.ok(doSubmit.indexOf('submitPayload.batch_token = submission.batchToken') >= 0, '交卷必须携带冻结的 batch_token')
  assert.ok(doSubmit.indexOf('submission.pendingPersisted') >= 0, '必须记录待确认快照是否真正持久化')
  assert.ok(doSubmit.indexOf('当前设备未能保存恢复快照') >= 0, '持久化失败时不得承诺关闭小程序后可恢复')
})


t('批次凭据强制且登出清理待确认提交', () => {
  assert.ok(js.indexOf("throw new Error('服务器未返回可提交的练习批次凭据')") >= 0, '拉题缺少批次凭据时不得进入正常作答链路')
  const doSubmit = extractMethod(js, 'doSubmit')
  assert.ok(doSubmit.indexOf('submitPayload.batch_token = submission.batchToken') >= 0, 'batch_token 必须无条件随提交发送')
  const storageJs = fs.readFileSync(path.join(__dirname, '../utils/storage.js'), 'utf8')
  assert.ok(storageJs.indexOf("practice_pending_submission_v1:") >= 0, '登出清理必须覆盖动态 pending submission key')
  assert.ok(storageJs.indexOf("practice_recent_subjects_v1") >= 0, '切换账号需清理用户相关最近科目缓存')
})

const resultJs = fs.readFileSync(path.join(__dirname, '../subpackages/study/practice-result/index.js'), 'utf8')
const resultWxml = fs.readFileSync(path.join(__dirname, '../subpackages/study/practice-result/index.wxml'), 'utf8')
t('结果页正确率与完成率分母分离，部分多空题显示未完成', () => {
  assert.ok(resultJs.indexOf('const answeredTotal = correctCount + wrongCount') >= 0, '正确率应以实际作答题为分母')
  assert.ok(resultJs.indexOf('correctCount / answeredTotal * 100') >= 0, '正确率不应把跳过题计入分母')
  assert.ok(resultJs.indexOf('answeredTotal / totalCount * 100') >= 0, '必须单独计算完成率')
  assert.ok(resultJs.indexOf("return 'partial'") >= 0, '多空题部分作答需有 partial 状态')
  assert.ok(resultWxml.indexOf('完成率 {{completionPct}}%') >= 0, '结果页需显示完成率')
  assert.ok(resultWxml.indexOf('未完成') >= 0, '结果页需区分未完成与跳过')
})

t('部分多空题可提交但完全未作答仍阻止交卷', () => {
  const doSubmit = extractMethod(js, 'doSubmit')
  assert.ok(doSubmit.indexOf('answeredCount === 0 && partialQuestionIds.length === 0') >= 0, '完全未作答应继续阻止交卷')
  assert.ok(doSubmit.indexOf('partialQuestionIds: partialQuestionIds.slice()') >= 0, '部分作答题必须冻结进提交快照')
  assert.ok(doSubmit.indexOf('skippedQuestionIds: skippedQuestionIds.slice()') >= 0, '未完成题仍需以 skipped ids 提交给后端复盘')
})

t('趋势接口失败不伪造历史 0 数据，未完成题不显示全部答对', () => {
  assert.strictEqual(resultJs.indexOf('buildFallbackTrend'), -1, '不得生成虚假的历史趋势 fallback')
  assert.ok(resultJs.indexOf('trendAvailable: false') >= 0, '趋势不可用需有明确状态')
  assert.ok(resultWxml.indexOf('趋势暂不可用') === -1 || resultJs.indexOf('趋势暂不可用') >= 0, '趋势失败需明确提示不可用')
  assert.ok(resultWxml.indexOf('partialCount > 0') >= 0, '未完成题存在时不得显示本组全部答对')
})

t('结果缓存失败可通过同一 requestId 重放 canonical response 恢复', () => {
  assert.ok(js.indexOf('_recover=${resultCacheStored') >= 0, '缓存失败结果页需带恢复标记')
  assert.ok(resultJs.indexOf('recoverSubmittedResult') >= 0, '结果页需支持恢复已提交结果')
  assert.ok(resultJs.indexOf("api.post('/practice/batch-submit'") >= 0, '结果恢复需重放同一 batch-submit')
  assert.ok(resultJs.indexOf('submission.batchToken') >= 0, '结果恢复需复用原 batch_token')
})


t('结果恢复保留完整题目展示字段', () => {
  assert.ok(js.indexOf('content: (q && q.content) || {}') >= 0, 'pending snapshot 需保留完整题目 content')
  assert.ok(js.indexOf('options: (q && q.options) || null') >= 0, 'pending snapshot 需保留选择题选项')
  assert.ok(js.indexOf('image_url: (q && q.image_url) || null') >= 0, 'pending snapshot 需保留题目图片')
  assert.ok(resultJs.indexOf('content: q.content ||') >= 0, '结果恢复需重建 content')
  assert.ok(resultJs.indexOf('options: q.options || null') >= 0, '结果恢复需重建 options')
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
