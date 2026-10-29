// Page capability assembly for miniprogram/subpackages/study/practice-result/index.js.
// Assemble live page ports here; the page keeps lazy controller memoisation.

function buildBackNavigationPageCapabilities(page, deps) {
  return {
    getNavigationLocked: () => page._navigationLocked,
    setNavigationLocked: value => { page._navigationLocked = value },
    getReturnTo: () => page._returnTo || '',
    getLaunchSource: () => page._launchSource,
    getLaunchSubjectId: () => page._launchSubjectId,
    isPageAlive: () => page._pageAlive,
    getCurrentPages: () => (typeof getCurrentPages === 'function' ? getCurrentPages() : []),
    navigateBack: options => wx.navigateBack(options),
    redirectTo: options => wx.redirectTo(options),
    reLaunch: options => wx.reLaunch(options),
    showToast: options => wx.showToast(options),
    setTimeout,
  }
}

module.exports = {
  buildBackNavigationPageCapabilities,
}
