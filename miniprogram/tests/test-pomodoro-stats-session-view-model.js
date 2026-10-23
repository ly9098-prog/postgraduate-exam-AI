const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  formatSession,
} = require('../subpackages/productivity/pomodoro-stats/session-view-model')

function createOptions(overrides = {}) {
  return {
    getTaskTypeLabel: () => '专注',
    getSubjectColor: key => `color:${key}`,
    ...overrides,
  }
}

test('maps a completed focus session', () => {
  const result = formatSession({
    start_time: '2026-10-23T01:20:00+08:00',
    actual_duration: 15540,
    subject_id: 3,
    subject_code: 'OS',
    subject_name: '操作系统',
    record_type: 'focus',
    preset: 'focus_25',
    status: 'completed',
  }, createOptions())

  assert.equal(result._subjectLabel, '操作系统')
  assert.equal(result._statusLabel, '完成')
  assert.equal(result._statusClass, 'status-done')
  assert.equal(result._iconType, 'focus')
  assert.equal(result._duration, '4时19分')
  assert.equal(result._color, 'color:3')
  assert.ok(result._time)
  assert.ok(result._date)
})

test('maps an interrupted free session', () => {
  const result = formatSession({
    start_time: '2026-10-23T01:20:00+08:00',
    duration_sec: 600,
    subject_name: '数学',
    preset: 'free',
    status: 'interrupted',
  }, createOptions())

  assert.equal(result._subjectLabel, '自由计时 · 数学')
  assert.equal(result._statusLabel, '中断')
  assert.equal(result._statusClass, 'status-interrupt')
  assert.equal(result._iconType, 'free')
})

test('maps equal-core attribution', () => {
  const result = formatSession({
    start_time: '2026-10-23T01:20:00+08:00',
    duration_sec: 600,
    subject_name: '408',
    allocation_mode: 'equal_408_core_v1',
    status: 'completed',
  }, createOptions())

  assert.equal(result._subjectLabel, '408（四科均分）')
})

test('maps practice and review sessions distinctly', () => {
  const opts = createOptions()
  const practice = formatSession({
    start_time: '2026-10-23T01:20:00+08:00',
    duration_sec: 600,
    subject_name: '数据结构',
    record_type: 'practice',
  }, opts)
  const review = formatSession({
    start_time: '2026-10-23T01:20:00+08:00',
    duration_sec: 600,
    subject_name: '组成原理',
    record_type: 'review',
  }, opts)

  assert.equal(practice._subjectLabel, '刷题 · 数据结构')
  assert.equal(practice._statusLabel, '刷题')
  assert.equal(practice._iconType, 'practice')
  assert.equal(review._subjectLabel, '复习 · 组成原理')
  assert.equal(review._statusLabel, '复习')
  assert.equal(review._iconType, 'practice')
})

test('falls back to uncategorized subject fields', () => {
  const result = formatSession({
    start_time: '2026-10-23T01:20:00+08:00',
    duration_sec: 0,
    status: 'completed',
  }, createOptions())

  assert.equal(result._subjectLabel, '未分类')
  assert.equal(result._color, 'color:未分类')
  assert.equal(result._duration, '0分钟')
})
