const CANVAS_INIT_MAX_RETRIES = 16
const STAGE_ALIGN_TOLERANCE = 2
const STABLE_LAYOUT_TOLERANCE = 1

function canvasRetryDelay(retryCount) {
  const count = Math.max(0, Number(retryCount) || 0)
  return Math.min(140, 16 + count * 8)
}

function buildCanvasRect(stageRect, canvasInfo) {
  if (!stageRect || !canvasInfo || !canvasInfo.node || !canvasInfo.width || !canvasInfo.height) {
    return null
  }
  return {
    left: Number.isFinite(canvasInfo.left) ? canvasInfo.left : stageRect.left,
    top: Number.isFinite(canvasInfo.top) ? canvasInfo.top : stageRect.top,
    width: canvasInfo.width,
    height: canvasInfo.height,
  }
}

function isStageAligned(rect, stageRect) {
  if (!rect || !stageRect) return false
  return Math.abs(rect.left - stageRect.left) <= STAGE_ALIGN_TOLERANCE &&
    Math.abs(rect.top - stageRect.top) <= STAGE_ALIGN_TOLERANCE &&
    Math.abs(rect.width - stageRect.width) <= STAGE_ALIGN_TOLERANCE &&
    Math.abs(rect.height - stageRect.height) <= STAGE_ALIGN_TOLERANCE
}

function isRectStable(rect, previousRect) {
  if (!rect || !previousRect) return false
  return Math.abs(rect.left - previousRect.left) <= STABLE_LAYOUT_TOLERANCE &&
    Math.abs(rect.top - previousRect.top) <= STABLE_LAYOUT_TOLERANCE &&
    Math.abs(rect.width - previousRect.width) <= STABLE_LAYOUT_TOLERANCE &&
    Math.abs(rect.height - previousRect.height) <= STABLE_LAYOUT_TOLERANCE
}

function evaluateCanvasLayout(stageRect, canvasInfo, previousRect) {
  const rect = buildCanvasRect(stageRect, canvasInfo)
  if (!rect) return { status: 'missing', rect: null }
  if (!isStageAligned(rect, stageRect)) return { status: 'misaligned', rect }
  if (!isRectStable(rect, previousRect)) return { status: 'unstable', rect }
  return { status: 'ready', rect }
}

function buildCanvasSetup(rect, pixelRatio) {
  const dpr = Number(pixelRatio) || 1
  return {
    dpr,
    width: rect.width,
    height: rect.height,
    size: Math.min(rect.width, rect.height),
    pixelWidth: Math.round(rect.width * dpr),
    pixelHeight: Math.round(rect.height * dpr),
  }
}

module.exports = {
  CANVAS_INIT_MAX_RETRIES,
  STAGE_ALIGN_TOLERANCE,
  STABLE_LAYOUT_TOLERANCE,
  canvasRetryDelay,
  buildCanvasRect,
  isStageAligned,
  isRectStable,
  evaluateCanvasLayout,
  buildCanvasSetup,
}
