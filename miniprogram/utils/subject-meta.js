/**
 * 科目编码与中文名称映射。
 *
 * 仅用于展示兜底。业务标识始终使用 subject_id；subject_code 只接受数据库
 * canonical code，不再解析历史别名。
 */

const SUBJECT_META = {
  exam408: { name: '408', shortName: '408' },
  data_structure: { name: '数据结构', shortName: '数据结构' },
  computer_organization: { name: '计算机组成原理', shortName: '计组' },
  operating_system: { name: '操作系统', shortName: '操作系统' },
  computer_network: { name: '计算机网络', shortName: '网络' },

  // 非 408 科目仅保留展示定义；当前产品入口不会暴露这些科目。
  math: { name: '数学', shortName: '数学' },
  advanced_math: { name: '高等数学', shortName: '高数' },
  linear_algebra: { name: '线性代数', shortName: '线代' },
  politics: { name: '政治', shortName: '政治' },
  english: { name: '英语', shortName: '英语' },
}

function getSubjectName(code) {
  if (!code) return '其他科目'
  const meta = SUBJECT_META[String(code).trim().toLowerCase()]
  return meta ? meta.name : '其他科目'
}

function getSubjectShortName(code) {
  if (!code) return '其他'
  const meta = SUBJECT_META[String(code).trim().toLowerCase()]
  return meta ? meta.shortName : '其他'
}

function normalizeSubjectCode(code) {
  if (!code) return ''
  const normalized = String(code).trim().toLowerCase()
  return SUBJECT_META[normalized] ? normalized : ''
}

module.exports = {
  SUBJECT_META,
  getSubjectName,
  getSubjectShortName,
  normalizeSubjectCode,
}
