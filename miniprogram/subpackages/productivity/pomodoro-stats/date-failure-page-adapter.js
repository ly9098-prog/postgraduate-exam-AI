function buildDateFailurePageCapabilities(page, dependencies) {
  const { wx } = dependencies
  return {
    isAlive: () => page._alive,
    isVisible: () => page._isVisible,
    getDateRequestSeq: () => page._dateRequestSeq,
    logError: (message, error) => console.error(message, error),
    setData: patch => page.setData(patch),
    showToast: title => { if (wx.showToast) wx.showToast({ title, icon: 'none' }) },
  }
}

module.exports = {
  buildDateFailurePageCapabilities,
}
