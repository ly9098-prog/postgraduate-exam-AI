const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  renderTrendBars,
} = require('../subpackages/productivity/pomodoro-stats/trend-chart')

const PALETTE = {
  grid: 'grid',
  baseline: 'baseline',
  emptyBar: 'empty',
  pendingBar: 'pending',
  dateText: 'date',
}

function createGradient() {
  return {
    stops: [],
    addColorStop(offset, color) {
      this.stops.push({ offset, color })
    },
  }
}

function createContext(log) {
  return {
    globalAlpha: 1,
    fillStyle: '',
    strokeStyle: '',
    lineWidth: 0,
    font: '',
    textAlign: '',
    save() { log.push(['save']) },
    restore() { log.push(['restore']) },
    beginPath() { log.push(['beginPath']) },
    closePath() { log.push(['closePath']) },
    moveTo(...args) { log.push(['moveTo', ...args]) },
    lineTo(...args) { log.push(['lineTo', ...args]) },
    stroke() { log.push(['stroke']) },
    fill() { log.push(['fill']) },
    clearRect(...args) { log.push(['clearRect', ...args]) },
    fillRect(...args) { log.push(['fillRect', ...args, this.fillStyle]) },
    arc(...args) { log.push(['arc', ...args]) },
    translate(...args) { log.push(['translate', ...args]) },
    scale(...args) { log.push(['scale', ...args]) },
    fillText(...args) { log.push(['fillText', ...args]) },
    createRadialGradient(...args) {
      const gradient = createGradient()
      log.push(['createRadialGradient', ...args, gradient])
      return gradient
    },
    createLinearGradient(...args) {
      const gradient = createGradient()
      log.push(['createLinearGradient', ...args, gradient])
      return gradient
    },
  }
}

function render(options = {}) {
  const log = []
  const ctx = createContext(log)
  renderTrendBars(ctx, {
    trends: options.trends ?? [
      { duration_sec: 3600, _shortDate: '10-23' },
      { duration_sec: 0, _shortDate: '10-24' },
    ],
    rect: options.rect ?? { width: 320, height: 190 },
    progress: options.progress ?? 1,
    themeMode: options.themeMode ?? 'dark',
    palette: PALETTE,
  })
  return { ctx, log }
}

test('renders grid, bars, empty state and date labels at final progress', () => {
  const { log } = render()

  assert.ok(log.some(entry => entry[0] === 'clearRect' && entry[1] === 0))
  assert.equal(log.filter(entry => entry[0] === 'stroke').length, 5)
  assert.ok(log.some(entry => entry[0] === 'fillRect' && entry[5] === 'pending' && entry[4] === 2))
  assert.ok(log.some(entry => entry[0] === 'fillText' && entry[1] === '10-23'))
  assert.ok(log.some(entry => entry[0] === 'fillText' && entry[1] === '10-24'))
})

test('uses light and dark trend palettes', () => {
  const dark = render({ trends: [{ duration_sec: 100 }], progress: 1, themeMode: 'dark' }).log
  const light = render({ trends: [{ duration_sec: 100 }], progress: 1, themeMode: 'light' }).log

  const darkColor = dark.find(entry => entry[0] === 'fillRect' && entry[5].stops?.some(stop => stop.color.includes('34,197,94')))
  const lightColor = light.find(entry => entry[0] === 'fillRect' && entry[5].stops?.some(stop => stop.color.includes('47,107,79')))
  assert.ok(darkColor)
  assert.ok(lightColor)
})

test('renders a zero-duration bar as pending and skips bar decorations', () => {
  const { log } = render({ trends: [{ duration_sec: 0, _shortDate: 'idle' }], progress: 1 })

  assert.ok(log.some(entry => entry[0] === 'fillRect' && entry[5] === 'pending' && entry[4] === 2))
  assert.ok(!log.some(entry => entry[0] === 'createRadialGradient'))
})

test('does not draw without trends, context, or a sized rectangle', () => {
  const cases = [
    { trends: [] },
    { trends: [{ duration_sec: 1 }], rect: { width: 0, height: 100 } },
  ]
  cases.forEach(options => {
    const log = []
    renderTrendBars(createContext(log), {
      trends: options.trends,
      rect: options.rect ?? { width: 100, height: 100 },
      progress: 1,
      themeMode: 'dark',
      palette: PALETTE,
    })
    assert.deepEqual(log, [])
  })

  const direct = []
  renderTrendBars(null, {
    trends: [{ duration_sec: 1 }],
    rect: { width: 100, height: 100 },
    progress: 1,
    themeMode: 'dark',
    palette: PALETTE,
  })
  assert.deepEqual(direct, [])
})

test('keeps progress clamped through fade calculations', () => {
  const { ctx, log } = render({ progress: 0 })

  assert.equal(ctx.globalAlpha, 1)
  assert.ok(log.some(entry => entry[0] === 'fillRect' && entry[5] === 'empty' && entry[4] === 1))
  assert.ok(log.some(entry => entry[0] === 'fillRect' && entry[5] === 'pending'))
  assert.ok(!log.some(entry => entry[0] === 'save'))
})
