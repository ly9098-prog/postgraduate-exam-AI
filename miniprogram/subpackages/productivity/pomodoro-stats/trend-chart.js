const LIGHT_TREND_COLORS = ['#2F6B4F', '#7A9B76', '#2B8C83', '#B59A38', '#C4773B', '#D96B5F', '#6685A3']
const DARK_TREND_COLORS = ['#22C55E', '#06B6D4', '#3B82F6', '#818CF8', '#A78BFA', '#D946EF']

function fadeIn(progress, start) {
  return Math.max(0, Math.min(1, (progress - start) / (1 - start)))
}

function drawGrid(ctx, layout, palette) {
  const { w, padL, padR, padT, chartH } = layout
  for (let i = 0; i <= 3; i++) {
    const y = padT + chartH * (1 - i / 3)
    ctx.beginPath()
    ctx.strokeStyle = palette.grid
    ctx.lineWidth = 0.5
    ctx.moveTo(padL, y)
    ctx.lineTo(w - padR, y)
    ctx.stroke()
  }
}

function drawBaseline(ctx, layout, palette) {
  const { w, padL, padR, padT, chartH } = layout
  ctx.beginPath()
  ctx.strokeStyle = palette.baseline
  ctx.lineWidth = 1
  ctx.moveTo(padL, padT + chartH)
  ctx.lineTo(w - padR, padT + chartH)
  ctx.stroke()
}

function parseColor(hex) {
  return [
    parseInt(hex.slice(1, 3), 16),
    parseInt(hex.slice(3, 5), 16),
    parseInt(hex.slice(5, 7), 16),
  ]
}

function drawGroundShadow(ctx, x, baseY, barW, finalFade) {
  ctx.save()
  ctx.globalAlpha = finalFade * 0.45
  ctx.translate(x + barW / 2, baseY + 2)
  ctx.scale(1, 0.28)
  const gradient = ctx.createRadialGradient(0, 0, 0, 0, 0, barW * 0.75)
  gradient.addColorStop(0, 'rgba(0,0,0,0.32)')
  gradient.addColorStop(0.5, 'rgba(0,0,0,0.14)')
  gradient.addColorStop(1, 'rgba(0,0,0,0)')
  ctx.fillStyle = gradient
  ctx.beginPath()
  ctx.arc(0, 0, barW * 0.75, 0, Math.PI * 2)
  ctx.fill()
  ctx.restore()
}

function drawRightFace(ctx, x, topY, baseY, barW, depth, topTilt, finalFade, color) {
  const [red, green, blue] = color
  ctx.save()
  ctx.globalAlpha = finalFade
  ctx.fillStyle = `rgba(${Math.round(red*0.5)},${Math.round(green*0.5)},${Math.round(blue*0.5)},0.85)`
  ctx.beginPath()
  ctx.moveTo(x + barW, topY)
  ctx.lineTo(x + barW + depth, topY - depth * topTilt)
  ctx.lineTo(x + barW + depth, baseY - depth * topTilt)
  ctx.lineTo(x + barW, baseY)
  ctx.closePath()
  ctx.fill()
  ctx.restore()
}

function drawFrontFace(ctx, x, topY, baseY, barW, barH, color) {
  const [red, green, blue] = color
  ctx.fillStyle = `rgba(${Math.min(255,red+110)},${Math.min(255,green+110)},${Math.min(255,blue+110)},0.3)`
  ctx.fillRect(x, topY + 2, 1.5, barH - 4)

  const gradient = ctx.createLinearGradient(0, topY, 0, baseY)
  gradient.addColorStop(0, 'rgba(255,255,255,0.12)')
  gradient.addColorStop(0.1, `rgba(${red},${green},${blue},0.6)`)
  gradient.addColorStop(0.42, `rgba(${red},${green},${blue},0.92)`)
  gradient.addColorStop(0.82, `rgba(${Math.round(red*0.7)},${Math.round(green*0.7)},${Math.round(blue*0.7)},0.72)`)
  gradient.addColorStop(1, `rgba(${Math.round(red*0.4)},${Math.round(green*0.4)},${Math.round(blue*0.4)},0.5)`)
  ctx.fillStyle = gradient
  ctx.fillRect(x, topY, barW, barH)
}

function drawLightChannel(ctx, x, topY, barW, barH) {
  if (barH <= 8) return
  const width = Math.max(2, barW * 0.28)
  const left = x + (barW - width) / 2
  const gradient = ctx.createLinearGradient(0, topY, 0, topY + barH * 0.7)
  gradient.addColorStop(0, 'rgba(255,255,255,0.52)')
  gradient.addColorStop(0.35, 'rgba(255,255,255,0.12)')
  gradient.addColorStop(1, 'rgba(255,255,255,0)')
  ctx.fillStyle = gradient
  ctx.fillRect(left, topY, width, barH)
}

function drawTopEdge(ctx, x, topY, barW, barH) {
  if (barH <= 4) return
  ctx.fillStyle = 'rgba(255,255,255,0.35)'
  ctx.fillRect(x, topY, barW, Math.min(2.5, barH / 5))
  ctx.fillStyle = 'rgba(255,255,255,0.15)'
  ctx.fillRect(x, topY + Math.min(2.5, barH / 5), barW, Math.min(1.5, barH / 8))
}

function drawGloss(ctx, x, topY, barW, barH, alpha) {
  ctx.save()
  ctx.globalAlpha = alpha
  const gradient = ctx.createLinearGradient(x, topY, x + barW, topY)
  gradient.addColorStop(0, 'rgba(255,255,255,0)')
  gradient.addColorStop(0.2, 'rgba(255,255,255,0.5)')
  gradient.addColorStop(0.45, 'rgba(255,255,255,0.04)')
  gradient.addColorStop(1, 'rgba(255,255,255,0)')
  ctx.fillStyle = gradient
  ctx.fillRect(x, topY, barW, barH * 0.55)
  ctx.restore()
}

function drawTopFace(ctx, x, topY, barW, depth, topTilt, alpha, color) {
  const [red, green, blue] = color
  ctx.save()
  ctx.globalAlpha = alpha
  ctx.fillStyle = `rgba(${Math.min(255,red+100)},${Math.min(255,green+100)},${Math.min(255,blue+100)},0.6)`
  ctx.beginPath()
  ctx.moveTo(x, topY)
  ctx.lineTo(x + depth, topY - depth * topTilt)
  ctx.lineTo(x + barW + depth, topY - depth * topTilt)
  ctx.lineTo(x + barW, topY)
  ctx.closePath()
  ctx.fill()

  ctx.fillStyle = 'rgba(255,255,255,0.4)'
  ctx.fillRect(x + depth * 0.15, topY - depth * topTilt * 0.3, barW * 0.7, depth * topTilt * 0.3)
  ctx.fillStyle = 'rgba(255,255,255,0.18)'
  const spotW = barW * 0.3
  const spotX = x + barW * 0.5
  ctx.fillRect(spotX, topY - depth * topTilt * 0.65, spotW, depth * topTilt * 0.35)
  ctx.restore()
}

function drawDateLabel(ctx, trend, x, baseY, barW, palette) {
  ctx.fillStyle = palette.dateText
  ctx.font = '9px sans-serif'
  ctx.textAlign = 'center'
  ctx.fillText(trend._shortDate || '', x + barW / 2, baseY + 18)
}

function drawTrendBar(ctx, trend, index, options) {
  const { layout, palette, progress, trendColors } = options
  const x = layout.padL + layout.gap * index + (layout.gap - layout.barW) / 2
  const finalBarH = (trend.duration_sec || 0) / layout.maxDur * layout.chartH
  const barH = Math.max(0, finalBarH * progress)
  const baseY = layout.padT + layout.chartH
  const topY = baseY - barH
  const finalFade = options.finalFade
  const show3D = finalFade > 0.01 && barH > layout.depth * layout.topTilt * 2

  if (trend.duration_sec > 0 && barH > 0) {
    if (finalFade > 0) drawGroundShadow(ctx, x, baseY, layout.barW, finalFade)
    const color = parseColor(trendColors[index % trendColors.length])
    if (show3D) {
      drawRightFace(ctx, x, topY, baseY, layout.barW, layout.depth, layout.topTilt, finalFade, color)
    }
    drawFrontFace(ctx, x, topY, baseY, layout.barW, barH, color)
    drawLightChannel(ctx, x, topY, layout.barW, barH)
    drawTopEdge(ctx, x, topY, layout.barW, barH)
    if (show3D && barH > 20) drawGloss(ctx, x, topY, layout.barW, barH, options.glossAlpha)
    if (show3D) {
      drawTopFace(ctx, x, topY, layout.barW, layout.depth, layout.topTilt, options.topFaceAlpha, color)
    }
  } else if (trend.duration_sec > 0) {
    ctx.fillStyle = palette.emptyBar
    ctx.fillRect(x, baseY - 1, layout.barW, 1)
  } else {
    ctx.fillStyle = palette.pendingBar
    ctx.fillRect(x, baseY - 2, layout.barW, 2)
  }
  drawDateLabel(ctx, trend, x, baseY, layout.barW, palette)
}

function renderTrendBars(ctx, options) {
  const { trends, rect, progress, themeMode, palette } = options
  if (!trends || !trends.length) return
  if (!ctx || !rect || !rect.width) return

  const trendColors = themeMode === 'light' ? LIGHT_TREND_COLORS : DARK_TREND_COLORS
  const w = rect.width
  const h = rect.height
  const padL = 44
  const padR = 16
  const padT = 24
  const padB = 32
  const chartW = w - padL - padR
  const chartH = h - padT - padB
  const barW = Math.min(32, chartW / trends.length * 0.5)
  const gap = chartW / trends.length
  const layout = {
    w,
    padL,
    padR,
    padT,
    chartW,
    chartH,
    barW,
    gap,
    maxDur: Math.max.apply(Math, [1].concat(trends.map(trend => trend.duration_sec || 0))),
    depth: Math.min(7, barW * 0.28),
    topTilt: 0.45,
  }
  const finalFade = fadeIn(progress, 0.82)
  const barOptions = {
    layout,
    palette,
    progress,
    trendColors,
    finalFade,
    glossAlpha: fadeIn(progress, 0.84) * 0.28,
    topFaceAlpha: fadeIn(progress, 0.83),
  }

  ctx.clearRect(0, 0, w, h)
  drawGrid(ctx, layout, palette)
  drawBaseline(ctx, layout, palette)
  trends.forEach((trend, index) => drawTrendBar(ctx, trend, index, barOptions))
}

module.exports = {
  DARK_TREND_COLORS,
  LIGHT_TREND_COLORS,
  renderTrendBars,
}
