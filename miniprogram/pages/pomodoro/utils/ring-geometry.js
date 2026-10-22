const RING_PADDING = 18
const RING_LINE_WIDTH = 12

function buildRingColors(isBreak, isFreeTimer) {
  if (isBreak) return { start: '#F43F5E', end: '#F97316', dot: '#F97316' }
  if (isFreeTimer) return { start: '#34D399', end: '#059669', dot: '#10B981' }
  return { start: '#06B6D4', end: '#3B82F6', dot: '#3B82F6' }
}

function buildRingGeometry(size) {
  const safeSize = Math.max(0, Number(size) || 0)
  return {
    size: safeSize,
    center: safeSize / 2,
    radius: Math.max(0, safeSize / 2 - RING_PADDING),
    lineWidth: RING_LINE_WIDTH,
  }
}

function buildRingCache(ctx, size, isBreak, isFreeTimer) {
  if (!ctx) return null
  const geometry = buildRingGeometry(size)
  const colors = buildRingColors(isBreak, isFreeTimer)
  const glowGrad = ctx.createLinearGradient(0, 0, geometry.size, geometry.size)
  glowGrad.addColorStop(0, colors.start)
  glowGrad.addColorStop(1, colors.end)
  const grad = ctx.createLinearGradient(0, 0, geometry.size, geometry.size)
  grad.addColorStop(0, colors.start)
  grad.addColorStop(1, colors.end)
  return {
    ...geometry,
    colors,
    glowGrad,
    grad,
  }
}

function shouldDrawRing(progress, isBreak, previous, now) {
  if (!previous || previous.progress === undefined || previous.isBreak !== isBreak) return true
  const diff = Math.abs(progress - previous.progress)
  const minProgressStep = previous.totalSec > 0
    ? Math.min(1 / 360, 0.8 / previous.totalSec)
    : 0
  const sinceLastDraw = now - Number(previous.at || 0)
  return diff >= minProgressStep || sinceLastDraw >= 1000
}

module.exports = {
  RING_PADDING,
  RING_LINE_WIDTH,
  buildRingColors,
  buildRingGeometry,
  buildRingCache,
  shouldDrawRing,
}
