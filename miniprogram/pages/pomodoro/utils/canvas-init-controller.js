/**
 * Controller for initializing and scheduling the native canvas.
 *
 * Owns the retry/scheduling logic and selector-query orchestration.
 * All wx APIs and page-state effects are injected callbacks.
 */

const { evaluateCanvasLayout, buildCanvasSetup, canvasRetryDelay } = require('./canvas-layout')

function createCanvasInitController(options) {
  return {
    init: force => init(force, options),
    schedule: (retryCount, initSeq, previousRect) => schedule(retryCount, initSeq, previousRect, options),
  }
}

function init(force, options) {
  if (!force && ((options.canvasReady() && options.getCtx()) || options.canvasInitPending())) return

  const initSeq = (options.getCanvasInitSeq() || 0) + 1
  options.setCanvasInitSeq(initSeq)
  options.setCanvasInitPending(true)
  options.setCanvasReady(false)
  options.setCtx(null)
  options.setRingCache(null)
  if (options.ringCanvasPaintReady()) {
    options.setData({ ringCanvasPaintReady: false })
  }
  options.setLastDrawnProgress(undefined)
  options.setLastDrawnIsBreak(undefined)
  options.setLastDrawnAt(0)
  schedule(0, initSeq, null, options)
}

function schedule(retryCount, initSeq, previousRect, options) {
  if (initSeq !== options.getCanvasInitSeq()) return
  if (retryCount > options.maxRetries()) {
    options.setCanvasInitPending(false)
    return
  }

  options.nextTick(() => {
    if (initSeq !== options.getCanvasInitSeq()) return
    if (!options.isPageVisible()) {
      options.setCanvasInitPending(false)
      return
    }

    const query = options.createSelectorQuery()
    query.select('.ring-stage').boundingClientRect()
    query.select('#progress-ring').fields({ node: true, size: true, rect: true })
    query.exec(res => handleQueryResult(
      res, retryCount, initSeq, previousRect, options,
    ))
  })
}

function handleQueryResult(res, retryCount, initSeq, previousRect, options) {
  if (initSeq !== options.getCanvasInitSeq()) return

  const stageRect = res && res[0]
  const canvasInfo = res && res[1]
  const layout = evaluateCanvasLayout(stageRect, canvasInfo, previousRect)
  if (layout.status !== 'ready') {
    const delay = canvasRetryDelay(retryCount)
    const retryRect = layout.rect || previousRect
    options.setTimeout(() => schedule(retryCount + 1, initSeq, retryRect, options), delay)
    return
  }

  const canvas = canvasInfo.node
  const windowInfo = options.getWindowInfo()
  const setup = buildCanvasSetup(layout.rect, windowInfo.pixelRatio)
  options.setDpr(setup.dpr)
  options.setCanvasSize(setup.size)
  canvas.width = setup.pixelWidth
  canvas.height = setup.pixelHeight
  const ctx = canvas.getContext('2d')
  ctx.setTransform(setup.dpr, 0, 0, setup.dpr, 0, 0)
  options.setCtx(ctx)
  options.setCanvasReady(true)
  options.setCanvasInitPending(false)
  options.setRingCache(null)
  const pending = options.getPendingDraw()
  if (pending) {
    options.setPendingDraw(null)
    options.drawRing(pending.totalSec, pending.isBreak)
  }
}

module.exports = { createCanvasInitController }
