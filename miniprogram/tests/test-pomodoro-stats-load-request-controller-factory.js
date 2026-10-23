const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createLoadRequestControllerFactory,
} = require('../subpackages/productivity/pomodoro-stats/load-request-controller-factory')

test('creates the controller with every explicitly supplied capability', () => {
  const passedOptions = []
  const capabilities = Object.fromEntries(
    ['isAlive', 'ensureSettings', 'ensureSubjectMeta', 'getRequestId', 'getSelectedDate',
      'getTodayDate', 'incrementDateRequestSeq', 'getDateRequestSeq', 'hasData', 'setHasData',
      'cancelDeferredHistory', 'setData', 'incrementStatsLoadInFlight', 'decrementStatsLoadInFlight',
      'getInitialResponses', 'getHistory', 'normalizeOverview', 'reconcileFromServer', 'logError',
      'getDistributionPeriod', 'resetPieCache', 'cancelDurationAnimation', 'buildLoadViewState',
      'commitLoad', 'handleLoadFailure'].map(name => [name, () => name])
  )
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
})

test('creates a new controller instance on each call', () => {
  const instances = [{}, {}]
  const factory = createLoadRequestControllerFactory({
    createLoadRequestController: () => instances.shift(),
  })

  assert.notEqual(factory.create(), factory.create())
})
