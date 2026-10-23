const { roundRectPath } = require('./pie-geometry')

/**
 * Draws the compact one-line callout near each pie slice.  All inputs are
 * explicit, so this module does not touch Page state, theme mode, or the
 * canvas DPR.  The caller supplies the palette and device pixel ratio
 * resolved for the current render pass.
 */
function drawPieLabels(ctx, layout, reveal, palette, dpr, startIndex = 0, endIndex = layout ? layout.length : 0) {
  if (!layout || !layout.length || reveal <= 0) return
  // Badge positions come from the collision solver, so they are fractional.
  // Drawing the box and a 10px label on a fractional device-pixel boundary is
  // the other half of the blur problem: snap them so both land on whole
  // device pixels.
  const ratio = dpr || 1
  const snap = value => Math.round(value * ratio) / ratio
  ctx.save()
  ctx.globalAlpha = Math.max(0, Math.min(1, reveal))
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'

  for (let i = startIndex; i < Math.min(endIndex, layout.length); i++) {
    const item = layout[i]
    const sec = item.sec

    // Short two-segment elbow: sector edge -> local outward elbow -> badge.
    ctx.strokeStyle = sec.color
    ctx.lineWidth = 1.15
    ctx.beginPath()
    ctx.moveTo(item.startX, item.startY)
    ctx.lineTo(item.elbowX, item.elbowY)
    ctx.lineTo(item.lineEndX, item.lineEndY)
    ctx.stroke()

    ctx.fillStyle = sec.color
    ctx.beginPath()
    ctx.arc(item.startX, item.startY, 2.1, 0, Math.PI * 2)
    ctx.fill()

    const badgeX = snap(item.badgeX)
    const badgeY = snap(item.badgeY)
    roundRectPath(ctx, badgeX, badgeY, item.badgeW, item.badgeH, 8)
    ctx.fillStyle = palette.badgeFill
    ctx.fill()
    ctx.strokeStyle = sec.color
    ctx.lineWidth = 0.8
    ctx.stroke()

    ctx.fillStyle = palette.badgeText
    ctx.font = '600 10px sans-serif'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    // Snap only the glyph origin horizontally: horizontal subpixel offsets are
    // what smear the stroke edges. The vertical +0.5 is the existing optical
    // nudge for CJK under textBaseline:'middle' and is left untouched.
    ctx.fillText(
      sec.subject._durationBadgeText || '0时0分',
      snap(badgeX + item.badgeW / 2),
      badgeY + item.badgeH / 2 + 0.5
    )
  }
  ctx.restore()
}

module.exports = {
  drawPieLabels,
}
