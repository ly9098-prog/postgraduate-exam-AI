const { fixture: lifecycleFixture, deferred, flush } = require('./wrong-book-lifecycle-fixture')

function fixture() {
  const f = lifecycleFixture(), timers = new Map(), values = new Map()
  let timerId = 0
  f.page._alive = true
  f.page._restoreAiAutoSetting = f.methods._restoreAiAutoSetting
  f.page._restoreAiDiagnosisFromCache = f.methods._restoreAiDiagnosisFromCache
  const storage = f.stubs['../../../utils/storage']
  Object.assign(storage, {
    KEYS: { USER: 'user' },
    get(key) { f.calls.push(['get', key]); return values.get(key) },
    set(key, value) { f.calls.push(['set', key, value]); values.set(key, value) },
  })
  const aiCache = f.stubs['../utils/ai-diagnosis-cache']
  Object.assign(aiCache, {
    restore(userId) { f.calls.push(['restore', userId]); return { status: 'miss' } },
    buildSignature(stats, list) { f.calls.push(['signature', stats, list]); return 'signature' },
    save(...args) { f.calls.push(['save', ...args]) },
    formatCacheTime(time) { f.calls.push(['formatTime', time]); return 'time:' + time },
  })
  f.context.setTimeout = (callback, delay) => {
    const id = ++timerId
    timers.set(id, { callback, delay }); f.calls.push(['timer', id, delay]); return id
  }
  f.context.clearTimeout = id => { timers.delete(id); f.calls.push(['clear', id]) }
  return Object.assign(f, {
    storage, aiCache, values, timers,
    fire(id) {
      const timer = timers.get(id)
      if (!timer) throw Error('Unknown timer ' + id)
      timers.delete(id); timer.callback()
    },
  })
}

module.exports = { fixture, deferred, flush }
