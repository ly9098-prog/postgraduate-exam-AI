/**
 * Adapt page state and lifecycle methods to the load-request controller.
 * The controller contract remains explicit; this module only owns the page
 * bindings and API request shapes.
 */
function buildLoadRequestPageCapabilities(page, dependencies) {
  return {
    ...buildLifecycleCapabilities(page),
    ...buildRequestStateCapabilities(page),
    ...buildNetworkCapabilities(dependencies),
    ...buildViewCapabilities(page),
  }
}

function buildLifecycleCapabilities(page) {
  return {
    isAlive: () => page._alive,
    ensureSettings: () => page._ensureSettings(),
    ensureSubjectMeta: () => page._ensureSubjectMeta(),
    getRequestId: () => page._requestId,
    getSelectedDate: () => page.data.selectedDate,
    getTodayDate: () => page.data._todayDate,
  }
}

function buildRequestStateCapabilities(page) {
  return {
    incrementDateRequestSeq: () => {
      page._dateRequestSeq = (page._dateRequestSeq || 0) + 1
    },
    getDateRequestSeq: () => page._dateRequestSeq,
    hasData: () => page._hasData,
    setHasData: value => {
      page._hasData = value
    },
    cancelDeferredHistory: clearPending => page._cancelDeferredHistory(clearPending),
    setData: patch => page.setData(patch),
    incrementStatsLoadInFlight: () => {
      page._statsLoadInFlight = (page._statsLoadInFlight || 0) + 1
    },
    decrementStatsLoadInFlight: () => {
      page._statsLoadInFlight = Math.max(0, (page._statsLoadInFlight || 1) - 1)
    },
  }
}

function buildNetworkCapabilities(dependencies) {
  const { api, normalizeOverview } = dependencies
  return {
    getInitialResponses: (requestedDate, viewingToday) => Promise.all([
      api.get(
        '/pomodoro/statistics-overview',
        viewingToday ? {} : { date: requestedDate },
      ),
      api.get('/pomodoro/history', {
        page: 1,
        page_size: 20,
        date: requestedDate,
      }),
    ]),
    getHistory: date => api.get('/pomodoro/history', {
      page: 1,
      page_size: 20,
      date,
    }),
    normalizeOverview: response => normalizeOverview(response),
  }
}

function buildViewCapabilities(page) {
  return {
    reconcileFromServer: (stats, summary) => page._reconcileFromServer(stats, summary),
    logError: (message, error) => console.error(message, error),
    getDistributionPeriod: () => page.data.distributionPeriod,
    resetPieCache: () => page._resetPieCache(),
    cancelDurationAnimation: resetState => page._cancelDurationAnimation(resetState),
    buildLoadViewState: overrides => page._buildLoadViewState(overrides),
    commitLoad: (viewState, context) => page._getLoadCommitController().commit(
      viewState,
      context,
    ),
    handleLoadFailure: (error, context) => page._getLoadFailureController().handle(
      error,
      context,
    ),
  }
}

module.exports = {
  buildLoadRequestPageCapabilities,
}
