const assert = require('assert')

const memory = Object.create(null)
global.wx = {
  getStorageSync(key) { return memory[key] },
  setStorageSync(key, value) { memory[key] = value },
  removeStorageSync(key) { delete memory[key] },
  getStorageInfoSync() { return { keys: Object.keys(memory) } },
}

memory.user = { id: 1001 }
const storage = require('../utils/storage')
const strategy = storage.studyStrategy
const taskTypes = storage.pomodoroTaskTypes
const diagnosis = require('../subpackages/study/utils/error-diagnosis')
const graduation = require('../subpackages/knowledge/knowledge-subject/tree-groups')

// P0: four subjects + stages + manual weights.
const defaults = strategy.getProfile()
assert.strictEqual(defaults.subjects.length, 4)
assert.strictEqual(defaults.subjects.reduce((sum, item) => sum + item.weight, 0), 100)
assert.deepStrictEqual(defaults.subjects.map(item => item.stage), ['maintenance', 'second_round', 'not_started', 'not_started'])
assert.strictEqual(strategy.validateProfile(defaults).valid, true)
const invalid = JSON.parse(JSON.stringify(defaults))
invalid.subjects[0].weight += 5
assert.strictEqual(strategy.validateProfile(invalid).valid, false)
strategy.saveProfile(defaults)
assert.strictEqual(strategy.getProfile().owner, '1001')
// account isolation: another account never inherits the previous strategy.
memory.user = { id: 2002 }
assert.strictEqual(strategy.getProfile().owner, '2002')
assert.deepStrictEqual(strategy.getProfile().subjects.map(item => item.weight), [15, 35, 35, 15])
memory.user = { id: 1001 }

// P0: choice-only 130 loss budget. 90% across 40 questions = 8 points expected loss.
const budget = strategy.buildChoiceLossBudget([
  { subject_code: 'data_structure', totalQuestions: 100, accuracyPct: 90 },
  { subject_code: 'computer_organization', totalQuestions: 100, accuracyPct: 90 },
  { subject_code: 'operating_system', totalQuestions: 100, accuracyPct: 90 },
  { subject_code: 'computer_network', totalQuestions: 100, accuracyPct: 90 },
])
assert.strictEqual(budget.totalPoints, 80)
assert.strictEqual(budget.targetPoints, 72)
assert.strictEqual(budget.lossBudgetPoints, 8)
assert.strictEqual(budget.maxWrongQuestions, 4)
assert.strictEqual(budget.coveredQuestions, 40)
assert.strictEqual(budget.projectedLoss, 8)
assert.strictEqual(budget.status, 'on_track')
const partialBudget = strategy.buildChoiceLossBudget([{ subject_name: '数据结构', totalQuestions: 20, accuracy: 0.8 }])
assert.strictEqual(partialBudget.fullCoverage, false)
assert.strictEqual(partialBudget.status, 'building')
assert.strictEqual(partialBudget.subjects.find(item => item.code === 'operating_system').hasData, false)
const onePctBudget = strategy.buildChoiceLossBudget([{ subjectCode: 'data_structure', totalQuestions: 10, accuracyPct: 1 }])
assert.strictEqual(onePctBudget.subjects[0].accuracyPct, 1, 'accuracyPct=1 must mean 1%, not 100%')
const nullAccuracyBudget = strategy.buildChoiceLossBudget([{ subject_code: 'operating_system', totalQuestions: 12, accuracy: null, accuracyPct: null }])
assert.strictEqual(nullAccuracyBudget.subjects.find(item => item.code === 'operating_system').hasData, false)

// S1: a historical attempt cannot clear a pending practice receipt.
assert.strictEqual(storage.knowledgePracticeSync.resolveReceipt({
  subjectId: 3,
  knowledgePointId: 7,
  baselineAttemptCount: 10,
  answeredCount: 2,
}, 10), false, 'old attempt_count alone must not resolve the current session receipt')
assert.strictEqual(storage.knowledgePracticeSync.resolveReceipt({
  subjectId: 3,
  knowledgePointId: 7,
  baselineAttemptCount: 10,
  answeredCount: 2,
}, 12), true, 'direct attempt_count must reach baseline + answered count')
const baselineOwner = { id: 9001 }
memory.user = baselineOwner
storage.knowledgePracticeSync.setBaseline(3, 7, 10)
assert.strictEqual(storage.knowledgePracticeSync.consumeBaseline(3, 7), 10)
assert.strictEqual(storage.knowledgePracticeSync.consumeBaseline(3, 7), 0, 'baseline must be consumed once')
const receipt = storage.knowledgePracticeSync.record({
  subjectId: 3,
  knowledgePointId: 7,
  answeredCount: 2,
  correctCount: 1,
  wrongCount: 1,
  baselineAttemptCount: 10,
})
assert.strictEqual(receipt.expectedMinAttemptCount, 12)
assert.deepStrictEqual(storage.knowledgePracticeSync.getForSubject(3).map(item => item.knowledgePointId), [7])
assert.strictEqual(storage.knowledgePracticeSync.hasPending(4), false)
storage.knowledgePracticeSync.remove([receipt])
assert.strictEqual(storage.knowledgePracticeSync.hasPending(3), false)
memory.user = { id: 1001 }

// P0: error-cause -> next action router.
const wq = { subject_id: 10, subject_code: 'operating_system', knowledge_point_id: 99 }
const expectedRoutes = {
  knowledge_gap: 'knowledge_detail',
  concept_confusion: 'practice',
  memory_error: 'review_today',
  calculation_error: 'practice',
  reasoning_error: 'practice',
  misread: 'practice',
  careless: 'practice',
  time_pressure: 'exam_list',
  unknown: 'diagnosis',
}
Object.keys(expectedRoutes).forEach(type => {
  const action = diagnosis.buildNextAction(wq, { primaryType: type })
  assert.strictEqual(action.route, expectedRoutes[type], `route mismatch for ${type}`)
  assert.ok(action.title && action.reason && action.actionLabel)
})
assert.strictEqual(diagnosis.buildNextAction(wq, { primaryType: 'concept_confusion' }).routeParams.knowledge_point_id, 99)
// subject_code fallback works even before the subject has a server id.
const codeFallback = diagnosis.buildNextAction({ subject_code: 'computer_network' }, { primaryType: 'careless' })
assert.strictEqual(codeFallback.routeParams.subject_code, 'computer_network')

// P1: chapter graduation criteria.
function node(id, attempts, accuracy, status) {
  return { knowledge_point_id: id, trainable_question_count: 10, attempt_count: attempts, accuracy, status }
}
const passing = graduation.evaluateChapter({ nodes: [
  node(1, 10, 0.9, 'good'), node(2, 10, 0.88, 'mastered'), node(3, 10, 0.9, 'good'),
  node(4, 10, 0.86, 'good'), node(5, 10, 0.91, 'mastered'),
] })
assert.strictEqual(passing.graduated, true)
const failingWeak = graduation.evaluateChapter({ nodes: [
  node(1, 10, 0.95, 'good'), node(2, 10, 0.95, 'good'), node(3, 10, 0.95, 'good'),
  node(4, 10, 0.95, 'good'), node(5, 10, 0.95, 'weak'),
] })
assert.strictEqual(failingWeak.graduated, false)
assert.strictEqual(failingWeak.weakCount, 1)
const missingAccuracy = graduation.evaluateChapter({ nodes: [
  node(1, 10, null, 'good'), node(2, 10, 0.95, 'good'), node(3, 10, 0.95, 'good'),
  node(4, 10, 0.95, 'good'), node(5, 10, 0.95, 'good'),
] })
assert.strictEqual(missingAccuracy.graduated, false)
assert.strictEqual(missingAccuracy.accuracyPct, null)
const insufficient = graduation.evaluateChapter({ nodes: [
  node(1, 10, 0.95, 'good'), node(2, 0, null, 'no_data'), node(3, 0, null, 'no_data'), node(4, 0, null, 'no_data'), node(5, 0, null, 'no_data'),
] })
assert.strictEqual(insufficient.graduated, false)
assert.ok(insufficient.evidenceCoveragePct < graduation.CRITERIA.evidenceCoveragePct)

// P1: Next Best Action combines stage + weight + learning evidence.
const mastery = [
  { subjectId: 1, subjectCode: 'data_structure', hasData: true, score: 90, attemptCount: 80 },
  { subjectId: 2, subjectCode: 'computer_organization', hasData: true, score: 70, attemptCount: 30 },
  { subjectId: 3, subjectCode: 'operating_system', hasData: false, score: 0, attemptCount: 0 },
  { subjectId: 4, subjectCode: 'computer_network', hasData: false, score: 0, attemptCount: 0 },
]
let nba = strategy.buildNextBestAction({ profile: defaults, subjectMastery: mastery, dueReviewCount: 0 })
assert.strictEqual(nba.route, 'pomodoro')
assert.strictEqual(nba.route_params.subject_id, 3)
assert.strictEqual(nba.route_params.task_type, 'lecture')
assert.ok(nba.title.includes('操作系统'))
// Many due reviews outrank strategy work.
nba = strategy.buildNextBestAction({ profile: defaults, subjectMastery: mastery, dueReviewCount: 30 })
assert.strictEqual(nba.route, 'review_today')
// Weight=0 is a hard pause for both local and backend subject recommendations.
const custom = JSON.parse(JSON.stringify(defaults))
custom.subjects = custom.subjects.map(item => ({ ...item }))
custom.subjects.find(item => item.code === 'operating_system').weight = 0
custom.subjects.find(item => item.code === 'computer_organization').weight = 70
nba = strategy.buildNextBestAction({
  profile: custom,
  subjectMastery: mastery,
  dueReviewCount: 0,
  hub: { primary_task: { key: 'old-os', route: 'practice', subject_code: 'operating_system', title: 'OS old recommendation' } },
})
assert.notStrictEqual(nba.title, 'OS old recommendation')
assert.strictEqual(nba.route, 'practice')
assert.strictEqual(nba.route_params.subject_id, 2)

// P1: Pomodoro task type persistence and session attribution.
taskTypes.setSelected('lecture')
assert.strictEqual(taskTypes.getSelected(), 'lecture')
taskTypes.recordSession({ id: 123, client_start_id: 'abc' }, 'review')
assert.strictEqual(taskTypes.typeForSession({ id: 123 }), 'review')
assert.strictEqual(taskTypes.typeForSession({ client_start_id: 'abc' }), 'review')
assert.strictEqual(taskTypes.labelForSession({ id: 123 }), '复习')
// Legacy sessions remain unlabeled in history instead of inheriting current selection.
assert.strictEqual(taskTypes.typeForSession({ id: 999 }), '')
assert.strictEqual(taskTypes.labelForSession({ id: 999 }), '')
taskTypes.recordSession({ id: 999 }, '')
assert.strictEqual(taskTypes.labelForSession({ id: 999 }), '', 'invalid/legacy task type must stay unclassified')

console.log('408 strategy feature tests passed')
