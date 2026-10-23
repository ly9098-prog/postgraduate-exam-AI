const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  buildPieRenderCapabilities,
} = require('../subpackages/productivity/pomodoro-stats/pie-render-capabilities')

test('builds pie rendering capabilities from page-owned state adapters', () => {
  const state = {
    ctx: { id: 'ctx' },
    rect: { width: 100, height: 100 },
    subjects: [{ subject: 'math', duration_sec: 60 }],
    themeMode: 'dark',
    dpr: 2,
    selectedSubject: 'math',
    palette: { shadowStart: 'black' },
    cache: { sectors: null },
    shade: (hex, amount) => `${hex}:${amount}`,
  }

  const capabilities = buildPieRenderCapabilities({
    getCtx: () => state.ctx,
    getRect: () => state.rect,
    getSubjects: () => state.subjects,
    getThemeMode: () => state.themeMode,
    getDpr: () => state.dpr,
    getSelectedSubject: () => state.selectedSubject,
    getPalette: () => state.palette,
    getCache: () => state.cache,
    getShade: () => state.shade,
  })

  assert.deepEqual(capabilities, {
    ctx: state.ctx,
    rect: state.rect,
    subjects: state.subjects,
    themeMode: state.themeMode,
    dpr: state.dpr,
    selectedSubject: state.selectedSubject,
    palette: state.palette,
    cache: state.cache,
    shade: state.shade,
  })
})

test('evaluates each rendering adapter in contract order', () => {
  const evaluated = []
  const track = name => {
    evaluated.push(name)
    return name
  }

  const capabilities = buildPieRenderCapabilities({
    getCtx: () => track('ctx'),
    getRect: () => track('rect'),
    getSubjects: () => track('subjects'),
    getThemeMode: () => track('themeMode'),
    getDpr: () => track('dpr'),
    getSelectedSubject: () => track('selectedSubject'),
    getPalette: () => track('palette'),
    getCache: () => track('cache'),
    getShade: () => track('shade'),
  })

  assert.equal(capabilities.ctx, 'ctx')
  assert.equal(capabilities.rect, 'rect')
  assert.equal(capabilities.subjects, 'subjects')
  assert.equal(capabilities.themeMode, 'themeMode')
  assert.equal(capabilities.dpr, 'dpr')
  assert.equal(capabilities.selectedSubject, 'selectedSubject')
  assert.equal(capabilities.palette, 'palette')
  assert.equal(capabilities.cache, 'cache')
  assert.equal(capabilities.shade, 'shade')
  assert.deepEqual(evaluated, [
    'ctx', 'rect', 'subjects', 'themeMode', 'dpr',
    'selectedSubject', 'palette', 'cache', 'shade',
  ])
})
