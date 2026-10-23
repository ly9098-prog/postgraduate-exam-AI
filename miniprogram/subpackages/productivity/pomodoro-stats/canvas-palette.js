const LIGHT_PALETTE = Object.freeze({
  grid: 'rgba(21,51,35,0.065)',
  baseline: 'rgba(21,51,35,0.14)',
  emptyBar: 'rgba(21,51,35,0.10)',
  pendingBar: 'rgba(21,51,35,0.065)',
  dateText: 'rgba(21,35,26,0.44)',
  badgeFill: 'rgba(255,255,255,0.96)',
  badgeText: 'rgba(21,35,26,0.92)',
  pieLeader: 'rgba(57,76,64,0.52)',
  pieLabelText: 'rgba(37,54,43,0.90)',
  pieLabelSubtext: 'rgba(82,101,89,0.72)',
  pieInsideText: 'rgba(31,48,37,0.88)',
  emptyPieFill: 'rgba(21,51,35,0.045)',
  emptyPieStroke: 'rgba(21,51,35,0.13)',
  emptyPieText: 'rgba(21,35,26,0.42)',
  shadowStart: 'rgba(21,35,26,0.16)',
  shadowMid: 'rgba(21,35,26,0.06)',
  separator: 'rgba(21,35,26,0.14)',
  selectedMask: 'rgba(244,244,238,0.88)',
})

const DARK_PALETTE = Object.freeze({
  grid: 'rgba(255,255,255,0.03)',
  baseline: 'rgba(255,255,255,0.08)',
  emptyBar: 'rgba(255,255,255,0.05)',
  pendingBar: 'rgba(255,255,255,0.03)',
  dateText: 'rgba(255,255,255,0.25)',
  badgeFill: 'rgba(11,17,33,0.9)',
  badgeText: 'rgba(255,255,255,0.92)',
  pieLeader: 'rgba(255,255,255,0.44)',
  pieLabelText: 'rgba(255,255,255,0.90)',
  pieLabelSubtext: 'rgba(255,255,255,0.58)',
  pieInsideText: 'rgba(255,255,255,0.88)',
  emptyPieFill: 'rgba(255,255,255,0.05)',
  emptyPieStroke: 'rgba(255,255,255,0.08)',
  emptyPieText: 'rgba(255,255,255,0.28)',
  shadowStart: 'rgba(0,0,0,0.25)',
  shadowMid: 'rgba(0,0,0,0.10)',
  separator: 'rgba(0,0,0,0.18)',
  selectedMask: 'rgba(0,0,0,0.7)',
})

function getCanvasPalette(themeMode) {
  return themeMode === 'light' ? LIGHT_PALETTE : DARK_PALETTE
}

module.exports = {
  getCanvasPalette,
  LIGHT_PALETTE,
  DARK_PALETTE,
}
