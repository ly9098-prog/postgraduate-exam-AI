function createDeferredHistoryController(options) {
  const buildPending = (reqId, dateSeq, selectedDate, sessions, total) => ({
    reqId,
    dateSeq,
    selectedDate,
    sessions: Array.isArray(sessions) ? sessions : [],
    total: Number(total) || 0,
  })

  return {
    cancel(clearPending) {
      if (options.getTimer()) {
        options.clearTimeout(options.getTimer())
        options.setTimer(null)
      }
      if (clearPending) options.setPending(null)
    },
    queue(reqId, dateSeq, selectedDate, sessions, total) {
      this.cancel(true)
      const pending = buildPending(reqId, dateSeq, selectedDate, sessions, total)
      options.setPending(pending)
      // Keep the below-the-fold list out of the first layout and animation frames.
      options.setTimer(options.setTimeout(() => {
        options.setTimer(null)
        const queued = options.getPending()
        options.setPending(null)
        if (
          !queued ||
          !options.isAlive() ||
          !options.isVisible() ||
          queued.reqId !== options.getRequestId() ||
          queued.dateSeq !== options.getDateRequestSeq() ||
          queued.selectedDate !== options.getSelectedDate()
        ) return
        options.setData({
          history: queued.sessions.map(options.formatSession),
          historyTotal: queued.total,
          historyReady: true,
        })
      }, 1300))
    },
  }
}

module.exports = {
  createDeferredHistoryController,
}
