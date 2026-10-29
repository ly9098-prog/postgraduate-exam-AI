const { fixture: requestFixture, deferred } = require('./wrong-book-request-fixture')

function fixture() {
  const f = requestFixture(), timers = new Map()
  let timerId = 0
  f.api.post = function (...args) {
    f.calls.push(['post', ...args])
    return Promise.resolve({ updated_count: 1 })
  }
  f.context.wx = {
    showToast(options) { f.calls.push(['toast', options]) },
    showLoading(options) { f.calls.push(['loading', options]) },
    hideLoading() { f.calls.push(['hideLoading']) },
  }
  f.context.setTimeout = (callback, delay) => {
    const id = ++timerId
    timers.set(id, { callback, delay }); f.calls.push(['timer', id, delay])
    return id
  }
  f.context.clearTimeout = id => { timers.delete(id); f.calls.push(['clear', id]) }
  Object.assign(f.page, {
    selectComponent(id) { f.calls.push(['component', id]); return null },
    _clearBatchCapsuleIdleTimer() { f.calls.push(['clearCapsule']) },
    loadStats() { f.calls.push(['stats']); return Promise.resolve('stats') },
    loadList(reset) { f.calls.push(['list', reset]); return Promise.resolve('list') },
  })
  return Object.assign(f, {
    timers,
    fire(id) {
      const timer = timers.get(id)
      if (!timer) throw Error('Unknown timer ' + id)
      timers.delete(id); timer.callback()
    },
  })
}

const flush = () => new Promise(setImmediate)
module.exports = { fixture, deferred, flush }
