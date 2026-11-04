const assert = require('node:assert/strict')
const { test } = require('node:test')

const memory = new Map()
global.wx = {
  getStorageSync: key => memory.get(key),
  setStorageSync: (key, value) => memory.set(key, structuredClone(value)),
  removeStorageSync: key => memory.delete(key),
  getStorageInfoSync: () => ({ keys: [...memory.keys()] }),
}
const key = 'debug_snapshot:launch_resume:v1'

test('resume diagnostics retain only bounded entry metadata without identity or query values', () => {
  const { recordResumeEvent } = require('../utils/launch-resume-diagnostics')
  memory.clear()
  const entry = { path: 'pages/login/login', scene: 1017,
    query: { token: 'private-query', answer: 'private-answer' }, user: { id: 'private-owner' } }
  recordResumeEvent('entry_eligible', { entry, target: '/pages/home/home',
    token: 'private-token', answerMap: { 1: 'private-map' } })
  const first = memory.get(key)[0]
  assert.equal(first.scene, 1017)
  assert.equal(first.path, 'pages/login/login')
  assert.equal(first.queryCount, 2)
  assert.equal(JSON.stringify(first).includes('private-'), false)
  for (let index = 0; index < 30; index++) recordResumeEvent('target_practice')
  assert.equal(memory.get(key).length, 20)
})

test('unrecognized events and routes cannot store arbitrary content', () => {
  const { recordResumeEvent } = require('../utils/launch-resume-diagnostics')
  memory.clear()
  recordResumeEvent('private-event')
  assert.equal(memory.has(key), false)
  recordResumeEvent('entry_skipped', {
    entry: { path: '/private-owner', scene: 'invalid', query: {} },
    target: '/private-target',
  })
  const event = memory.get(key)[0]
  assert.equal(event.path, 'other')
  assert.equal(event.target, 'other')
  assert.equal(event.scene, null)
  assert.equal(JSON.stringify(event).includes('private-'), false)
})

test('diagnostic storage failures do not prevent startup and logout clears the history', () => {
  const { recordResumeEvent } = require('../utils/launch-resume-diagnostics')
  memory.clear()
  const write = global.wx.setStorageSync
  const warn = console.warn
  const warnings = []
  try {
    global.wx.setStorageSync = () => { throw Error('private-storage-error') }
    console.warn = message => warnings.push(message)
    assert.doesNotThrow(() => recordResumeEvent('entry_eligible'))
    assert.deepEqual(warnings, ['[LAUNCH_RESUME] diagnostics unavailable'])
  } finally {
    global.wx.setStorageSync = write
    console.warn = warn
  }
  recordResumeEvent('entry_eligible')
  assert.ok(memory.has(key))
  require('../utils/storage-core').clearSession()
  assert.equal(memory.has(key), false)
})
