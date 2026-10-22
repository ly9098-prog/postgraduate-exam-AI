const assert = require('node:assert/strict')
const {
  buildSubjectChoices,
  flattenSubjectTree,
  normalizeCachedSubjects,
  subjectIconByCode,
} = require('../pages/pomodoro/utils/subject-options')

const tree = [
  {
    subject_id: 408,
    subject_code: 'exam408',
    subject_name: '计算机综合',
    children: [
      { subject_id: 1, subject_code: 'data_structure', subject_name: '数据结构', children: [] },
      { subject_id: 2, subject_code: 'computer_organization', subject_name: '计算机组成原理', children: [] },
      { subject_id: 3, subject_code: 'operating_system', subject_name: '操作系统', children: [] },
      { subject_id: 4, subject_code: 'computer_network', subject_name: '计算机网络', children: [] },
    ],
  },
  { subject_id: 5, subject_code: 'politics', subject_name: '政治', children: [] },
]

assert.deepEqual(flattenSubjectTree(tree), [
  { id: 1, code: 'data_structure', name: '数据结构' },
  { id: 2, code: 'computer_organization', name: '计算机组成原理' },
  { id: 3, code: 'operating_system', name: '操作系统' },
  { id: 4, code: 'computer_network', name: '计算机网络' },
  { id: 5, code: 'politics', name: '政治' },
])

assert.equal(subjectIconByCode('data_structure'), '/assets/icons/pomodoro-subject/list-tree.svg')
assert.equal(subjectIconByCode('unknown'), '/assets/icons/pomodoro-subject/book-open.svg')

const built = buildSubjectChoices(tree)
assert.equal(built.choices.length, 6)
assert.equal(built.choices[0]._isAggregate, true)
assert.equal(built.choices[0]._disabled, false)
assert.equal(built.choices[0]._icon, '/assets/icons/pomodoro-subject/monitor.svg')
assert.equal(built.choices[1]._icon, '/assets/icons/pomodoro-subject/list-tree.svg')
assert.equal(built.choices[1]._iconDark, '/assets/icons/pomodoro-subject/list-tree-dark.svg')

const missingCore = buildSubjectChoices([
  {
    subject_id: 408,
    subject_code: 'exam408',
    children: [
      { subject_id: 1, subject_code: 'data_structure', children: [] },
    ],
  },
])
assert.equal(missingCore.choices[0]._disabled, true)

const normalized = normalizeCachedSubjects([
  { id: 1, code: 'data_structure', name: '数据结构', _icon: '/stale.svg' },
  { id: 2, code: 'computer_organization', name: '组成' },
  { id: 3, code: 'operating_system', name: '系统' },
  { id: 4, code: 'computer_network', name: '网络' },
  { id: 408, code: 'exam408', name: '计算机综合', _isAggregate: true },
])
assert.equal(normalized.choices.find(item => item.id === 1)._icon, '/assets/icons/pomodoro-subject/list-tree.svg')
assert.equal(normalized.coreSubjects.length, 4)
assert.equal(normalized.leaves.length, 4)

assert.deepEqual(buildSubjectChoices(null), {
  leaves: [],
  coreSubjects: [undefined, undefined, undefined, undefined],
  choices: [],
})

console.log('Pomodoro subject options passed: flatten/presentation/aggregate/core')
