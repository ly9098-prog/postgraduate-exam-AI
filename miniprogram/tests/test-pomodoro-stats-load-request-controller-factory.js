const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createLoadRequestControllerFactory,
} = require('../subpackages/productivity/pomodoro-stats/load-request-controller-factory')
const {
  CAPABILITY_NAMES,
} = require('../subpackages/productivity/pomodoro-stats/load-request-controller-capabilities')

test('creates the controller with every explicitly supplied capability', () => {
  const passedOptions = []
  const capabilities = Object.fromEntries(CAPABILITY_NAMES.map(name => [name, () => name]))
  const controller = {}
  const factory = createLoadRequestControllerFactory({
    ...capabilities,
    createLoadRequestController: options => {
      passedOptions.push(options)
      return controller
    },
  })

  const actual = factory.create()

  assert.equal(actual, controller)
  assert.equal(passedOptions.length, 1)
  for (const [name, capability] of Object.entries(capabilities)) {
    assert.equal(passedOptions[0][name], capability)
  }
  assert.deepEqual(Object.keys(passedOptions[0]), CAPABILITY_NAMES)
})

test('creates a new controller instance on each call', () => {
  const instances = [{}, {}]
  const factory = createLoadRequestControllerFactory({
    createLoadRequestController: () => instances.shift(),
  })

  assert.notEqual(factory.create(), factory.create())
})
