const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  mapPracticePayload,
  buildPracticeDataPatch,
  maybeRecordKnowledgeSync,
} = require('../subpackages/study/practice-result/utils/practice-payload-mapper')

function ports(overrides = {}) {
  const calls = { knowledgeSync: [], baselines: [] }
  const base = {
    buildReviewItem: (q, r, a, i) => ({ id: q.id, status: r.status || 'wrong', index: i }),
    normalizeReviewItem: (item, i) => ({ ...item, index: i, status: item.status || 'wrong' }),
    resolveResultCounts: () => ({ correctCount: 2, wrongCount: 1, skippedCount: 0, partialCount: 0, totalCount: 3 }),
    normalizePercent: v => Math.round(Number(v) * 100),
    formatDuration: () => '5:00',
    getQuestionListHeightRpx: n => n * 100,
    buildErrorDonutGradient: () => 'gradient',
    buildErrorDonutSvg: () => '<svg/>',
    normalizeGrowthProfile: () => null,
    buildLocalErrorDistribution: () => ({ items: [] }),
    getResultTip: () => 'tip',
    getLaunchKnowledgePointId: () => 0,
    getLaunchSource: () => 'practice',
    getLaunchSubjectId: () => 0,
    getPracticeRequestId: () => 'req-1',
    recordKnowledgePractice: data => { calls.knowledgeSync.push(data) },
    consumeKnowledgeBaseline: (sid, kid) => { calls.baselines.push({ sid, kid }); return 5 },
    ...overrides,
  }
  return { ports: base, calls }
}

function samplePayload() {
  return {
    results: [
      { question_id: 1, status: 'correct' },
      { question_id: 2, status: 'wrong' },
    ],
    questions: [{ id: 1 }, { id: 2 }],
    answers: [{ question_id: 1, used_time: 60 }],
    accuracy: 0.67,
    used_time: 300,
    subjectName: '数学',
  }
}

test('maps payload source, review items and counts', () => {
  const { ports: p } = ports()
  const mapped = mapPracticePayload(samplePayload(), p)
  assert.equal(mapped.source.subjectName, '数学')
  assert.equal(mapped.reviewItems.length, 2)
  assert.equal(mapped.counts.correctCount, 2)
  assert.equal(mapped.counts.wrongCount, 1)
  assert.equal(mapped.counts.answeredTotal, 3)
})

test('computes accuracy from explicit value', () => {
  const { ports: p } = ports()
  const mapped = mapPracticePayload(samplePayload(), p)
  assert.equal(mapped.accuracyPct, 67)
})

test('computes accuracy from counts when no explicit value', () => {
  const { ports: p } = ports()
  const payload = samplePayload()
  delete payload.accuracy
  const mapped = mapPracticePayload(payload, p)
  assert.equal(mapped.accuracyPct, 67)
})

test('extracts subject name from question fallback', () => {
  const { ports: p } = ports()
  const payload = { questions: [{ id: 1, subject_name: '英语' }], results: [{ question_id: 1, status: 'correct' }] }
  const mapped = mapPracticePayload(payload, p)
  assert.equal(mapped.subjectName, '英语')
})

test('builds data patch with all expected fields', () => {
  const { ports: p } = ports()
  const mapped = mapPracticePayload(samplePayload(), p)
  const patch = buildPracticeDataPatch(mapped, p)
  assert.equal(patch.subjectName, '数学')
  assert.equal(patch.correctCount, 2)
  assert.equal(patch.accuracyPct, 67)
  assert.equal(patch.durationText, '5:00')
  assert.equal(patch.batchDiagnosisMode, false)
  assert.equal(patch.errorDonutSvg, '<svg/>')
  assert.ok(patch.reviewItems.length === 2)
})

test('knowledge sync is recorded when launch conditions are met', () => {
  const { ports: p, calls } = ports({
    getLaunchSource: () => 'knowledge_map',
    getLaunchSubjectId: () => 10,
    getLaunchKnowledgePointId: () => 20,
  })
  const mapped = mapPracticePayload(samplePayload(), p)
  maybeRecordKnowledgeSync(mapped, p)
  assert.equal(calls.knowledgeSync.length, 1)
  assert.equal(calls.knowledgeSync[0].subjectId, 10)
  assert.equal(calls.knowledgeSync[0].knowledgePointId, 20)
})

test('knowledge sync is skipped when no launch subject', () => {
  const { ports: p, calls } = ports({
    getLaunchSource: () => 'knowledge_map',
    getLaunchSubjectId: () => 0,
    getLaunchKnowledgePointId: () => 20,
  })
  const mapped = mapPracticePayload(samplePayload(), p)
  maybeRecordKnowledgeSync(mapped, p)
  assert.equal(calls.knowledgeSync.length, 0)
})

test('handles wrapped payload with data property', () => {
  const { ports: p } = ports()
  const payload = { data: { results: [{ question_id: 1, status: 'correct' }], questions: [{ id: 1 }] } }
  const mapped = mapPracticePayload(payload, p)
  assert.equal(mapped.reviewItems.length, 1)
})
