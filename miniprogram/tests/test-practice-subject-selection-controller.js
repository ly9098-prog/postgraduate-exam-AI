const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createSubjectSelectionController,
} = require('../subpackages/study/practice/utils/subject-selection-controller')

function createHarness(overrides = {}) {
  const state = {
    data: {
      selectedSubjectId: 1,
      selectedMode: 'random',
      count: 5,
      expandedSubjectId: null,
    },
    patches: [],
    callbacks: [],
    overridesCleared: 0,
    remembered: [],
    taps: [],
    computedUpdates: 0,
  }
  const controller = createSubjectSelectionController({
    getSelectedSubjectId: () => state.data.selectedSubjectId,
    getSelectedMode: () => state.data.selectedMode,
    getCount: () => state.data.count,
    getExpandedSubjectId: () => state.data.expandedSubjectId,
    findParentSubjectId: id => (id === 7 ? 408 : null),
    subjectHasChildren: id => id === 408,
    clearLaunchOverrides: () => { state.overridesCleared += 1 },
    queueRememberSubject: (id, name) => state.remembered.push({ id, name }),
    handleSubjectOptionTap: (id, source) => state.taps.push({ id, source }),
    setData: (patch, callback) => {
      state.patches.push(patch)
      Object.assign(state.data, patch)
      if (callback) state.callbacks.push(callback)
    },
    updateComputedFields: () => { state.computedUpdates += 1 },
    ...overrides,
  })
  return { controller, state }
}

function event(dataset) {
  return { currentTarget: { dataset } }
}

test('select validates input, resolves children and expands parent subjects', () => {
  const { controller, state } = createHarness()

  controller.select(0, '无效')
  controller.select(408, '')
  assert.deepEqual(state.patches, [])

  controller.select('408', '计算机综合', undefined, undefined)
  assert.equal(state.overridesCleared, 1)
  assert.deepEqual(state.patches, [{
    selectedSubjectId: 408,
    selectedSubjectName: '计算机综合',
    selectedSubjectHasChildren: true,
    expandedSubjectId: 408,
  }])
  assert.deepEqual(state.remembered, [{ id: 408, name: '计算机综合' }])

  controller.select(408, '计算机综合', 7, false)
  assert.equal(state.overridesCleared, 1)
  assert.deepEqual(state.patches[1], {
    selectedSubjectId: 408,
    selectedSubjectName: '计算机综合',
    selectedSubjectHasChildren: false,
    expandedSubjectId: 7,
  })
})

test('recent selection expands to parent or itself and records the option tap', () => {
  const { controller, state } = createHarness()

  controller.chooseRecent(event({ subjectId: 7, subjectName: '数据结构', hasChildren: 'false' }))
  controller.chooseRecent(event({ subjectId: 408, subjectName: '计算机综合', hasChildren: true }))

  assert.deepEqual(state.patches[0].expandedSubjectId, 408)
  assert.deepEqual(state.patches[1].expandedSubjectId, 408)
  assert.deepEqual(state.taps, [
    { id: 7, source: 'recent' },
    { id: 408, source: 'recent' },
  ])
})

test('parent selection appends the all-scope label only for parents with children', () => {
  const { controller, state } = createHarness()

  controller.chooseParent(event({ subjectId: 408, subjectName: '计算机综合', hasChildren: 'true' }))
  controller.chooseParent(event({ subjectId: 1, subjectName: '政治', hasChildren: false }))

  assert.equal(state.patches[0].selectedSubjectName, '计算机综合（全部）')
  assert.equal(state.patches[0].expandedSubjectId, 408)
  assert.equal(state.patches[1].selectedSubjectName, '政治')
  assert.equal('expandedSubjectId' in state.patches[1], false)
})

test('expansion toggles only the requested parent id', () => {
  const { controller, state } = createHarness()
  state.data.expandedSubjectId = 408

  controller.toggleExpansion(event({ subjectId: 408 }))
  assert.deepEqual(state.patches, [{ expandedSubjectId: null }])
  state.data.expandedSubjectId = 1
  controller.toggleExpansion(event({ subjectId: 408 }))
  assert.deepEqual(state.patches[1], { expandedSubjectId: 408 })
  controller.toggleExpansion(event({ subjectId: 0 }))
  assert.equal(state.patches.length, 2)
})

test('child selection expands its parent and records the child tap', () => {
  const { controller, state } = createHarness()

  controller.chooseChild(event({ subjectId: 7, subjectName: '数据结构', hasChildren: false }))

  assert.deepEqual(state.patches, [{
    selectedSubjectId: 7,
    selectedSubjectName: '数据结构',
    selectedSubjectHasChildren: false,
    expandedSubjectId: 408,
  }])
  assert.deepEqual(state.taps, [{ id: 7, source: 'child' }])
})

test('manual mode and count changes clear overrides and update computed fields', () => {
  const { controller, state } = createHarness()

  controller.chooseMode(event({ mode: 'random' }))
  assert.equal(state.overridesCleared, 0)
  assert.equal(state.patches.length, 1)
  assert.equal(state.callbacks.length, 1)

  controller.chooseMode(event({ mode: 'smart' }))
  assert.equal(state.overridesCleared, 1)
  assert.deepEqual(state.patches[1], { selectedMode: 'smart' })
  state.callbacks[0]()
  assert.equal(state.computedUpdates, 1)

  controller.setCount(event({ count: 5 }))
  assert.equal(state.overridesCleared, 1)
  assert.equal(state.patches.length, 3)

  controller.setCount(event({ count: 10 }))
  assert.equal(state.overridesCleared, 2)
  assert.deepEqual(state.patches[3], { count: 10 })
  state.callbacks[2]()
  assert.equal(state.computedUpdates, 2)
})
