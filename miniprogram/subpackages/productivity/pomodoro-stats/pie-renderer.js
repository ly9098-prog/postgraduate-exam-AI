const pieGeometry = require('./pie-geometry')
const pieLabelRenderer = require('./pie-label-renderer')
const pieSectorBuilder = require('./pie-sector-builder')

function sortSectorsBySelected(sectors, selectedSubject) {
  if (!selectedSubject) return sectors
  return sectors.slice().sort((a, b) => {
    const aSelected = a.subject.subject === selectedSubject ? 1 : 0
    const bSelected = b.subject.subject === selectedSubject ? 1 : 0
    return aSelected - bSelected
  })
}

function hasPositiveDuration(subjects) {
  return Array.isArray(subjects) && subjects.length &&
    subjects.some(item => Number(item && item.duration_sec) > 0)
}

function drawShadow(ctx, geometry, reveal, palette) {
  const { centerX, centerY, radius, tilt, depth } = geometry
  ctx.save()
  ctx.globalAlpha = reveal
  ctx.translate(centerX + 4, centerY + depth * 1.3)
  ctx.scale(1, tilt)
  const shadowGrad = ctx.createRadialGradient(0, 0, 0, 0, 0, radius * 1.05)
  shadowGrad.addColorStop(0, palette.shadowStart)
  shadowGrad.addColorStop(0.5, palette.shadowMid)
  shadowGrad.addColorStop(1, 'rgba(0,0,0,0)')
  ctx.fillStyle = shadowGrad
  ctx.beginPath()
  ctx.arc(0, 0, radius * 1.05, 0, Math.PI * 2)
  ctx.fill()
  ctx.restore()
}

function drawSideWalls(ctx, sectors, selectedSubject, geometry, progress, wallSteps, shade) {
  const { centerX, centerY, radius, tilt, depth } = geometry
  const sortedSectors = sortSectorsBySelected(sectors, selectedSubject)
  for (let layer = wallSteps; layer >= 1; layer--) {
    const layerOffset = depth * layer / wallSteps * progress
    sortedSectors.forEach(sec => {
      const curEnd = sec.startA + (sec.endA - sec.startA) * progress
      if (curEnd - sec.startA < 0.002) return
      const mid = (sec.startA + curEnd) / 2
      const isSelected = selectedSubject && sec.subject.subject === selectedSubject
      const pull = isSelected ? 6 : 0
      const cx = centerX + Math.cos(mid) * pull
      const cy = centerY + Math.sin(mid) * pull * tilt + layerOffset
      pieGeometry.drawEllipticSector(
        ctx, cx, cy, radius, tilt, sec.startA, curEnd,
        sec._wallShades[layer - 1]
      )
    })
  }
  return sortedSectors
}

function drawTopSectors(ctx, sortedSectors, selectedSubject, geometry, progress, shade) {
  const { centerX, centerY, radius, tilt } = geometry
  sortedSectors.forEach(sec => {
    const curEnd = sec.startA + (sec.endA - sec.startA) * progress
    if (curEnd - sec.startA < 0.002) return
    const mid = (sec.startA + curEnd) / 2
    const isSelected = selectedSubject && sec.subject.subject === selectedSubject
    const pull = isSelected ? 6 : 0
    const cx = centerX + Math.cos(mid) * pull
    const cy = centerY + Math.sin(mid) * pull * tilt
    const fillColor = isSelected ? shade(sec.color, 12) : sec.color
    pieGeometry.drawEllipticSector(ctx, cx, cy, radius, tilt, sec.startA, curEnd, fillColor)
  })
}

function drawSeparators(ctx, sectors, geometry, reveal, palette) {
  const { centerX, centerY, radius, tilt } = geometry
  ctx.save()
  ctx.globalAlpha = reveal
  ctx.translate(centerX, centerY)
  ctx.scale(1, tilt)
  ctx.strokeStyle = palette.separator
  ctx.lineWidth = 1
  sectors.forEach(sec => {
    ctx.beginPath()
    ctx.moveTo(0, 0)
    ctx.lineTo(Math.cos(sec.startA) * radius, Math.sin(sec.startA) * radius)
    ctx.stroke()
  })
  ctx.restore()
}

function drawLighting(ctx, geometry, reveal) {
  const { centerX, centerY, radius, tilt } = geometry
  ctx.save()
  ctx.globalAlpha = reveal
  ctx.translate(centerX, centerY)
  ctx.scale(1, tilt)
  ctx.beginPath()
  ctx.arc(0, 0, radius, 0, Math.PI * 2)
  ctx.clip()
  const lightGrad = ctx.createRadialGradient(
    -radius * 0.2, -radius * 0.2, 0,
    -radius * 0.2, -radius * 0.2, radius
  )
  lightGrad.addColorStop(0, 'rgba(255,255,255,0.14)')
  lightGrad.addColorStop(0.35, 'rgba(255,255,255,0.04)')
  lightGrad.addColorStop(0.7, 'rgba(0,0,0,0.04)')
  lightGrad.addColorStop(1, 'rgba(0,0,0,0.10)')
  ctx.fillStyle = lightGrad
  ctx.beginPath()
  ctx.arc(0, 0, radius, 0, Math.PI * 2)
  ctx.fill()
  ctx.restore()
}

function drawSelectedMask(ctx, sectors, selectedSubject, geometry, palette) {
  const { centerX, centerY, radius, tilt } = geometry
  sectors.forEach(sec => {
    if (sec.subject.subject === selectedSubject) return
    ctx.save()
    ctx.globalAlpha = 0.12
    pieGeometry.drawEllipticSector(
      ctx, centerX, centerY, radius, tilt,
      sec.startA, sec.endA, palette.selectedMask
    )
    ctx.restore()
  })
}

/**
 * Renders one 3D pie frame.  `cache` is the page-owned per-dataset cache; the
 * renderer lazily fills `sectors`, `wallSteps`, and `labelLayout` on first use
 * so wall shades and label collisions are not recomputed on every frame.
 * All dependencies are explicit and no Page state is touched.
 */
function renderPieChart(options) {
  const {
    ctx,
    rect,
    subjects,
    themeMode,
    dpr,
    selectedSubject,
    progress,
    includeLabels = true,
    cache,
    palette,
    shade,
  } = options
  if (!ctx || !rect || !rect.width) return

  const geometry = pieGeometry.getPieGeometry(rect)
  const { w, h } = geometry
  const reveal = Math.max(0, Math.min(1, (progress - 0.5) / 0.5))
  const labelReveal = Math.max(0, Math.min(1, (progress - 0.62) / 0.38))

  ctx.clearRect(0, 0, w, h)

  // The empty state is supplied by the WXML illustration. Canvas stays
  // transparent to avoid the old “empty pie + no data” overlay bleeding through
  // the illustration layer on real-device Canvas compositing.
  if (!hasPositiveDuration(subjects)) return

  if (!cache.sectors) {
    const built = pieSectorBuilder.buildPieSectors(subjects, geometry, shade)
    cache.sectors = built.sectors
    cache.wallSteps = built.wallSteps
    cache.labelLayout = built.labelLayout
  }

  if (reveal > 0) drawShadow(ctx, geometry, reveal, palette)
  const sortedSectors = drawSideWalls(ctx, cache.sectors, selectedSubject, geometry, progress, cache.wallSteps, shade)
  drawTopSectors(ctx, sortedSectors, selectedSubject, geometry, progress, shade)
  if (reveal > 0 && cache.sectors.length > 1) drawSeparators(ctx, cache.sectors, geometry, reveal, palette)
  if (reveal > 0) drawLighting(ctx, geometry, reveal)
  if (selectedSubject && reveal > 0.9) drawSelectedMask(ctx, cache.sectors, selectedSubject, geometry, palette)
  if (includeLabels) {
    pieLabelRenderer.drawPieLabels(ctx, cache.labelLayout, labelReveal, palette, dpr)
  }
}

module.exports = {
  renderPieChart,
}
