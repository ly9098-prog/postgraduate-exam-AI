/**
 * 科目编码与中文名称统一映射
 *
 * 仅作「离线展示兜底」使用：当接口未返回 subject_name 时，用编码映射出显示名称。
 * 禁止用于业务 ID、请求参数或数据关联 —— 业务标识统一使用 API 返回的 subject_id。
 * 各页面应从 /practice/subjects 或 practice-subjects 接口加载科目数据。
 */

const SUBJECT_META = {
  // ── 新树形科目编码 ──
  // 数学大类（用于错题本筛选等通用分类）
  math: {
    name: '数学',
    shortName: '数学',
    aliases: [],
  },
  advanced_math: {
    name: '高等数学',
    shortName: '高数',
    aliases: ['higher_math', 'math2', 'math2-calculus'],
  },
  linear_algebra: {
    name: '线性代数',
    shortName: '线代',
    aliases: ['linalg', 'math2-linalg'],
  },
  computer: {
    name: '计算机基础',
    shortName: '计算机',
    aliases: ['cs', 'computer_science'],
  },
  data_structure: {
    name: '数据结构',
    shortName: '数据结构',
    aliases: ['ds', 'exam408-ds'],
  },
  computer_organization: {
    name: '计组',
    shortName: '计组',
    aliases: ['co', 'exam408-co'],
  },
  operating_system: {
    name: '操作系统',
    shortName: '操作系统',
    aliases: ['os', 'exam408-os'],
  },
  computer_network: {
    name: '计算机网络',
    shortName: '网络',
    aliases: ['cn', 'exam408-cn'],
  },
  politics: {
    name: '政治',
    shortName: '政治',
    aliases: ['pol'],
  },
  english: {
    name: '英语',
    shortName: '英语',
    aliases: ['eng'],
  },

  // ── 旧兼容编码（映射到新编码）──
  math2: { name: '数学二', shortName: '数学', aliases: [] },
  'math2-calculus': { name: '数学二·高数', shortName: '高数', aliases: [] },
  'math2-linalg': { name: '数学二·线代', shortName: '线代', aliases: [] },
  exam408: { name: '408', shortName: '408', aliases: [] },
  'exam408-ds': { name: '408·DS', shortName: 'DS', aliases: [] },
  'exam408-os': { name: '408·OS', shortName: 'OS', aliases: [] },
  'exam408-co': { name: '408·CO', shortName: 'CO', aliases: [] },
  'exam408-cn': { name: '408·CN', shortName: 'CN', aliases: [] },
}

/** 解析科目名称 */
function getSubjectName(code) {
  if (!code) return '其他科目'
  const meta = SUBJECT_META[code]
  if (meta) return meta.name
  // 别名查找
  for (const key of Object.keys(SUBJECT_META)) {
    if (SUBJECT_META[key].aliases && SUBJECT_META[key].aliases.indexOf(code) >= 0) {
      return SUBJECT_META[key].name
    }
  }
  return '其他科目'
}

/** 解析科目短名称 */
function getSubjectShortName(code) {
  if (!code) return '其他'
  const meta = SUBJECT_META[code]
  if (meta) return meta.shortName
  for (const key of Object.keys(SUBJECT_META)) {
    if (SUBJECT_META[key].aliases && SUBJECT_META[key].aliases.indexOf(code) >= 0) {
      return SUBJECT_META[key].shortName
    }
  }
  return '其他'
}

/** 标准化科目编码 */
function normalizeSubjectCode(code) {
  if (!code) return ''
  if (SUBJECT_META[code]) return code
  for (const key of Object.keys(SUBJECT_META)) {
    if (SUBJECT_META[key].aliases && SUBJECT_META[key].aliases.indexOf(code) >= 0) {
      return key
    }
  }
  return code
}

module.exports = {
  SUBJECT_META,
  getSubjectName,
  getSubjectShortName,
  normalizeSubjectCode,
}
