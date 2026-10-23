const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  buildSubjectItems,
  getSubjectColor,
  getPieSubjectColor,
  DARK_SUBJECT_COLORS,
  LIGHT_SUBJECT_COLORS,
  LIGHT_PIE_COLORS,
} = require('../subpackages/productivity/pomodoro-stats/subject-items')

test('maps normalized subjects into pie view-model items', () => {
  const items = buildSubjectItems([
    { subject_id: 101, subject_code: 'cs', subject_name: '计算机', duration_sec: 90, sessions: 2, participation_sessions: 2 },
    { subject_id: 202, subject_code: 'math', subject_name: '数学', duration_sec: 30, sessions: 1, participation_sessions: 1 },
  ], null, 'light')

  assert.equal(items.length, 2)
  assert.equal(items[0].subject, 101)
  assert.equal(items[0]._label, '计算机')
  assert.equal(items[0]._durationText, '1分钟')
  assert.equal(items[0]._durationBadgeText, '0时1分')
  assert.equal(items[0]._pct, 0.75)
  assert.equal(items[0]._pctText, '75.0%')
  assert.equal(items[1]._pct, 0.25)
})

test('falls back to uncategorized for missing subject identity', () => {
  const [item] = buildSubjectItems([{}], null, 'dark')
  assert.equal(item.subject, 'uncategorized')
  assert.equal(item._label, '未分类')
  assert.equal(item._durationText, '0分钟')
})

test('buildSubjectItems uses one minute as the minimum denominator', () => {
  const [empty] = buildSubjectItems([{}], null, 'dark')
  assert.equal(empty._pct, 0)
  assert.equal(empty._pctText, '0.0%')
})

test('subject identity keys match for stable colors', () => {
  const [a] = buildSubjectItems([{ subject_id: 101, subject_code: 'cs', duration_sec: 1 }], null, 'dark')
  assert.equal(a._color, getPieSubjectColor('101', 'dark'))
})

test('subject colors select the expected theme palettes', () => {
  assert.ok(DARK_SUBJECT_COLORS.includes(getSubjectColor('操作系统', 'dark')))
  assert.ok(LIGHT_SUBJECT_COLORS.includes(getSubjectColor('操作系统', 'light')))
  assert.ok(DARK_SUBJECT_COLORS.includes(getPieSubjectColor('操作系统', 'dark')))
  assert.ok(LIGHT_PIE_COLORS.includes(getPieSubjectColor('操作系统', 'light')))
})

test('subject colors are stable for the same input', () => {
  assert.equal(getSubjectColor('数据结构', 'light'), getSubjectColor('数据结构', 'light'))
  assert.equal(getPieSubjectColor('数据结构', 'dark'), getPieSubjectColor('数据结构', 'dark'))
})
