/**
 * Controller for drawing the progress ring on the native canvas.
 *
 * Throttles redraws, caches gradients/geometry, and paints the ring
 * through injected canvas-context callbacks.
 */

const { shouldDrawRing } = require('./ring-geometry')

function createDrawRingController(options) {
  return {
    draw: (totalSec, isBreak) => draw(totalSec, isBreak, options),
  }
}

function resolveCache(isBreak, options) {
  const cacheKey = (isBreak ? 'break' : (options.isFreeTimer() ? 'free' : 'focus')) + '|' + options.themeMode()
  if (!options.getRingCache() || options.getRingCache()._key !== cacheKey) {
    options.setRingCache(options.buildRingCache(isBreak))
    if (options.getRingCache()) options.getRingCache()._key = cacheKey
  }
  return options.getRingCache()
}

function paintRing(ctx, cache, progress, options) {
  const center = cache.center
  const radius = cache.radius
  const lineWidth = cache.lineWidth
  const colors = cache.colors

  ctx.clearRect(0, 0, cache.size, cache.size)

  if (progress > 0) {
    ctx.beginPath()
    ctx.strokeStyle = cache.glowGrad
    ctx.lineWidth = lineWidth + 14
    ctx.lineCap = 'round'
    ctx.globalAlpha = 0.18
    ctx.arc(center, center, radius, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * progress)
    ctx.stroke()
    ctx.globalAlpha = 1
  }

  ctx.beginPath()
  ctx.strokeStyle = options.themeMode() === 'light' ? 'rgba(21,51,35,0.12)' : 'rgba(255,255,255,0.06)'
  ctx.lineWidth = lineWidth
  ctx.arc(center, center, radius, 0, Math.PI * 2)
  ctx.stroke()

  ctx.beginPath()
  ctx.strokeStyle = cache.grad
  ctx.lineWidth = lineWidth
  ctx.lineCap = 'round'
  ctx.arc(center, center, radius, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * progress)
  ctx.stroke()

  if (progress > 0 && progress < 1) {
    const endAngle = -Math.PI / 2 + Math.PI * 2 * progress
    const endX = center + radius * Math.cos(endAngle)
    const endY = center + radius * Math.sin(endAngle)
    ctx.beginPath()
    ctx.fillStyle = colors.dot
    ctx.arc(endX, endY, lineWidth / 2 + 1, 0, Math.PI * 2)
    ctx.fill()
  }

  if (!options.ringCanvasPaintReady()) {
    options.setData({ ringCanvasPaintReady: true })
  }
}

function draw(totalSec, isBreak, options) {
  const ctx = options.getCtx()
  if (!ctx) {
    options.setPendingDraw({ totalSec, isBreak })
    if (options.isPageVisible() && !options.showEndConfirm() &&
        options.ringCanvasVisible() && !options.canvasInitPending()) {
      options.initCanvas(false)
    }
    return
  }

  const progress = options.getProgress()
  const now = options.now()

  if (!shouldDrawRing(progress, isBreak, {
    progress: options.getLastDrawnProgress(),
    isBreak: options.getLastDrawnIsBreak(),
    totalSec,
    at: options.getLastDrawnAt(),
  }, now)) return

  options.setLastDrawnProgress(progress)
  options.setLastDrawnIsBreak(isBreak)
  options.setLastDrawnAt(now)

  const cache = resolveCache(isBreak, options)
  if (!cache) return
  paintRing(ctx, cache, progress, options)
}

module.exports = { createDrawRingController }
