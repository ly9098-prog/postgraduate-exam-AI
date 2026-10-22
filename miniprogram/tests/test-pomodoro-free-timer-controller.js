const assert = require('node:assert/strict')
const {
  createFreeTimerController,
  nextFreeTimerDelay,
} = require('../pages/pomodoro/utils/free-timer-controller')

const flush = () => new Promise(resolve => setImmediate(resolve))

function fixture() {
  const timers = new Map()
  const events = []
  let nextId = 0
  let elapsedMs = 1000
  const options = {
    setTimeout(fn, delay) {
      const id = ++nextId
      timers.set(id, { fn, delay })
      return id
    },
    clearTimeout(id) { timers.delete(id) },
    getElapsedMs: () => elapsedMs,
    isBlocked: () => false,
    onTick: () => events.push('tick'),
    shouldFinalize: () => false,
  }
  const controller = createFreeTimerController(options)
  async function fire() {
    const [id, timer] = timers.entries().next().value
    timers.delete(id)
    await timer.fn()
    await flush()
  }
  return {
    controller,
    options,
    timers,
    events,
    fire,
    setElapsed(value) { elapsedMs = value },
  }
}

for (const [elapsedMs, expected] of [
  [0, 1000],
  [1, 999],
  [999, 100],
  [1000, 1000],
  [1001, 999],
  [1999, 100],
  [2500, 500],
]) {
  assert.equal(nextFreeTimerDelay(elapsedMs), expected)
}
assert.ok(Number.isNaN(nextFreeTimerDelay(NaN)))

const f = fixture()
assert.equal(f.controller.start(), true)
assert.equal(f.controller.start(), false)
assert.equal(f.timers.size, 1)
assert.equal([...f.timers.values()][0].delay, 1000)

async function main() {
  await f.fire()
  assert.deepEqual(f.events, ['tick'])
  assert.equal(f.timers.size, 1)
  assert.equal([...f.timers.values()][0].delay, 1000)

  f.setElapsed(1234)
  f.controller.restart()
  assert.equal(f.timers.size, 1)
  assert.equal([...f.timers.values()][0].delay, 766)

  f.options.isBlocked = () => true
  await f.fire()
  assert.deepEqual(f.events, ['tick'])
  assert.equal(f.timers.size, 0)

  f.options.isBlocked = () => false
  f.options.shouldFinalize = () => true
  f.controller.start()
  await f.fire()
  assert.deepEqual(f.events, ['tick', 'tick'])
  assert.equal(f.timers.size, 0)

  f.options.shouldFinalize = () => false
  f.controller.start()
  assert.equal(f.controller.clear(), true)
  assert.equal(f.timers.size, 0)
  assert.equal(f.controller.clear(), false)

  console.log('Pomodoro free timer controller passed: delay/start/tick/block/finalize/clear')
}

main().catch(error => {
  console.error(error)
  process.exitCode = 1
})
