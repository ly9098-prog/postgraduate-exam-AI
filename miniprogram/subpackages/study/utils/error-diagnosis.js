const TAXONOMY = [
  { type: 'knowledge_gap', label: '知识点不会', description: '相关知识、规则或结论尚未掌握' },
  { type: 'concept_confusion', label: '概念混淆', description: '相近概念、条件或边界混在一起' },
  { type: 'memory_error', label: '记忆错误', description: '定义、公式或固定结论记错/忘记' },
  { type: 'calculation_error', label: '计算错误', description: '计算、换算或中间数值处理出错' },
  { type: 'misread', label: '审题错误', description: '遗漏或误读题干、限定条件或选项信息' },
  { type: 'reasoning_error', label: '推理/思路错误', description: '算法、推理链路或解题思路出现偏差' },
  { type: 'time_pressure', label: '时间不足', description: '受时间压力影响，没有完整判断或检查' },
  { type: 'careless', label: '粗心', description: '本来会做，但因操作、抄写或检查疏漏出错' },
  { type: 'unknown', label: '暂未分类', description: '目前证据不足或尚未确认' },
]

const BY_TYPE = TAXONOMY.reduce((map, item) => {
  map[item.type] = item
  return map
}, {})

const LEGACY_MAP = {
  concept_mistake: 'concept_confusion',
  concept: 'concept_confusion',
  calculation: 'calculation_error',
  memory: 'memory_error',
  method: 'reasoning_error',
  logic: 'reasoning_error',
  other: 'unknown',
}

function normalizeType(value) {
  const raw = String(value || '').trim()
  const type = LEGACY_MAP[raw] || raw
  return BY_TYPE[type] ? type : 'unknown'
}

function labelOf(value) {
  const type = normalizeType(value)
  return (BY_TYPE[type] && BY_TYPE[type].label) || '暂未分类'
}

function normalizeDiagnosis(raw) {
  if (!raw || typeof raw !== 'object') return null
  // Dedicated diagnosis endpoints may wrap the occurrence under `diagnosis`
  // or `data`, while the wrong-question detail may embed it directly. Accept
  // all three shapes so a saved user diagnosis always rehydrates correctly.
  if (raw.diagnosis && typeof raw.diagnosis === 'object') raw = raw.diagnosis
  else if (raw.data && typeof raw.data === 'object' && (
    raw.data.primary_type || raw.data.primaryType || raw.data.user_confirmed !== undefined || raw.data.userConfirmed !== undefined
  )) raw = raw.data
  const hasDiagnosisSignal = raw.primary_type !== undefined || raw.primaryType !== undefined ||
    raw.secondary_types !== undefined || raw.secondaryTypes !== undefined ||
    raw.user_confirmed !== undefined || raw.userConfirmed !== undefined ||
    raw.ai_primary_type !== undefined || raw.aiPrimaryType !== undefined ||
    raw.effective_source !== undefined || raw.effectiveSource !== undefined
  if (!hasDiagnosisSignal) return null
  const primaryType = normalizeType(raw.primary_type || raw.primaryType)
  const secondaryTypes = (raw.secondary_types || raw.secondaryTypes || [])
    .map(normalizeType)
    .filter((type, index, list) => type !== 'unknown' && type !== primaryType && list.indexOf(type) === index)
    .slice(0, 3)
  const aiPrimaryType = raw.ai_primary_type || raw.aiPrimaryType
    ? normalizeType(raw.ai_primary_type || raw.aiPrimaryType)
    : null
  const aiSecondaryTypes = (raw.ai_secondary_types || raw.aiSecondaryTypes || [])
    .map(normalizeType)
    .filter((type, index, list) => type !== 'unknown' && type !== aiPrimaryType && list.indexOf(type) === index)
    .slice(0, 3)
  const confidence = Number(raw.ai_confidence ?? raw.aiConfidence)
  return Object.assign({}, raw, {
    primaryType,
    primaryLabel: raw.primary_label || raw.primaryLabel || labelOf(primaryType),
    secondaryTypes,
    secondaryLabels: secondaryTypes.map(labelOf),
    effectiveSource: raw.effective_source || raw.effectiveSource || 'unknown',
    // Older persisted rows may omit user_confirmed, and some API versions can
    // persist a manual primary_type while returning user_confirmed=false. A
    // user-sourced diagnosis is authoritative and must rehydrate as confirmed.
    userConfirmed: (raw.user_confirmed === true || raw.userConfirmed === true) ||
      (primaryType !== 'unknown' && String(raw.effective_source || raw.effectiveSource || '').toLowerCase() === 'user') ||
      ((raw.user_confirmed === undefined && raw.userConfirmed === undefined) &&
        primaryType !== 'unknown' && String(raw.effective_source || raw.effectiveSource || '').toLowerCase() !== 'ai'),
    aiStatus: raw.ai_status || raw.aiStatus || 'not_requested',
    aiPrimaryType,
    aiPrimaryLabel: aiPrimaryType ? (raw.ai_primary_label || raw.aiPrimaryLabel || labelOf(aiPrimaryType)) : '',
    aiSecondaryTypes,
    aiSecondaryLabels: aiSecondaryTypes.map(labelOf),
    aiConfidence: Number.isFinite(confidence) ? Math.round(confidence * 100) : null,
    aiReason: String(raw.ai_reason || raw.aiReason || ''),
  })
}

const QUICK_TYPES = [
  'knowledge_gap', 'concept_confusion', 'misread', 'careless', 'calculation_error', 'reasoning_error'
].map(type => BY_TYPE[type])



// Confirmed diagnosis -> concrete next action. Kept next to the taxonomy so
// routing cannot drift from error-type normalization.
function positiveInt(value) {
  const n = Number(value)
  return Number.isInteger(n) && n > 0 ? n : 0
}

function firstKnowledgePointId(wq) {
  if (!wq) return 0
  const direct = positiveInt(wq.knowledge_point_id || wq.knowledgePointId)
  if (direct) return direct
  const list = Array.isArray(wq.knowledge_points) ? wq.knowledge_points : (Array.isArray(wq.knowledgePoints) ? wq.knowledgePoints : [])
  for (let i = 0; i < list.length; i++) {
    const item = list[i]
    const id = positiveInt(item && (item.id || item.knowledge_point_id || item.knowledgePointId))
    if (id) return id
  }
  return 0
}

function routeParamsForPractice(wq, count, mode) {
  const params = { count: count || 6, mode: mode || 'smart', source: 'error_route' }
  const subjectId = positiveInt(wq && (wq.subject_id || wq.subjectId))
  const subjectCode = String(wq && (wq.subject_code || wq.subjectCode) || '').trim().slice(0, 64)
  const pointId = firstKnowledgePointId(wq)
  if (subjectId) params.subject_id = subjectId
  else if (subjectCode) params.subject_code = subjectCode
  if (pointId) params.knowledge_point_id = pointId
  if (pointId) params.include_children = 1
  return params
}

const ACTIONS = {
  knowledge_gap: {
    title: '先补知识点，再回来重做',
    reason: '这是知识缺口型错误。先回到对应知识点建立定义、条件和边界，再用少量题验证。',
    actionLabel: '去补知识点',
    build(wq) {
      const pointId = firstKnowledgePointId(wq)
      const subjectId = positiveInt(wq && (wq.subject_id || wq.subjectId))
      if (pointId) return { route: 'knowledge_detail', routeParams: { knowledge_point_id: pointId } }
      if (subjectId) return { route: 'knowledge_subject', routeParams: { subject_id: subjectId } }
      return { route: 'practice', routeParams: routeParamsForPractice(wq, 6, 'smart') }
    },
  },
  concept_confusion: {
    title: '做一组同知识点辨析题',
    reason: '概念混淆需要用相近选项反复辨析，不建议只重新阅读解析。',
    actionLabel: '开始辨析训练',
    build: wq => ({ route: 'practice', routeParams: routeParamsForPractice(wq, 6, 'smart') }),
  },
  memory_error: {
    title: '进入今日复习',
    reason: '记忆型错误先进入今日复习循环，用时间间隔验证是否真正记住。',
    actionLabel: '去今日复习',
    build: () => ({ route: 'review_today', routeParams: {} }),
  },
  calculation_error: {
    title: '连续做 5 题同类计算',
    reason: '计算错误要靠连续输出校准步骤和边界，直到过程稳定。',
    actionLabel: '开始计算训练',
    build: wq => ({ route: 'practice', routeParams: routeParamsForPractice(wq, 5, 'smart') }),
  },
  reasoning_error: {
    title: '用同类题重建推理链',
    reason: '思路型错误需要换题重新推导，而不是重复看原题答案。',
    actionLabel: '开始同类训练',
    build: wq => ({ route: 'practice', routeParams: routeParamsForPractice(wq, 6, 'smart') }),
  },
  misread: {
    title: '做 10 题审题训练',
    reason: '审题错误不需要继续堆知识输入，改用一小组选择题训练关键词与条件识别。',
    actionLabel: '开始审题训练',
    build: wq => ({ route: 'practice', routeParams: routeParamsForPractice(wq, 10, 'random') }),
  },
  careless: {
    title: '做 10 题稳定性训练',
    reason: '粗心只有在稳定做对后才算解决；用短题组检查选项、单位和计算过程。',
    actionLabel: '开始稳定训练',
    build: wq => ({ route: 'practice', routeParams: routeParamsForPractice(wq, 10, 'random') }),
  },
  time_pressure: {
    title: '进入选择题套卷训练',
    reason: '时间压力需要在连续选择题环境中训练节奏，而不是单题继续思考。',
    actionLabel: '去套卷训练',
    build: () => ({ route: 'exam_list', routeParams: {} }),
  },
  unknown: {
    title: '先确认错因',
    reason: '错因未明确前不自动安排训练，避免把时间投到错误方向。',
    actionLabel: '记录错因',
    build: () => ({ route: 'diagnosis', routeParams: {} }),
  },
}

function buildNextAction(wq, diagnosis) {
  // Legacy diagnosis records can still carry the old taxonomy name, so normalize
  // before the ACTIONS lookup instead of falling through to the unknown action.
  const primary = normalizeType(String(
    diagnosis && (diagnosis.primaryType || diagnosis.primary_type) ||
    wq && (wq.error_type || wq.errorType) ||
    'unknown'
  ))
  const spec = ACTIONS[primary] || ACTIONS.unknown
  const route = spec.build(wq || {})
  return {
    type: primary,
    title: spec.title,
    reason: spec.reason,
    actionLabel: spec.actionLabel,
    route: route.route,
    routeParams: route.routeParams || {},
  }
}

module.exports = {
  TAXONOMY,
  QUICK_TYPES,
  normalizeType,
  labelOf,
  normalizeDiagnosis,
  buildNextAction,
  firstKnowledgePointId,
}
