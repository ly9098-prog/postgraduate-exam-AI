const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  normalizeSubjectTree,
  flattenSelectableSubjects,
  subjectMark,
  subjectIconMeta,
  decorateRecentSubjects,
  findParentSubjectId,
  subjectHasChildren,
  getPracticeSubjectScopeIds,
} = require('../subpackages/study/practice/utils/subject-tree')

const rawTree = [
  {
    id: 408,
    name: '计算机综合',
    code: 'exam408',
    parent_id: null,
    level: 1,
    sort_order: 1,
    children: [
      { subject_id: 2, display_name: '数据结构', parent_id: 408, level: 2, sort_order: 2, children: [] },
      { subject_id: 1, display_name: '组成原理', parent_id: 408, level: 2, sort_order: 1, children: [] },
      { subject_id: 9, display_name: '停用科目', parent_id: 408, level: 2, is_active: false, children: [] },
    ],
  },
  { subject_id: 20, display_name: '线性代数', parent_id: 19, level: 2, sort_order: 2 },
  { subject_id: 21, display_name: '高等数学', parent_id: 19, level: 2, sort_order: 1 },
]

function buildTree() {
  return normalizeSubjectTree(rawTree)
}

test('normalizes aliases, sorting, orphan children and presentation fields', () => {
  const tree = buildTree()
  assert.deepEqual(tree.map(item => item.subject_id), [21, 408, 20])
  const computerRoot = tree.find(item => item.subject_id === 408)
  assert.deepEqual(computerRoot.children.map(item => item.subject_id), [1, 2])
  assert.equal(computerRoot.flat_children.length, 2)
  assert.equal(computerRoot.descendant_count, 2)
  assert.deepEqual(computerRoot.flat_children[0], {
    subject_id: 1,
    display_name: '组成原理',
    raw_display_name: '组成原理',
    parent_id: 408,
    level: 2,
    has_children: false,
    depth: 1,
    indent_rpx: 0,
  })
  assert.equal(computerRoot.icon_type, 'computer')
  assert.equal(computerRoot.icon_mark, '')
  assert.equal(computerRoot.icon_src, '/assets/icons/practice-subject/monitor.svg')
  assert.deepEqual(normalizeSubjectTree([]), [])
})

test('flattens children before roots and preserves aggregate labels', () => {
  const tree = buildTree()
  const available = flattenSelectableSubjects(tree)
  assert.deepEqual(available.map(item => item.subject_id), [21, 1, 2, 408, 20])
  assert.deepEqual(available.find(item => item.subject_id === 408), {
    subject_id: 408,
    display_name: '计算机综合（全部）',
    parent_subject_id: 408,
    has_children: true,
  })
  assert.deepEqual(flattenSelectableSubjects(null), [])
})

test('builds subject marks and icons without page state', () => {
  assert.equal(subjectMark('数据结构'), '</>')
  assert.equal(subjectMark('高等数学'), 'Σ')
  assert.equal(subjectMark('英语'), 'A')
  assert.equal(subjectMark('政治'), '政')
  assert.equal(subjectMark(''), '·')
  assert.deepEqual(subjectIconMeta('计算机', 'data_structure'), {
    type: 'computer',
    mark: '',
    src: '/assets/icons/practice-subject/monitor.svg',
  })
  assert.equal(subjectIconMeta('高等数学').src, '/assets/icons/practice-subject/code-xml.svg')
  assert.equal(subjectIconMeta('未知').src, '')
})

test('decorates recent subjects and resolves tree relationships', () => {
  const tree = buildTree()
  const recent = decorateRecentSubjects([
    { subject_id: 2, display_name: '数据结构', parent_subject_id: 408, has_children: true },
    { subject_id: 408, display_name: '计算机综合', parent_subject_id: 408, has_children: true },
  ], id => subjectHasChildren(id, tree))
  assert.deepEqual(recent, [
    {
      subject_id: 2,
      display_name: '数据结构',
      parent_subject_id: 408,
      has_children: true,
      mark: '</>',
      icon_src: '/assets/icons/practice-subject/code-xml.svg',
      scope_label: '全部范围',
    },
    {
      subject_id: 408,
      display_name: '计算机综合',
      parent_subject_id: 408,
      has_children: true,
      mark: '</>',
      icon_src: '/assets/icons/practice-subject/code-xml.svg',
      scope_label: '全部范围',
    },
  ])
  assert.equal(findParentSubjectId(2, tree), 408)
  assert.equal(findParentSubjectId(408, tree), 408)
  assert.equal(findParentSubjectId(99, tree), null)
  assert.equal(subjectHasChildren(2, tree), false)
  assert.equal(subjectHasChildren(408, tree), true)
  assert.equal(subjectHasChildren(99, tree), false)
})

test('resolves direct and descendant practice scopes', () => {
  const tree = buildTree()
  assert.deepEqual(getPracticeSubjectScopeIds(2, false, tree), [2])
  assert.deepEqual(getPracticeSubjectScopeIds(408, true, tree), [408, 2, 1])
  assert.deepEqual(getPracticeSubjectScopeIds(99, true, tree), [])
  assert.deepEqual(getPracticeSubjectScopeIds(0, true, tree), [])
})
