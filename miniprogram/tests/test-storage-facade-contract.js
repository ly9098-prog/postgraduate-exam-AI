/**
 * Client storage facade contract.
 *
 * `utils/storage.js` is the aggregated namespace consumed by pages, controllers,
 * subpackages and scripts. This pins its export surface and the behavior of the
 * session primitives, the 408 study strategy, pomodoro task typing and the
 * knowledge-map practice receipts.
 *
 * Run: node --test tests/test-storage-facade-contract.js
 */

const assert = require('node:assert/strict')
const { test } = require('node:test')

const memory = new Map()
let storageInfoFailure = false
let setFailure = null
let readFailure = null
let removeFailure = null
const errors = []
global.wx = {
  getStorageSync(key) {
    if (readFailure) throw readFailure
    return memory.has(key) ? memory.get(key) : ''
  },
  setStorageSync(key, value) {
    if (setFailure) throw setFailure
    memory.set(key, value)
  },
  removeStorageSync(key) {
    if (removeFailure) throw removeFailure
    memory.delete(key)
  },
  getStorageInfoSync() {
    if (storageInfoFailure) throw new Error('storage info unavailable')
    return { keys: Array.from(memory.keys()) }
  },
}
console.error = (...args) => { errors.push(args) }

const storage = require('../utils/storage')

function reset(entries = {}) {
  memory.clear()
  storageInfoFailure = false
  setFailure = null
  readFailure = null
  removeFailure = null
  errors.length = 0
  Object.entries(entries).forEach(([key, value]) => memory.set(key, value))
  return storage
}

test('facade exports keep their names and order', () => {
  assert.deepEqual(Object.keys(storage), [
    'KEYS', 'get', 'set', 'setStrict', 'remove', 'clearSession',
    'BUSINESS_CACHE_KEYS', 'PROTECTED_KEYS', 'SESSION_DYNAMIC_KEY_PREFIXES',
    'studyStrategy', 'pomodoroTaskTypes', 'knowledgePracticeSync',
  ])
  assert.deepEqual(storage.KEYS, {
    TOKEN: 'token', USER: 'user', TOKEN_EXPIRES_AT: 'token_expires_at',
    REFRESH_TOKEN: 'refresh_token',
  })
  assert.deepEqual(storage.PROTECTED_KEYS, ['privacy_acceptance'])
  assert.deepEqual(storage.SESSION_DYNAMIC_KEY_PREFIXES, [
    'ai_', 'aiCache', 'ai_diagnosis', 'practice_pending_submission_v1:',
    'exam_attempt_pending_v1:', 'exam_attempt_pending_v2:', 'exam_attempt_pending_v3:',
    'review_today_draft_v1:',
    'practice_resume_v1:', 'study_active_v1:',
  ])
  assert.ok(storage.BUSINESS_CACHE_KEYS.includes('pomodoro_running_state'))
  assert.ok(storage.BUSINESS_CACHE_KEYS.includes('home_today_goal_total'))
})

test('primitive writes keep their success and failure semantics', () => {
  reset()
  storage.set('k', { a: 1 })
  assert.deepEqual(storage.get('k'), { a: 1 })
  storage.setStrict('s', 'v')
  assert.equal(memory.get('s'), 'v')
  storage.remove('k')
  assert.equal(storage.get('k'), '')
  assert.deepEqual(errors, [])
  setFailure = new Error('quota exceeded')
  storage.set('k', 1)
  assert.equal(memory.has('k'), false)
  assert.equal(errors.length, 1)
  assert.equal(errors[0][0], 'Storage set error:')
  assert.equal(errors[0][1], setFailure)
  assert.throws(() => storage.setStrict('s2', 1), error => error === setFailure)
  setFailure = null
  readFailure = new Error('read failure')
  assert.equal(storage.get('k'), null)
  readFailure = null
  storage.set('k', 1)
  removeFailure = new Error('remove failure')
  storage.remove('k')
  assert.equal(memory.get('k'), 1)
})

test('session cleanup keeps protected, unrelated and opt-in debug keys', () => {
  reset({
    token: 'a', refresh_token: 'b', user: { id: 1 }, token_expires_at: 9,
    privacy_acceptance: true, other_screen_cache: 1, lastPracticeResult: 2,
    'exam_attempt_pending_v3:12': 3, 'practice_pending_submission_v1:12': 4,
    'review_today_draft_v1:9': 5, 'exam_attempt_pending_v1:12': 6,
    'debug_snapshot:a': 7, 'debug_snapshot:b': 8,
  })
  storage.clearSession()
  assert.deepEqual(Array.from(memory.keys()).sort(),
    ['other_screen_cache', 'privacy_acceptance'])
  reset({ token: 'a', privacy_acceptance: true, 'ai_cache:1': 1, 'debug_snapshot:a': 1 })
  storage.clearSession({ preservePrivacyAcceptance: true, includeDebugSnapshots: false })
  assert.deepEqual(Array.from(memory.keys()).sort(), ['debug_snapshot:a', 'privacy_acceptance'])
  reset({ token: 'a', 'debug_snapshot:a': 1 })
  storageInfoFailure = true
  storage.clearSession()
  assert.deepEqual(Array.from(memory.keys()), ['debug_snapshot:a'])
})

function strategyItems(accuracy) {
  return ['data_structure', 'computer_organization', 'operating_system', 'computer_network']
    .map(code => ({ subjectCode: code, totalQuestions: 11, accuracy }))
}

test('study strategy metadata and profile normalization stay stable', () => {
  reset({ user: { id: 1001 } })
  const strategy = storage.studyStrategy
  assert.deepEqual(Object.keys(strategy), [
    'STORAGE_KEY', 'SCHEMA_VERSION', 'SUBJECTS', 'STAGES', 'STAGE_MAP',
    'CHOICE_TOTAL_POINTS', 'CHOICE_LOSS_BUDGET_POINTS', 'CHOICE_TARGET_POINTS',
    'createDefaultProfile', 'normalizeProfile', 'getProfile', 'saveProfile',
    'validateProfile', 'getSubjectStrategy', 'stageLabel', 'subjectCodeFromItem',
    'buildChoiceLossBudget', 'buildNextBestAction',
  ])
  assert.equal(strategy.STORAGE_KEY, 'study_strategy_v1')
  assert.deepEqual(strategy.SUBJECTS.map(item => [item.code, item.choiceQuestions, item.defaultStage,
    item.defaultWeight]), [
    ['data_structure', 11, 'maintenance', 15],
    ['computer_organization', 12, 'second_round', 35],
    ['operating_system', 10, 'not_started', 35],
    ['computer_network', 7, 'not_started', 15],
  ])
  assert.deepEqual(strategy.STAGES.map(item => item.value), ['not_started', 'strengthening',
    'second_round', 'exam', 'maintenance'])
  assert.deepEqual(Object.keys(strategy.STAGE_MAP).map(key => strategy.STAGE_MAP[key].index),
    [0, 1, 2, 3, 4])
  assert.equal(strategy.CHOICE_TOTAL_POINTS, 80)
  assert.equal(strategy.CHOICE_LOSS_BUDGET_POINTS, 8)
  assert.equal(strategy.CHOICE_TARGET_POINTS, 72)
  const defaults = strategy.getProfile()
  assert.equal(defaults.version, 1)
  assert.equal(defaults.owner, '1001')
  assert.deepEqual(defaults.subjects, [
    { code: 'data_structure', stage: 'maintenance', weight: 15 },
    { code: 'computer_organization', stage: 'second_round', weight: 35 },
    { code: 'operating_system', stage: 'not_started', weight: 35 },
    { code: 'computer_network', stage: 'not_started', weight: 15 },
  ])
  assert.equal(strategy.saveProfile(defaults).owner, '1001')
  assert.equal(strategy.getProfile().subjects[0].weight, 15)
})

test('study strategy owner isolation, rounding and validation stay stable', () => {
  reset({ user: { id: 1001 } })
  const strategy = storage.studyStrategy
  const saved = strategy.saveProfile(strategy.getProfile())
  assert.equal(memory.get('study_strategy_v1').owner, '1001')
  memory.set('user', { username: 'someone-else' })
  assert.equal(strategy.getProfile().owner, 'someone-else')
  assert.deepEqual(strategy.getProfile().subjects.map(item => item.weight), [15, 35, 35, 15])
  memory.set('user', {})
  assert.equal(strategy.getProfile().owner, 'anonymous')
  assert.equal(strategy.normalizeProfile(undefined).subjects.length, 4)
  const rounded = strategy.normalizeProfile({
    owner: 'anonymous',
    subjects: [
      { code: 'data_structure', stage: 'nope', weight: 12.4 },
      { code: 'data_structure', stage: 'exam', weight: 12.6 },
      { code: 'operating_system', weight: 200 },
      { code: 'nope', weight: 10 },
    ],
  })
  assert.deepEqual(rounded.subjects.map(item => [item.stage, item.weight]), [
    ['exam', 15], ['second_round', 35], ['not_started', 100], ['not_started', 15],
  ])
  const invalid = strategy.validateProfile(rounded)
  assert.equal(invalid.valid, false)
  assert.equal(invalid.totalWeight, 165)
  assert.equal(invalid.message, '四科权重合计需为 100%，当前为 165%')
  assert.equal(strategy.validateProfile(strategy.getProfile()).message, '')
  assert.throws(() => strategy.saveProfile(rounded), error => {
    assert.equal(error.code, 'invalid_study_strategy')
    assert.match(error.message, /100%/)
    return true
  })
  const stageProfile = strategy.getProfile()
  stageProfile.subjects[0].stage = 'nope'
  const stageInvalid = strategy.validateProfile(stageProfile)
  // normalizeSubjectEntry already falls back to the subject default stage, so the
  // "存在无效学习阶段" branch is unreachable through the public validator.
  assert.equal(stageInvalid.valid, true)
  assert.equal(stageInvalid.message, '')
  assert.equal(stageInvalid.profile.subjects[0].stage, 'maintenance')
  assert.equal(strategy.stageLabel('exam'), '真题检测')
  assert.equal(strategy.stageLabel('unknown'), '未开始')
  assert.deepEqual(strategy.getSubjectStrategy(saved, 'operating_system'),
    { code: 'operating_system', stage: 'not_started', weight: 35 })
  assert.equal(strategy.getSubjectStrategy(saved, 'nope'), null)
  memory.set('study_strategy_v1', saved)
  assert.equal(strategy.getSubjectStrategy(null, 'data_structure').weight, 15)
})

test('subject code inference keeps alias and Chinese name rules', () => {
  reset()
  const { subjectCodeFromItem } = storage.studyStrategy
  assert.equal(subjectCodeFromItem({ subjectCode: 'DATA_STRUCTURE' }), 'data_structure')
  assert.equal(subjectCodeFromItem({ code: 'computer_network' }), 'computer_network')
  assert.equal(subjectCodeFromItem({ subject_code: 'operating_system' }), 'operating_system')
  assert.equal(subjectCodeFromItem({ subject: 'computer_organization' }), 'computer_organization')
  assert.equal(subjectCodeFromItem({ name: '数据结构复习' }), 'data_structure')
  assert.equal(subjectCodeFromItem({ subjectName: '计算机组成原理' }), 'computer_organization')
  assert.equal(subjectCodeFromItem({ name: '计组专项' }), 'computer_organization')
  assert.equal(subjectCodeFromItem({ label: '操作系统' }), 'operating_system')
  assert.equal(subjectCodeFromItem({ name: '计算机网络' }), 'computer_network')
  assert.equal(subjectCodeFromItem({ name: '计网' }), 'computer_network')
  assert.equal(subjectCodeFromItem({ name: '数学' }), '')
  assert.equal(subjectCodeFromItem(null), '')
  // Code wins over a contradicting name.
  assert.equal(subjectCodeFromItem({ code: 'data_structure', name: '操作系统' }), 'data_structure')
  assert.equal(subjectCodeFromItem({ code: 'unknown', name: '操作系统' }), 'operating_system')
})

test('choice loss budget keeps coverage, rounding and status rules', () => {
  reset()
  const { buildChoiceLossBudget } = storage.studyStrategy
  const empty = buildChoiceLossBudget(undefined)
  assert.equal(empty.coveredQuestions, 0)
  assert.equal(empty.coveredSubjects, 0)
  assert.equal(empty.coveragePct, 0)
  assert.equal(empty.fullCoverage, false)
  assert.equal(empty.projectedLoss, 0)
  assert.equal(empty.projectedScore, 0)
  assert.equal(empty.remainingBudget, 8)
  assert.equal(empty.status, 'building')
  assert.equal(empty.statusText, '已覆盖 0/40 道选择题配额')
  assert.deepEqual(empty.subjects.map(item => item.hasData), [false, false, false, false])
  assert.equal(empty.subjects[0].lossText, '待建立数据')
  const percent = buildChoiceLossBudget(strategyItems(0.9))
  assert.equal(percent.subjects[0].accuracyPct, 90)
  assert.equal(percent.subjects[0].expectedLoss, 2.2)
  assert.equal(percent.subjects[0].expectedScore, 19.8)
  assert.equal(percent.subjects[0].lossText, '预计失 2.2 分')
  assert.equal(percent.fullCoverage, true)
  assert.equal(percent.coveredQuestions, 40)
  assert.equal(percent.coveragePct, 100)
  assert.equal(percent.status, 'on_track')
  assert.match(percent.statusText, /在预算内$/)
  const fraction = buildChoiceLossBudget([{ subjectCode: 'data_structure', total_questions: 5, accuracy: 0.5 }])
  assert.equal(fraction.subjects[0].attempts, 5)
  assert.equal(fraction.subjects[0].accuracyPct, 50)
  assert.equal(fraction.coveredQuestions, 11)
  assert.equal(fraction.coveredSubjects, 1)
  assert.equal(fraction.coveragePct, 28)
  assert.equal(fraction.status, 'building')
  const lossy = buildChoiceLossBudget(strategyItems(0.5).map(item => ({
    ...item, accuracyPct: 50,
  })))
  assert.equal(lossy.status, 'over_budget')
  assert.equal(lossy.projectedLoss, 40)
  assert.equal(lossy.projectedScore, 40)
  assert.equal(lossy.remainingBudget, -32)
  assert.equal(lossy.statusText, '预计超预算 32 分')
  assert.equal(lossy.maxWrongQuestions, 4)
  const firstWins = buildChoiceLossBudget([
    { subjectCode: 'data_structure', totalQuestions: 1, accuracyPct: 10 },
    { subjectCode: 'data_structure', totalQuestions: 9, accuracyPct: 90 },
    { subjectCode: 'unknown', totalQuestions: 9, accuracyPct: 90 },
  ])
  assert.equal(firstWins.subjects[0].attempts, 1)
  assert.equal(firstWins.coveredSubjects, 1)
})

test('next best action keeps candidate scoring, routes and cleanup rules', () => {
  reset({ user: { id: 1001 } })
  const { buildNextBestAction, createDefaultProfile, saveProfile } = storage.studyStrategy
  const fallback = buildNextBestAction({})
  assert.equal(fallback.key, 'nba:operating_system:not_started')
  assert.equal(fallback.route, 'pomodoro')
  const paused = createDefaultProfile()
  paused.subjects.forEach(item => { item.weight = 0 })
  assert.equal(buildNextBestAction({ profile: paused }), null)
  const start = buildNextBestAction({ profile: paused, dueReviewCount: 9 })
  assert.equal(start.key, 'nba:review:due')
  assert.equal(start.task_type, 'review')
  assert.equal(start.route, 'review_today')
  assert.equal(start.estimated_minutes, 18)
  assert.equal(start.estimated_question_count, 9)
  assert.equal('_nbaScore' in start, false)
  assert.equal('_subjectCode' in start, false)
  const defaultProfile = saveProfile(createDefaultProfile())
  const study = buildNextBestAction({ profile: defaultProfile })
  assert.equal(study.key, 'nba:operating_system:not_started')
  assert.equal(study.task_type, 'strategy_progress')
  assert.equal(study.title, '启动操作系统强化')
  assert.equal(study.reason, '手动权重 35% · 当前未开始，先推进主线再用选择题验证。')
  assert.equal(study.route, 'pomodoro')
  assert.deepEqual(study.route_params, { subject_code: 'operating_system', task_type: 'lecture' })
  assert.equal(study.estimated_minutes, 50)
  assert.equal(study.estimated_question_count, 0)
  const started = buildNextBestAction({
    profile: { ...defaultProfile, subjects: defaultProfile.subjects.map(item =>
      item.code === 'operating_system' ? { ...item, stage: 'strengthening' } : item) },
  })
  assert.equal(started.key, 'nba:operating_system:strengthening')
  assert.equal(started.task_type, 'strategy_progress')
  assert.equal(started.title, '推进操作系统强化')
  assert.equal(started.estimated_minutes, 50)
  const maintenance = buildNextBestAction({
    profile: { ...defaultProfile, subjects: defaultProfile.subjects.map(item =>
      item.code === 'operating_system' ? { ...item, stage: 'maintenance' } : item) },
  })
  assert.equal(maintenance.key, 'nba:computer_organization:second_round')
  assert.equal(maintenance.task_type, 'smart_practice')
  assert.equal(maintenance.title, '计组二轮专项 20 题')
  assert.equal(maintenance.route, 'practice')
  assert.deepEqual(maintenance.route_params, {
    subject_code: 'computer_organization', mode: 'smart', count: 20, source: 'nba',
  })
  assert.equal(maintenance.estimated_minutes, 24)
  const onlyNetwork = createDefaultProfile()
  onlyNetwork.subjects.forEach(item => { item.weight = item.code === 'computer_network' ? 30 : 0 })
  onlyNetwork.subjects[3].stage = 'maintenance'
  const holding = buildNextBestAction({ profile: onlyNetwork })
  assert.equal(holding.key, 'nba:computer_network:maintenance')
  assert.equal(holding.task_type, 'maintenance')
  assert.equal(holding.title, '计网保温 10 题')
  assert.deepEqual(holding.route_params, {
    subject_code: 'computer_network', mode: 'smart', count: 10, source: 'nba',
  })
  assert.equal(holding.estimated_minutes, 12)
  assert.equal(holding.estimated_question_count, 10)
  const mastered = buildNextBestAction({
    profile: onlyNetwork,
    subjectMastery: [{ subjectId: 7, score: 40 }],
    hub: {
      primary_task: { key: 'hub:1', route: 'practice', subject_id: 7, completed_today: true },
      tasks: [{ route: 'practice', subject_id: 7 }],
    },
  })
  assert.equal(mastered.key, 'nba:backend:1')
  assert.equal(mastered.route, 'practice')
  assert.equal(mastered.subject_id, 7)
  assert.equal('_nbaScore' in mastered, false)
  assert.equal('_subjectCode' in mastered, false)
  const hubOnly = buildNextBestAction({
    profile: onlyNetwork,
    hub: { primary_task: { key: 'hub:9', route: 'practice', subject_id: 7 } },
  })
  assert.equal(hubOnly.key, 'hub:9')
  assert.equal(hubOnly.subject_id, 7)
  assert.deepEqual(buildNextBestAction({ profile: paused, dueReviewCount: 0 }), null)
  assert.equal('completed_today' in mastered, false)
})

test('pomodoro task typing keeps keys, classification and record cap rules', () => {
  reset()
  const types = storage.pomodoroTaskTypes
  assert.deepEqual(Object.keys(types), ['STORAGE_KEY', 'SELECTION_KEY', 'TYPES', 'TYPE_MAP',
    'DEFAULT_TYPE', 'normalize', 'label', 'getSelected', 'setSelected', 'recordSession',
    'typeForSession', 'labelForSession'])
  assert.equal(types.STORAGE_KEY, 'pomodoro_task_type_records_v1')
  assert.equal(types.SELECTION_KEY, 'pomodoro_task_type_selection_v1')
  assert.equal(types.DEFAULT_TYPE, 'new_questions')
  assert.deepEqual(types.TYPES.map(item => item.value), ['lecture', 'textbook', 'new_questions',
    'wrong_questions', 'review', 'exam'])
  assert.equal(types.normalize('exam'), 'exam')
  assert.equal(types.normalize('unknown'), 'new_questions')
  assert.equal(types.normalize(undefined), 'new_questions')
  assert.equal(types.label('wrong_questions'), '错题')
  assert.equal(types.label('unknown'), '新题')
  assert.equal(types.getSelected(), 'new_questions')
  assert.equal(types.setSelected('review'), 'review')
  assert.equal(memory.get('pomodoro_task_type_selection_v1'), 'review')
  assert.equal(types.getSelected(), 'review')
  assert.deepEqual(types.typeForSession(undefined), '')
  assert.equal(types.typeForSession({ task_type: 'exam' }), 'exam')
  assert.equal(types.typeForSession({ task_type: 'legacy' }), '')
  assert.equal(types.labelForSession({ task_type: 'lecture' }), '听课')
  types.recordSession(null, 'exam')
  types.recordSession({ id: 1 }, 'unknown')
  types.recordSession({ client_start_id: 'c1' }, 'unknown')
  assert.equal(memory.has('pomodoro_task_type_records_v1'), false)
  types.recordSession({ id: 11, client_start_id: 'c11' }, 'exam')
  types.recordSession({ client_start_id: 'c12' }, 'lecture')
  const records = memory.get('pomodoro_task_type_records_v1').records
  assert.deepEqual(Object.keys(records).sort(), ['client:c11', 'client:c12', 'id:11'])
  assert.equal(records['id:11'].type, 'exam')
  assert.equal(records['id:11'].clientId, 'c11')
  assert.equal(records['client:c11'].sessionId, '11')
  assert.equal(types.typeForSession({ id: 11 }), 'exam')
  assert.equal(types.typeForSession({ client_start_id: 'c12' }), 'lecture')
  assert.equal(types.typeForSession({ id: 999, client_start_id: 'c999' }), '')
  assert.equal(types.typeForSession({ id: 11, client_start_id: 'missing' }), 'exam')
  const bulk = { version: 1, records: {} }
  for (let index = 0; index < 650; index += 1) {
    bulk.records[`id:${index}`] = { type: 'exam', savedAt: index }
  }
  storage.set(types.STORAGE_KEY, bulk)
  types.recordSession({ id: 700 }, 'review')
  const capped = memory.get('pomodoro_task_type_records_v1').records
  assert.equal(Object.keys(capped).length, 600)
  assert.equal(capped['id:700'].type, 'review')
  assert.equal(types.typeForSession({ id: 0 }), '')
  assert.equal(memory.get('pomodoro_task_type_records_v1').records['id:700'].type, 'review')
  assert.equal('loadRecords' in types, false)
})

test('knowledge practice receipts keep normalization, merge and owner rules', () => {
  reset({ user: { id: 1001 } })
  const sync = storage.knowledgePracticeSync
  assert.deepEqual(Object.keys(sync), ['STORAGE_KEY', 'BASELINE_STORAGE_KEY', 'setBaseline',
    'consumeBaseline', 'record', 'getForSubject', 'hasPending', 'remove', 'resolveReceipt'])
  assert.equal(sync.STORAGE_KEY, 'knowledge_practice_sync_receipts_v1')
  assert.equal(sync.BASELINE_STORAGE_KEY, 'knowledge_practice_sync_baselines_v1')
  sync.setBaseline(0, 0, 5)
  assert.equal(memory.has('knowledge_practice_sync_baselines_v1'), false)
  sync.setBaseline(3, 9, 4.7)
  assert.deepEqual(memory.get('knowledge_practice_sync_baselines_v1'), {
    version: 1, owner: '1001', baselines: { '3:9': 4 },
  })
  assert.equal(sync.consumeBaseline(3, 9), 4)
  assert.equal(sync.consumeBaseline(3, 9), 0)
  assert.equal(sync.consumeBaseline(0, 0), 0)
  memory.set('user', { id: 2002 })
  assert.equal(sync.consumeBaseline(3, 9), 0)
  sync.setBaseline(3, 9, 6)
  assert.equal(memory.get('knowledge_practice_sync_baselines_v1').owner, '2002')
  assert.equal(sync.record({ subjectId: 0, knowledgePointId: 1, answeredCount: 2 }), null)
  assert.equal(sync.record({ subjectId: 1, knowledgePointId: 0, answeredCount: 2 }), null)
  assert.equal(sync.record({ subjectId: 1, knowledgePointId: 1, answeredCount: 0 }), null)
  const first = sync.record({ subjectId: 1, knowledgePointId: 2, answeredCount: 3,
    correctCount: 5, wrongCount: -2, baselineAttemptCount: 10, requestId: 'r1',
    rootName: '根节点', includeDescendants: true })
  assert.equal(first.subjectId, 1)
  assert.equal(first.correctCount, 3)
  assert.equal(first.wrongCount, 0)
  assert.equal(first.expectedMinAttemptCount, 13)
  assert.equal(first.includeDescendants, true)
  assert.equal(first.requestId, 'r1')
  assert.equal(first.rootName, '根节点')
  const merged = sync.record({ subjectId: 1, knowledgePointId: 2, answeredCount: 5,
    correctCount: 5, baselineAttemptCount: 12, requestId: '' })
  assert.equal(merged.baselineAttemptCount, 10)
  assert.equal(merged.expectedMinAttemptCount, 17)
  assert.equal(merged.requestId, 'r1')
  // Only requestId (plus baseline/expected/createdAt) survives a merge; the rest
  // of the latest launch wins.
  assert.equal(merged.rootName, '')
  assert.equal(merged.includeDescendants, false)
  assert.equal(sync.getForSubject(1).length, 1)
  assert.equal(sync.hasPending(1), true)
  assert.equal(sync.getForSubject(0).length, 0)
  // resolveReceipt recomputes the baseline from the normalized fields, so the
  // stored max expected count (17) is not the authoritative threshold.
  assert.equal(sync.resolveReceipt(merged, 14), false)
  assert.equal(sync.resolveReceipt(merged, 15), true)
  assert.equal(sync.resolveReceipt({ subjectId: 1, knowledgePointId: 0 }, 99), false)
  memory.set('user', { id: 3003 })
  assert.deepEqual(sync.getForSubject(1), [])
  assert.equal(sync.hasPending(1), false)
  sync.remove([{ subjectId: 1, knowledgePointId: 2 }])
  assert.equal(memory.get('knowledge_practice_sync_receipts_v1').owner, '2002')
  memory.set('user', { id: 2002 })
  sync.remove([{ subjectId: 1, knowledgePointId: 2 }])
  assert.deepEqual(sync.getForSubject(1), [])
  assert.equal(sync.hasPending(1), false)
  sync.remove(null)
  assert.deepEqual(memory.get('knowledge_practice_sync_receipts_v1').receipts, [])
})
