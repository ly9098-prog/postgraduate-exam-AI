function buildLoadFailurePageCapabilities(page) {
  return {
    isAlive: () => page._alive,
    getRequestId: () => page._requestId,
    getDateRequestSeq: () => page._dateRequestSeq,
    getSelectedDate: () => page.data.selectedDate,
    isContentReady: () => !!page.data.contentReady,
    logError: (message, error) => console.error(message, error),
    setData: patch => page.setData(patch),
  }
}

module.exports = {
  buildLoadFailurePageCapabilities,
}
