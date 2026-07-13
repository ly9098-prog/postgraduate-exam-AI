/**
 * Dashboard chart drawing utilities.
 * All canvas operations centralized here for consistency and DPR support.
 */

const COLORS = {
  primary: '#66844F',
  primaryLight: 'rgba(102, 132, 79, 0.20)',
  success: '#2D9B68',
  successLight: 'rgba(134, 207, 169, 0.94)',
  warning: '#D99A45',
  danger: '#D9685B',
  track: '#E4E8E1',
  textHint: '#818A82',
  white: '#FFFFFF',
  gradientStart: '#587643',
  gradientMid: '#789661',
  gradientEnd: '#587643',
}

const BAR_COLORS = ['#587643', '#2D9B68', '#D99A45', '#D9685B', '#7A6E9B', '#6E8B8F']

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
function drawTrendChart(canvasId, pageThis, points, options) {
  if (!points || !points.length) return
  const opts = options || {}
  const metric = opts.metric === 'questions' ? 'questions' : 'accuracy'
  const previousPoints = Array.isArray(opts.previousPoints) ? opts.previousPoints : []

  getCanvasRect(canvasId, pageThis).then(rect => {
    if (!rect || !rect.width || !rect.height) return
    const ctx = getCtx(canvasId, pageThis)
    if (!ctx) return

    const w = rect.width
    const h = rect.height
    ctx.clearRect(0, 0, w, h)

    const formatAxisValue = value => {
      const n = Math.max(0, Number(value) || 0)
      if (n >= 10000) return (n / 10000).toFixed(n % 10000 === 0 ? 0 : 1) + 'w'
      if (n >= 1000) return (n / 1000).toFixed(n % 1000 === 0 ? 0 : 1) + 'k'
      return String(Math.round(n))
    }

    const niceScale = maxValue => {
      const rawMax = Math.max(1, Number(maxValue) || 0)
      const roughStep = rawMax / 3
      const exponent = Math.floor(Math.log10(Math.max(roughStep, 0.0001)))
      const power = Math.pow(10, exponent)
      const fraction = roughStep / power
      let niceFraction = 1
      if (fraction <= 1) niceFraction = 1
      else if (fraction <= 2) niceFraction = 2
      else if (fraction <= 5) niceFraction = 5
      else niceFraction = 10
      const step = niceFraction * power
      return {
        step,
        max: Math.max(step * 3, Math.ceil(rawMax / step) * step),
      }
    }

    const drawTopRoundedBar = (x, y, width, height, radius, fillStyle) => {
      if (height <= 0 || width <= 0) return
      const r = Math.max(0, Math.min(radius, width / 2, height / 2))
      ctx.beginPath()
      ctx.moveTo(x, y + height)
      ctx.lineTo(x, y + r)
      ctx.quadraticCurveTo(x, y, x + r, y)
      ctx.lineTo(x + width - r, y)
      ctx.quadraticCurveTo(x + width, y, x + width, y + r)
      ctx.lineTo(x + width, y + height)
      ctx.closePath()
      ctx.setFillStyle(fillStyle)
      ctx.fill()
    }

    const sampledLabel = (list, i) => {
      if (list.length <= 7) return true
      const every = Math.ceil(list.length / 6)
      return i === 0 || i === list.length - 1 || i % every === 0
    }

    if (metric === 'questions') {
      // Keep the reference chart's generous spacing on 30/90-day ranges by
      // grouping daily data into at most seven visual columns.
      const maxGroups = 7
      const bucketSize = points.length > maxGroups ? Math.ceil(points.length / maxGroups) : 1
      const grouped = []
      for (let startIndex = 0; startIndex < points.length; startIndex += bucketSize) {
        const currentSlice = points.slice(startIndex, startIndex + bucketSize)
        const previousSlice = previousPoints.slice(startIndex, startIndex + bucketSize)
        const lastPoint = currentSlice[currentSlice.length - 1] || {}
        grouped.push({
          shortDate: lastPoint.shortDate || '',
          questions: currentSlice.reduce((sum, item) => sum + (item.questions || 0), 0),
          correct: currentSlice.reduce((sum, item) => sum + (item.correct || 0), 0),
          previousQuestions: previousSlice.reduce((sum, item) => sum + (item.questions || 0), 0),
          hasPrevious: previousSlice.length > 0,
        })
      }

      const hasPrevious = grouped.some(item => item.hasPrevious)
      const values = []
      grouped.forEach(item => {
        values.push(item.correct || 0, item.questions || 0)
        if (item.hasPrevious) values.push(item.previousQuestions || 0)
      })
      const scale = niceScale(Math.max(1, ...values))

      // More left padding is reserved for editorial y-axis labels.
      const pad = { l: 38, r: 8, t: 12, b: 34 }
      const plotW = Math.max(1, w - pad.l - pad.r)
      const plotH = Math.max(1, h - pad.t - pad.b)
      const baselineY = pad.t + plotH
      const tickCount = 3

      ctx.setFontSize(9)
      ctx.setTextAlign('right')
      ctx.setTextBaseline('middle')
      for (let tick = 0; tick <= tickCount; tick++) {
        const value = scale.step * tick
        const ratio = value / scale.max
        const y = baselineY - ratio * plotH
        ctx.setStrokeStyle(tick === 0 ? 'rgba(17,18,20,.075)' : 'rgba(17,18,20,.045)')
        ctx.setLineWidth(1)
        ctx.beginPath()
        ctx.moveTo(pad.l, y)
        ctx.lineTo(w - pad.r, y)
        ctx.stroke()

        ctx.setFillStyle('#8B8F96')
        ctx.fillText(formatAxisValue(value), pad.l - 8, y)
      }

      const bandW = plotW / Math.max(grouped.length, 1)
      const seriesCount = hasPrevious ? 3 : 2
      const gap = Math.max(2.5, Math.min(4.5, bandW * 0.075))
      const desiredGroupW = Math.min(bandW * 0.72, 48)
      const barW = Math.max(5, Math.min(14, (desiredGroupW - gap * (seriesCount - 1)) / seriesCount))
      const groupW = barW * seriesCount + gap * (seriesCount - 1)

      grouped.forEach((item, i) => {
        const centerX = pad.l + bandW * (i + 0.5)

        // Very faint vertical guides reproduce the reference's chart rhythm.
        ctx.setStrokeStyle('rgba(17,18,20,.032)')
        ctx.setLineWidth(1)
        ctx.beginPath()
        ctx.moveTo(centerX, pad.t)
        ctx.lineTo(centerX, baselineY)
        ctx.stroke()

        const series = [
          { value: item.correct || 0, color: '#2D9B68' },
          { value: item.questions || 0, color: '#DDE4DB' },
        ]
        if (hasPrevious) {
          series.push({ value: item.hasPrevious ? (item.previousQuestions || 0) : 0, color: '#B8BDB8' })
        }

        const startX = centerX - groupW / 2
        series.forEach((entry, seriesIndex) => {
          const barHeight = entry.value > 0 ? Math.max(2, entry.value / scale.max * plotH) : 0
          const x = startX + seriesIndex * (barW + gap)
          const y = baselineY - barHeight
          drawTopRoundedBar(x, y, barW, barHeight, Math.min(3, barW * 0.26), entry.color)
        })

        ctx.setFillStyle('#7E8289')
        ctx.setFontSize(9)
        ctx.setTextAlign('center')
        ctx.setTextBaseline('alphabetic')
        ctx.fillText(item.shortDate || '', centerX, baselineY + 23)
      })
    } else {
      const pad = { l: 16, r: 14, t: 18, b: 30 }
      const cw = w - pad.l - pad.r
      const ch = h - pad.t - pad.b
      const count = points.length
      const step = count > 1 ? cw / (count - 1) : cw

      // Editorial-style grid: only two very light reference lines.
      ctx.setStrokeStyle('rgba(20, 22, 26, 0.075)')
      ctx.setLineWidth(1)
      ;[0.34, 0.68].forEach(ratio => {
        const y = pad.t + ch * ratio
        ctx.beginPath()
        ctx.moveTo(pad.l, y)
        ctx.lineTo(w - pad.r, y)
        ctx.stroke()
      })

      const toPoint = (p, i) => ({
        x: count > 1 ? pad.l + step * i : pad.l + cw / 2,
        y: pad.t + ch - Math.max(0, Math.min(1, p.accuracy || 0)) * ch,
      })
      const current = points.map(toPoint)
      const previous = previousPoints.slice(0, count).map(toPoint)

      const fillArea = (list, fillStyle, strokeStyle) => {
        if (!list.length) return
        ctx.beginPath()
        ctx.moveTo(list[0].x, pad.t + ch)
        list.forEach((pt, i) => {
          if (i === 0) ctx.lineTo(pt.x, pt.y)
          else ctx.lineTo(pt.x, pt.y)
        })
        ctx.lineTo(list[list.length - 1].x, pad.t + ch)
        ctx.closePath()
        ctx.setFillStyle(fillStyle)
        ctx.fill()

        ctx.beginPath()
        list.forEach((pt, i) => {
          if (i === 0) ctx.moveTo(pt.x, pt.y)
          else ctx.lineTo(pt.x, pt.y)
        })
        ctx.setStrokeStyle(strokeStyle)
        ctx.setLineWidth(1.4)
        ctx.stroke()
      }

      fillArea(previous, 'rgba(205, 209, 203, 0.66)', 'rgba(171, 177, 169, 0.88)')
      const currentGradient = ctx.createLinearGradient(0, pad.t, 0, pad.t + ch)
      currentGradient.addColorStop(0, 'rgba(88, 118, 67, 0.72)')
      currentGradient.addColorStop(1, 'rgba(88, 118, 67, 0.10)')
      fillArea(current, currentGradient, '#587643')

      let activeIndex = -1
      for (let i = points.length - 1; i >= 0; i--) {
        if ((points[i].questions || 0) > 0 || (points[i].accuracy || 0) > 0) {
          activeIndex = i
          break
        }
      }
      if (activeIndex >= 0) {
        const pt = current[activeIndex]
        ctx.beginPath()
        ctx.setFillStyle('#F4F4F1')
        ctx.arc(pt.x, pt.y, 5, 0, Math.PI * 2)
        ctx.fill()
        ctx.setStrokeStyle('#B7E82A')
        ctx.setLineWidth(2.4)
        ctx.stroke()
      }

      points.forEach((p, i) => {
        if (!sampledLabel(points, i)) return
        const x = count > 1 ? pad.l + step * i : pad.l + cw / 2
        ctx.setFillStyle('#8A8D93')
        ctx.setFontSize(9)
        ctx.setTextAlign('center')
        ctx.setTextBaseline('alphabetic')
        ctx.fillText(p.shortDate || '', x, pad.t + ch + 20)
      })
    }

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
