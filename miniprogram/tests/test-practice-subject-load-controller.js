const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const { test } = require('node:test')
const {
  createPracticeSubjectLoadController,
} = require('../subpackages/study/practice/utils/practice-subject-load-controller')
const {
  createPracticeSubjectLoadPageController,
} = require('../subpackages/study/practice/utils/practice-subject-load-page-adapter')

function createHarness(overrides = {}) {
  const calls = []
  let requestSeq = 0
  const controller = createPracticeSubjectLoadController({
    nextRequestSeq: () => ++requestSeq,
    isCurrent: requestSeq => overrides.stale
      ? requestSeq !== requestSeq
      : requestSeq === requestSeq,
    fetchSubjects: async () => {
      calls.push(['fetch'])
      if (overrides.fetchError) throw overrides.fetchError
      return overrides.rawTree || [{ subject_id: 1 }]
    },
    filterSubjectTree: value => {
      calls.push(['filter', value])
      return overrides.filteredTree || value
    },
    normalizeSubjectTree: value => {
      calls.push(['normalize', value])
      return overrides.subjectTree || value
    },
    setData: patch => calls.push(['setData', patch]),
    getSelectedSubjectId: () => overrides.selectedSubjectId || null,
    preserveSelectedSubject: tree => calls.push(['preserve', tree]),
    initDefaultSubject: tree => calls.push(['default', tree]),
    applyLaunchPreset: async tree => {
      calls.push(['preset', tree])
      return overrides.presetApplied !== false
    },
    shouldAutostart: () => overrides.autostart !== false,
    startPractice: async () => calls.push(['start']),
    logError: (...args) => calls.push(['error', ...args]),
    showToast: options => calls.push(['toast', options]),
  })
  return { calls, controller }
}

test('loads, normalizes, initializes defaults and applies launch autostart', async () => {
  const { calls, controller } = createHarness()
  await controller.load({})

  assert.deepEqual(calls.map(call => call[0]), [
    'fetch',
    'filter',
    'normalize',
    'setData',
    'default',
    'preset',
    'start',
  ])
})

test('preserve selection keeps the existing subject and skips autostart when requested', async () => {
  const { calls, controller } = createHarness({
    selectedSubjectId: 7,
  })
  await controller.load({ preserveSelection: true, skipAutostart: true })

  assert.deepEqual(calls.map(call => call[0]), [
    'fetch',
    'filter',
    'normalize',
    'setData',
    'preserve',
  ])
})

test('does not autostart when the launch preset cannot be applied', async () => {
  const { calls, controller } = createHarness({ presetApplied: false })
  await controller.load({})

  assert.deepEqual(calls.map(call => call[0]), [
    'fetch',
    'filter',
    'normalize',
    'setData',
    'default',
    'preset',
  ])
})

test('network failures are logged and surfaced unless silent', async () => {
  const failure = new Error('offline')
  const loud = createHarness({ fetchError: failure })
  await loud.controller.load({})
  assert.deepEqual(loud.calls.map(call => call[0]), ['fetch', 'error', 'toast'])

  const silent = createHarness({ fetchError: failure })
  await silent.controller.load({ silent: true })
  assert.deepEqual(silent.calls.map(call => call[0]), ['fetch', 'error'])
})

test('page adapter preserves request sequencing and selected subject wiring', async () => {
  const calls = []
  const page = {
    _pageAlive: true,
    _subjectsRequestSeq: 0,
    data: { selectedSubjectId: 7, selectedSubjectName: '' },
    setData: patch => calls.push(['setData', patch]),
    _flattenSelectableSubjects: tree => tree,
    initDefaultSubject: tree => calls.push(['default', tree]),
    _applyLaunchPreset: async tree => {
      calls.push(['preset', tree])
      return true
    },
    _launchPreset: { autostart: true },
    startPractice: async () => calls.push(['start']),
  }
  const controller = createPracticeSubjectLoadPageController(page, {
    api: { get: async () => [{ subject_id: 7, display_name: '数据结构', has_children: false }] },
    filterSubjectTree: value => value,
    normalizeSubjectTree: value => value,
    wx: { showToast: options => calls.push(['toast', options]) },
  })

  await controller.load({ preserveSelection: true })

  assert.equal(page._subjectsRequestSeq, 1)
  assert.deepEqual(calls.map(call => call[0]), [
    'setData',
    'setData',
    'preset',
    'start',
  ])
  assert.deepEqual(calls[1][1], {
    selectedSubjectName: '数据结构',
    selectedSubjectHasChildren: false,
    expandedSubjectId: 7,
  })
})

test('registered practice page wires its imported subject filter into the loader', async () => {
  const calls = []
  let definition
  const filename = path.join(__dirname, '../subpackages/study/practice/practice.js')
  const rawTree = [{ subject_id: 7 }]
  vm.runInNewContext(fs.readFileSync(filename, 'utf8'), {
    Page: value => { definition = value },
    wx: { showToast: value => calls.push(['toast', value]) },
    require(name) {
      if (name === '../../../utils/api') return { get: async () => rawTree }
      if (name === '../utils/subject-scope') {
        return { filter408SubjectTree: tree => {
          calls.push(['filter', tree])
          return tree
        } }
      }
      if (name === './utils/subject-tree') return { normalizeSubjectTree: tree => tree }
      if (name === './utils/practice-subject-load-page-adapter') {
        return { createPracticeSubjectLoadPageController }
      }
      return {}
    },
  }, { filename })
  const page = {
    ...definition,
    _pageAlive: true,
    _subjectsRequestSeq: 0,
    data: { ...definition.data },
    setData(patch) { Object.assign(this.data, patch) },
    initDefaultSubject: tree => calls.push(['default', tree]),
    _applyLaunchPreset: async () => false,
  }

  await page.loadPracticeSubjects()

  assert.equal(page.data.subjectTree, rawTree)
  assert.equal(page._subjectsRequestSeq, 1)
  assert.deepEqual(calls.map(call => call[0]), ['filter', 'default'])
})
