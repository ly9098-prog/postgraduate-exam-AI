const { fixture: requestFixture } = require('./wrong-book-request-fixture')

function fixture() {
  const f = requestFixture()
  const timers = new Map(), cleared = []
  let timerId = 0, now = 1000
  Object.assign(f.page, {
    _syncSelectionState: f.methods._syncSelectionState,
    _suppressQuestionTapUntil: 0,
    setData(patch, callback) {
      f.calls.push(['setData', patch])
      Object.assign(this.data, patch)
      if (callback) callback()
    },
  })
  f.context.Date = { now: () => now }
  f.context.setTimeout = (callback, delay) => {
    const id = ++timerId
    timers.set(id, { callback, delay })
    f.calls.push(['timer', id, delay])
    return id
  }
  f.context.clearTimeout = id => {
    cleared.push(id); timers.delete(id); f.calls.push(['clear', id])
  }
  f.context.wx = {
    vibrateShort(options) { f.calls.push(['vibrate', options]) },
  }
  return Object.assign(f, {
    timers, cleared,
    setNow(value) { now = value },
    fire(id) {
      const timer = timers.get(id)
      if (!timer) throw new Error('Unknown timer ' + id)
      timers.delete(id); timer.callback()
    },
  })
}

module.exports = { fixture }
