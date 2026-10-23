const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  buildSubjectMeta,
  distributeAggregateValue,
  normalizeDistributionSubjects,
} = require('../subpackages/productivity/pomodoro-stats/subject-distribution')

const TREE = [
  {
    subject_id: 1,
    subject_name: '408',
    children: [
      { subject_id: 11, subject_name: '数据结构' },
      { subject_id: 12, subject_name: '操作系统' },
    ],
  },
  { subject_id: 2, subject_name: '数学' },
]

test('buildSubjectMeta identifies leaves and parents', () => {
  const meta = buildSubjectMeta(TREE)
  assert.equal(meta.byId[1].isLeaf, false)
  assert.equal(meta.byId[11].isLeaf, true)
  assert.equal(meta.byId[12].isLeaf, true)
  assert.equal(meta.byId[2].isLeaf, true)
  assert.deepEqual(meta.leafIds, [11, 12, 2])
  assert.deepEqual(meta.byId[1].descendantLeafIds, [11, 12])
})

test('distributeAggregateValue distributes evenly with no weights', () => {
  const result = distributeAggregateValue(10, [1, 2, 3], {})
  const total = result.reduce((sum, item) => sum + item.value, 0)
  assert.equal(total, 10)
  result.forEach(item => assert.ok(item.value >= 3))
})

test('distributeAggregateValue distributes proportionally by weight', () => {
  const result = distributeAggregateValue(10, [1, 2], { 1: 3, 2: 1 })
  const byId = Object.fromEntries(result.map(item => [item.id, item.value]))
  assert.equal(byId[1], 8) // 10 * 3/4 = 7.5, floor 7, remainder +1 = 8
  assert.equal(byId[2], 2)
})

test('normalizeDistributionSubjects splits parent across leaves', () => {
  const meta = buildSubjectMeta(TREE)
  const result = normalizeDistributionSubjects([
    { subject_id: 1, subject_name: '408', duration_sec: 100, sessions: 2 },
  ], meta)

  const totalDur = result.reduce((sum, item) => sum + item.duration_sec, 0)
  assert.equal(totalDur, 100)
  const totalSessions = result.reduce((sum, item) => sum + item.sessions, 0)
  assert.equal(totalSessions, 2)
  assert.ok(result.some(item => item.subject_id === 11))
  assert.ok(result.some(item => item.subject_id === 12))
})

test('normalizeDistributionSubjects aggregates duplicate leaves', () => {
  const meta = buildSubjectMeta(TREE)
  const result = normalizeDistributionSubjects([
    { subject_id: 11, subject_name: '数据结构', duration_sec: 30, sessions: 1 },
    { subject_id: 11, subject_name: '数据结构', duration_sec: 40, sessions: 2 },
  ], meta)

  assert.equal(result.length, 1)
  assert.equal(result[0].duration_sec, 70)
  assert.equal(result[0].sessions, 3)
})

test('normalizeDistributionSubjects keeps unknown subject as passthrough', () => {
  const meta = buildSubjectMeta(TREE)
  const result = normalizeDistributionSubjects([
    { subject_id: 99, subject_name: '未知', duration_sec: 50, sessions: 1 },
  ], meta)

  assert.equal(result.length, 1)
  assert.equal(result[0].subject_id, 99)
  assert.equal(result[0].duration_sec, 50)
})

test('normalizeDistributionSubjects returns copy without meta', () => {
  const subjects = [{ subject_id: 1 }]
  const result = normalizeDistributionSubjects(subjects, null)
  assert.notEqual(result, subjects)
  assert.deepEqual(result, subjects)
})
