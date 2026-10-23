const CAPABILITY_NAMES = [
  'isAlive',
  'ensureSettings',
  'ensureSubjectMeta',
  'getRequestId',
  'getSelectedDate',
  'getTodayDate',
  'incrementDateRequestSeq',
  'getDateRequestSeq',
  'hasData',
  'setHasData',
  'cancelDeferredHistory',
  'setData',
  'incrementStatsLoadInFlight',
  'decrementStatsLoadInFlight',
  'getInitialResponses',
  'getHistory',
  'normalizeOverview',
  'reconcileFromServer',
  'logError',
  'getDistributionPeriod',
  'resetPieCache',
  'cancelDurationAnimation',
  'buildLoadViewState',
  'commitLoad',
  'handleLoadFailure',
]

function buildLoadRequestControllerCapabilities(options) {
  return Object.fromEntries(
    CAPABILITY_NAMES.map(name => [name, options[name]])
  )
}

module.exports = {
  CAPABILITY_NAMES,
  buildLoadRequestControllerCapabilities,
}
