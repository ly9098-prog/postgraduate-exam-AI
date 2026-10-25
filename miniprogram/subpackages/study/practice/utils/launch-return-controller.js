function createLaunchReturnController(options) {
  return {
    findStackIndex: (pages, returnTo) => findStackIndex(options, pages, returnTo),
    navigateBack: (returnTo, attempt) => navigateBack(options, returnTo, attempt),
    returnToOrigin: () => returnToOrigin(options),
  }
}

function findStackIndex(options, pages, returnTo) {
  if (!Array.isArray(pages) || pages.length < 2 || !returnTo) return -1
  const targetPath = String(returnTo).split('?')[0].replace(/^\//, '')
  if (!targetPath) return -1
  let expectedSubjectId = 0
  let expectedPointId = 0
  const query = String(returnTo).split('?')[1] || ''
  query.split('&').forEach((part) => {
    const pair = String(part || '').split('=')
    const key = pair[0]
    const value = Number(options.safeDecodeURIComponent(pair.slice(1).join('='), ''))
    if (key === 'subject_id' && Number.isInteger(value) && value > 0) expectedSubjectId = value
    if (key === 'knowledge_point_id' && Number.isInteger(value) && value > 0) expectedPointId = value
  })
  const matchesIdentity = (page) => {
    if (!page) return false
    const route = String(page.route || '').replace(/^\//, '')
    if (route !== targetPath) return false
    if (targetPath === 'subpackages/knowledge/knowledge-subject/index' && expectedSubjectId) {
      const pageSubjectId = Number(page.subjectId || (page.options && page.options.subject_id)) || 0
      return !pageSubjectId || pageSubjectId === expectedSubjectId
    }
    if (targetPath === 'subpackages/knowledge/knowledge-detail/index' && expectedPointId) {
      const currentPointId = Number(page.knowledgePointId || (page.options && page.options.knowledge_point_id)) || 0
      return !currentPointId || currentPointId === expectedPointId
    }
    return true
  }
  let nearest = -1
  for (let i = pages.length - 2; i >= 0; i -= 1) {
    if (matchesIdentity(pages[i])) {
      nearest = i
      break
    }
  }
  if (nearest < 0) return -1
  let targetIndex = nearest
  for (let i = nearest - 1; i >= 0; i -= 1) {
    if (!matchesIdentity(pages[i])) break
    targetIndex = i
  }
  return targetIndex
}

function navigateBack(options, returnTo, attempt = 0) {
  if (!options.isPageAlive()) {
    options.setNavigationLocked(false)
    return
  }
  const pages = options.getCurrentPages()
  const targetIndex = findStackIndex(options, pages, returnTo)
  if (targetIndex < 0) {
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
    return
  }
  const delta = Math.max(1, pages.length - 1 - targetIndex)
  const retryDelays = [44, 96, 180]
  let retryQueued = false
  const retry = () => {
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
  options.navigateBack({
    delta,
    success: () => {
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
    },
    fail: retry,
  })
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
