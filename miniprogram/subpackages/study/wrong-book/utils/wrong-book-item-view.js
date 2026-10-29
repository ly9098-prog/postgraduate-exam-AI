function decorateItem(item, ports) {
    const wrongCount = ports.positiveNumber(item.wrong_count || item.error_count || item.mistake_count || item.incorrect_count, 0)
    const reviewCount = ports.resolveReviewCount(item)
    const lastErrorAt = item.last_wrong_at || item.last_error_at || item.updated_at || item.created_at
    const mastery = ports.masteryProgress(item, reviewCount)
    const isMastered = item.is_mastered === true || item.status === "mastered" || item.mastered === true
    const dueInfo = ports.reviewDueInfo(item, isMastered)
    const isRecent = ports.isRecentDate(item.created_at || item.last_wrong_at || item.updated_at, 14)
    const statusInfo = ports.resolveItemStatus(isMastered, dueInfo, isRecent)
    const contentInfo = ports.resolveItemContent(item)
    return ports.buildDecoratedItem(item, { wrongCount, reviewCount, lastErrorAt, mastery, isMastered, dueInfo, isRecent, statusInfo, contentInfo })
  }

function resolveReviewCount(item, ports) {
    const raw = item.review_record_count !== undefined && item.review_record_count !== null ? item.review_record_count : item.review_count
    return ports.positiveNumber(raw, 0)
  }

function resolveItemStatus(isMastered, dueInfo, isRecent, ports) {
    let label = "待巩固", tone = "waiting"
    if (isMastered) { label = "已掌握"; tone = "mastered" }
    else if (dueInfo.overdue) { label = "已逾期"; tone = "overdue" }
    else if (dueInfo.today) { label = "今天到期"; tone = "due" }
    else if (isRecent) { label = "最近新增"; tone = "recent" }
    else if (dueInfo.date) { label = ports.shortDateLabel(dueInfo.date) + "复习" }
    return { label, tone }
  }

function resolveItemContent(item, ports) {
    const rawContent = item.content
    const contentText = typeof rawContent === "string" ? rawContent : (rawContent && (rawContent.text || rawContent.stem)) || ""
    const cleanText = ports.toCleanText(contentText)
    const hasImage = Array.isArray(item.image_url) ? item.image_url.length > 0 : !!item.image_url
    return { cleanText, hasImage }
  }

function buildDecoratedItem(item, ctx, ports) {
    const { wrongCount, reviewCount, lastErrorAt, mastery, isMastered, dueInfo, isRecent, statusInfo, contentInfo } = ctx
    return {
      ...item,
      _subjectLabel: ports.subjectLabel(item.subject_code, item.subject_name),
      _errorTypeLabel: ports.errorTypeLabel(item.error_type),
      _timeLabel: ports.timeLabel(item.created_at),
      _lastErrorLabel: ports.timeLabel(lastErrorAt) || "待记录",
      _wrongCount: wrongCount,
      _reviewCount: reviewCount,
      _masteryPercent: mastery.percent,
      _masteryLabel: mastery.label,
      _cleanText: contentInfo.cleanText || (contentInfo.hasImage ? "图片题 · 点击查看完整题目" : ""),
      _isMastered: isMastered,
      _isTodayDue: dueInfo.today,
      _isOverdue: dueInfo.overdue,
      _isRecent: isRecent,
      _nextReviewAt: dueInfo.date ? dueInfo.date.toISOString() : "",
      _taskStatusLabel: statusInfo.label,
      _statusTone: statusInfo.tone,
    }
  }

function flattenSubjectOptions(raw) {
const source = Array.isArray(raw)
? raw
: (raw && Array.isArray(raw.items) ? raw.items : [])
const result = []
const seen = new Set()
const visit = (node) => {
if (!node || node.is_active === false) return
const value = node.subject_id != null
? node.subject_id
: (node.id != null ? node.id : null)
const label = node.subject_name != null
? node.subject_name
: (node.display_name != null ? node.display_name : (node.name != null ? node.name : null))
if (value != null && label) {
const key = String(value)
if (!seen.has(key)) {
seen.add(key)
result.push({ value: Number(value), label: String(label) })
}
}
if (Array.isArray(node.children)) node.children.forEach(visit)
}
source.forEach(visit)
return result
}

function buildTaskGroups(list = [], parseServerUtc) {
const used = new Set()
const take = predicate => {
const rows = list.filter(item => !used.has(String(item.id)) && predicate(item))
rows.forEach(item => used.add(String(item.id)))
return rows
}
const today = take(item => !item._isMastered && item._isTodayDue)
.sort((a, b) => Number(b._isOverdue) - Number(a._isOverdue) || b._wrongCount - a._wrongCount)
const high = take(item => !item._isMastered && item._wrongCount >= 3)
.sort((a, b) => b._wrongCount - a._wrongCount)
const recent = take(item => !item._isMastered && item._isRecent)
.sort((a, b) => (parseServerUtc(b.created_at) || 0) - (parseServerUtc(a.created_at) || 0))
const waiting = take(item => !item._isMastered)
.sort((a, b) => a._masteryPercent - b._masteryPercent || b._wrongCount - a._wrongCount)
const mastered = take(item => item._isMastered)
.sort((a, b) => (parseServerUtc(b.updated_at || b.created_at) || 0) - (parseServerUtc(a.updated_at || a.created_at) || 0))
const maxPreview = 3
const configs = [
{ key: 'today', title: '今日应复习', desc: '基于复习计划，今天最值得先做的题', icon: '今', tone: 'lime', rows: today },
{ key: 'high', title: '高频错题', desc: '重复出错次数较多，建议集中攻克', icon: '频', tone: 'orange', rows: high },
{ key: 'recent', title: '最近新增', desc: '近 14 天新加入错题本的题目', icon: '新', tone: 'blue', rows: recent },
{ key: 'waiting', title: '待巩固', desc: '尚未到复习日，但仍未完全掌握', icon: '固', tone: 'neutral', rows: waiting },
{ key: 'mastered', title: '已经掌握', desc: '已达到掌握标准，不再进入正常复习；再次答错会重新加入', icon: '✓', tone: 'green', rows: mastered },
]
const groups = configs
.filter(group => group.rows.length > 0)
.map(group => ({
key: group.key,
title: group.title,
desc: group.desc,
icon: group.icon,
tone: group.tone,
total: group.rows.length,
items: group.rows.slice(0, maxPreview),
}))
const visibleCount = groups.reduce((sum, group) => sum + group.items.length, 0)
return {
groups,
ungroupedCount: Math.max(0, list.length - visibleCount),
}
}

module.exports = { decorateItem, resolveReviewCount, resolveItemStatus, resolveItemContent, buildDecoratedItem, flattenSubjectOptions, buildTaskGroups }
