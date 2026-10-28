const { test } = require('node:test')
const assert = require('node:assert')

const {
  buildApplySubjectsPlan,
  createSubjectLoadController,
} = require('../pages/pomodoro/utils/apply-subjects-controller')

test('apply subjects: returns base patch with choices and loading state', () => {
  const flat = [
    { id: 1, code: 'ds', name: '数据结构', _isCore: true },
  ]
  const plan = buildApplySubjectsPlan(flat, {})
  assert.ok(plan.patches.length >= 1)
  assert.strictEqual(plan.patches[0].subjectsLoading, false)
  assert.strictEqual(plan.patches[0].subjectsError, '')
  assert.ok(Array.isArray(plan.patches[0].subjects))
  assert.ok(Array.isArray(plan.leaves))
})

test('apply subjects: no route selection when fromSubjectId and fromSubjectCode absent', () => {
  const flat = [{ id: 1, code: 'ds', name: 'DS', _isCore: true }]
  const plan = buildApplySubjectsPlan(flat, {})
  assert.strictEqual(plan.patches.length, 1)
})

test('apply subjects: route selection added when fromSubjectId matches', () => {
  const flat = [
    { id: 10, code: 'ds', name: '数据结构', _isCore: true, _isAggregate: false },
  ]
  const plan = buildApplySubjectsPlan(flat, { fromSubjectId: 10 })
  assert.ok(plan.patches.length >= 2)
})

test('apply subjects: legacy selection added when selectedSubject matches a leaf', () => {
  const flat = [
    { id: 10, code: 'ds', name: '数据结构', _isCore: true, _isAggregate: false },
  ]
  const plan = buildApplySubjectsPlan(flat, { selectedSubject: { code: 'ds' } })
  assert.ok(plan.patches.length >= 2)
})

test('apply subjects: empty flat still produces base patch', () => {
  const plan = buildApplySubjectsPlan([], {})
  assert.strictEqual(plan.patches.length, 1)
  assert.strictEqual(plan.patches[0].subjectsLoading, false)
})

test('subject load: cache hit applies cached choices without network or loading flash', async () => {
  const calls = []
  const controller = createSubjectLoadController({
    readSubjectCache: () => [{ id: 1, code: 'ds' }],
    fetchSubjects: async () => calls.push('fetch'),
    filterSubjectTree: tree => tree,
    buildSubjectChoices: tree => ({ choices: tree }),
    writeSubjectCache: () => calls.push('write'),
    applySubjects: subjects => calls.push(subjects),
    setSubjectsState: patch => calls.push(patch),
    logError: () => calls.push('log'),
  })

  await controller.load()

  assert.deepStrictEqual(calls, [[{ id: 1, code: 'ds' }]])
})

test('subject load: network choices are filtered, cached and applied', async () => {
  const calls = []
  const rawTree = [{ subject_id: 1 }]
  const tree = [{ subject_id: 1, filtered: true }]
  const choices = [{ id: 1, code: 'ds' }]
  const controller = createSubjectLoadController({
    readSubjectCache: () => null,
    fetchSubjects: async () => rawTree,
    filterSubjectTree: value => {
      calls.push(['filter', value])
      return tree
    },
    buildSubjectChoices: value => {
      calls.push(['choices', value])
      return { choices }
    },
    writeSubjectCache: value => calls.push(['write', value]),
    applySubjects: value => calls.push(['apply', value]),
    setSubjectsState: patch => calls.push(['state', patch]),
    logError: (...args) => calls.push(['log', ...args]),
  })

  await controller.load()

  assert.deepStrictEqual(calls, [
    ['state', { subjectsLoading: true, subjectsError: '' }],
    ['filter', rawTree],
    ['choices', tree],
    ['write', choices],
    ['apply', choices],
  ])
})

test('subject load: malformed tree records the existing error state', async () => {
  const calls = []
  const controller = createSubjectLoadController({
    readSubjectCache: () => null,
    fetchSubjects: async () => ({}),
    filterSubjectTree: value => value,
    buildSubjectChoices: () => ({ choices: [] }),
    writeSubjectCache: () => {},
    applySubjects: () => calls.push('apply'),
    setSubjectsState: patch => calls.push(['state', patch]),
    logError: (message, error) => calls.push(['log', message, error.message]),
  })

  await controller.load()

  assert.deepStrictEqual(calls, [
    ['state', { subjectsLoading: true, subjectsError: '' }],
    ['log', '加载科目失败', '科目数据格式错误'],
    ['state', { subjectsLoading: false, subjectsError: '科目加载失败，请稍后重试' }],
  ])
})
