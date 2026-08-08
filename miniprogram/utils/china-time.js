/**
 * 中国固定时区（Asia/Shanghai, UTC+8）与"统计日"工具。
 *
 * 产品时区固定为中国时间，不随设备/系统 timezone 变化。后端负责统计口径权威，
 * 本模块只用于：
 *  - 计算"当前中国统计日"（day_start 之前的凌晨属于前一天）
 *  - minute <-> HH:MM 转换
 *  - 把服务端 naive-UTC 时间按中国时间格式化显示
 */

var CHINA_OFFSET_MS = 8 * 60 * 60 * 1000
var DAY_MS = 24 * 60 * 60 * 1000

function clampMinute(minute) {
  var m = Number(minute)
  if (!isFinite(m)) return 0
  return Math.max(0, Math.min(1439, Math.floor(m)))
}

function pad2(n) {
  return n < 10 ? '0' + n : '' + n
}

/** 分钟数（0~1439）-> "HH:MM"。360 -> "06:00" */
function minuteToTimeText(minute) {
  var m = clampMinute(minute)
  return pad2(Math.floor(m / 60)) + ':' + pad2(m % 60)
}

/** "HH:MM" -> 分钟数（0~1439），非法输入回退 0 */
function timeTextToMinute(text) {
  if (typeof text !== 'string') return 0
  var parts = text.split(':')
  if (parts.length !== 2) return 0
  var h = parseInt(parts[0], 10)
  var m = parseInt(parts[1], 10)
  if (!isFinite(h) || !isFinite(m)) return 0
  return clampMinute(h * 60 + m)
}

/**
 * 解析服务端时间值为 Unix 毫秒。
 * naive-UTC ISO（如 "2026-08-07T15:50:00"）按 UTC 解析；
 * 带时区/后缀的 ISO 直接交给 Date 解析。
 */
function parseServerUtc(value) {
  if (value == null) return NaN
  if (typeof value === 'number') return value
  var s = String(value).trim()
  if (!s) return NaN
  var hasTimezone = /Z$|[+-]\d{2}:?\d{2}$/.test(s)
  return new Date(hasTimezone ? s : s + '+00:00').getTime()
}

/**
 * 把"中国墙上时钟读数"（epoch 毫秒坐标 +8h 偏移后）格式化为 YYYY-MM-DD。
 * 内部工具：通过 getUTCFullYear 等读取，避免依赖设备时区。
 */
function wallDateText(wallMs) {
  var d = new Date(wallMs)
  return d.getUTCFullYear() + '-' + pad2(d.getUTCMonth() + 1) + '-' + pad2(d.getUTCDate())
}

/** 当前中国统计日（YYYY-MM-DD）。dayStartMinute=360 时，凌晨 02:00 仍属于前一天。 */
function getChinaStudyDate(dayStartMinute) {
  return wallDateText(Date.now() + CHINA_OFFSET_MS - clampMinute(dayStartMinute) * 60000)
}

/** 给定一个 Unix 毫秒时间戳（UTC epoch），返回其所属的中国统计日。 */
function getStudyDateOf(utcMs, dayStartMinute) {
  if (!isFinite(utcMs)) return ''
  return wallDateText(utcMs + CHINA_OFFSET_MS - clampMinute(dayStartMinute) * 60000)
}

/** Unix 毫秒 -> 中国日历日期 YYYY-MM-DD */
function formatChinaDate(utcMs) {
  if (!isFinite(utcMs)) return ''
  return wallDateText(utcMs + CHINA_OFFSET_MS)
}

/** 服务端 naive-UTC ISO -> 中国 HH:MM（历史记录显示用，不依赖设备时区） */
function formatChinaTimeHM(value) {
  var ms = parseServerUtc(value)
  if (!isFinite(ms)) return ''
  var d = new Date(ms + CHINA_OFFSET_MS)
  return pad2(d.getUTCHours()) + ':' + pad2(d.getUTCMinutes())
}

/** 服务端 naive-UTC ISO -> 中国 M/D（历史记录日期显示用） */
function formatChinaMonthDay(value) {
  var ms = parseServerUtc(value)
  if (!isFinite(ms)) return ''
  var d = new Date(ms + CHINA_OFFSET_MS)
  return d.getUTCMonth() + 1 + '/' + d.getUTCDate()
}

module.exports = {
  CHINA_OFFSET_MS: CHINA_OFFSET_MS,
  DAY_MS: DAY_MS,
  minuteToTimeText: minuteToTimeText,
  timeTextToMinute: timeTextToMinute,
  parseServerUtc: parseServerUtc,
  getChinaStudyDate: getChinaStudyDate,
  getStudyDateOf: getStudyDateOf,
  formatChinaDate: formatChinaDate,
  formatChinaTimeHM: formatChinaTimeHM,
  formatChinaMonthDay: formatChinaMonthDay,
}
