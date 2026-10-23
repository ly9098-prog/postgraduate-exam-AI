/**
 * Controller for updating the free-timer elapsed display.
 *
 * Reads timer state and page data through injected callbacks, computes
 * the formatted display, and writes back — without holding a page
 * reference.
 */

const { formatElapsedSec } = require('./timer-math')

function createUpdateFreeElapsedController(options) {
  return {
    update: () => update(options),
  }
}

function update(options) {
  if (!options.isFreeTimer()) return
  if (options.showEndConfirm()) return

  if (options.isPaused()) {
    const fmt = formatElapsedSec(options.getElapsedSec() || 0)
    options.setData({ freeDisplayTime: fmt.display })
    options.setFreeFriendlyText(fmt.friendly)
    return
  }

  const elapsedMs = options.getEffectiveFreeElapsedMs()
  const cappedMs = Math.min(elapsedMs, options.maxMs())
  const elapsedSec = Math.floor(cappedMs / 1000)

  if (elapsedSec === options.getElapsedSec()) return
  const fmt = formatElapsedSec(elapsedSec)
  options.setElapsedSec(elapsedSec)
  options.setFreeFriendlyText(fmt.friendly)
  options.setData({ freeDisplayTime: fmt.display })
}

module.exports = { createUpdateFreeElapsedController }
