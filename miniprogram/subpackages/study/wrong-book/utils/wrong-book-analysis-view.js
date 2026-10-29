function buildAnalysis(stats = {}, list = [], ports) {
stats = stats || {}
const errorRows = ports.rowsFromStats(stats, ['by_error_type', 'error_types', 'errors'])
const subjectRows = ports.rowsFromStats(stats, ['by_subject', 'subjects'])
const errorCounts = errorRows.length ? errorRows : ports.countsFromList(list, 'error_type')
const subjectCounts = subjectRows.length ? subjectRows : ports.countsFromList(list, 'subject_id')
const sourceLabel = errorRows.length || subjectRows.length ? '按错因统计' : (list.length ? '按当前列表统计' : '待积累')
const weaknessTags = ports.topItems(errorCounts, 5).map(row => ({
key: row.key,
label: ports.errorTypeLabel(row.key),
count: row.count,
}))
const radarItems = ports.toPercentItems(ports.topItems(errorCounts, 4), ports.errorTypeLabel.bind(ports))
const subjectItems = ports.toPercentItems(ports.topItems(subjectCounts, 4), ports.subjectLabel.bind(ports))
return {
sourceLabel,
weaknessTags,
radarItems,
subjectItems,
summaryCards: ports.buildSummaryCards(stats, list, weaknessTags),
actionPlan: ports.buildActionPlan(weaknessTags, subjectItems, list),
radarPolygonStyle: ports.radarPolygonStyle(radarItems),
radarAxisText: ports.radarAxisText(radarItems),
focusInsight: ports.focusInsight(weaknessTags, subjectItems, list),
}
}

function buildSummaryCards(stats = {}, list = [], weaknessTags = [], ports) {
stats = stats || {}
const hasStats = Object.keys(stats).length > 0
const unmastered = hasStats
? ports.positiveNumber(stats.unmastered, stats.total || list.length || 0)
: list.length
const reviewed = list.filter(item => ports.positiveNumber(item._reviewCount, 0) > 0).length
const avgMastery = list.length
? Math.round(list.reduce((sum, item) => sum + ports.positiveNumber(item._masteryPercent, 0), 0) / list.length)
: 0
const topWeakness = weaknessTags[0] ? weaknessTags[0].label : '待积累'
return [
{ key: 'unmastered', value: unmastered, label: '待攻克', tone: 'danger' },
{ key: 'weakness', value: topWeakness, label: '首要弱项', tone: 'blue' },
{ key: 'reviewed', value: `${reviewed}/${list.length || 0}`, label: '已复盘', tone: 'success' },
{ key: 'mastery', value: `${avgMastery}%`, label: '平均掌握', tone: 'gold' },
]
}

function buildActionPlan(weaknessTags = [], subjectItems = [], list = [], ports) {
if (!list.length && !weaknessTags.length && !subjectItems.length) return []
const firstWeakness = weaknessTags[0]
const firstSubject = subjectItems[0]
const lowMasteryCount = list.filter(item => ports.positiveNumber(item._masteryPercent, 0) < 40).length
return [
{
key: 'weakness',
title: firstWeakness ? `优先复盘「${firstWeakness.label}」` : '先完成一组错题复盘',
desc: firstWeakness ? `${firstWeakness.count} 道题集中暴露该问题` : '积累数据后会生成更明确的弱项计划',
},
{
key: 'subject',
title: firstSubject ? `重点看 ${firstSubject.label}` : '按学科建立错题节奏',
desc: firstSubject ? `${firstSubject.count} 道错题集中在该方向` : '筛选学科后可缩小复盘范围',
},
{
key: 'mastery',
title: lowMasteryCount > 0 ? `先攻克 ${lowMasteryCount} 道低掌握题` : '保持复盘节奏',
desc: lowMasteryCount > 0 ? '掌握进度低于 40% 的题建议优先重做' : '当前列表掌握度较稳定，适合做限时巩固',
},
]
}

function rowsFromStats(stats, keys, ports) {
for (let keyIndex = 0; keyIndex < keys.length; keyIndex++) {
const key = keys[keyIndex]
const value = stats && stats[key]
if (Array.isArray(value)) {
return value.map(row => ({
key: row.key || row.type || row.error_type || (row.subject_id != null ? row.subject_id : (row.name || row.label || '')),
label: row.subject_name || row.name || row.label || '',
count: ports.positiveNumber(row.count || row.total || row.value, 0),
})).filter(row => row.key !== '' && row.key != null && row.count > 0)
}
if (value && typeof value === 'object') {
return Object.keys(value).map(k => ({ key: k, label: '', count: ports.positiveNumber(value[k], 0) }))
.filter(row => row.key !== '' && row.key != null && row.count > 0)
}
}
return []
}

function countsFromList(list, field) {
const counts = {}
list.forEach(item => {
const key = item[field] != null ? item[field] : 'unknown'
if (!counts[key]) counts[key] = { key, label: item.subject_name || '', count: 0 }
counts[key].count += 1
})
return Object.keys(counts).map(key => counts[key]).filter(row => row.key !== 'unknown')
}

function topItems(rows, limit) {
return rows
.filter(row => row.key && row.count > 0)
.sort((a, b) => b.count - a.count)
.slice(0, limit)
}

function toPercentItems(rows, labelFn) {
const max = rows.reduce((m, row) => Math.max(m, row.count), 0) || 1
return rows.map(row => ({
key: row.key,
label: row.label || labelFn(row.key),
count: row.count,
percent: Math.max(12, Math.round((row.count / max) * 100)),
height: Math.max(46, Math.round((row.count / max) * 100) + 34),
}))
}

function radarPolygonStyle(items = []) {
if (!items.length) return ''
const points = [
[50, 50 - items[0].percent * 0.42],
[50 + (items[1] ? items[1].percent : items[0].percent) * 0.42, 50],
[50, 50 + (items[2] ? items[2].percent : items[0].percent) * 0.42],
[50 - (items[3] ? items[3].percent : items[0].percent) * 0.42, 50],
]
return `clip-path: polygon(${points.map(point => `${Math.round(point[0])}% ${Math.round(point[1])}%`).join(', ')});`
}

function radarAxisText(items = []) {
if (!items.length) return '暂无能力图谱数据'
return items.map(item => `${item.label}${item.count}题`).join('，')
}

function focusInsight(weaknessTags = [], subjectItems = [], list = []) {
const weakness = weaknessTags[0]
const subject = subjectItems[0]
if (weakness && subject) return `${subject.label}的「${weakness.label}」最需要优先攻克`
if (weakness) return `优先攻克「${weakness.label}」相关错题`
if (list.length) return '当前错题已形成复盘样本，建议先完成一轮筛选复盘'
return '错题数据积累后，将生成知识漏洞诊断。'
}

module.exports = { buildAnalysis, buildSummaryCards, buildActionPlan, rowsFromStats, countsFromList, topItems, toPercentItems, radarPolygonStyle, radarAxisText, focusInsight }
