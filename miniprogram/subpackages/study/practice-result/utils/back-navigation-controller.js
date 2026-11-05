// Pure controller for handleBack navigation. Extracted from
// subpackages/study/practice-result/index.js handleBack.

function createBackNavigationController(options) {
  return {
    back: backImpl.bind(null, options),
    repeatGuest: repeatGuestImpl.bind(null, options),
  }
}

function repeatGuestImpl(options) {
  if (options.getNavigationLocked()) return
  options.setNavigationLocked(true)
  options.redirectTo({
    url: '/subpackages/study/practice/practice?guest=1',
    fail: () => options.setNavigationLocked(false),
  })
}

function backImpl(options) {
  if (options.getNavigationLocked()) return
  options.setNavigationLocked(true)
  const originalReturnTo = options.getReturnTo() || ''
  const fromKnowledgeDetail = options.getLaunchSource() === 'knowledge_map' &&
    /^\/subpackages\/knowledge\/knowledge-detail\/index(?:\?.*)?$/.test(originalReturnTo)
  const preferredReturnTo = fromKnowledgeDetail && options.getLaunchSubjectId()
    ? `/subpackages/knowledge/knowledge-subject/index?subject_id=${options.getLaunchSubjectId()}&restore_state=1`
    : originalReturnTo
  const targetPath = String(preferredReturnTo || '').split('?')[0].replace(/^\//, '')
  navigateExisting(options, preferredReturnTo, targetPath, 0)
}

function navigateExisting(options, preferredReturnTo, targetPath, attempt) {
  const pages = options.getCurrentPages()
  const targetIndex = findTargetIndex(options, pages, targetPath)
  if (targetIndex < 0) {
    handleNoTarget(options, pages, preferredReturnTo)
    return
  }
  const delta = Math.max(1, pages.length - 1 - targetIndex)
  options.navigateBack({
    delta,
    fail: () => retryOrFail(options, attempt, preferredReturnTo, targetPath),
  })
}

function findTargetIndex(options, pages, targetPath) {
  if (!targetPath || !Array.isArray(pages) || pages.length < 2) return -1
  for (let i = pages.length - 2; i >= 0; i -= 1) {
    const page = pages[i] || {}
    const route = String(page.route || '').replace(/^\//, '')
    if (route !== targetPath) continue
    if (targetPath === 'subpackages/knowledge/knowledge-subject/index' && options.getLaunchSubjectId()) {
      const pageSubjectId = Number(page.subjectId || (page.options && page.options.subject_id)) || 0
      if (pageSubjectId && pageSubjectId !== options.getLaunchSubjectId()) continue
    }
    return i
  }
  return -1
}

function handleNoTarget(options, pages, preferredReturnTo) {
  if (pages.length > 1 && !preferredReturnTo) {
    options.navigateBack({ delta: 1, fail: () => fallback(options, preferredReturnTo) })
    return
  }
  fallback(options, preferredReturnTo)
}

function retryOrFail(options, attempt, preferredReturnTo, targetPath) {
  if (attempt < 2) {
    options.setTimeout(() => navigateExisting(options, preferredReturnTo, targetPath, attempt + 1), attempt === 0 ? 48 : 120)
    return
  }
  options.setNavigationLocked(false)
  if (options.isPageAlive()) options.showToast({ title: '返回失败，请再试一次', icon: 'none' })
}

function fallback(options, preferredReturnTo) {
  options.setNavigationLocked(false)
  if (preferredReturnTo) {
    options.redirectTo({ url: preferredReturnTo, fail: () => options.reLaunch({ url: '/pages/home/home' }) })
    return
  }
  options.reLaunch({ url: '/pages/home/home' })
}

module.exports = {
  createBackNavigationController,
}
