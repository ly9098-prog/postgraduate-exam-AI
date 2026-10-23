function createLoadRequestControllerFactory(options) {
  return {
    create() {
      return options.createLoadRequestController({
        isAlive: options.isAlive,
        ensureSettings: options.ensureSettings,
        ensureSubjectMeta: options.ensureSubjectMeta,
        getRequestId: options.getRequestId,
        getSelectedDate: options.getSelectedDate,
        getTodayDate: options.getTodayDate,
        incrementDateRequestSeq: options.incrementDateRequestSeq,
        getDateRequestSeq: options.getDateRequestSeq,
        hasData: options.hasData,
        setHasData: options.setHasData,
        cancelDeferredHistory: options.cancelDeferredHistory,
        setData: options.setData,
        incrementStatsLoadInFlight: options.incrementStatsLoadInFlight,
        decrementStatsLoadInFlight: options.decrementStatsLoadInFlight,
        getInitialResponses: options.getInitialResponses,
        getHistory: options.getHistory,
        normalizeOverview: options.normalizeOverview,
        reconcileFromServer: options.reconcileFromServer,
        logError: options.logError,
        getDistributionPeriod: options.getDistributionPeriod,
        resetPieCache: options.resetPieCache,
        cancelDurationAnimation: options.cancelDurationAnimation,
        buildLoadViewState: options.buildLoadViewState,
        commitLoad: options.commitLoad,
        handleLoadFailure: options.handleLoadFailure,
      })
    },
  }
}

module.exports = {
  createLoadRequestControllerFactory,
}
