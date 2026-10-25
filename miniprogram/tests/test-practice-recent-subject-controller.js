const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createRecentSubjectController,
} = require('../subpackages/study/practice/utils/recent-subject-controller')

function createHarness(overrides = {}) {
  const state = {
    pending: null,
    patches: [],
    storage: [],
    warnings: [],
  }
  const controller = createRecentSubjectController({
    findParentSubjectId: id => (id === 1 ? 408 : id),
    subjectHasChildren: id => id === 408,
    getRecentSubjects: () => [
      { subject_id: 20, display_name: '高等数学', parent_subject_id: 20, has_children: false },
    ],
    decorateRecentSubjects: subjects => subjects,
    setData: patch => state.patches.push(patch),
    setStorage: (key, value) => {
      if (key === 'throw') throw new Error('storage full')
      state.storage.push({ key, value })
    },
    logWarn: (...args) => state.warnings.push(args),
    getPending: () => state.pending,
    setPending: value => { state.pending = value },
    ...overrides,
  })
  return { controller, state }
}

test('remember promotes a subject, updates the view and persists storage', () => {
  const { controller, state } = createHarness()

  controller.remember(408, '计算机综合（全部）')

  assert.deepEqual(state.patches, [{
    recentSubjects: [{
      subject_id: 408,
      display_name: '计算机综合（全部）',
      parent_subject_id: 408,
      has_children: true,
    }, {
      subject_id: 20,
      display_name: '高等数学',
      parent_subject_id: 20,
      has_children: false,
    }],
  }])
  assert.equal(state.storage[0].key, 'practice_recent_subjects_v1')
  assert.deepEqual(state.storage[0].value[0], {
    subject_id: 408,
    display_name: '计算机综合（全部）',
    parent_subject_id: 408,
  })
})

test('remember ignores invalid ids and names', () => {
  const { controller, state } = createHarness()

  controller.remember(0, '无效')
  controller.remember(408, '')

  assert.deepEqual(state.patches, [])
  assert.deepEqual(state.storage, [])
})

test('storage failure keeps the view update and logs a warning', () => {
  const { controller, state } = createHarness({
    setStorage: () => { throw new Error('storage full') },
  })

  controller.remember(408, '计算机综合（全部）')

  assert.equal(state.patches.length, 1)
  assert.equal(state.warnings[0][0], '保存最近使用科目失败')
})

test('queue stores only valid pending subjects and flush consumes them once', () => {
  const { controller, state } = createHarness()

  controller.queue(0, '无效')
  controller.queue(408, '')
  assert.equal(state.pending, null)

  controller.queue(1, '数据结构')
  assert.deepEqual(state.pending, { subjectId: 1, subjectName: '数据结构' })

  controller.flush()
  assert.equal(state.pending, null)
  assert.equal(state.patches.length, 1)
  assert.equal(state.patches[0].recentSubjects[0].subject_id, 1)

  controller.flush()
  assert.equal(state.patches.length, 1)
})
