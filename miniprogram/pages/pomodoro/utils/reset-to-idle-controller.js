/**
 * Controller for resetting the pomodoro page to idle state.
 *
 * Clears timers, invalidates canvas state, removes all persisted
 * pomodoro storage keys, resets the view to idle, and updates
 * computed fields — all through injected callbacks.
 */

function createResetToIdleController(options) {
  return {
    reset: () => reset(options),
  }
}

function reset(options) {
  options.clearFreeTimerInterval()
  options.setConfirmTimerSnapshot(null)
  options.invalidateCanvas()
  options.resetTimerState()
  const keys = [
    'pomodoro_break', 'pomodoro_completion', 'pomodoro_pause',
    'pomodoro_free_pause', 'pomodoro_running_state',
    'pomodoro_confirm_pause', 'pomodoro_pause_adjustment',
  ]
  for (const key of keys) options.safeRemoveStorage(key)
  const preferredTaskType = options.getSelectedTaskType()
  options.setData({
    phase: options.idlePhase(),
    selectedTaskType: preferredTaskType,
    selectedTaskTypeLabel: options.taskTypeLabel(preferredTaskType),
    displayMin: '00',
    displaySec: '00',
    isPaused: false,
    isFreeTimer: false,
    freeDisplayTime: '00:00:00',
    showEndConfirm: false,
    ringCanvasPaintReady: false,
    endConfirmTheme: '',
    endConfirmTitle: '',
    endConfirmText: '',
    endConfirmLine1: '',
    endConfirmLine2: '',
    endConfirmLine3: '',
  })
  options.setCompletionBreakSec(null)
  options.updateComputedFields()
}

module.exports = { createResetToIdleController }
