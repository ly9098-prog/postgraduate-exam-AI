#!/usr/bin/env node
/**
 * test-china-time.js
 *
 * Regression tests for:
 * - subpackages/productivity/utils/china-time.js（中国固定时区 + 统计日工具）
 * - pomodoro-stats 页面：统计日设置驱动 today、selectedDate 修正、
 *   daily-summary 驱动 overview、history 时间按 UTC+8 格式化
 *
 * Usage: node scripts/test-china-time.js
 * Exit code: 0 = pass, 1 = fail
 */
/* eslint-disable no-console */
const path = require('path')

const chinaTime = require('../subpackages/productivity/utils/china-time.js')

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

function assertEqual(actual, expected, message) {
  if (actual === expected) {
    passed++
    console.log('  ✓ ' + message)
  } else {
    failed++
    console.error('  ✗ ' + message + ' (expected ' + JSON.stringify(expected) + ', got ' + JSON.stringify(actual) + ')')
  }
}

const FIXED_NOW_MS = Date.UTC(2026, 7, 7, 18, 0, 0) // == 中国 2026-08-08 02:00
const originalNow = Date.now

function useFixedNow() {
  Date.now = () => FIXED_NOW_MS
}
function restoreNow() {
  Date.now = originalNow
}

// ── china-time 纯函数 ─────────────────────────────────────────────
console.log('\n=== subpackages/productivity/utils/china-time.js ===')

useFixedNow()
assertEqual(chinaTime.getChinaStudyDate(360), '2026-08-07', 'day_start=06:00 时凌晨 02:00 属于前一个统计日')
assertEqual(chinaTime.getChinaStudyDate(0), '2026-08-08', 'day_start=00:00 时当前统计日为 08-08')
restoreNow()

// getStudyDateOf：session 时间戳归属统计日
assertEqual(chinaTime.getStudyDateOf(Date.UTC(2026, 7, 7, 15, 50, 0), 0), '2026-08-07', '23:50 中国 (UTC 15:50) 归属 08-07')
assertEqual(chinaTime.getStudyDateOf(Date.UTC(2026, 7, 7, 18, 0, 0), 360), '2026-08-07', '08-08 02:00 中国 (UTC 08-07 18:00) 归属 08-07')
assertEqual(chinaTime.getStudyDateOf(Date.UTC(2026, 7, 8, 3, 0, 0), 360), '2026-08-08', '08-08 11:00 中国 归属 08-08')

// minute <-> HH:mm
assertEqual(chinaTime.minuteToTimeText(0), '00:00', '0 -> 00:00')
assertEqual(chinaTime.minuteToTimeText(180), '03:00', '180 -> 03:00')
assertEqual(chinaTime.minuteToTimeText(360), '06:00', '360 -> 06:00')
assertEqual(chinaTime.minuteToTimeText(390), '06:30', '390 -> 06:30')
assertEqual(chinaTime.minuteToTimeText(1439), '23:59', '1439 -> 23:59')
assertEqual(chinaTime.timeTextToMinute('06:00'), 360, '"06:00" -> 360')
assertEqual(chinaTime.timeTextToMinute('23:59'), 1439, '"23:59" -> 1439')
assertEqual(chinaTime.timeTextToMinute('06:30'), 390, '"06:30" -> 390')
assertEqual(chinaTime.timeTextToMinute('bad'), 0, '非法输入 -> 0')
assertEqual(chinaTime.timeTextToMinute(chinaTime.minuteToTimeText(545)), 545, 'round-trip 545')

// history 时间按 UTC+8 格式化
assertEqual(chinaTime.formatChinaTimeHM('2026-08-07T15:50:00'), '23:50', 'naive-UTC 15:50 -> 中国 23:50')
assertEqual(chinaTime.formatChinaTimeHM('2026-08-07T16:20:00'), '00:20', 'naive-UTC 16:20 -> 中国 00:20(次日)')
assertEqual(chinaTime.formatChinaMonthDay('2026-08-07T15:50:00'), '8/7', 'naive-UTC -> 中国 M/D')
assertEqual(chinaTime.formatChinaDate(Date.UTC(2026, 7, 7, 16, 0, 0)), '2026-08-08', 'UTC 08-07 16:00 中国 08-08')

// ── 页面行为 ─────────────────────────────────────────────────────
console.log('\n=== pomodoro-stats 页面 ===')

// Mock WeChat globals before requiring the page module
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
      in() { return this },
      select() { return this },
      fields() { return this },
      exec(cb) { cb && cb([]) },
    }
  },
}
global.Page = function () {}

// api mock（可控制）
const apiMockPath = path.resolve(__dirname, '../utils/api.js')
const storageMockPath = path.resolve(__dirname, '../utils/storage.js')
const configMockPath = path.resolve(__dirname, '../config.js')
const debugMockPath = path.resolve(__dirname, '../utils/debug.js')
const apiMock = { get: () => Promise.resolve({}), put: () => Promise.resolve({}) }
const storageMock = require('../utils/storage.js')
const configMock = {}
const debugMock = { debugLog() {}, isDebugMode: () => false, saveDebugSnapshot() {} }
require.cache = require.cache || {}
require.cache[apiMockPath] = { exports: apiMock }
require.cache[storageMockPath] = { exports: storageMock }
require.cache[configMockPath] = { exports: configMock }
require.cache[debugMockPath] = { exports: debugMock }

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

async function run() {
  // _studyDayRangeText
  const inst = createInstance()
  assertEqual(inst._studyDayRangeText(0), '统计日从 00:00 开始', 'day_start=0 文案')
  assertEqual(inst._studyDayRangeText(360), '统计周期 06:00 - 次日 06:00', 'day_start=360 文案')

  // _formatPieDateLabel
  inst.data._todayDate = '2026-08-08'
  assertEqual(inst._formatPieDateLabel('2026-08-08'), '今日', '今日 label')
  assertEqual(inst._formatPieDateLabel('2026-08-07'), '昨日', '昨日 label')
  assertEqual(inst._formatPieDateLabel('2026-08-05'), '8月5日', '历史日期 label')

  // _formatSession：history 时间按 UTC+8
  const s = {
    start_time: '2026-08-07T15:50:00',
    actual_duration: 1800,
    subject_name: '数学二',
    subject_code: 'math2',
    subject_id: 1,
    preset: 'standard',
    status: 'completed',
  }
  const fmt = inst._formatSession(s)
  assertEqual(fmt._time, '23:50', 'history 时间按中国时间显示')
  assertEqual(fmt._date, '8/7', 'history 日期按中国时间显示')
  assertEqual(fmt._duration, '30分钟', 'history 时长格式化')

  // _ensureSettings：day_start 加载后校正 today / selectedDate
  useFixedNow()
  const inst2 = createInstance()
  inst2.data._todayDate = '2026-08-08'
  inst2.data.selectedDate = '2026-08-08'
  apiMock.get = (url) => {
    if (url === '/pomodoro/settings') return Promise.resolve({ day_start_minute: 360 })
    return Promise.resolve({})
  }
  await inst2._ensureSettings()
  assertEqual(inst2.data.dayStartMinute, 360, 'settings 读取 day_start_minute')
  assertEqual(inst2.data._todayDate, '2026-08-07', 'day_start=360 时 today 校正为前一天')
  assertEqual(inst2.data.selectedDate, '2026-08-07', '停留在"今天"时 selectedDate 跟随 today')
  assertEqual(inst2.data.dayStartTime, '06:00', 'dayStartTime 展示 06:00')

  // 明确查看历史日期时保持该日期
  const inst3 = createInstance()
  inst3.data._todayDate = '2026-08-08'
  inst3.data.selectedDate = '2026-08-05'
  await inst3._ensureSettings()
  assertEqual(inst3.data.selectedDate, '2026-08-05', '历史日期不受 day_start 变更影响')

  // _saveDayStart：保存后修正 selectedDate 并刷新
  const inst4 = createInstance()
  inst4.data._todayDate = '2026-08-08'
  inst4.data.selectedDate = '2026-08-08'
  inst4.data.dayStartMinute = 0
  apiMock.put = () => Promise.resolve({ day_start_minute: 180 })
  let reloaded = false
  inst4.loadData = async function () { reloaded = true }
  await inst4._saveDayStart(180)
  assertEqual(inst4.data.dayStartMinute, 180, '_saveDayStart 更新本地设置')
  assertEqual(inst4.data._todayDate, '2026-08-07', 'day_start=180 (03:00) 时凌晨 02:00 仍属前一天')
  assertEqual(inst4.data.studyDayRangeText, '统计周期 03:00 - 次日 03:00', '设置后范围文案更新')
  restoreNow()

  // statistics-overview 驱动 overview / pie：loadData 不再逐个拉 stats/trends/daily-summary
  apiMock.get = (url, params) => {
    if (url === '/pomodoro/settings') return Promise.resolve({ day_start_minute: 0 })
    if (url === '/pomodoro/statistics-overview') {
      return Promise.resolve({
        stats: { week_sessions: 2, week_duration_sec: 7200, today_date: '2026-08-08', day_start_minute: 0 },
        trends: [{ date: '2026-08-08', sessions: 1, duration_sec: 600 }],
        daily_summary: {
          date: '2026-08-08',
          duration_sec: 600,
          sessions: 1,
          subjects: [{ subject_id: 1, subject_code: 'math2', subject_name: '数学二', sessions: 1, duration_sec: 600 }],
        },
      })
    }
    if (url === '/pomodoro/history') {
      return Promise.resolve({
        total: 1,
        items: [{ id: 9, record_key: 'pomodoro:9', record_type: 'pomodoro', start_time: '2026-08-07T15:50:00', actual_duration: 600, subject_name: '数学二', subject_code: 'math2', subject_id: 1, preset: 'standard', status: 'completed' }],
      })
    }
    return Promise.resolve({})
  }
  useFixedNow()   // 中国 2026-08-08 02:00，day_start=0 -> 今日 08-08
  const inst5 = createInstance()
  inst5._alive = true
  inst5._isVisible = true
  inst5._requestId = 1
  inst5.data.selectedDate = '2026-08-08'
  inst5.data._todayDate = '2026-08-08'
  inst5._dateRequestSeq = 0
  inst5._hasData = true   // 非首帧动画，history 直接写入
  inst5._initCanvases = () => {}
  inst5._cancelDeferredHistory = () => {}
  inst5._queueDeferredHistory = () => {}
  inst5._cancelDurationAnimation = () => {}
  inst5._resetPieCache = () => {}
  let overviewParams = null
  let historyCalls = []
  const origGet = apiMock.get
  apiMock.get = (url, params) => {
    if (url === '/pomodoro/statistics-overview') overviewParams = params || {}
    if (url === '/pomodoro/history') historyCalls.push((params && params.date) || null)
    return origGet(url, params)
  }
  await inst5.loadData()
  assertEqual(inst5.data.todaySessions, 1, 'overview sessions 来自 statistics-overview.daily_summary')
  assertEqual(inst5.data.todayDurationText, '10分钟', 'overview 时长来自 daily-summary (600s)')
  assertEqual(inst5.data.weekSessions, 2, 'week sessions 来自 stats')
  assertEqual(inst5.data.subjects.length, 1, 'pie 数据来自 daily-summary.subjects')
  assertEqual(inst5.data.history[0]._time, '23:50', 'history 最近记录按中国时间显示')
  assertEqual(inst5.data.historyTotal, 1, 'history total 来自第一页响应')
  assertEqual(inst5.data._todayDate, '2026-08-08', '今日与后端一致，不校正')
  assertEqual(overviewParams.date == null, true, '查看"今日"时 statistics-overview 不传 date（后端权威）')

  // settings 请求失败 + 设备时钟偏差 -> 以后端 stats.today_date 校正"今日"
  const inst6 = createInstance()
  inst6._alive = true
  inst6._isVisible = true
  inst6._requestId = 1
  inst6._dateRequestSeq = 0
  inst6._hasData = true
  inst6._initCanvases = () => {}
  inst6._cancelDeferredHistory = () => {}
  inst6._queueDeferredHistory = () => {}
  inst6._cancelDurationAnimation = () => {}
  inst6._resetPieCache = () => {}
  inst6.data._todayDate = '2026-08-08'   // 设备时钟偏差导致的错误"今日"
  inst6.data.selectedDate = '2026-08-08'
  let reFetchedHistoryDate = null
  apiMock.get = (url, params) => {
    if (url === '/pomodoro/settings') return Promise.reject(new Error('network'))
    if (url === '/pomodoro/statistics-overview') {
      return Promise.resolve({
        stats: { week_sessions: 0, week_duration_sec: 0, today_date: '2026-08-07', day_start_minute: 360 },
        trends: [],
        daily_summary: { date: '2026-08-07', duration_sec: 1800, sessions: 1, subjects: [] },
      })
    }
    if (url === '/pomodoro/history') {
      if (params && params.date === '2026-08-07') reFetchedHistoryDate = params.date
      return Promise.resolve({ total: 0, items: [] })
    }
    return Promise.resolve({})
  }
  await inst6.loadData()
  assertEqual(inst6.data._todayDate, '2026-08-07', 'settings 失败时以后端 stats.today_date 校正今日')
  assertEqual(inst6.data.selectedDate, '2026-08-07', '错误"今日"被后端权威纠正')
  assertEqual(inst6.data.dayStartMinute, 360, 'day_start 从 stats 兜底读取')
  assertEqual(reFetchedHistoryDate, '2026-08-07', '今日变化后按权威日期重取 history')
  restoreNow()

  console.log('\n结果: ' + passed + ' passed, ' + failed + ' failed')
  process.exit(failed ? 1 : 0)
}

run().catch(e => {
  console.error('ERROR:', e)
  process.exit(1)
})
