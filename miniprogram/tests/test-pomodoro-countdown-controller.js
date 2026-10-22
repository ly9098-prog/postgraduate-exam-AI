const assert = require('node:assert/strict')
const { createCountdownController } = require('../pages/pomodoro/utils/countdown-controller')

const timers = new Map()
let nextId = 0
const controller = createCountdownController({
  setTimeout(fn, delay) {
    const id = ++nextId
    timers.set(id, { fn, delay })
    return id
  },
  clearTimeout(id) { timers.delete(id) },
  clearInterval(id) { timers.delete(id) },
})

assert.equal(controller.clear(), false)
const first = controller.scheduleTick(() => {}, 250)
assert.equal(timers.get(first).delay, 250)
assert.equal(controller.clear(), true)
assert.equal(timers.size, 0)

const second = controller.scheduleTick(() => {}, 80)
controller.stop()
assert.equal(timers.has(second), false)
assert.equal(controller.clear(), false)
assert.equal(timers.size, 0)
assert.equal(controller.clear(), false)

console.log('Pomodoro countdown controller passed: clear/stop lifecycle')
