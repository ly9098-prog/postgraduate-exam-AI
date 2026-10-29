const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const { test } = require('node:test')

const root = path.resolve(__dirname, '..')
const pagePath = path.join(root, 'subpackages/study/review-today/review-today.js')

let definition
// The page builds controller ports inside its Node-required page adapters, so the
// harness exposes one wx stub to both the vm sandbox and the host realm.
global.wx = {}
vm.runInNewContext(fs.readFileSync(pagePath, 'utf8'), {
  Page(value) { definition = value },
  require(request) {
    if (request === '../../../utils/api') return { post: async () => ({}) }
    if (request === '../../../config' || request === '../../../utils/storage') return {}
    return require(path.resolve(path.dirname(pagePath), request))
  },
  wx: {}, console, setTimeout, clearTimeout, setInterval, clearInterval,
})

function createPage() {
  const page = Object.assign({}, definition, {
    data: {
      currentGroupIdx: 0,
      groups: [],
      todayRemainingCount: 0,
      resultTransitioning: false,
    },
    _alive: true,
    _flowRequestSeq: 0,
    _reviewSession: { answers: {}, allQuestions: [] },
    calls: [],
    setData(patch, callback) {
      Object.assign(this.data, patch)
      if (callback) callback()
    },
    _clearMasterUndo() { this.calls.push('clear-undo') },
    _clearResultDockFadeTimer() { this.calls.push('clear-fade') },
    _syncReviewSessionDayIfNeeded() { this.calls.push('sync-day'); return true },
    _syncAnsweredFlags() { this.calls.push('sync-flags') },
    _showQuestion(index) { this.calls.push(['show', index]) },
    _startReviewTimer() { this.calls.push('start-timer') },
    _showResultDockAndRefreshTimer() { this.calls.push('dock') },
  })
  return page
}

test('lazily creates one next-group controller and delegates next', async () => {
  const page = createPage()
  const first = page._nextGroupController()
  const second = page._nextGroupController()

  assert.equal(first, second)
  assert.equal(page._nextGroupController(), first)
  assert.deepEqual(page.calls, [])

  assert.equal((await page.nextGroup()).status, 'complete')
  assert.deepEqual(page.calls, ['clear-undo', 'clear-fade', 'sync-day', 'dock'])
  assert.equal(page.data.resultTransitioning, false)
  assert.equal(page.data.resultDockVisible, true)
})

test('lazily creates the retry-group controller with page ports', async () => {
  const page = createPage()
  // The accessor method exists; the cached instance is lazily created.
  assert.equal(typeof page._nextRetryGroupController, 'function')
  assert.equal(page._nextRetryGroup, undefined)

  page.data.groups = [[{ schedule_id: 1 }], [{ schedule_id: 2 }]]
  page.data.currentGroupIdx = 0
  page.data.todayRemainingCount = 1
  assert.equal((await page.nextGroup()).status, 'retry-group')
  assert.ok(page._nextRetryGroup)
  assert.deepEqual(page.calls, [
    'clear-undo',
    'clear-fade',
    'sync-day',
    'sync-flags',
    ['show', 0],
    'start-timer',
  ])
  assert.equal(page.data.currentGroupIdx, 1)
  assert.equal(page.data.resultTransitioning, false)
})

test('next-group controller delegates sub-controllers to dedicated accessors', () => {
  const page = createPage()
  page._nextGroupController()
  // The sub-controllers are now wired via accessor methods, not inline IIFEs.
  const retry = page._nextRetryGroupController()
  const remote = page._nextRemoteBatchController()
  assert.ok(retry, 'retry-group controller accessor returns an instance')
  assert.ok(remote, 'remote-batch controller accessor returns an instance')
  // Cached on second call.
  assert.equal(page._nextRetryGroupController(), retry)
  assert.equal(page._nextRemoteBatchController(), remote)
})
