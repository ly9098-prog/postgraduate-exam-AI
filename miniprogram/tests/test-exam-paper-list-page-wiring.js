const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { test } = require('node:test')

const pageSource = fs.readFileSync(
  path.resolve(__dirname, '../subpackages/exam/paper-list/index.js'),
  'utf8'
)

function method(name) {
  const start = pageSource.indexOf(`  _${name}() {`)
  assert.ok(start >= 0, `missing _${name}`)
  const end = pageSource.indexOf('\n  },', start)
  return pageSource.slice(start, end)
}

test('loadPapers delegates to the paper list load controller', () => {
  const source = method('paperListLoadController')
  assert.ok(source.includes('createPaperListLoadController'))
  assert.ok(source.includes('buildPapers(rows, this.data.suggestedPaperId)'))
  assert.ok(source.includes("api.get('/exams/papers')"))
  assert.ok(source.includes('api.getErrorMessage(error)'))
  assert.ok(source.includes('wx.showToast(options)'))
  assert.ok(source.includes('this._commitPapers(papers, commitOptions)'))
  assert.ok(source.includes('this._loadedOnce = true'))
  assert.ok(source.includes('this._loadGeneration = (this._loadGeneration || 0) + 1'))
})

test('page wiring exposes the exact controller port set', () => {
  const source = method('paperListLoadController')
  const expectedPorts = [
    'nextGeneration',
    'getGeneration',
    'isPageAlive',
    'wasLoadedOnce',
    'markLoadedOnce',
    'getErrorText',
    'setData',
    'getPapers',
    'getErrorMessage',
    'showToast',
    'buildPapers',
    'commitPapers',
  ]
  for (const port of expectedPorts) {
    assert.ok(source.includes(`${port}:`), `missing port wiring: ${port}`)
  }
  // No unexpected extra ports
  const portMatches = source.match(/^\s{8}([A-Za-z]\w*):/gm) || []
  const actualPorts = portMatches.map(match => match.trim().replace(':', ''))
  assert.deepEqual([...actualPorts].sort(), [...expectedPorts].sort())
})

test('controller instance is cached under a matching private name', () => {
  const source = method('paperListLoadController')
  assert.ok(source.includes('if (!this._paperListLoad)'))
  assert.ok(source.includes('return this._paperListLoad'))
  assert.ok(!source.includes('_paperLoadController'), 'stale cached-property name must not remain')
})

test('loadPapers method is a thin delegate', () => {
  const start = pageSource.indexOf('  async loadPapers(options = {}) {')
  assert.ok(start >= 0)
  const end = pageSource.indexOf('\n  },', start)
  const source = pageSource.slice(start, end)
  assert.ok(source.includes('return this._paperListLoadController().load(options)'))
  assert.ok(source.split('\n').length <= 4)
})

test('cancelResume delegates to the paper cancel-resume controller', () => {
  const start = pageSource.indexOf('  async cancelResume(e) {')
  assert.ok(start >= 0, 'missing cancelResume')
  const end = pageSource.indexOf('\n  },', start)
  const source = pageSource.slice(start, end)
  assert.ok(source.includes('return this._paperCancelResumeController().cancel(e)'))
  assert.ok(source.split('\n').length <= 4)
})

test('paper cancel-resume wiring exposes the exact controller port set', () => {
  const source = method('paperCancelResumeController')
  const expectedPorts = [
    'getStartingId',
    'getCancellingAttemptId',
    'setCancellingAttemptId',
    'isPageAlive',
    'findPaper',
    'refreshAfterStateMismatch',
    'confirmCancel',
    'abandonAttempt',
    'clearAttemptCache',
    'optimisticallyClearResume',
    'refreshAfterCancel',
    'reconcileAttemptCache',
    'getErrorMessage',
    'showToast',
  ]
  for (const port of expectedPorts) {
    assert.ok(source.includes(`${port}:`), `missing port wiring: ${port}`)
  }
  const portMatches = source.match(/^\s{8}([A-Za-z]\w*):/gm) || []
  const actualPorts = portMatches.map(match => match.trim().replace(':', ''))
  assert.deepEqual([...actualPorts].sort(), [...expectedPorts].sort())
})

test('paper cancel-resume dialog payload is preserved exactly', () => {
  const source = method('paperCancelResumeController')
  const expectedDialog = [
    "scenario: 'danger',",
    "title: '取消本次作答？',",
    "message: '当前未提交的作答进度将被放弃，之后会从头开始；本次不会生成考试记录。',",
    "confirmText: '取消本次',",
    "cancelText: '继续作答',",
    'maskClose: false,',
  ]
  for (const fragment of expectedDialog) {
    assert.ok(source.includes(fragment), `missing dialog fragment: ${fragment}`)
  }
})

test('paper cancel-resume ports are wired to exact page helpers and refresh options', () => {
  const source = method('paperCancelResumeController')
  // Refresh options must keep force=true to override an older onShow request.
  assert.ok(source.includes('this.loadPapers({ silent: true, force: true, suppressErrorToast: true })'))
  // Both refresh ports share the same durable options.
  const refreshCount = (source.match(/this\.loadPapers\(\{ silent: true, force: true, suppressErrorToast: true \}\)/g) || []).length
  assert.equal(refreshCount, 2, 'both refresh ports must use the same force options')
  // Abandon endpoint and cache helpers are wired to the real page/api helpers.
  assert.ok(source.includes('api.post(`/exams/attempts/${attemptId}/abandon`)'))
  assert.ok(source.includes('this._clearCancelledAttemptCache(attemptId)'))
  assert.ok(source.includes('this._optimisticallyClearResume(paperId, attemptId)'))
  assert.ok(source.includes('this._reconcileCancelledAttemptCache(attemptId)'))
  assert.ok(source.includes('api.getErrorMessage(error)'))
  assert.ok(source.includes('wx.showToast(options)'))
})

test('paper cancel-resume cached field name is stable and not stale', () => {
  const source = method('paperCancelResumeController')
  assert.ok(source.includes('if (!this._paperCancelResume)'))
  assert.ok(source.includes('this._paperCancelResume = createPaperCancelResumeController'))
  assert.ok(source.includes('return this._paperCancelResume'))
  // No stale controller-name-style cached property should remain.
  assert.ok(!source.includes('_paperCancelResumeControllerInstance'), 'stale cached-property name must not remain')
})
