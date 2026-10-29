function _launchReturnController(page, dependencies) {
const { createLaunchReturnController, getPagesFunction, getPlatform, getSetTimeout, safeDecodeURIComponent } = dependencies
return page._launchReturnControllerInstance || (
page._launchReturnControllerInstance = createLaunchReturnController({
safeDecodeURIComponent,
isPageAlive: () => page._pageAlive,
getCurrentPages: () => (getPagesFunction() ? getPagesFunction()() : []),
setNavigationLocked: value => { page._returnNavigationLocked = value },
isNavigationLocked: () => page._returnNavigationLocked,
redirectTo: options => getPlatform().redirectTo(options),
reLaunch: options => getPlatform().reLaunch(options),
navigateBack: options => getPlatform().navigateBack(options),
showToast: options => getPlatform().showToast(options),
setTimeout: (callback, delay) => getSetTimeout()(callback, delay),
hasNextTick: () => typeof getPlatform().nextTick === 'function',
nextTick: callback => getPlatform().nextTick(callback),
getReturnTo: () => page._launchReturnTo || (page._launchPreset && page._launchPreset.returnTo) || '',
isExitGuardVisible: () => page.data.practiceExitGuardVisible,
setData: (patch, callback) => page.setData(patch, callback),
})
)
}

function _exitGuardController(page, dependencies) {
const { createExitGuardController, getClearTimeout, getConsole, getPlatform, getSetTimeout } = dependencies
  return page._exitGuardControllerInstance || (
    page._exitGuardControllerInstance = createExitGuardController({
      getSession: () => page._practiceSession,
      hasDisableAlertBeforeUnload: () => !!getPlatform().disableAlertBeforeUnload,
      disableAlertBeforeUnload: () => getPlatform().disableAlertBeforeUnload(),
      isPageAlive: () => page._pageAlive,
      isGuardVisible: () => page.data.practiceExitGuardVisible,
      isStarted: () => page.data.started,
      isSubmitted: () => page.data.submitted,
      isRearming: () => page._systemBackRearming,
      setRearming: value => { page._systemBackRearming = value },
      getRearmTimer: () => page._systemBackRearmTimer,
      setRearmTimer: timer => { page._systemBackRearmTimer = timer },
      clearTimeout: timer => getClearTimeout()(timer),
      isPromptQueued: () => page._systemBackPromptQueued,
      setPromptQueued: value => { page._systemBackPromptQueued = value },
      isExitConfirmInFlight: () => page._exitConfirmInFlight,
      hasNextTick: () => typeof getPlatform().nextTick === 'function',
      nextTick: callback => getPlatform().nextTick(callback),
      setData: (patch, callback) => page.setData(patch, callback),
      setTimeout: (callback, delay) => getSetTimeout()(callback, delay),
      queueMicrotask: callback => Promise.resolve().then(callback),
      requestExit: options => page.requestExitPractice(options),
      logWarn: (...args) => getConsole().warn(...args),
    })
  )
}

function _exitRequestController(page, dependencies) {
const { createExitRequestController, getClearTimeout, getPlatform } = dependencies
  return page._exitRequestControllerInstance || (
    page._exitRequestControllerInstance = createExitRequestController({
      isExitConfirmInFlight: () => page._exitConfirmInFlight,
      setExitConfirmInFlight: value => { page._exitConfirmInFlight = value },
      isSubmitting: () => page.data.submitting,
      isSubmitted: () => page.data.submitted,
      getPendingResultUrl: () => page._pendingResultUrl,
      getSubmissionSnapshot: () => page._practiceSession && page._practiceSession.submissionSnapshot,
      showConfirm: options => page._showSubmitConfirm(options),
      showPausedConfirm: options => page._showSubmitConfirmPaused(options),
      openSubmittedResult: (resultUrl, submission) => page._openSubmittedResult(resultUrl, submission),
      isPageAlive: () => page._pageAlive,
      clearPendingSubmission: requestId => page._clearPendingSubmission(requestId),
      setUnloadGuard: enabled => page._setPracticeUnloadGuard(enabled),
      incrementQuestionRequestSeq: () => { page._questionsRequestSeq++ },
      clearTimer: () => page._clearTimer(),
      clearFeedbackTimer: () => {
        if (page._feedbackTimer) {
          getClearTimeout()(page._feedbackTimer)
          page._feedbackTimer = null
        }
      },
      resetPracticeState: () => page._resetPracticeStateAfterExit(),
      setLastExitSource: value => { page._lastExitSource = value || '' },
      scrollToSetupTop: () => {
        if (typeof getPlatform().pageScrollTo === 'function') getPlatform().pageScrollTo({ scrollTop: 0, duration: 0 })
      },
    })
  )
}

function _pausedConfirmController(page, dependencies) {
const { createPausedConfirmController, monotonicNow } = dependencies
  return page._pausedConfirmControllerInstance || (
    page._pausedConfirmControllerInstance = createPausedConfirmController({
      getSession: () => page._practiceSession,
      monotonicNow,
      settleQuestionTime: pause => page._settleQuestionTime(pause),
      clearTimer: () => page._clearTimer(),
      showConfirm: options => page._showSubmitConfirm(options),
      isPageAlive: () => page._pageAlive,
      isStarted: () => page.data.started,
      isSubmitted: () => page.data.submitted,
      isSubmitting: () => page.data.submitting,
      startTimer: () => page._startTimer(),
    })
  )
}

function _showSubmitConfirm(page, opts, dependencies) {
const { getPlatform } = dependencies
var comp = page.selectComponent('#submitConfirm')
if (!comp || typeof comp.show !== 'function') {
getPlatform().showToast({ title: opts.title || '请稍后重试', icon: 'none' })
return Promise.resolve(false)
}
return comp.show(opts)
}

module.exports = { _launchReturnController, _exitGuardController, _exitRequestController, _pausedConfirmController, _showSubmitConfirm }
