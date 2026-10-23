function createCompletionCelebrationController(options) {
  return {
    show: (sessionId, celebrationOptions) => show(sessionId, celebrationOptions, options),
  }
}

function show(sessionId, celebrationOptions, options) {
  const celebration = options.buildCompletionCelebration(sessionId, celebrationOptions, {
    data: options.data(),
    mottoes: options.mottoes,
    nextCelebrationType: () => options.nextCelebrationType(),
    MathRandom: Math.random,
  })
  const { completionFlag, viewData, breakSec } = celebration
  // Re-assert attribution at completion so history keeps the task type even if
  // an earlier start-response mapping was interrupted by a restart.
  if (celebration.selectedTaskType) options.recordSession({ id: celebration.sessionId }, celebration.selectedTaskType)

  // Completion is final locally immediately. Remove every running snapshot
  // before showing the animation so onHide cannot persist/resurrect this session.
  options.removeStorage('pomodoro_running_state', 'best-effort cleanup')
  options.removeStorage('pomodoro_pause', 'best-effort cleanup')
  options.removeStorage('pomodoro_free_pause', 'best-effort cleanup')
  options.removeStorage('pomodoro_confirm_pause', 'best-effort cleanup')
  options.removeStorage('pomodoro_pause_adjustment', 'best-effort cleanup')
  options.clearConfirmSnapshot()
  options.timer().endConfirmMode = ''
  options.setCompletionBreakSec(breakSec)

  options.setStorage('pomodoro_completion', completionFlag, 'completion marker')

  // Invalidate the native canvas before the running wx:if block disappears.
  options.invalidateCanvas()

  options.setData(viewData)
}

module.exports = { createCompletionCelebrationController }
