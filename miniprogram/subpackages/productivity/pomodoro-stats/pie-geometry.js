/**
 * Pie chart geometry primitives and the shared canvas drawing helpers that
 * depend only on the provided context and geometry.  These functions do not
 * touch any Page state, so they can be unit-tested and reused by the pie
 * render and label layers without crossing the controller boundary.
 */

function getPieGeometry(rect) {
  const w = rect.width
  const h = rect.height
  // Reserve explicit side gutters for reference-style labels.  The old 25.5%
  // radius left too little horizontal room, forcing leader lines into a
  // vertical stack on one side of the pie.
  const radius = Math.min(w * 0.215, h * 0.275)
  return {
    w,
    h,
    centerX: w / 2,
    centerY: h * 0.49,
    radius,
    tilt: 0.74,
    depth: radius * 0.08,
  }
}

function drawEllipticSector(ctx, cx, cy, radius, scaleY, startA, endA, fillStyle, strokeStyle, lineW) {
  ctx.save()
  ctx.translate(cx, cy)
  ctx.scale(1, scaleY)
  ctx.beginPath()
  ctx.moveTo(0, 0)
  ctx.arc(0, 0, radius, startA, endA)
  ctx.closePath()
  if (fillStyle) {
    ctx.fillStyle = fillStyle
    ctx.fill()
  }
  if (strokeStyle) {
    ctx.strokeStyle = strokeStyle
    ctx.lineWidth = lineW || 1
    ctx.stroke()
  }
  ctx.restore()
}

function roundRectPath(ctx, x, y, width, height, radius) {
  const r = Math.min(radius, width / 2, height / 2)
  ctx.beginPath()
  ctx.moveTo(x + r, y)
  ctx.lineTo(x + width - r, y)
  ctx.quadraticCurveTo(x + width, y, x + width, y + r)
  ctx.lineTo(x + width, y + height - r)
  ctx.quadraticCurveTo(x + width, y + height, x + width - r, y + height)
  ctx.lineTo(x + r, y + height)
  ctx.quadraticCurveTo(x, y + height, x, y + height - r)
  ctx.lineTo(x, y + r)
  ctx.quadraticCurveTo(x, y, x + r, y)
  ctx.closePath()
}

module.exports = {
  getPieGeometry,
  drawEllipticSector,
  roundRectPath,
}
