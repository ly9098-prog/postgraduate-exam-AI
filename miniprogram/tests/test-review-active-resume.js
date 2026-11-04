const assert = require('node:assert/strict')
const { test } = require('node:test')
const memory = new Map()
global.wx = {
  getStorageSync: key => memory.get(key),
  setStorageSync: (key, value) => memory.set(key, structuredClone(value)),
  removeStorageSync: key => memory.delete(key),
  reLaunch: () => {},
}
global.getCurrentPages = () => []
const store = require('../utils/launch-session-store')
const { getChinaDate } = require('../utils/china-time')
const sessionPorts = require('../subpackages/study/review-today/utils/review-session-page-adapter')
const submitPorts = require('../subpackages/study/review-today/utils/review-submit-page-adapter')
const progressPorts = require('../subpackages/study/review-today/utils/review-progress-page-adapter')
const overviewPorts = require('../subpackages/study/review-today/utils/review-overview-page-adapter')

function page() {
  memory.clear()
  memory.set('user', { id: 10 })
  return {
    _reviewSession: { taskDate: getChinaDate(0) }, data: {},
    setData(patch) { Object.assign(this.data, patch) },
    _clearReviewTimer() {}, _clearMasterUndo() {},
  }
}

test('entering reviewing via initial batch sets the active marker; group result clears it', () => {
  const subject = page()
  sessionPorts.buildStartBatchPageCapabilities(subject, {}).setData({ phase: 'reviewing' })
  assert.equal(store.readActive().kind, 'review-today')
  submitPorts.buildGroupSubmitResultPageCapabilities(subject, {}).setData({ phase: 'group-result' })
  assert.equal(store.readActive(), null)
})

test('retry, remote batch and master undo transitions restore the same active slot', () => {
  const subject = page()
  for (const name of ['buildReviewMasterPageCapabilities', 'buildNextRetryGroupPageCapabilities',
    'buildNextRemoteBatchPageCapabilities']) {
    progressPorts[name](subject, {}).setData({ phase: 'reviewing' })
    assert.equal(store.readActive().kind, 'review-today')
    store.clearActive('review-today')
  }
})

test('confirmed exit clears only activity while leaving the existing draft intact', () => {
  const subject = page()
  const draftKey = 'review_today_draft_v1:10:' + getChinaDate(0)
  memory.set(draftKey, { answers: { 2: 'A' } })
  store.markReview(getChinaDate(0))
  sessionPorts.buildNavBackPageCapabilities(subject, {}).clearReviewTimer()
  assert.equal(store.readActive(), null)
  assert.deepEqual(memory.get(draftKey), { answers: { 2: 'A' } })
})

test('callbacks from an old review page cannot change the new account active marker', () => {
  const subject = page()
  const writer = sessionPorts.buildStartBatchPageCapabilities(subject, {})
  const nav = sessionPorts.buildNavBackPageCapabilities(subject, {})
  memory.set('user', { id: 20 })
  store.markReview(getChinaDate(0))
  writer.setData({ phase: 'group-result' })
  nav.clearReviewTimer()
  assert.equal(store.readActive().owner, '20')
})

test('autostart from the overview sets the marker even before a reviewing setData occurs', () => {
  const subject = page()
  subject.data = { phase: 'overview', todayRemainingCount: 4 }
  overviewPorts.buildOverviewLoadPageCapabilities(subject, { api: {} })
    .setData({ phase: 'reviewing' })
  assert.equal(store.readActive().kind, 'review-today')
})
