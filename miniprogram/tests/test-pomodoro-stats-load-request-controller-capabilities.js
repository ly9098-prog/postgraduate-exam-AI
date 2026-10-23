const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  CAPABILITY_NAMES,
  buildLoadRequestControllerCapabilities,
} = require('../subpackages/productivity/pomodoro-stats/load-request-controller-capabilities')

test('builds exactly the controller capability contract', () => {
  const source = Object.fromEntries(CAPABILITY_NAMES.map(name => [name, () => name]))
  const capabilities = buildLoadRequestControllerCapabilities(source)

  assert.deepEqual(Object.keys(capabilities), CAPABILITY_NAMES)
  for (const [name, capability] of Object.entries(capabilities)) {
    assert.equal(capability, source[name])
  }
})

test('omits capabilities that the source does not supply', () => {
  const capabilities = buildLoadRequestControllerCapabilities({})
  assert.equal(CAPABILITY_NAMES.length, 25)
  assert.equal(capabilities.isAlive, undefined)
  assert.equal(capabilities.handleLoadFailure, undefined)
})
