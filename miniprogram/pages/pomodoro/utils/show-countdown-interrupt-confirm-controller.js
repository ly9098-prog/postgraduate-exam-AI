/**
 * Controller for showing the countdown-interrupt end-confirm overlay.
 *
 * Pauses the countdown, builds the confirm view model, and triggers
 * a canvas redraw — all through injected callbacks.
 */

const { buildEndConfirmViewModel } = require('./end-confirm-view-model')

function createShowCountdownInterruptConfirmController(options) {
  return {
    show: () => show(options),
  }
}

function show(options) {
  if (options.isActionLoading()) return

  options.pauseCountdown().then(ok => {
    if (!ok || !options.getConfirmTimerSnapshot()) return

    const snapshot = options.getConfirmTimerSnapshot()

    options.setData({
      ...buildEndConfirmViewModel('countdown-interrupt', snapshot),
      ringCanvasVisible: true,
    })

    options.nextTick(() => {
      options.initCanvas(true)
      options.drawRing(snapshot.totalSec, snapshot.phase === 'break')
    })
  })
}

module.exports = { createShowCountdownInterruptConfirmController }
