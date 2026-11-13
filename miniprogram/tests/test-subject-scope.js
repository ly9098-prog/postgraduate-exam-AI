const assert = require('node:assert/strict')
const { test } = require('node:test')

const scopes = [
  ['shared', require('../utils/subject-scope')],
  ['study', require('../subpackages/study/utils/subject-scope')],
  ['pomodoro', require('../pages/pomodoro/utils/subject-scope')],
]

for (const [name, scope] of scopes) {
  test(`${name}: disabled subjects and disabled parents are excluded`, () => {
    const tree = [
      { subject_id: 1, subject_code: 'math', is_active: false, children: [
        { subject_id: 2, subject_code: 'advanced_math', is_active: true },
      ] },
      { subject_id: 3, subject_code: 'linear_algebra', is_active: false },
      { subject_id: 4, subject_code: 'english', is_active: false },
      { subject_id: 5, subject_code: 'pol', is_active: false },
      { subject_id: 6, subject_code: 'exam408', is_active: false, children: [
        { subject_id: 7, subject_code: 'data_structure', is_active: true },
      ] },
    ]
    assert.deepEqual(scope.filter408SubjectTree(tree), [])
  })

  test(`${name}: enabled catalog and responses without flags remain supported`, () => {
    const tree = [{ subject_id: 1, subject_code: 'math', is_active: true, children: [
      { subject_id: 2, subject_code: 'advanced_math', is_active: true },
      { subject_id: 3, subject_code: 'linear_algebra' },
    ] }]
    const result = scope.filter408SubjectTree(tree)
    assert.deepEqual(result[0].children.map(item => item.subject_id), [2, 3])
    assert.equal(tree[0].children.length, 2)
  })
}
