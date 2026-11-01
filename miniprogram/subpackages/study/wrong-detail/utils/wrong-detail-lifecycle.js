function onLoad(page, options) {
    page._initWrongDetailState()
    page._initWrongDetailFromOptions(options)
  }

function _initWrongDetailState(page, { setRenderGuardPage }) {
    setRenderGuardPage('wrong-detail')
    page._alive = true
    page._aiRequestId = 0
    page._currentWqId = null
    page._aiGenerationMarker = ''
    page._switching = false
    page._navigationSeq = 0
    page._aiSwipeStart = null
    page._contentTransitionStartedAt = 0
    page._contentTransitionDirection = ''
    page._teacherRequestSeq = 0
    page._diagnosisRequestSeq = 0
    page._teacherCache = Object.create(null)
    page._teacherInflight = Object.create(null)
    page._teacherFeedbackCache = Object.create(null)
    page._activeTeacherCacheKey = ''
    page._wqCache = {}
    page._switchMaskTimer = null
    page._contentTransitionTimer = null
    page._switchWatchdogTimer = null
    page._masterUndoTimer = null
    page._masterAdvanceTimer = null
    page._removeBackTimer = null
    page._bottomActionsTimer = null
    page._bottomActionsLastActiveAt = 0
    page._masterUndoInFlight = false
    page._pendingMasterUndo = null
    if (page._initAiAvailabilityState) page._initAiAvailabilityState()
  }

function _initWrongDetailFromOptions(page, options) {
    const currentId = Number(options.id)
    if (!Number.isFinite(currentId) || currentId <= 0) {
      page.setData({ loading: false, errorText: '错题ID无效', wq: null })
      return
    }
    const questionIds = page._resolveQuestionIds(options, currentId)
    const currentIdx = questionIds.indexOf(currentId)
    page.setData({
      questionIds,
      currentIdx: currentIdx >= 0 ? currentIdx : 0,
      totalQuestions: questionIds.length,
    })
    page.loadData(currentId)
    page._showBottomActions()
  }

function _resolveQuestionIds(options, currentId, deps) {
    let questionIds = []
    try {
      if (options.source === 'wrong-book' || options.source === 'practice-result' || options.source === 'exam-result') {
        const nav = deps.platform.getStorageSync('wrong_detail_nav')
        if (nav && Array.isArray(nav.ids) && Date.now() - Number(nav.ts || 0) < 30 * 60 * 1000) {
          const normalized = nav.ids.map(Number).filter(Number.isFinite)
          const sourceMatches = !nav.source || nav.source === options.source
          if (sourceMatches && normalized.includes(currentId)) questionIds = normalized
        }
      }
    } catch (_) {}
    if (!questionIds.length) questionIds = [currentId]
    return questionIds
  }

function onShow(page) {
if (page._alive && page.data.wq) page._showBottomActions()
if (page._alive && page.data.wq && page._refreshAiAvailability) {
  page._refreshAiAvailability({ force: true, silent: true })
}
}

function onHide(page) {
page._clearBottomActionsTimer()
if (page._clearAiAvailabilityRetry) page._clearAiAvailabilityRetry()
}

function onPageScroll(page) {
page._showBottomActions()
}

function onPageInteraction(page) {
page._showBottomActions()
}

function _clearBottomActionsTimer(page) {
if (!page._bottomActionsTimer) return
clearTimeout(page._bottomActionsTimer)
page._bottomActionsTimer = null
}

function _scheduleBottomActionsAutoHide(page) {
if (!page._alive || page._bottomActionsTimer) return
const tick = () => {
page._bottomActionsTimer = null
if (!page._alive) return
const idleFor = Date.now() - Number(page._bottomActionsLastActiveAt || 0)
const wait = Math.max(0, 3000 - idleFor)
if (wait > 0) {
page._bottomActionsTimer = setTimeout(tick, wait)
return
}
if (page.data.bottomActionsVisible) page.setData({ bottomActionsVisible: false })
}
page._bottomActionsTimer = setTimeout(tick, 3000)
}

function _showBottomActions(page) {
if (!page._alive) return
page._bottomActionsLastActiveAt = Date.now()
if (!page.data.bottomActionsVisible) page.setData({ bottomActionsVisible: true })
page._scheduleBottomActionsAutoHide()
}

function onUnload(page, { resetRenderGuard }) {
page._alive = false
page._aiRequestId++
page._teacherRequestSeq++
page._diagnosisRequestSeq++
if (page._switchMaskTimer) {
clearTimeout(page._switchMaskTimer)
page._switchMaskTimer = null
}
if (page._contentTransitionTimer) {
clearTimeout(page._contentTransitionTimer)
page._contentTransitionTimer = null
}
if (page._switchWatchdogTimer) {
clearTimeout(page._switchWatchdogTimer)
page._switchWatchdogTimer = null
}
if (page._removeBackTimer) {
clearTimeout(page._removeBackTimer)
page._removeBackTimer = null
}
page._clearBottomActionsTimer()
page._clearMasterUndo()
page._wqCache = null
page._teacherCache = null
page._teacherInflight = null
page._teacherFeedbackCache = null
page._activeTeacherCacheKey = ''
if (page._clearAiAvailabilityState) page._clearAiAvailabilityState()
page._aiGenerationMarker = ''
resetRenderGuard()
}

module.exports = { onLoad, _initWrongDetailState, _initWrongDetailFromOptions, _resolveQuestionIds, onShow, onHide, onPageScroll, onPageInteraction, _clearBottomActionsTimer, _scheduleBottomActionsAutoHide, _showBottomActions, onUnload }
