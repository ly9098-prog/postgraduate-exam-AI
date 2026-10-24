const assert = require('node:assert/strict')
const { test } = require('node:test')
const { DEFAULT_GROWTH, stripLevelPrefix, growthFromTotalExp, normalizeGrowthProfile, growthFromOverview } = require('../subpackages/study/practice-result/utils/growth-helpers')

test('stripLevelPrefix: removes Lv prefix', () => {
  assert.equal(stripLevelPrefix('Lv3 刷题达人', 3), '刷题达人')
})

test('stripLevelPrefix: returns 起步 for empty at level 1', () => {
  assert.equal(stripLevelPrefix('', 1), '起步')
})

test('stripLevelPrefix: returns empty for empty at level > 1', () => {
  assert.equal(stripLevelPrefix('', 3), '')
})

test('growthFromTotalExp: level 1 for 0 exp', () => {
  const g = growthFromTotalExp(0)
  assert.equal(g.level, 1)
  assert.equal(g.total_exp, 0)
})

test('growthFromTotalExp: level 3 for 800 exp', () => {
  const g = growthFromTotalExp(800)
  assert.equal(g.level, 3)
  assert.equal(g.exp_current, 200)
})

test('growthFromTotalExp: level 5 for 5000 exp', () => {
  const g = growthFromTotalExp(5000)
  assert.equal(g.level, 5)
  assert.equal(g.exp_to_next, 0)
  assert.equal(g.level_progress_pct, 100)
})

test('growthFromTotalExp: includes streak and badges', () => {
  const g = growthFromTotalExp(100, 7, [{ id: 1 }])
  assert.equal(g.streak_days, 7)
  assert.deepEqual(g.badges, [{ id: 1 }])
})

test('normalizeGrowthProfile: returns null for null input', () => {
  assert.equal(normalizeGrowthProfile(null), null)
})

test('normalizeGrowthProfile: normalizes raw profile', () => {
  const g = normalizeGrowthProfile({ level: 3, total_exp: 800, exp_current: 200, exp_to_next: 900 })
  assert.equal(g.level, 3)
  assert.equal(g.total_exp, 800)
  assert.ok(g.levelTitle)
})

test('normalizeGrowthProfile: unwraps nested growth', () => {
  const g = normalizeGrowthProfile({ growth: { level: 2, total_exp: 300 } })
  assert.equal(g.level, 2)
})

test('normalizeGrowthProfile: computes progress from exp', () => {
  const g = normalizeGrowthProfile({ level: 1, exp_current: 100, exp_to_next: 200 })
  assert.equal(g.level_progress_pct, 50)
})

test('growthFromOverview: returns null for null', () => {
  assert.equal(growthFromOverview(null), null)
})

test('growthFromOverview: computes from overview', () => {
  const g = growthFromOverview({ total_questions: 50, accuracy: 0.8, consecutive_days: 3, mastered_count: 10 })
  assert.ok(g.total_exp > 0)
  assert.equal(g.streak_days, 3)
})
