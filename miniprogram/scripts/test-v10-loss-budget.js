const assert = require('assert')
const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const dashboardPath = path.join(root, 'pages/dashboard/dashboard.js')
const dashboard = fs.readFileSync(dashboardPath, 'utf8')

// Runtime regression: the calculated budget must actually be committed to page state.
const processStart = dashboard.indexOf("_processDashboard(res, mode = 'initial', choiceSubjectStats = [])")
assert.ok(processStart >= 0, 'dashboard _processDashboard signature missing choiceSubjectStats fallback')
const processSlice = dashboard.slice(processStart, dashboard.indexOf('// ── Trend ──', processStart))
assert.ok(/const choiceLossBudget = buildChoiceBudgetWithFallback\(subjects, choiceSubjectStats\)/.test(processSlice), 'loss budget is not calculated from dashboard subjects')
assert.ok(/this\.setData\(\{[\s\S]*?subjects,\s*choiceLossBudget,\s*reviewRisk,/.test(processSlice), 'calculated loss budget is not committed by setData')

// Long-term compatibility: legacy subject_stats is reserved for a real v2 contract
// gap (no subject rows), not for partial user coverage of 1-3 subjects.
assert.ok(/api\.get\('\/stats\/dashboard'\)/.test(dashboard), 'legacy subject_stats fallback request missing')
assert.ok(/legacyDashboard\.subject_stats/.test(dashboard), 'legacy subject_stats are not consumed')
assert.ok(/!hasSubjectContract/.test(dashboard), 'fallback should run only when the v2 subject contract is missing')
assert.ok(/include_subjects:\s*true/.test(dashboard), 'dashboard-v2 should explicitly request subject statistics when supported')
assert.ok(/insightChoiceBudget\.coveredSubjects >= currentChoiceBudget\.coveredSubjects/.test(dashboard), 'insight refresh must not downgrade an already better budget snapshot')

// Data contract regression: the legacy subject_stats fields used elsewhere in the
// app must be accepted by the loss-budget calculator.
const memory = Object.create(null)
global.wx = {
  getStorageSync(key) { return memory[key] },
  setStorageSync(key, value) { memory[key] = value },
  removeStorageSync(key) { delete memory[key] },
  getStorageInfoSync() { return { keys: Object.keys(memory) } },
}
memory.user = { id: 1001 }
const { studyStrategy } = require('../utils/storage')
const budget = studyStrategy.buildChoiceLossBudget([
  { subject_code: 'data_structure', subject_name: '数据结构', total_questions: 120, correct_count: 108, accuracy: 0.90 },
  { subject_code: 'computer_organization', subject_name: '计算机组成原理', total_questions: 80, correct_count: 64, accuracy: 0.80 },
  { subject_code: 'operating_system', subject_name: '操作系统', total_questions: 40, correct_count: 30, accuracy: 0.75 },
  { subject_code: 'computer_network', subject_name: '计算机网络', total_questions: 30, correct_count: 24, accuracy: 0.80 },
])
assert.strictEqual(budget.coveredSubjects, 4, 'legacy subject_stats should establish all four subjects')
assert.strictEqual(budget.coveragePct, 100)
assert.ok(budget.subjects.every(item => item.hasData), 'all four subject rows should have usable loss estimates')
assert.ok(budget.projectedLoss > 0, 'projected loss should be calculated from real accuracy data')

// Runtime helper regression: dashboard-v2 remains authoritative; legacy stats only
// fills a missing subject instead of overwriting a valid primary row.
const dashboardSource = fs.readFileSync(path.join(root, 'pages/dashboard/dashboard.js'), 'utf8')
assert.ok(dashboardSource.includes('primaryCodes.has(code)'), 'legacy fallback must not overwrite an existing primary subject')
assert.ok(dashboardSource.includes('!hasSubjectContract'), 'legacy fallback must detect a v2 contract gap, not user coverage')

console.log('v10 choice loss budget regression checks passed')
