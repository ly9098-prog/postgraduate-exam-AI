const { test } = require('node:test')
const assert = require('node:assert')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')

const {
  buildApplySubjectsPlan,
  createSubjectLoadController,
} = require('../pages/pomodoro/utils/apply-subjects-controller')
const {
  buildSubjectLoadPageCapabilities,
} = require('../pages/pomodoro/utils/pomodoro-session-page-adapter')
const {
  createPomodoroRunningStateMigrator,
} = require('../pages/pomodoro/utils/running-state-migrator')

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

test('apply subjects: removed subject clears idle selection but preserves a running session', () => {
  const selected = { id: 3, code: 'english' }
  const idle = buildApplySubjectsPlan([], {
    phase: 'idle', selectedSubjectId: 3, selectedSubject: selected, allocationMode: 'single',
  })
  assert.deepStrictEqual(idle.patches.at(-1), {
    selectedSubjectId: null, selectedSubject: null, allocationMode: 'single',
  })
  const running = buildApplySubjectsPlan([], {
    phase: 'running', selectedSubjectId: 3, selectedSubject: selected,
  })
  assert.strictEqual(running.patches.length, 1)
})

test('subject load: old cached choices cannot bypass the current subject catalog', async () => {
  const calls = []
  const controller = createSubjectLoadController({
    readSubjectCache: () => [{ id: 1, code: 'ds' }],
    fetchSubjects: async () => { calls.push('fetch'); return [] },
    filterSubjectTree: tree => tree,
    buildSubjectChoices: tree => ({ choices: tree }),
    writeSubjectCache: () => calls.push('write'),
    applySubjects: subjects => calls.push(subjects),
    setSubjectsState: patch => calls.push(patch),
    logError: () => calls.push('log'),
  })

  await controller.load()

  assert.deepStrictEqual(calls, [
    { subjectsLoading: true, subjectsError: '' },
    'fetch',
    [],
  ])
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
    'apply',
    ['state', { subjectsLoading: false, subjectsError: '科目加载失败，请稍后重试' }],
  ])
})

test('subject load: network failure never restores disabled choices from old cache', async () => {
  const applied = []
  const states = []
  const controller = createSubjectLoadController({
    readSubjectCache: () => [{ id: 3, code: 'english' }],
    fetchSubjects: async () => { throw new Error('offline') },
    applySubjects: choices => applied.push(choices),
    setSubjectsState: patch => states.push(patch),
    logError: () => {},
  })
  await controller.load()
  assert.deepStrictEqual(applied, [[]])
  assert.strictEqual(states.at(-1).subjectsLoading, false)
  assert.ok(states.at(-1).subjectsError)
})

test('page subject-load failure clears idle choices while preserving a legacy running snapshot', async () => {
  const snapshot = { sessionId: 41, sessionStartTime: Date.now(), selectedSubjectCode: 'advanced_math' }
  const storage = new Map([['pomodoro_running_state', snapshot]])
  const migrator = createPomodoroRunningStateMigrator({
    safeGetPomodoroStorage: key => ({ ok: true, value: storage.get(key) }),
    safeSetPomodoroStorage: (key, value) => { storage.set(key, value); return true },
    safeRemovePomodoroStorage: key => storage.delete(key),
  })
  let available = false
  let definition
  const filename = path.join(__dirname, '../pages/pomodoro/pomodoro.js')
  vm.runInNewContext(fs.readFileSync(filename, 'utf8'), {
    Page: value => { definition = value },
    require(name) {
      if (name === './utils/pomodoro-page-support') return { PHASE: { IDLE: 'idle' }, PRESETS: [] }
      if (name === '../../utils/storage') return { pomodoroTaskTypes: { label: () => '', TYPES: [], DEFAULT_TYPE: 'study' } }
      if (name === './utils/apply-subjects-controller') return { buildApplySubjectsPlan, createSubjectLoadController }
      if (name === './utils/pomodoro-session-page-adapter') return { buildSubjectLoadPageCapabilities }
      if (name === '../../utils/api') return { get: async () => {
        if (!available) throw new Error('offline')
        return [{ subject_id: 7, subject_code: 'advanced_math', subject_name: '高数' }]
      } }
      return {}
    },
  }, { filename })
  const page = {
    ...definition,
    data: { ...definition.data, selectedSubjectId: 3, selectedSubject: { id: 3, code: 'english' } },
    setData(patch) { Object.assign(this.data, patch) },
    _updateComputedFields() {},
    _migrateRunningStateCache: leaves => migrator.migrate(leaves),
  }
  await page._loadSubjects()
  assert.strictEqual(storage.get('pomodoro_running_state'), snapshot)
  assert.strictEqual(snapshot.selectedSubjectId, undefined)
  assert.strictEqual(page.data.subjects.length, 0)
  assert.strictEqual(page.data.selectedSubjectId, null)
  assert.ok(page.data.subjectsError)

  available = true
  await page._loadSubjects()
  assert.strictEqual(storage.get('pomodoro_running_state').selectedSubjectId, 7)
  assert.strictEqual(page.data.subjects.length, 1)
  assert.strictEqual(page.data.subjectsError, '')
})
