const pieLabelLayout = require('./pie-label-layout')

/**
 * Builds the per-dataset sector geometry, wall shades, and label layout used by
 * every pie animation frame.  This is cached by the page for one data set, so
 * wall shades and label collisions are computed only once per distribution.
 * All inputs are explicit; the caller supplies the current shade helper.
 */
function buildPieSectors(subjects, geometry, shade) {
  const totalDur = subjects.reduce((sum, item) => sum + (item.duration_sec || 0), 0) || 1
  const sectors = []
  let angle = -Math.PI / 2
  subjects.filter(item => (item.duration_sec || 0) > 0).forEach(item => {
    const pct = (item.duration_sec || 0) / totalDur
    const endA = angle + Math.PI * 2 * pct
    sectors.push({
      subject: item,
      color: item._color || '#3B82F6',
      pct,
      startA: angle,
      endA,
    })
    angle = endA
  })

  // Keep layer count stable across the animation. The previous final-frame
  // jump from 3 layers to ~12 caused the visible tail-end hitch.
  const wallSteps = Math.max(5, Math.min(7, Math.round(geometry.depth)))
  sectors.forEach(sec => {
    sec._wallShades = []
    for (let layer = 1; layer <= wallSteps; layer++) {
      const ratio = layer / wallSteps
      sec._wallShades.push(shade(sec.color, Math.round(-52 + ratio * 38)))
    }
  })

  const labelLayout = pieLabelLayout.buildPieLabelLayout(sectors, geometry)
  return { sectors, wallSteps, labelLayout }
}

module.exports = {
  buildPieSectors,
}
