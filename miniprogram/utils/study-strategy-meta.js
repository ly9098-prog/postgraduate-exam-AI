const STUDY_STRATEGY_STORAGE_KEY = 'study_strategy_v1'
const SCHEMA_VERSION = 1
const CHOICE_TOTAL_POINTS = 80
const CHOICE_LOSS_BUDGET_POINTS = 8
const CHOICE_TARGET_POINTS = CHOICE_TOTAL_POINTS - CHOICE_LOSS_BUDGET_POINTS

const SUBJECTS = [
  { code: 'data_structure', name: '数据结构', shortName: '数据结构', choiceQuestions: 11, defaultStage: 'maintenance', defaultWeight: 15 },
  { code: 'computer_organization', name: '计算机组成原理', shortName: '计组', choiceQuestions: 12, defaultStage: 'second_round', defaultWeight: 35 },
  { code: 'operating_system', name: '操作系统', shortName: '操作系统', choiceQuestions: 10, defaultStage: 'not_started', defaultWeight: 35 },
  { code: 'computer_network', name: '计算机网络', shortName: '计网', choiceQuestions: 7, defaultStage: 'not_started', defaultWeight: 15 },
]

const STAGES = [
  { value: 'not_started', label: '未开始', hint: '优先建立课程/教材进度' },
  { value: 'strengthening', label: '强化中', hint: '输入与章节检测并行' },
  { value: 'second_round', label: '二轮刷题', hint: '以选择题专项和错题为主' },
  { value: 'exam', label: '真题检测', hint: '以选择题套卷暴露漏洞' },
  { value: 'maintenance', label: '保温', hint: '低频复习，避免挤占短板时间' },
]

const STAGE_MAP = STAGES.reduce((map, item, index) => {
  map[item.value] = { ...item, index }
  return map
}, {})
const SUBJECT_MAP = SUBJECTS.reduce((map, item) => {
  map[item.code] = item
  return map
}, {})

function clamp(value, min, max) {
  const n = Number(value)
  if (!Number.isFinite(n)) return min
  return Math.max(min, Math.min(max, n))
}

function stageLabel(stage) {
  return STAGE_MAP[stage] ? STAGE_MAP[stage].label : '未开始'
}

function subjectCodeFromItem(item) {
  const code = String(item && (item.subjectCode || item.subject_code || item.code || item.subject) || '').toLowerCase()
  if (SUBJECT_MAP[code]) return code
  const name = String(item && (item.subjectName || item.subject_name || item.name || item.label) || '')
  if (name.includes('数据结构')) return 'data_structure'
  if (name.includes('组成') || name.includes('计组')) return 'computer_organization'
  if (name.includes('操作系统')) return 'operating_system'
  if (name.includes('网络') || name.includes('计网')) return 'computer_network'
  return ''
}

module.exports = {
  STUDY_STRATEGY_STORAGE_KEY,
  SCHEMA_VERSION,
  CHOICE_TOTAL_POINTS,
  CHOICE_LOSS_BUDGET_POINTS,
  CHOICE_TARGET_POINTS,
  SUBJECTS,
  STAGES,
  STAGE_MAP,
  SUBJECT_MAP,
  clamp,
  stageLabel,
  subjectCodeFromItem,
}
