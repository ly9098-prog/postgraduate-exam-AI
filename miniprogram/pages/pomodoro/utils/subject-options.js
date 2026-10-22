const SUBJECT_ICON = {
  exam408: '/assets/icons/pomodoro-subject/monitor.svg',
  data_structure: '/assets/icons/pomodoro-subject/list-tree.svg',
  computer_organization: '/assets/icons/diagnosis-subject/computer-organization.svg',
  operating_system: '/assets/icons/diagnosis-subject/operating-system.svg',
  computer_network: '/assets/icons/diagnosis-subject/computer-network.svg',
  'math2-calculus': '/assets/icons/pomodoro-subject/square-function.svg',
  advanced_math: '/assets/icons/pomodoro-subject/square-function.svg',
  'math2-linalg': '/assets/icons/pomodoro-subject/grid-2x2.svg',
  linear_algebra: '/assets/icons/pomodoro-subject/grid-2x2.svg',
  english: '/assets/icons/pomodoro-subject/languages.svg',
  pol: '/assets/icons/pomodoro-subject/landmark.svg',
  politics: '/assets/icons/pomodoro-subject/landmark.svg',
}

const EXAM408_CORE_CODES = [
  'data_structure',
  'computer_organization',
  'operating_system',
  'computer_network',
]

function flattenSubjectTree(tree) {
  const result = []
  function walk(nodes) {
    const list = Array.isArray(nodes) ? nodes : []
    for (const node of list) {
      if (!node) continue
      const activeChildren = (node.children || []).filter(child => child.is_active !== false)
      if (activeChildren.length === 0) {
        result.push({
          id: node.subject_id,
          code: node.subject_code || '',
          name: node.subject_name || node.display_name || '',
        })
      } else {
        walk(activeChildren)
      }
    }
  }
  walk(tree || [])
  return result
}

function subjectIconByCode(code) {
  return SUBJECT_ICON[code] || '/assets/icons/pomodoro-subject/book-open.svg'
}

function withPresentation(subject) {
  if (!subject) return null
  const icon = subjectIconByCode(subject.code)
  return {
    ...subject,
    _icon: icon,
    _iconDark: icon.replace('.svg', '-dark.svg'),
  }
}

function findCoreSubjects(subjects) {
  return EXAM408_CORE_CODES
    .map(code => (subjects || []).find(item => item && item.code === code))
}

function buildSubjectChoices(tree) {
  const leaves = flattenSubjectTree(tree).map(withPresentation)
  const root = (Array.isArray(tree) ? tree : [])
    .find(item => item && item.subject_code === 'exam408')
  const coreSubjects = findCoreSubjects(leaves)
  const aggregate = root
    ? [{
      ...root,
      id: root.subject_id,
      code: root.subject_code,
      name: root.subject_name || root.display_name || '计算机综合',
      _isAggregate: true,
      _disabled: !coreSubjects.every(Boolean),
      _icon: subjectIconByCode(root.subject_code),
      _iconDark: subjectIconByCode(root.subject_code).replace('.svg', '-dark.svg'),
    }]
    : []
  return {
    leaves,
    coreSubjects,
    choices: aggregate.concat(leaves),
  }
}

function normalizeCachedSubjects(subjects) {
  const choices = (Array.isArray(subjects) ? subjects : []).map(withPresentation)
  const aggregate = choices.find(subject => subject && subject._isAggregate)
  const leaves = choices.filter(subject => subject && !subject._isAggregate)
  const coreSubjects = findCoreSubjects(leaves).filter(Boolean)
  return {
    choices,
    aggregate,
    leaves,
    coreSubjects,
  }
}

module.exports = {
  EXAM408_CORE_CODES,
  SUBJECT_ICON,
  flattenSubjectTree,
  subjectIconByCode,
  buildSubjectChoices,
  normalizeCachedSubjects,
}
