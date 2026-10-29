function masteryProgress(item, reviewCount) {
const mastered = item.is_mastered === true || item.status === 'mastered' || item.mastered === true
if (mastered) return { percent: 100, label: '已掌握' }
const raw = item.mastery_progress || item.mastery_percent || item.mastery
if (raw !== undefined && raw !== null && raw !== '') {
const percent = Math.max(0, Math.min(100, Number(raw) > 1 ? Number(raw) : Number(raw) * 100))
return { percent: Math.round(percent), label: percent >= 40 ? '巩固中' : '待攻克' }
}
const percent = Math.min(90, reviewCount * 20)
return { percent, label: reviewCount > 0 ? '按复习次数估算' : '待复习' }
}

function positiveNumber(value, fallback) {
const n = Number(value)
if (!Number.isFinite(n) || n < 0) return fallback
return Math.round(n)
}

function subjectLabel(code, name, getSubjectName) {
if (name) return name
return getSubjectName(code)
}

function errorTypeLabel(t, errorDiagnosis) {
const map = { concept_mistake: '概念错误', calculation: '计算错误', careless: '粗心', method: '方法错误', other: '其他', unknown: '未分类' }
if (!t) return '未知'
return map[t] || errorDiagnosis.labelOf(t)
}

function timeLabel(dateStr, parseServerUtc, chinaCalendarDayDiff, formatChinaMonthDayCn) {
if (!dateStr) return ''
const ms = parseServerUtc(dateStr)
if (!isFinite(ms)) return ''
const days = chinaCalendarDayDiff(ms, Date.now())
if (days === 0) return '今天'
if (days === 1) return '昨天'
if (days > 1 && days <= 7) return `${days} 天前`
return formatChinaMonthDayCn(ms)
}

function toCleanText(text, toPlainInlineMathText) {
if (!text || typeof text !== 'string') return ''
const plain = toPlainInlineMathText(text)
return plain !== null ? plain : String(text).replace(/\n/g, ' ')
}

function reviewDueInfo(item, isMastered, parseServerUtc, getChinaDayRangeUtcMs) {
if (isMastered) return { today: false, overdue: false, date: null }
const raw = item.next_review_at || item.review_due_at || item.scheduled_at || item.due_at
const dueMs = raw ? parseServerUtc(raw) : NaN
const date = isFinite(dueMs) ? new Date(dueMs) : null
const explicitToday = item.is_today_due === true || item.today_due === true || item.is_due === true
if (!date && explicitToday) return { today: true, overdue: false, date: null }
if (!date) return { today: false, overdue: false, date: null }
const range = getChinaDayRangeUtcMs()
return {
today: dueMs < range.end,
overdue: dueMs < range.start,
date,
}
}

function isRecentDate(raw, days, parseServerUtc) {
if (!raw) return false
const ms = parseServerUtc(raw)
if (!isFinite(ms)) return false
const diff = Date.now() - ms
return diff >= 0 && diff <= days * 86400000
}

function shortDateLabel(date, formatChinaMonthDayCn) {
if (!date || Number.isNaN(date.getTime())) return ''
return formatChinaMonthDayCn(date.getTime())
}

function oneLineInsight(text) {
const cleaned = String(text || '').replace(/\s+/g, ' ').trim()
if (!cleaned) return '错题数据积累后，AI 会自动发现最需要优先复盘的错误模式。'
return cleaned.length > 70 ? `${cleaned.slice(0, 70)}…` : cleaned
}

module.exports = { masteryProgress, positiveNumber, subjectLabel, errorTypeLabel, timeLabel, toCleanText, reviewDueInfo, isRecentDate, shortDateLabel, oneLineInsight }
