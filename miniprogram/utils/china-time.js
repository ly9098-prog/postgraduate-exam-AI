/**
 * 产品统一时区工具：Asia/Shanghai（UTC+8，无夏令时）。
 *
 * 后端 DateTime 按 naive UTC 存储；新接口返回显式 Z，同时兼容历史上
 * 没有 Z 的 UTC ISO 字符串。所有“今天/昨天/业务自然日”均以北京时间为准，
 * 不依赖手机或开发者工具所在设备的系统时区。
 */

var CHINA_OFFSET_MS = 8 * 60 * 60 * 1000
var DAY_MS = 24 * 60 * 60 * 1000

function pad2(n) {
  return n < 10 ? '0' + n : '' + n
}

function clampMinute(minute) {
  var m = Number(minute)
  if (!isFinite(m)) return 0
  return Math.max(0, Math.min(1439, Math.floor(m)))
}

function minuteToTimeText(minute) {
  var m = clampMinute(minute)
  return pad2(Math.floor(m / 60)) + ':' + pad2(m % 60)
}

function timeTextToMinute(text) {
  if (typeof text !== 'string') return 0
  var parts = text.split(':')
  if (parts.length !== 2) return 0
  var h = parseInt(parts[0], 10)
  var m = parseInt(parts[1], 10)
  if (!isFinite(h) || !isFinite(m)) return 0
  return clampMinute(h * 60 + m)
}

/** 服务端时间 -> epoch ms。无时区 ISO 一律视为 UTC。 */
function parseServerUtc(value) {
  if (value == null) return NaN
  if (typeof value === 'number') return value
  var s = String(value).trim()
  if (!s) return NaN
  if (/^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}/.test(s)) {
    s = s.replace(/^(\d{4}-\d{2}-\d{2})\s+/, '$1T')
  }
  var hasTimezone = /Z$|[+-]\d{2}:?\d{2}$/.test(s)
  return new Date(hasTimezone ? s : s + '+00:00').getTime()
}

function wallDateText(wallMs) {
  var d = new Date(wallMs)
  return d.getUTCFullYear() + '-' + pad2(d.getUTCMonth() + 1) + '-' + pad2(d.getUTCDate())
}

/** 给定 epoch，取得对应的北京时间墙上时钟字段。 */
function getChinaWallParts(utcMs) {
  var ms = Number(utcMs)
  if (!isFinite(ms)) ms = Date.now()
  var d = new Date(ms + CHINA_OFFSET_MS)
  return {
    year: d.getUTCFullYear(),
    month: d.getUTCMonth() + 1,
    day: d.getUTCDate(),
    weekday: d.getUTCDay(),
    hour: d.getUTCHours(),
    minute: d.getUTCMinutes(),
    second: d.getUTCSeconds(),
  }
}

/** 当前/偏移 N 天的北京时间自然日 YYYY-MM-DD。 */
function getChinaDate(offsetDays, nowMs) {
  var base = Number(nowMs)
  if (!isFinite(base)) base = Date.now()
  var offset = Number(offsetDays)
  if (!isFinite(offset)) offset = 0
  return wallDateText(base + CHINA_OFFSET_MS + Math.trunc(offset) * DAY_MS)
}

/** 北京时间自然日 00:00 对应的 UTC epoch ms。 */
function getChinaDayStartUtcMs(dateText) {
  var text = dateText || getChinaDate(0)
  var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(text))
  if (!m) return NaN
  return Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])) - CHINA_OFFSET_MS
}

function getChinaDayRangeUtcMs(dateText) {
  var start = getChinaDayStartUtcMs(dateText)
  if (!isFinite(start)) return { start: NaN, end: NaN }
  return { start: start, end: start + DAY_MS }
}

/** 两个 epoch 所属北京时间自然日的差：0=今天，1=昨天。 */
function chinaCalendarDayDiff(earlierMs, laterMs) {
  var a = Number(earlierMs)
  var b = Number(laterMs)
  if (!isFinite(a) || !isFinite(b)) return NaN
  return Math.floor((b + CHINA_OFFSET_MS) / DAY_MS) - Math.floor((a + CHINA_OFFSET_MS) / DAY_MS)
}

function getChinaStudyDate(dayStartMinute) {
  return wallDateText(Date.now() + CHINA_OFFSET_MS - clampMinute(dayStartMinute) * 60000)
}

function getStudyDateOf(utcMs, dayStartMinute) {
  if (!isFinite(utcMs)) return ''
  return wallDateText(utcMs + CHINA_OFFSET_MS - clampMinute(dayStartMinute) * 60000)
}

function formatChinaDate(utcMs) {
  if (!isFinite(utcMs)) return ''
  return wallDateText(utcMs + CHINA_OFFSET_MS)
}

function formatChinaTimeHM(value) {
  var ms = parseServerUtc(value)
  if (!isFinite(ms)) return ''
  var parts = getChinaWallParts(ms)
  return pad2(parts.hour) + ':' + pad2(parts.minute)
}

function formatChinaMonthDay(value) {
  var ms = typeof value === 'number' ? value : parseServerUtc(value)
  if (!isFinite(ms)) return ''
  var parts = getChinaWallParts(ms)
  return parts.month + '/' + parts.day
}

function formatChinaMonthDayCn(value) {
  var ms = typeof value === 'number' ? value : parseServerUtc(value)
  if (!isFinite(ms)) return ''
  var parts = getChinaWallParts(ms)
  return parts.month + '月' + parts.day + '日'
}

module.exports = {
  CHINA_OFFSET_MS: CHINA_OFFSET_MS,
  DAY_MS: DAY_MS,
  minuteToTimeText: minuteToTimeText,
  timeTextToMinute: timeTextToMinute,
  parseServerUtc: parseServerUtc,
  getChinaWallParts: getChinaWallParts,
  getChinaDate: getChinaDate,
  getChinaDayStartUtcMs: getChinaDayStartUtcMs,
  getChinaDayRangeUtcMs: getChinaDayRangeUtcMs,
  chinaCalendarDayDiff: chinaCalendarDayDiff,
  getChinaStudyDate: getChinaStudyDate,
  getStudyDateOf: getStudyDateOf,
  formatChinaDate: formatChinaDate,
  formatChinaTimeHM: formatChinaTimeHM,
  formatChinaMonthDay: formatChinaMonthDay,
  formatChinaMonthDayCn: formatChinaMonthDayCn,
}
