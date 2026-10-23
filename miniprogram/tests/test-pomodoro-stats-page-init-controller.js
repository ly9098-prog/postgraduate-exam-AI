const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createPageInitController,
} = require('../subpackages/productivity/pomodoro-stats/page-init-controller')

function createHarness() {
  const calls = []
  const shadeColorCache = { cache: true }
  const pieRenderCache = { sectors: null, wallSteps: null, labelLayout: null }
  const controller = createPageInitController({
    getTheme: () => 'dark',
    applyNativeTheme: mode => {
      calls.push(['applyNativeTheme', mode])
    },
    getChinaStudyDate: () => {
      calls.push(['getChinaStudyDate', 0])
      return '2026-10-24'
    },
    getDefaultDayStartMinute: () => 0,
    shiftDate: (date, delta) => {
      calls.push(['shiftDate', date, delta])
      return `shifted:${delta}`
    },
    createShadeColorCache: () => shadeColorCache,
    createPieRenderCache: () => pieRenderCache,
  })
  return { controller, calls, shadeColorCache, pieRenderCache }
}

test('initializes page state and the default view', () => {
  const { controller, calls, shadeColorCache, pieRenderCache } = createHarness()
  const result = controller.initialize()

  assert.equal(result.internal._alive, true)
  assert.equal(result.internal._isVisible, false)
  assert.equal(result.internal._requestId, 0)
  assert.equal(result.internal._viewReady, false)
  assert.equal(result.internal._hasData, false)
  assert.equal(result.internal._subjectMetaPromise, null)
  assert.equal(result.internal._shadeColorCache, shadeColorCache)
  assert.equal(result.internal._pieRenderCache, pieRenderCache)
  assert.deepEqual(calls[0], ['applyNativeTheme', 'dark'])
  assert.deepEqual(calls[1], ['getChinaStudyDate', 0])
  assert.deepEqual(result.data, {
    selectedDate: '2026-10-24',
    _todayDate: '2026-10-24',
    pieDateLabel: '今日',
    canGoNextDate: false,
    cumulativePickerStartDate: 'shifted:-365',
    customRangePickerStartDate: 'shifted:-365',
    customRangeStartDate: '2026-10-24',
    distributionRangeStart: '2026-10-24',
    distributionRangeEnd: '2026-10-24',
    themeMode: 'dark',
  })
  assert.deepEqual(calls.at(-1), ['shiftDate', '2026-10-24', -365])
})

test('applies the persisted native theme before returning data', () => {
  const { controller, calls } = createHarness()
  controller.initialize()

  assert.deepEqual(calls[0], ['applyNativeTheme', 'dark'])
  assert.deepEqual(calls[1], ['getChinaStudyDate', 0])
  assert.deepEqual(calls[2], ['shiftDate', '2026-10-24', -365])
})

test('returns fresh cache instances on each initialization', () => {
  const { controller, shadeColorCache, pieRenderCache } = createHarness()
  const first = controller.initialize()
  const second = controller.initialize()

  assert.equal(first.internal._shadeColorCache, shadeColorCache)
  assert.equal(first.internal._pieRenderCache, pieRenderCache)
  assert.deepEqual(second.internal._shadeColorCache, shadeColorCache)
  assert.deepEqual(second.internal._pieRenderCache, pieRenderCache)
})

test('does not retain mutable page state between initializations', () => {
  const { controller } = createHarness()
  const first = controller.initialize()
  first.internal._requestId = 99
  first.internal._daySubjectsRaw.push('mutated')

  const second = controller.initialize()
  assert.equal(second.internal._requestId, 0)
  assert.deepEqual(second.internal._daySubjectsRaw, [])
})
