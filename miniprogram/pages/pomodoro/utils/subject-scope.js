const EXAM408_ROOT_CODE = 'exam408'
const EXAM408_CORE_CODES = [
  'data_structure',
  'computer_organization',
  'operating_system',
  'computer_network',
]
const EXAM408_ORDER = {
  exam408: 0,
  data_structure: 10,
  computer_organization: 20,
  operating_system: 30,
  computer_network: 40,
}

const EXTRA_STUDY_CODES = new Set([
  'advanced_math', 'math2-calculus',
  'linear_algebra', 'math2-linalg',
  'english',
  'politics', 'pol',
])
const EXTRA_PARENT_CODES = new Set(['math', 'math2'])
const EXTRA_STUDY_NAMES = new Set(['高等数学', '高数', '线性代数', '线代', '英语', '政治'])

function readCode(item) {
  if (!item) return ''
  return String(item.product_code || item.subject_code || item.code || '').trim().toLowerCase()
}

function readName(item) {
  if (!item) return ''
  return String(item.display_name || item.subject_name || item.name || '').trim()
}

function stripProductNumber(value) {
  const text = String(value || '').replace(/408/g, '').replace(/\s{2,}/g, ' ').trim()
  return text || '计算机综合'
}

function productCodeOf(item) {
  const code = readCode(item)
  if (code === EXAM408_ROOT_CODE || EXAM408_CORE_CODES.includes(code)) return code
  return null
}

function is408Subject(item) {
  return Boolean(productCodeOf(item))
}

function is408CoreSubject(item) {
  return EXAM408_CORE_CODES.includes(productCodeOf(item))
}

function isExtraStudySubject(item) {
  return EXTRA_STUDY_CODES.has(readCode(item)) || EXTRA_STUDY_NAMES.has(readName(item))
}

function isExtraParent(item) {
  return EXTRA_PARENT_CODES.has(readCode(item))
}

function by408Order(a, b) {
  const aCode = productCodeOf(a)
  const bCode = productCodeOf(b)
  const aOrder = EXAM408_ORDER[aCode] == null ? 999 : EXAM408_ORDER[aCode]
  const bOrder = EXAM408_ORDER[bCode] == null ? 999 : EXAM408_ORDER[bCode]
  if (aOrder !== bOrder) return aOrder - bOrder
  const as = Number(a && a.sort_order) || 0
  const bs = Number(b && b.sort_order) || 0
  return as - bs
}

function byStudyOrder(a, b) {
  const a408 = productCodeOf(a)
  const b408 = productCodeOf(b)
  if (a408 || b408) return by408Order(a, b)
  const as = Number(a && a.sort_order) || 0
  const bs = Number(b && b.sort_order) || 0
  if (as !== bs) return as - bs
  return Number((a && (a.subject_id || a.id)) || 0) - Number((b && (b.subject_id || b.id)) || 0)
}

function filter408Items(items) {
  return (Array.isArray(items) ? items : []).filter(is408Subject).sort(by408Order)
}

function sanitizeNode(item, children) {
  const result = { ...item, children }
  if (Object.prototype.hasOwnProperty.call(result, 'display_name')) result.display_name = stripProductNumber(result.display_name)
  if (Object.prototype.hasOwnProperty.call(result, 'subject_name')) result.subject_name = stripProductNumber(result.subject_name)
  if (Object.prototype.hasOwnProperty.call(result, 'name')) result.name = stripProductNumber(result.name)
  return result
}

function filterStudyNode(item) {
  if (!item) return null
  const isExtra = isExtraStudySubject(item)
  const isParent = isExtraParent(item)
  const isComputer = is408Subject(item)
  if (item.is_active === false) return null

  const children = (Array.isArray(item.children) ? item.children : [])
    .map(filterStudyNode)
    .filter(Boolean)
    .sort(byStudyOrder)

  // Keep the existing computer-science catalog, the four explicitly restored
  // subjects, and parent nodes needed to group the math leaves.
  if (!isComputer && !isExtra && !(isParent && children.length > 0)) return null
  return sanitizeNode(item, children)
}

function filter408SubjectTree(tree) {
  return (Array.isArray(tree) ? tree : [])
    .map(filterStudyNode)
    .filter(Boolean)
    .sort(byStudyOrder)
}

module.exports = {
  EXAM408_ROOT_CODE,
  EXAM408_CORE_CODES,
  productCodeOf,
  is408Subject,
  is408CoreSubject,
  isExtraStudySubject,
  stripProductNumber,
  filter408Items,
  filter408SubjectTree,
}
