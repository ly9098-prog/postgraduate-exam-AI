const EXAM408_ROOT_CODE = 'exam408'
const EXAM408_CORE_CODES = ['exam408-ds', 'exam408-co', 'exam408-os', 'exam408-cn']
const EXAM408_ORDER = {
  exam408: 0,
  'exam408-ds': 10,
  'exam408-co': 20,
  'exam408-os': 30,
  'exam408-cn': 40,
}

const CODE_ALIASES = {
  exam408: ['exam408', 'computer', '408', 'cs', 'computer_science'],
  'exam408-ds': ['exam408-ds', 'ds', 'data_structure'],
  'exam408-co': ['exam408-co', 'co', 'computer_organization'],
  'exam408-os': ['exam408-os', 'os', 'operating_system'],
  'exam408-cn': ['exam408-cn', 'cn', 'computer_network'],
}

const NAME_ALIASES = {
  '408': EXAM408_ROOT_CODE,
  '408计算机综合': EXAM408_ROOT_CODE,
  '计算机学科专业基础综合': EXAM408_ROOT_CODE,
  '计算机基础': EXAM408_ROOT_CODE,
  '数据结构': 'exam408-ds',
  '计算机组成原理': 'exam408-co',
  '组成原理': 'exam408-co',
  '计组': 'exam408-co',
  '操作系统': 'exam408-os',
  '计算机网络': 'exam408-cn',
  '计网': 'exam408-cn',
}

function readCode(item) {
  if (!item) return ''
  return String(item.product_code || item.subject_code || item.code || item.subject || '').trim()
}

function readName(item) {
  if (!item) return ''
  return String(item.subject_name || item.display_name || item.name || item.label || item.subject_label || '').trim()
}

function canonical408Code(code, name) {
  const raw = String(code || '').trim().toLowerCase()
  if (raw) {
    for (const canonical of Object.keys(CODE_ALIASES)) {
      if (CODE_ALIASES[canonical].includes(raw)) return canonical
    }
  }
  return NAME_ALIASES[String(name || '').trim()] || null
}

function productCodeOf(item) {
  return canonical408Code(readCode(item), readName(item))
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
  if (!items.length) return []

  const root = items.find(item => productCodeOf(item) === EXAM408_ROOT_CODE)
  if (root) {
    if (root.is_active === false) return []
    const children = (Array.isArray(root.children) ? root.children : [])
      .filter(item => item.is_active !== false && is408CoreSubject(item))
      .sort(by408Order)
    return [{ ...root, product_code: EXAM408_ROOT_CODE, children }]
  }

  // Compatibility fallback for legacy datasets that expose the four disciplines
  // without a 408 root. Never fall back to unrelated active subjects.
  return filter408Items(items).filter(is408CoreSubject)
}

module.exports = {
  EXAM408_ROOT_CODE,
  EXAM408_CORE_CODES,
  canonical408Code,
  productCodeOf,
  is408Subject,
  is408CoreSubject,
  filter408Items,
  filter408SubjectTree,
}
