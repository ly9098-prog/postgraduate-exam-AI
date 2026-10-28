function buildExamReconnectPageCapabilities(page) {
  return {
    isPageAlive: () => page._pageAlive,
    isAttemptLoaded: () => page._attemptLoaded,
    isReconnectSyncing: () => page._reconnectSyncing,
    isAttemptTerminal: () => page._attemptTerminal,
    isTerminalNavigation: () => page._terminalNavigation,
    setReconnectSyncing: value => { page._reconnectSyncing = value },
    tickTimer: () => page._tickTimer(),
    isTimeExpired: () => page.data.timeExpired,
    isSubmitting: () => page.data.submitting,
    submitExam: options => page.submitExam(options),
    flushAllPending: options => page._flushAllPending(options),
  }
}

module.exports = {
  buildExamReconnectPageCapabilities,
}
