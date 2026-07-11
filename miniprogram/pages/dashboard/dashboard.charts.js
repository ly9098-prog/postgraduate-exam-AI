/**
 * Dashboard chart drawing utilities.
 * All canvas operations centralized here for consistency and DPR support.
 */

const COLORS = {
  primary: '#4F7FFF',
  primaryLight: 'rgba(79, 127, 255, 0.32)',
  success: '#22C55E',
  successLight: 'rgba(34, 197, 94, 0.72)',
  warning: '#F59E0B',
  danger: '#EF4444',
  track: '#E2EAF7',
  textHint: '#8EA0BA',
  white: '#FFFFFF',
  gradientStart: '#4F7FFF',
  gradientMid: '#6EC1FF',
  gradientEnd: '#4F7FFF',
}

const BAR_COLORS = ['#4F7FFF', '#22C55E', '#F59E0B', '#EF4444', '#8B5CF6', '#06B6D4']

/**
 * Get canvas 2d context safely, checking node existence.
 * Returns null if canvas not found.
 */
function getCtx(canvasId, pageThis) {
  try {
    const ctx = wx.createCanvasContext(canvasId, pageThis)
    return ctx
  } catch (e) {
    console.warn('[charts] createCanvasContext failed:', canvasId, e)
    return null
  }
}

/**
 * Get canvas dimensions via SelectorQuery.
 */
function getCanvasRect(canvasId, pageThis) {
  return new Promise(resolve => {
    const query = wx.createSelectorQuery().in(pageThis)
    query.select('#' + canvasId).boundingClientRect(rect => {
      resolve(rect)
    }).exec()
  })
}

// ──────────────────────────────────────────────
// Score ring (hero section)
// ──────────────────────────────────────────────
function drawScoreRing(canvasId, pageThis, accuracy, size) {
  if (accuracy === undefined || accuracy === null) return
  getCanvasRect(canvasId, pageThis).then(rect => {
    if (!rect || !rect.width || !rect.height) return
    const s = size || Math.min(rect.width, rect.height)
    const center = s / 2
    const radius = center - 12
    const lw = 10
    const acc = Math.max(0, Math.min(1, accuracy || 0))
    const ctx = getCtx(canvasId, pageThis)
    if (!ctx) return

    // Clear
    ctx.clearRect(0, 0, s, s)

    // Track ring
    ctx.beginPath()
    ctx.setStrokeStyle(COLORS.track)
    ctx.setLineWidth(lw)
    ctx.arc(center, center, radius, 0, Math.PI * 2)
    ctx.stroke()

    // Progress arc
    const start = -Math.PI / 2
    const end = start + Math.PI * 2 * acc
    const grad = ctx.createLinearGradient(0, 0, s, s)
    grad.addColorStop(0, COLORS.gradientStart)
    grad.addColorStop(0.5, COLORS.gradientMid)
    grad.addColorStop(1, COLORS.gradientEnd)
    ctx.beginPath()
    ctx.setStrokeStyle(grad)
    ctx.setLineWidth(lw)
    ctx.setLineCap('round')
    ctx.arc(center, center, radius, start, end)
    ctx.stroke()

    // End dot
    if (acc > 0.02) {
      const dx = center + radius * Math.cos(end)
      const dy = center + radius * Math.sin(end)
      ctx.beginPath()
      ctx.setFillStyle(COLORS.white)
      ctx.arc(dx, dy, 5, 0, Math.PI * 2)
      ctx.fill()
      ctx.setStrokeStyle(COLORS.primary)
      ctx.setLineWidth(2)
      ctx.stroke()
    }

    ctx.draw()
  })
}

// ──────────────────────────────────────────────
// Mastery semi-gauge (ring with gap at bottom)
// ──────────────────────────────────────────────
function drawMasteryGauge(canvasId, pageThis, rate) {
  if (rate === undefined || rate === null) return
  getCanvasRect(canvasId, pageThis).then(rect => {
    if (!rect || !rect.width || !rect.height) return
    const s = Math.min(rect.width, rect.height)
    const center = s / 2
    const radius = center - 14
    const lw = 12
    const r = Math.max(0, Math.min(1, rate || 0))

    // Semi-gauge: 240° arc (bottom 120° gap)
    const startAngle = -Math.PI * 2 / 3  // -120°
    const endAngle = Math.PI * 2 / 3      // +120°
    const sweepAngle = endAngle - startAngle  // 240°

    const ctx = getCtx(canvasId, pageThis)
    if (!ctx) return

    ctx.clearRect(0, 0, s, s)

    // Track
    ctx.beginPath()
    ctx.setStrokeStyle(COLORS.track)
    ctx.setLineWidth(lw)
    ctx.arc(center, center, radius, startAngle, endAngle)
    ctx.stroke()

    // Progress
    const progressEnd = startAngle + sweepAngle * r
    const color = r > 0.6 ? COLORS.success : COLORS.primary
    ctx.beginPath()
    ctx.setStrokeStyle(color)
    ctx.setLineWidth(lw)
    ctx.setLineCap('round')
    ctx.arc(center, center, radius, startAngle, progressEnd)
    ctx.stroke()

    ctx.draw()
  })
}

// ──────────────────────────────────────────────
// Subject donut chart (题量占比)
// ──────────────────────────────────────────────
function drawSubjectDonut(canvasId, pageThis, items) {
  if (!items || !items.length) return
  getCanvasRect(canvasId, pageThis).then(rect => {
    if (!rect || !rect.width || !rect.height) return
    const s = Math.min(rect.width, rect.height)
    const center = s / 2
    const radius = center - 8
    const lw = 18
    const total = items.reduce((sum, i) => sum + (i.totalQuestions || 0), 0)
    if (total === 0) return

    const ctx = getCtx(canvasId, pageThis)
    if (!ctx) return

    ctx.clearRect(0, 0, s, s)

    let currentAngle = -Math.PI / 2  // Start from top
    const slices = items.map((item, idx) => {
      const pct = (item.totalQuestions || 0) / total
      const sliceAngle = Math.PI * 2 * pct
      const color = BAR_COLORS[idx % BAR_COLORS.length]
      const start = currentAngle
      const end = currentAngle + sliceAngle
      currentAngle = end
      return { start, end, color, pct, label: item.label }
    })

    // Draw slices
    slices.forEach(slice => {
      ctx.beginPath()
      ctx.setStrokeStyle(slice.color)
      ctx.setLineWidth(lw)
      ctx.arc(center, center, radius, slice.start, slice.end)
      ctx.stroke()
    })

    ctx.draw()
  })
}

// ──────────────────────────────────────────────
// Trend chart (bars + accuracy line)
// ──────────────────────────────────────────────
function drawTrendChart(canvasId, pageThis, points) {
  if (!points || !points.length) return
  getCanvasRect(canvasId, pageThis).then(rect => {
    if (!rect || !rect.width || !rect.height) return
    const ctx = getCtx(canvasId, pageThis)
    if (!ctx) return

    const w = rect.width
    const h = rect.height
    const pad = { l: 36, r: 20, t: 24, b: 32 }
    const cw = w - pad.l - pad.r
    const ch = h - pad.t - pad.b
    const count = points.length
    const maxQ = Math.max(1, ...points.map(p => p.questions || 0))
    const step = count > 1 ? cw / (count - 1) : cw

    ctx.clearRect(0, 0, w, h)

    // Grid lines
    ctx.setStrokeStyle(COLORS.track)
    ctx.setLineWidth(1)
    for (let i = 0; i <= 3; i++) {
      const y = pad.t + (ch * i) / 3
      ctx.beginPath()
      ctx.moveTo(pad.l, y)
      ctx.lineTo(w - pad.r, y)
      ctx.stroke()
    }

    // Y-axis label
    ctx.setFillStyle(COLORS.textHint)
    ctx.setFontSize(10)
    ctx.fillText(maxQ + '题', 2, pad.t + 10)
    ctx.fillText('0', 8, pad.t + ch + 4)

    // Bar width
    const barW = Math.min(step * 0.6, 28)

    // Draw bars
    points.forEach((p, i) => {
      const x = pad.l + step * i - barW / 2
      const barH = (p.questions || 0) / maxQ * ch
      ctx.beginPath()
      ctx.setFillStyle(COLORS.primaryLight)
      ctx.rect(x, pad.t + ch - barH, barW, barH)
      ctx.fill()
    })

    // Accuracy line
    const accPts = points.map((p, i) => ({
      x: pad.l + step * i,
      y: pad.t + ch - (p.accuracy || 0) * ch,
      acc: p.accuracy || 0,
    }))

    ctx.beginPath()
    accPts.forEach((p, i) => {
      if (i === 0) ctx.moveTo(p.x, p.y)
      else ctx.lineTo(p.x, p.y)
    })
    ctx.setStrokeStyle(COLORS.successLight)
    ctx.setLineWidth(2)
    ctx.stroke()

    // Accuracy dots
    accPts.forEach(p => {
      if (p.acc > 0) {
        ctx.beginPath()
        ctx.setFillStyle(COLORS.white)
        ctx.arc(p.x, p.y, 3.5, 0, Math.PI * 2)
        ctx.fill()
        ctx.setStrokeStyle('rgba(34, 197, 94, 0.82)')
        ctx.setLineWidth(1.5)
        ctx.stroke()
      }
    })

    // X labels (auto-sample for dense data)
    points.forEach((p, i) => {
      if (count > 7 && i % Math.ceil(count / 7) !== 0 && i !== count - 1) return
      ctx.setFillStyle(COLORS.textHint)
      ctx.setFontSize(9)
      ctx.setTextAlign('center')
      ctx.fillText(p.shortDate, pad.l + step * i, pad.t + ch + 18)
    })

    ctx.draw()
  })
}

// ──────────────────────────────────────────────
// Growth level ring (small ring with Lv in center)
// ──────────────────────────────────────────────
function drawGrowthRing(canvasId, pageThis, progressPct, label) {
  if (progressPct === undefined || progressPct === null) return
  getCanvasRect(canvasId, pageThis).then(rect => {
    if (!rect || !rect.width || !rect.height) return
    const s = Math.min(rect.width, rect.height)
    const center = s / 2
    const radius = center - 8
    const lw = 8
    const pct = Math.max(0, Math.min(100, progressPct || 0))

    const ctx = getCtx(canvasId, pageThis)
    if (!ctx) return

    ctx.clearRect(0, 0, s, s)

    // Track
    ctx.beginPath()
    ctx.setStrokeStyle(COLORS.track)
    ctx.setLineWidth(lw)
    ctx.arc(center, center, radius, 0, Math.PI * 2)
    ctx.stroke()

    // Progress
    const start = -Math.PI / 2
    const end = start + Math.PI * 2 * (pct / 100)
    const grad = ctx.createLinearGradient(0, 0, s, s)
    grad.addColorStop(0, COLORS.gradientStart)
    grad.addColorStop(1, COLORS.gradientEnd)
    ctx.beginPath()
    ctx.setStrokeStyle(grad)
    ctx.setLineWidth(lw)
    ctx.setLineCap('round')
    ctx.arc(center, center, radius, start, end)
    ctx.stroke()

    // Center text (drawn on canvas to avoid native canvas covering DOM text)
    if (label !== undefined && label !== null) {
      ctx.setFillStyle(COLORS.primary)
      ctx.setFontSize(12)
      ctx.setTextAlign('center')
      ctx.setTextBaseline('middle')
      ctx.fillText(String(label), center, center)
    }

    ctx.draw()
  })
}

// ──────────────────────────────────────────────
// Adaptive mini gauge (small semi-circle)
// ──────────────────────────────────────────────
function drawAdaptiveGauge(canvasId, pageThis, recallPct) {
  if (recallPct === undefined || recallPct === null) return
  getCanvasRect(canvasId, pageThis).then(rect => {
    if (!rect || !rect.width || !rect.height) return
    const s = Math.min(rect.width, rect.height)
    const center = s / 2
    const radius = center - 8
    const lw = 8
    const pct = Math.max(0, Math.min(100, recallPct || 0))

    const ctx = getCtx(canvasId, pageThis)
    if (!ctx) return

    ctx.clearRect(0, 0, s, s)

    // Use 180° semi-circle
    const startAngle = 0
    const sweepAngle = Math.PI
    const progressEnd = startAngle + sweepAngle * (pct / 100)

    // Track
    ctx.beginPath()
    ctx.setStrokeStyle(COLORS.track)
    ctx.setLineWidth(lw)
    ctx.arc(center, center, radius, startAngle, startAngle + sweepAngle)
    ctx.stroke()

    // Progress
    ctx.beginPath()
    ctx.setStrokeStyle(pct >= 70 ? COLORS.success : COLORS.primary)
    ctx.setLineWidth(lw)
    ctx.setLineCap('round')
    ctx.arc(center, center, radius, startAngle, progressEnd)
    ctx.stroke()

    ctx.draw()
  })
}

// ──────────────────────────────────────────────
// Score gauge (full ring, 0-100, color by tier)
// ──────────────────────────────────────────────
function drawScoreGauge(canvasId, pageThis, score, size, label) {
  if (score === undefined || score === null) return
  getCanvasRect(canvasId, pageThis).then(rect => {
    if (!rect || !rect.width || !rect.height) return
    const s = size || Math.min(rect.width, rect.height)
    const center = s / 2
    const radius = center - 10
    const lw = 8
    const pct = Math.max(0, Math.min(100, score || 0))

    const color = pct >= 80 ? COLORS.success : pct >= 60 ? COLORS.primary : pct >= 40 ? COLORS.warning : COLORS.danger
    const start = -Math.PI / 2
    const end = start + Math.PI * 2 * (pct / 100)

    const ctx = getCtx(canvasId, pageThis)
    if (!ctx) return

    ctx.clearRect(0, 0, s, s)

    // Track
    ctx.beginPath()
    ctx.setStrokeStyle(COLORS.track)
    ctx.setLineWidth(lw)
    ctx.arc(center, center, radius, 0, Math.PI * 2)
    ctx.stroke()

    // Progress
    ctx.beginPath()
    ctx.setStrokeStyle(color)
    ctx.setLineWidth(lw)
    ctx.setLineCap('round')
    ctx.arc(center, center, radius, start, end)
    ctx.stroke()

    // Center text (drawn on canvas to avoid native canvas covering DOM text)
    if (label !== undefined && label !== null) {
      ctx.setFillStyle(color)
      ctx.setFontSize(Math.round(s * 0.28))
      ctx.setTextAlign('center')
      ctx.setTextBaseline('middle')
      ctx.fillText(String(label), center, center)
    }

    ctx.draw()
  })
}

module.exports = {
  drawScoreRing,
  drawMasteryGauge,
  drawSubjectDonut,
  drawTrendChart,
  drawGrowthRing,
  drawAdaptiveGauge,
  drawScoreGauge,
}
