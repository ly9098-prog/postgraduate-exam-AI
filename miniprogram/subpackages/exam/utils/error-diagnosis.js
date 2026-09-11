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
    userConfirmed: !!(raw.user_confirmed ?? raw.userConfirmed),
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

module.exports = {
  TAXONOMY,
  QUICK_TYPES,
  normalizeType,
  labelOf,
  normalizeDiagnosis,
}
