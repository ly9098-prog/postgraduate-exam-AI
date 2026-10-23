const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  RECENT_SUBJECTS_STORAGE_KEY,
  selectDefaultSubject,
  rememberSubject,
} = require('../subpackages/study/practice/utils/recent-subjects')

const subjectTree = [
  { subject_id: 408, display_name: '计算机综合', children: [{ subject_id: 1, display_name: '数据结构', children: [] }] },
  { subject_id: 20, display_name: '高等数学', children: [] },
]

function flattenSelectableSubjects(tree) {
  return [
    { subject_id: 1, display_name: '数据结构', parent_subject_id: 408, has_children: false },
    { subject_id: 408, display_name: '计算机综合（全部）', parent_subject_id: 408, has_children: true },
    { subject_id: 20, display_name: '高等数学', parent_subject_id: 20, has_children: false },
  ].filter(item => tree.some(root => root.subject_id === item.subject_id || root.children.some(child => child.subject_id === item.subject_id)))
}

function decorateRecentSubjects(subjects) {
  return subjects.map(item => ({
    subject_id: item.subject_id,
    display_name: item.display_name,
    parent_subject_id: item.parent_subject_id,
    has_children: item.has_children,
  }))
}

test('uses the stable recent-subjects storage key', () => {
  assert.equal(RECENT_SUBJECTS_STORAGE_KEY, 'practice_recent_subjects_v1')
})

test('selects the newest valid stored subject and falls back to first selectable subject', () => {
  assert.deepEqual(selectDefaultSubject({
    subjectTree,
    storedSubjects: [{ subject_id: 999 }, { subject_id: 408 }],
    flattenSelectableSubjects,
    decorateRecentSubjects,
  }), {
    view: {
      expandedSubjectId: 408,
      selectedSubjectId: 408,
      selectedSubjectName: '计算机综合（全部）',
      selectedSubjectHasChildren: true,
      recentSubjects: [{
        subject_id: 408,
        display_name: '计算机综合（全部）',
        parent_subject_id: 408,
        has_children: true,
      }],
    },
  })

  assert.deepEqual(selectDefaultSubject({
    subjectTree,
    storedSubjects: [],
    flattenSelectableSubjects,
    decorateRecentSubjects,
  }).view.selectedSubjectId, 1)
  assert.equal(selectDefaultSubject({
    subjectTree,
    storedSubjects: [],
    flattenSelectableSubjects: () => [],
    decorateRecentSubjects,
  }), null)
})

test('promotes, deduplicates, trims and persists recent subjects', () => {
  const result = rememberSubject({
    subjectId: 408,
    subjectName: '计算机综合（全部）',
    parentSubjectId: 408,
    hasChildren: true,
    currentRecentSubjects: [
      { subject_id: 20, display_name: '高等数学', parent_subject_id: 20, has_children: false },
      { subject_id: 408, display_name: '计算机综合（全部）', parent_subject_id: 408, has_children: true },
      { subject_id: 1, display_name: '数据结构', parent_subject_id: 408, has_children: false },
    ],
    decorateRecentSubjects,
  })
  assert.deepEqual(result.view.recentSubjects.map(item => item.subject_id), [408, 20, 1])
  assert.deepEqual(result.storageValue, [
    { subject_id: 408, display_name: '计算机综合（全部）', parent_subject_id: 408 },
    { subject_id: 20, display_name: '高等数学', parent_subject_id: 20 },
    { subject_id: 1, display_name: '数据结构', parent_subject_id: 408 },
  ])
})
