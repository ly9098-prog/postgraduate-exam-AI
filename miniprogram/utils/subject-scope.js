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

function readCode(item) {
  if (!item) return ''
  return String(item.product_code || item.subject_code || item.code || '').trim().toLowerCase()
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

function filter408Items(items) {
  return (Array.isArray(items) ? items : []).filter(is408Subject).sort(by408Order)
}

function filter408SubjectTree(tree) {
  const items = Array.isArray(tree) ? tree : []
  const roots = items.filter(item => productCodeOf(item) === EXAM408_ROOT_CODE)
  if (roots.length !== 1) return []

  const root = roots[0]
  if (root.is_active === false) return []
  const children = (Array.isArray(root.children) ? root.children : [])
    .filter(item => item.is_active !== false && is408CoreSubject(item))
    .sort(by408Order)

  const seen = new Set()
  for (const item of children) {
    const code = productCodeOf(item)
    if (seen.has(code)) return []
    seen.add(code)
  }
  return [{ ...root, product_code: EXAM408_ROOT_CODE, children }]
}

module.exports = {
  EXAM408_ROOT_CODE,
  EXAM408_CORE_CODES,
  productCodeOf,
  is408Subject,
  is408CoreSubject,
  filter408Items,
  filter408SubjectTree,
}
