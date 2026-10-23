const BADGE_WIDTH = 54
const BADGE_HEIGHT = 23
const MARGIN_X = 6
const MARGIN_Y = 8
const GAP_X = 5
const GAP_Y = 4

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value))
}

function buildBaseItems(sectors, geometry) {
  const { w, h, centerX, centerY, radius, tilt } = geometry
  const outerRadiusX = radius + 36
  const outerRadiusY = radius * tilt + 31

  return sectors.map((sec, index) => {
    const mid = (sec.startA + sec.endA) / 2
    const cos = Math.cos(mid)
    const sin = Math.sin(mid)
    const startX = centerX + cos * radius * 1.02
    const startY = centerY + sin * radius * tilt * 1.02
    const elbowX = centerX + cos * (radius + 9)
    const elbowY = centerY + sin * (radius * tilt + 8)

    // Dense badges fan along the ellipse tangent instead of snapping into a
    // one-sided vertical stack.
    const baseX = centerX + cos * outerRadiusX
    const baseY = centerY + sin * outerRadiusY
    const tangentLen = Math.hypot(-sin, cos * tilt) || 1
    const tangentX = -sin / tangentLen
    const tangentY = (cos * tilt) / tangentLen
    const radialLen = Math.hypot(cos, sin * tilt) || 1
    const radialX = cos / radialLen
    const radialY = (sin * tilt) / radialLen

    return {
      sec,
      index,
      mid,
      startX,
      startY,
      elbowX,
      elbowY,
      baseX,
      baseY,
      badgeCenterX: clamp(baseX, MARGIN_X + BADGE_WIDTH / 2, w - MARGIN_X - BADGE_WIDTH / 2),
      badgeCenterY: clamp(baseY, MARGIN_Y + BADGE_HEIGHT / 2, h - MARGIN_Y - BADGE_HEIGHT / 2),
      badgeW: BADGE_WIDTH,
      badgeH: BADGE_HEIGHT,
      tangentX,
      tangentY,
      radialX,
      radialY,
    }
  })
}

function overlaps(a, b) {
  return Math.abs(a.badgeCenterX - b.badgeCenterX) < (BADGE_WIDTH + GAP_X) &&
    Math.abs(a.badgeCenterY - b.badgeCenterY) < (BADGE_HEIGHT + GAP_Y)
}

function resolveSoftCollisions(items, geometry) {
  const { w, h, tilt } = geometry
  for (let pass = 0; pass < 56; pass++) {
    let changed = false
    for (let i = 0; i < items.length; i++) {
      for (let j = i + 1; j < items.length; j++) {
        const a = items[i]
        const b = items[j]
        if (!overlaps(a, b)) continue
        changed = true

        const avgMid = (a.mid + b.mid) / 2
        const tangentLen = Math.hypot(-Math.sin(avgMid), Math.cos(avgMid) * tilt) || 1
        const tx = -Math.sin(avgMid) / tangentLen
        const ty = (Math.cos(avgMid) * tilt) / tangentLen
        const order = a.mid <= b.mid ? 1 : -1
        const overlapX = (BADGE_WIDTH + GAP_X) - Math.abs(a.badgeCenterX - b.badgeCenterX)
        const overlapY = (BADGE_HEIGHT + GAP_Y) - Math.abs(a.badgeCenterY - b.badgeCenterY)
        const needed = Math.max(2.2, Math.min(7.5, Math.min(overlapX, overlapY) * 0.35 + 1.8))

        a.badgeCenterX -= tx * needed * order
        a.badgeCenterY -= ty * needed * order
        b.badgeCenterX += tx * needed * order
        b.badgeCenterY += ty * needed * order

        if (pass % 3 === 2) {
          const outward = 1.35 + Math.min(2.4, pass * 0.035)
          a.badgeCenterX += a.radialX * outward
          a.badgeCenterY += a.radialY * outward
          b.badgeCenterX += b.radialX * outward
          b.badgeCenterY += b.radialY * outward
        }
      }
    }

    items.forEach(item => {
      // A weak tether keeps each badge close to its own sector.
      item.badgeCenterX += (item.baseX - item.badgeCenterX) * 0.035
      item.badgeCenterY += (item.baseY - item.badgeCenterY) * 0.035
      item.badgeCenterX = clamp(item.badgeCenterX, MARGIN_X + BADGE_WIDTH / 2, w - MARGIN_X - BADGE_WIDTH / 2)
      item.badgeCenterY = clamp(item.badgeCenterY, MARGIN_Y + BADGE_HEIGHT / 2, h - MARGIN_Y - BADGE_HEIGHT / 2)
    })
    if (!changed) break
  }
}

function resolveHardCollisions(items, geometry) {
  const { w, h, tilt } = geometry
  for (let pass = 0; pass < 32; pass++) {
    let changed = false
    for (let i = 0; i < items.length; i++) {
      for (let j = i + 1; j < items.length; j++) {
        const a = items[i]
        const b = items[j]
        if (!overlaps(a, b)) continue
        changed = true
        const avgMid = (a.mid + b.mid) / 2
        const tangentLen = Math.hypot(-Math.sin(avgMid), Math.cos(avgMid) * tilt) || 1
        const tx = -Math.sin(avgMid) / tangentLen
        const ty = (Math.cos(avgMid) * tilt) / tangentLen
        const order = a.mid <= b.mid ? 1 : -1
        const push = 2.8
        a.badgeCenterX -= tx * push * order
        a.badgeCenterY -= ty * push * order
        b.badgeCenterX += tx * push * order
        b.badgeCenterY += ty * push * order
        if (pass % 4 === 3) {
          a.badgeCenterX += a.radialX * 1.2
          a.badgeCenterY += a.radialY * 1.2
          b.badgeCenterX += b.radialX * 1.2
          b.badgeCenterY += b.radialY * 1.2
        }
        a.badgeCenterX = clamp(a.badgeCenterX, MARGIN_X + BADGE_WIDTH / 2, w - MARGIN_X - BADGE_WIDTH / 2)
        a.badgeCenterY = clamp(a.badgeCenterY, MARGIN_Y + BADGE_HEIGHT / 2, h - MARGIN_Y - BADGE_HEIGHT / 2)
        b.badgeCenterX = clamp(b.badgeCenterX, MARGIN_X + BADGE_WIDTH / 2, w - MARGIN_X - BADGE_WIDTH / 2)
        b.badgeCenterY = clamp(b.badgeCenterY, MARGIN_Y + BADGE_HEIGHT / 2, h - MARGIN_Y - BADGE_HEIGHT / 2)
      }
    }
    if (!changed) break
  }
}

function finalizeItems(items) {
  return items.map(item => {
    const badgeX = item.badgeCenterX - BADGE_WIDTH / 2
    const badgeY = item.badgeCenterY - BADGE_HEIGHT / 2

    const tangentDisplacement = (item.badgeCenterX - item.baseX) * item.tangentX +
      (item.badgeCenterY - item.baseY) * item.tangentY
    const bendSign = Math.abs(tangentDisplacement) > 0.5
      ? (tangentDisplacement > 0 ? 1 : -1)
      : (item.index % 2 === 0 ? 1 : -1)
    const elbowX = item.elbowX + item.tangentX * 7 * bendSign
    const elbowY = item.elbowY + item.tangentY * 7 * bendSign

    const dx = elbowX - item.badgeCenterX
    const dy = elbowY - item.badgeCenterY
    const sx = Math.abs(dx) > 1e-6 ? (BADGE_WIDTH / 2) / Math.abs(dx) : Infinity
    const sy = Math.abs(dy) > 1e-6 ? (BADGE_HEIGHT / 2) / Math.abs(dy) : Infinity
    const scale = Math.min(sx, sy)
    const lineEndX = item.badgeCenterX + dx * scale
    const lineEndY = item.badgeCenterY + dy * scale

    return {
      ...item,
      badgeX,
      badgeY,
      elbowX,
      elbowY,
      lineEndX,
      lineEndY,
    }
  })
}

function buildPieLabelLayout(sectors, geometry) {
  const items = buildBaseItems(sectors, geometry)
  resolveSoftCollisions(items, geometry)
  resolveHardCollisions(items, geometry)
  return finalizeItems(items)
}

module.exports = {
  buildPieLabelLayout,
}
