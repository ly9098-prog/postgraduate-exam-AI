const assert = require('node:assert/strict')
const { test } = require('node:test')
const { buildLocalErrorDistribution, getResultTip } = require('../subpackages/study/practice-result/utils/result-tips')

test('buildLocalErrorDistribution: empty array returns empty', () => {
  assert.deepEqual(buildLocalErrorDistribution([]), [])
})

test('buildLocalErrorDistribution: null returns empty', () => {
  assert.deepEqual(buildLocalErrorDistribution(null), [])
})

test('buildLocalErrorDistribution: groups by knowledgePoint', () => {
  const result = buildLocalErrorDistribution([
    { knowledgePoint: '排序' },
    { knowledgePoint: '排序' },
    { knowledgePoint: '树' },
  ])
  assert.equal(result.length, 2)
  assert.equal(result[0].label, '排序')
  assert.equal(result[0].count, 2)
  assert.equal(result[1].label, '树')
  assert.equal(result[1].count, 1)
})

test('buildLocalErrorDistribution: defaults to 其他 when no knowledgePoint', () => {
  const result = buildLocalErrorDistribution([{}, {}])
  assert.equal(result[0].label, '其他')
  assert.equal(result[0].count, 2)
})

test('buildLocalErrorDistribution: merges beyond top 4 into 其他', () => {
  const items = []
  for (let i = 0; i < 6; i++) {
    items.push({ knowledgePoint: 'KP' + i })
  }
  const result = buildLocalErrorDistribution(items)
  assert.equal(result.length, 5)
  assert.equal(result[4].label, '其他')
  assert.equal(result[4].count, 2)
})

test('buildLocalErrorDistribution: computes percentages', () => {
  const result = buildLocalErrorDistribution([
    { knowledgePoint: 'A' },
    { knowledgePoint: 'A' },
    { knowledgePoint: 'B' },
  ])
  assert.equal(result[0].percent, 67)
  assert.equal(result[1].percent, 33)
})

test('buildLocalErrorDistribution: assigns colors', () => {
  const result = buildLocalErrorDistribution([
    { knowledgePoint: 'A' },
    { knowledgePoint: 'B' },
  ])
  assert.ok(result[0].color)
  assert.ok(result[1].color)
  assert.notEqual(result[0].color, result[1].color)
})

test('getResultTip: all correct', () => {
  const tip = getResultTip(100, 0, 0, 0, 5)
  assert.ok(tip.includes('表现稳定'))
})

test('getResultTip: no wrong but has skipped', () => {
  const tip = getResultTip(80, 0, 2, 0, 5)
  assert.ok(tip.includes('2 题跳过'))
})

test('getResultTip: no wrong but has partial', () => {
  const tip = getResultTip(80, 0, 0, 1, 5)
  assert.ok(tip.includes('1 题未完成'))
})

test('getResultTip: no wrong but has partial and skipped', () => {
  const tip = getResultTip(80, 0, 2, 1, 5)
  assert.ok(tip.includes('1 题未完成'))
  assert.ok(tip.includes('2 题跳过'))
})

test('getResultTip: high accuracy with wrong', () => {
  const tip = getResultTip(85, 1, 0, 0, 5)
  assert.ok(tip.includes('整体掌握较好'))
})

test('getResultTip: medium accuracy', () => {
  const tip = getResultTip(65, 2, 0, 0, 5)
  assert.ok(tip.includes('基础已掌握'))
})

test('getResultTip: low accuracy', () => {
  const tip = getResultTip(40, 3, 0, 0, 5)
  assert.ok(tip.includes('错题较多'))
})
