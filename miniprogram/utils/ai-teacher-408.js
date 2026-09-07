const ACTIONS = [
  { action: 'explain_correct', label: '正确选项为什么对', shortLabel: '正确项为什么对' },
  { action: 'explain_options', label: '为什么 A/B/C/D 错', shortLabel: '逐项排除' },
  { action: 'core_concept', label: '这道题真正考什么', shortLabel: '真正考点' },
  { action: 'similar_question', label: '给我一道同类题', shortLabel: '同类题' },
  { action: 'harder_question', label: '给我一道更难的题', shortLabel: '更难一题' },
  { action: 'connect_knowledge', label: '帮我串联相关知识点', shortLabel: '知识串联' },
  { action: 'high_frequency_traps', label: '总结这个知识点的 408 高频陷阱', shortLabel: '408 高频陷阱' },
]

const ACTION_BY_KEY = ACTIONS.reduce((map, item) => {
  map[item.action] = item
  return map
}, {})

function cleanText(value) {
  return String(value == null ? '' : value).trim()
}

function normalizeResult(raw) {
  if (!raw || typeof raw !== 'object') return null
  const sections = Array.isArray(raw.sections) ? raw.sections.map((item, index) => ({
    key: `${index}-${cleanText(item && item.heading)}`,
    heading: cleanText(item && item.heading) || `要点 ${index + 1}`,
    points: Array.isArray(item && item.points)
      ? item.points.map(cleanText).filter(Boolean).slice(0, 5)
      : [],
  })).filter(item => item.points.length || item.heading) : []

  const knowledgePoints = Array.isArray(raw.knowledge_points)
    ? raw.knowledge_points.map((item, index) => ({
      key: `${index}-${cleanText(item && item.name)}`,
      name: cleanText(item && item.name),
      relation: cleanText(item && item.relation),
      masteryHint: cleanText(item && (item.mastery_hint || item.masteryHint)),
    })).filter(item => item.name).slice(0, 8)
    : []

  const practiceRaw = raw.practice_question || raw.practiceQuestion
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

  const action = cleanText(raw.action)
  const actionMeta = ACTION_BY_KEY[action] || {}
  return {
    action,
    actionLabel: cleanText(raw.action_label || raw.actionLabel) || actionMeta.label || '408 AI 老师',
    title: cleanText(raw.title) || actionMeta.label || '408 AI 老师',
    summary: cleanText(raw.summary),
    sections,
    knowledgePoints,
    practiceQuestion,
    nextAction: raw.next_action || raw.nextAction || null,
    fromFallback: !!(raw.from_fallback ?? raw.fromFallback),
    personalization: raw.personalization || {},
    promptVersion: cleanText(raw.prompt_version || raw.promptVersion),
  }
}


function errorMessage(error, api) {
  const raw = api && typeof api.getErrorMessage === 'function'
    ? api.getErrorMessage(error)
    : cleanText(error && error.message)
  if (raw.includes('exam_in_progress_ai_blocked') || raw.includes('考试进行中')) {
    return '考试进行中不开放答案型 AI 讲解，请交卷后再使用。'
  }
  return raw || '408 AI 老师暂不可用，请稍后重试'
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
