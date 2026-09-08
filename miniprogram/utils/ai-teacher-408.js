const ACTIONS = [
  { action: 'explain_correct', label: '正确选项为什么对', shortLabel: '正确项为什么对' },
  { action: 'explain_options', label: '为什么 A/B/C/D 错', shortLabel: '逐项排除' },
  { action: 'core_concept', label: '这道题真正考什么', shortLabel: '真正考点' },
  { action: 'similar_question', label: '给我一道同类题', shortLabel: '同类题' },
  { action: 'harder_question', label: '给我一道更难的题', shortLabel: '更难一题' },
  { action: 'connect_knowledge', label: '帮我串联相关知识点', shortLabel: '知识串联' },
  { action: 'high_frequency_traps', label: '总结这个知识点的高频陷阱', shortLabel: '高频陷阱' },
]

const ACTION_BY_KEY = ACTIONS.reduce((map, item) => {
  map[item.action] = item
  return map
}, {})

const STRUCTURED_ANALYSIS_KEYS = [
  { keys: ['mistake_diagnosis', 'mistakeDiagnosis', 'error_analysis', 'diagnosis', '错因诊断'], heading: '错因诊断' },
  { keys: ['knowledge_patch', 'knowledgePatch', 'knowledge_weakness', 'knowledgeGap', '知识补漏', '补漏重点'], heading: '知识补漏' },
  { keys: ['review_task', 'reviewTask', 'review_plan', 'suggestion', '复练任务', '复习建议'], heading: '复练建议' },
  { keys: ['analysis', 'explanation', 'solution', 'answer_analysis', '题目解析', '解析'], heading: '题目解析' },
]

function cleanText(value) {
  return String(value == null ? '' : value).trim()
}

function tryParseObject(value) {
  if (value && typeof value === 'object' && !Array.isArray(value)) return value
  let text = cleanText(value)
  if (!text) return null
  if (text.startsWith('```')) {
    const firstBreak = text.indexOf('\n')
    if (firstBreak >= 0) text = text.slice(firstBreak + 1)
    text = text.replace(/```\s*$/, '').trim()
  }
  const left = text.indexOf('{')
  const right = text.lastIndexOf('}')
  if (left >= 0 && right > left) text = text.slice(left, right + 1)
  try {
    const parsed = JSON.parse(text)
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : null
  } catch (_) {
    return null
  }
}

function textPoints(value, limit = 5) {
  if (Array.isArray(value)) {
    return value.map(item => {
      if (item && typeof item === 'object') {
        return cleanText(item.text || item.content || item.point || item.description || '')
      }
      return cleanText(item)
    }).filter(Boolean).slice(0, limit)
  }
  if (value && typeof value === 'object') {
    const preferred = value.text || value.content || value.summary || value.description || value.reason
    if (preferred) return [cleanText(preferred)].filter(Boolean)
    return Object.values(value).map(item => cleanText(item)).filter(text => text && text !== '[object Object]').slice(0, limit)
  }
  const text = cleanText(value)
  return text ? [text] : []
}

function structuredSections(value) {
  const obj = tryParseObject(value)
  if (!obj) return []
  const result = []
  const used = new Set()
  STRUCTURED_ANALYSIS_KEYS.forEach(group => {
    let picked
    for (const key of group.keys) {
      if (Object.prototype.hasOwnProperty.call(obj, key) && obj[key] != null && obj[key] !== '') {
        picked = obj[key]
        used.add(key)
        break
      }
    }
    const points = textPoints(picked)
    if (points.length) result.push({ heading: group.heading, points })
  })
  // Some historical payloads use arbitrary human-readable section keys. Render
  // their values as text instead of exposing the JSON source to the user.
  if (!result.length) {
    Object.keys(obj).slice(0, 4).forEach(key => {
      const points = textPoints(obj[key])
      if (points.length) result.push({ heading: cleanText(key).replace(/_/g, ' '), points })
    })
  }
  return result
}

function normalizeSections(rawSections) {
  const sections = []
  ;(Array.isArray(rawSections) ? rawSections : []).forEach((item, index) => {
    if (!item || typeof item !== 'object') return
    const heading = cleanText(item.heading) || `要点 ${index + 1}`
    const points = []
    ;(Array.isArray(item.points) ? item.points : []).forEach(point => {
      const nested = structuredSections(point)
      if (nested.length) {
        nested.forEach(section => sections.push(section))
      } else {
        const text = cleanText(point)
        if (text) points.push(text)
      }
    })
    if (points.length) sections.push({ heading, points: points.slice(0, 5) })
  })
  return sections
}

function dedupeSections(items) {
  const seen = new Set()
  const result = []
  ;(items || []).forEach((item, index) => {
    const points = (item.points || []).map(cleanText).filter(Boolean).slice(0, 5)
    if (!points.length) return
    const heading = cleanText(item.heading) || `要点 ${index + 1}`
    const key = `${heading}|${points.join('|')}`
    if (seen.has(key)) return
    seen.add(key)
    result.push({ key: `${result.length}-${heading}`, heading, points })
  })
  return result.slice(0, 8)
}

function normalizeResult(raw) {
  let source = raw
  if (typeof source === 'string') source = tryParseObject(source)
  if (!source || typeof source !== 'object' || Array.isArray(source)) return null
  if (source.result && typeof source.result === 'object') source = source.result
  if (source.data && typeof source.data === 'object' && !source.action && !source.sections) source = source.data

  const summaryStructured = structuredSections(source.summary)
  const sections = dedupeSections([
    ...summaryStructured,
    ...normalizeSections(source.sections),
  ])
  let summary = cleanText(source.summary)
  if (summaryStructured.length) {
    summary = summaryStructured[0].points[0] || ''
  } else if (tryParseObject(summary)) {
    // Never expose JSON source when parsing succeeded but there was no known key.
    summary = sections.length ? sections[0].points[0] : ''
  }

  const knowledgePoints = Array.isArray(source.knowledge_points)
    ? source.knowledge_points.map((item, index) => ({
      key: `${index}-${cleanText(item && item.name)}`,
      name: cleanText(item && item.name),
      relation: cleanText(item && item.relation),
      masteryHint: cleanText(item && (item.mastery_hint || item.masteryHint)),
    })).filter(item => item.name).slice(0, 8)
    : []

  const practiceRaw = source.practice_question || source.practiceQuestion
  let practiceQuestion = null
  if (practiceRaw && typeof practiceRaw === 'object') {
    const options = practiceRaw.options && typeof practiceRaw.options === 'object'
      ? Object.keys(practiceRaw.options).map(key => ({ key, text: cleanText(practiceRaw.options[key]) })).filter(item => item.text)
      : []
    practiceQuestion = {
      stem: cleanText(practiceRaw.stem),
      options,
      answer: cleanText(practiceRaw.answer),
      analysis: cleanText(practiceRaw.analysis),
      difficultyDelta: Number(practiceRaw.difficulty_delta ?? practiceRaw.difficultyDelta ?? 0) || 0,
    }
  }

  const action = cleanText(source.action)
  const actionMeta = ACTION_BY_KEY[action] || {}
  return {
    action,
    actionLabel: cleanText(source.action_label || source.actionLabel) || actionMeta.label || 'AI 老师',
    title: cleanText(source.title) || actionMeta.label || 'AI 老师',
    summary,
    sections,
    knowledgePoints,
    practiceQuestion,
    nextAction: source.next_action || source.nextAction || null,
    fromFallback: !!(source.from_fallback ?? source.fromFallback),
    personalization: source.personalization || {},
    promptVersion: cleanText(source.prompt_version || source.promptVersion),
  }
}

function errorMessage(error, api) {
  const raw = api && typeof api.getErrorMessage === 'function'
    ? api.getErrorMessage(error)
    : cleanText(error && error.message)
  if (raw.includes('exam_in_progress_ai_blocked') || raw.includes('考试进行中')) {
    return '考试进行中不开放答案型 AI 讲解，请交卷后再使用。'
  }
  return raw || 'AI 老师暂不可用，请稍后重试'
}

async function submitFeedback(api, options) {
  const opts = options || {}
  if (!api || typeof api.post !== 'function' || !opts.questionId || !opts.feedbackType) return false
  const result = opts.result || {}
  const detail = [
    result.action ? `action=${result.action}` : '',
    result.promptVersion ? `prompt_version=${result.promptVersion}` : '',
    result.fromFallback ? 'fallback=1' : 'fallback=0',
  ].filter(Boolean).join(';')
  await api.post('/ai/feedback', {
    source: '408_teacher',
    feedback_type: String(opts.feedbackType),
    question_id: Number(opts.questionId),
    detail,
  })
  return true
}

module.exports = {
  ACTIONS,
  ACTION_BY_KEY,
  normalizeResult,
  errorMessage,
  submitFeedback,
}
