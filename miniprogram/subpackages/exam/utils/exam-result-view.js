/**
 * Pure exam result view builders shared by the result page,
 * extracted from subpackages/exam/result/index.js.
 */

const RADAR_SIZE = 5

const RADAR_ANGLES = [-90, -18, 54, 126, 198]

function clamp(value, min, max) {
  const n = Number(value)
  if (!Number.isFinite(n)) return min
  return Math.min(max, Math.max(min, n))
}

function percentNumber(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return 0
  return Math.round(clamp(n <= 1 ? n * 100 : n, 0, 100))
}

function compactDuration(sec) {
  const total = Math.max(0, Math.round(Number(sec) || 0))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  const pad2 = n => String(n).padStart(2, '0')
  return h > 0 ? `${pad2(h)}:${pad2(m)}:${pad2(s)}` : `${pad2(m)}:${pad2(s)}`
}

function compactScore(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return '0'
  if (Math.abs(n - Math.round(n)) < 0.001) return String(Math.round(n))
  return n.toFixed(1).replace(/\.0$/, '')
}

function normalizeName(value, fallback) {
  const text = String(value || '').replace(/\s+/g, ' ').trim()
  return text || fallback || '未命名知识点'
}

function shortName(value, maxLength = 8) {
  const text = normalizeName(value, '')
  if (text.length <= maxLength) return text
  return `${text.slice(0, Math.max(2, maxLength - 1))}…`
}

function masteryTag(accuracyPct) {
  const pct = clamp(accuracyPct, 0, 100)
  if (pct >= 85) return { label: '优秀', tone: 'excellent' }
  if (pct >= 70) return { label: '良好', tone: 'good' }
  return { label: '待提升', tone: 'weak' }
}

function encouragement(scoreRatePct, accuracyPct) {
  const value = Math.max(scoreRatePct, accuracyPct)
  if (value >= 90) return '状态很棒！'
  if (value >= 80) return '表现不错！'
  if (value >= 60) return '继续保持！'
  return '再接再厉！'
}

function encouragementTail(wrongCount, unansweredCount) {
  const wrong = Math.max(0, Number(wrongCount) || 0)
  const unanswered = Math.max(0, Number(unansweredCount) || 0)
  if (wrong > 0) return '，继续查漏补缺'
  if (unanswered > 0) return `，还有 ${unanswered} 道题未作答`
  return '，继续保持！'
}

function firstWrongIdByQuestion(question) {
  const id = Number(question && question.wrong_question_id)
  return Number.isFinite(id) && id > 0 ? id : 0
}

function buildKnowledgeMetrics(result) {
  var questions = Array.isArray(result && result.questions) ? result.questions : []
  var stats = buildKnowledgeStats(questions)
  var metrics = sortAndSliceMetrics(stats)
  var usedNames = new Set(metrics.map(function(item) { return item.name }))
  fillSubjectBreakdown(metrics, usedNames, result, questions)
  fillOverallAndFallback(metrics, result)
  return metrics.slice(0, RADAR_SIZE)
}

function buildKnowledgeStats(questions) {
  var stats = new Map()
  questions.forEach(function(question) {
    var names = Array.isArray(question && question.knowledge_points)
      ? Array.from(new Set(question.knowledge_points.map(function(name) { return normalizeName(name, "") }).filter(Boolean)))
      : []
    names.forEach(function(name) {
      var item = stats.get(name)
      if (!item) { item = { name: name, questionCount: 0, correctCount: 0, wrongQuestionId: 0, source: "knowledge" }; stats.set(name, item) }
      item.questionCount += 1
      if (question.status === "correct") item.correctCount += 1
      if (!item.wrongQuestionId && question.status !== "correct") item.wrongQuestionId = firstWrongIdByQuestion(question)
    })
  })
  return stats
}

function sortAndSliceMetrics(stats) {
  var metrics = Array.from(stats.values()).map(function(item) {
    return Object.assign({}, item, { accuracyPct: item.questionCount ? Math.round(item.correctCount / item.questionCount * 100) : 0 })
  })
  metrics.sort(function(a, b) {
    if (b.questionCount !== a.questionCount) return b.questionCount - a.questionCount
    if (b.accuracyPct !== a.accuracyPct) return b.accuracyPct - a.accuracyPct
    return a.name.localeCompare(b.name, "zh-CN")
  })
  return metrics.slice(0, RADAR_SIZE)
}

function fillSubjectBreakdown(metrics, usedNames, result, questions) {
  var subjectBreakdown = Array.isArray(result && result.subject_breakdown) ? result.subject_breakdown : []
  for (var index = 0; index < subjectBreakdown.length && metrics.length < RADAR_SIZE; index += 1) {
    var subject = subjectBreakdown[index] || {}
    var name = normalizeName(subject.subject_name, "科目" + (index + 1))
    if (usedNames.has(name)) continue
    var matchingWrong = questions.find(function(question) {
      return normalizeName(question && question.subject_name, "") === name && question && question.status !== "correct" && firstWrongIdByQuestion(question)
    })
    metrics.push({ name: name, questionCount: Number(subject.question_count || 0), correctCount: Number(subject.correct_count || 0), accuracyPct: percentNumber(subject.accuracy), wrongQuestionId: firstWrongIdByQuestion(matchingWrong), source: "subject" })
    usedNames.add(name)
  }
}

function fillOverallAndFallback(metrics, result) {
  var overallAccuracy = percentNumber(result && result.accuracy)
  if (metrics.length < RADAR_SIZE) {
    var questions = Array.isArray(result && result.questions) ? result.questions : []
    metrics.push({ name: "综合表现", questionCount: Number(result && result.question_count || 0), correctCount: Number(result && result.correct_count || 0), accuracyPct: overallAccuracy, wrongQuestionId: firstWrongIdByQuestion(questions.find(function(q) { return q && q.status === "wrong" && firstWrongIdByQuestion(q) })), source: "overall" })
  }
  while (metrics.length < RADAR_SIZE) {
    var index = metrics.length + 1
    metrics.push({ name: "能力维度" + index, questionCount: Number(result && result.question_count || 0), correctCount: Number(result && result.correct_count || 0), accuracyPct: overallAccuracy, wrongQuestionId: 0, source: "fallback" })
  }
}

function buildRadar(items) {
  const center = 50
  const maxRadius = 42.5
  const points = []
  const radarItems = (items || []).slice(0, RADAR_SIZE).map((item, index) => {
    const angleDeg = RADAR_ANGLES[index]
    const angle = angleDeg * Math.PI / 180
    const ratio = clamp(item.accuracyPct, 0, 100) / 100
    const radius = maxRadius * ratio
    const x = center + Math.cos(angle) * radius
    const y = center + Math.sin(angle) * radius
    const tag = masteryTag(item.accuracyPct)
    points.push(`${x.toFixed(2)}% ${y.toFixed(2)}%`)
    return {
      ...item,
      index,
      displayName: shortName(item.name),
      tagLabel: tag.label,
      tagTone: tag.tone,
      pointX: x,
      pointY: y,
      pointStyle: `left:${x.toFixed(2)}%;top:${y.toFixed(2)}%;`,
    }
  })
  const radarEdges = radarItems.map((item, index) => {
    const next = radarItems[(index + 1) % radarItems.length]
    const x1 = Number(item.pointX)
    const y1 = Number(item.pointY)
    const x2 = Number(next.pointX)
    const y2 = Number(next.pointY)
    const dx = x2 - x1
    const dy = y2 - y1
    const length = Math.sqrt(dx * dx + dy * dy)
    const angle = Math.atan2(dy, dx) * 180 / Math.PI
    return {
      index,
      style: `left:${x1.toFixed(2)}%;top:${y1.toFixed(2)}%;width:${length.toFixed(2)}%;transform:rotate(${angle.toFixed(2)}deg);`,
    }
  })
  return {
    radarItems,
    radarEdges,
    radarPolygonStyle: `clip-path:polygon(${points.join(',')});-webkit-clip-path:polygon(${points.join(',')});`,
  }
}

function buildScoreRing(ratePct) {
  const rate = clamp(ratePct, 0, 100)
  if (rate <= 0 || rate >= 100) {
    return { showScoreRingCaps: false, scoreRingEndStyle: '' }
  }
  const angle = (-90 + rate * 3.6) * Math.PI / 180
  const radius = 46.3
  const x = 50 + Math.cos(angle) * radius
  const y = 50 + Math.sin(angle) * radius
  return {
    showScoreRingCaps: true,
    scoreRingEndStyle: `left:${x.toFixed(2)}%;top:${y.toFixed(2)}%;`,
  }
}

function buildTopItems(metrics) {
  return (metrics || [])
    .filter(item => item && item.source !== 'fallback')
    .slice()
    .sort((a, b) => {
      if (b.accuracyPct !== a.accuracyPct) return b.accuracyPct - a.accuracyPct
      if (b.questionCount !== a.questionCount) return b.questionCount - a.questionCount
      return a.name.localeCompare(b.name, 'zh-CN')
    })
    .slice(0, 3)
    .map((item, index) => ({
      ...item,
      rank: index + 1,
      displayName: shortName(item.name, 12),
      progressPct: clamp(item.accuracyPct, 0, 100),
    }))
}

function collectWrongIds(result) {
  const ids = []
  const seen = new Set()
  ;(Array.isArray(result && result.questions) ? result.questions : []).forEach((question) => {
    const id = firstWrongIdByQuestion(question)
    if (!id || seen.has(id)) return
    seen.add(id)
    ids.push(id)
  })
  return ids
}

module.exports = {
  RADAR_SIZE,
  RADAR_ANGLES,
  clamp,
  percentNumber,
  compactDuration,
  compactScore,
  normalizeName,
  shortName,
  masteryTag,
  encouragement,
  encouragementTail,
  firstWrongIdByQuestion,
  buildKnowledgeMetrics,
  buildKnowledgeStats,
  sortAndSliceMetrics,
  fillSubjectBreakdown,
  fillOverallAndFallback,
  buildRadar,
  buildScoreRing,
  buildTopItems,
  collectWrongIds,
}
