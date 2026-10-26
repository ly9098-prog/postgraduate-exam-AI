const {
  parseReturnIdentity,
  nearestMatchingIndex,
  oldestMatchingIndex,
} = require('./launch-return-state')

function createLaunchReturnController(options) {
  return {
    findStackIndex: (pages, returnTo) => findStackIndex(options, pages, returnTo),
    navigateBack: (returnTo, attempt) => navigateBack(options, returnTo, attempt),
    returnToOrigin: () => returnToOrigin(options),
  }
}

function findStackIndex(options, pages, returnTo) {
  if (!Array.isArray(pages) || pages.length < 2 || !returnTo) return -1
  const identity = parseReturnIdentity(options, returnTo)
  if (!identity) return -1
  const nearest = nearestMatchingIndex(pages, identity)
  if (nearest < 0) return -1
  return oldestMatchingIndex(pages, identity, nearest)
}

function navigateBack(options, returnTo, attempt = 0) {
  if (!options.isPageAlive()) {
    options.setNavigationLocked(false)
    return
  }
  const pages = options.getCurrentPages()
  const targetIndex = findStackIndex(options, pages, returnTo)
  if (targetIndex < 0) {
    navigateWithoutStackTarget(options, pages, returnTo)
    return
  }
  const delta = Math.max(1, pages.length - 1 - targetIndex)
  const retry = createNavigationRetry(options, returnTo, attempt)
  options.navigateBack({
    delta,
    success: () => checkNavigationSuccess(options, retry),
    fail: retry,
  })
}

function navigateWithoutStackTarget(options, pages, returnTo) {
  options.setNavigationLocked(false)
  if (returnTo) {
    options.redirectTo({
      url: returnTo,
      fail: () => options.reLaunch({ url: '/pages/home/home' }),
    })
    return
  }
  if (pages.length > 1) {
    options.navigateBack({
      delta: 1,
      fail: () => options.reLaunch({ url: '/pages/home/home' }),
    })
    return
  }
  options.reLaunch({ url: '/pages/home/home' })
}

function createNavigationRetry(options, returnTo, attempt) {
  const retryDelays = [44, 96, 180]
  let retryQueued = false
  return () => {
    if (retryQueued) return
    if (!options.isPageAlive()) {
      options.setNavigationLocked(false)
      return
    }
    retryQueued = true
    if (attempt >= retryDelays.length) {
      options.setNavigationLocked(false)
      options.showToast({ title: '返回失败，请再试一次', icon: 'none' })
      return
    }
    options.setTimeout(() => {
      if (!options.isPageAlive()) {
        options.setNavigationLocked(false)
        return
      }
      options.setNavigationLocked(true)
      navigateBack(options, returnTo, attempt + 1)
    }, retryDelays[attempt])
  }
}

function checkNavigationSuccess(options, retry) {
  options.setTimeout(() => {
    if (!options.isPageAlive()) {
      options.setNavigationLocked(false)
      return
    }
    const currentPages = options.getCurrentPages()
    const current = currentPages[currentPages.length - 1] || {}
    const currentRoute = String(current.route || '').replace(/^\//, '')
    if (currentRoute === 'subpackages/study/practice/practice') retry()
  }, 64)
}

function returnToOrigin(options) {
  if (options.isNavigationLocked()) return
  options.setNavigationLocked(true)
  const returnTo = options.getReturnTo()
  const navigate = () => {
    const run = () => options.setTimeout(() => options.navigateBack(returnTo, 0), 20)
    if (options.hasNextTick()) options.nextTick(run)
    else run()
  }
  if (options.isExitGuardVisible()) {
    options.setData({ practiceExitGuardVisible: false }, navigate)
  } else {
    navigate()
  }
}

module.exports = { createLaunchReturnController }
