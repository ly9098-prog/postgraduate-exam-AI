const assert = require('node:assert/strict')
const { test } = require('node:test')

const {
  createSkipBreakController,
} = require('../pages/pomodoro/utils/skip-break-controller')
const {
  createFontSizeController,
  FONT_SIZE_LEVELS,
} = require('../pages/pomodoro/utils/font-size-controller')
const {
  createSubjectViewController,
  SUBJECT_COLOR,
} = require('../pages/pomodoro/utils/subject-view-controller')
const {
  createPresetViewController,
} = require('../pages/pomodoro/utils/preset-view-controller')
const {
  createCelebrationTypeController,
  CELEBRATION_TYPES,
} = require('../pages/pomodoro/utils/celebration-type-controller')
const {
  createDateExamController,
} = require('../pages/pomodoro/utils/date-exam-controller')

test('skip break preserves cleanup order', () => {
  const calls = []
  createSkipBreakController({
    clearTimer: () => calls.push('clear'),
    removeStorage: (key, context) => calls.push(['remove', key, context]),
    resetIdle: () => calls.push('reset'),
  }).skip()

  assert.deepEqual(calls, [
    'clear',
    ['remove', 'pomodoro_break', 'best-effort cleanup'],
    'reset',
  ])
})

test('font size cycles medium and large and persists the next value', () => {
  const persisted = []
  let level = 'medium'
  const controller = createFontSizeController({
    getCurrentLevel: () => level,
    setLevel: value => { level = value },
    persist: value => persisted.push(value),
  })

  controller.cycle()
  controller.cycle()

  assert.deepEqual(FONT_SIZE_LEVELS, ['medium', 'large'])
  assert.equal(level, 'medium')
  assert.deepEqual(persisted, ['large', 'medium'])
})

test('subject view prefers page choices and preserves fallback/color', () => {
  const controller = createSubjectViewController({
    getSubjects: () => [
      { code: 'operating_system', name: '页面科目' },
      { code: 'unknown', name: '未知页面科目' },
    ],
  })

  assert.equal(controller.label('operating_system'), '页面科目')
  assert.equal(controller.label('data_structure'), '数据结构')
  assert.equal(controller.label('missing'), '其他科目')
  assert.equal(controller.color(), SUBJECT_COLOR)
  assert.equal(SUBJECT_COLOR, '#3B82F6')
})

test('preset label preserves configured label and raw fallback', () => {
  const controller = createPresetViewController({
    getPresets: () => [{ key: 'standard', label: '标准' }],
  })

  assert.equal(controller.label('standard'), '标准')
  assert.equal(controller.label('missing'), 'missing')
})

test('celebration type cycles and returns the previous slot', () => {
  const stored = []
  let index = 0
  const controller = createCelebrationTypeController({
    getIndex: () => index,
    setIndex: value => { index = value; stored.push(value) },
  })

  assert.equal(controller.next(), 'excellent')
  assert.equal(controller.next(), 'award')
  assert.equal(controller.next(), 'thumbsUp')
  assert.equal(controller.next(), 'excellent')
  assert.deepEqual(CELEBRATION_TYPES, ['excellent', 'award', 'thumbsUp'])
  assert.deepEqual(stored, [1, 2, 0, 1])
})

test('date and exam projections preserve wall-clock behavior', () => {
  const controller = createDateExamController({
    now: () => 0,
    getChinaWallParts: () => ({ year: 1970, month: 1, day: 1, weekday: 4 }),
    getChinaDayStartUtcMs: () => -8 * 60 * 60 * 1000,
    utc: ({ year, month, day }) => Date.UTC(year, month, day),
    getUtcDay: ms => new Date(ms).getUTCDay(),
  })

  assert.equal(controller.dateText(), '1月1日 星期四')
  assert.equal(controller.examDays(), 352)
})
