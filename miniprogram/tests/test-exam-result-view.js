const assert = require('node:assert/strict')
const { test } = require('node:test')

const {
  clamp,
  percentNumber,
  compactDuration,
  compactScore,
  normalizeName,
  shortName,
  masteryTag,
  encouragement,
  encouragementTail,
  firstWrongIdByQuestion,
  buildKnowledgeMetrics,
  buildKnowledgeStats,
  sortAndSliceMetrics,
  buildRadar,
  buildScoreRing,
  buildTopItems,
  collectWrongIds,
} = require('../subpackages/exam/utils/exam-result-view')

test('compactDuration formats hours and clamps invalid input to zero', () => {
  assert.equal(compactDuration(3661), '01:01:01')
  assert.equal(compactDuration(65), '01:05')
  // Seconds are rounded before formatting, so fractions cannot leak into the text.
  assert.equal(compactDuration(65.6), '01:06')
  assert.equal(compactDuration(3599.7), '01:00:00')
  assert.equal(compactDuration(0), '00:00')
  assert.equal(compactDuration(-5), '00:00')
  assert.equal(compactDuration('abc'), '00:00')
})

test('compactScore trims integer scores and keeps one decimal otherwise', () => {
  assert.equal(compactScore(12), '12')
  assert.equal(compactScore(12.5), '12.5')
  assert.equal(compactScore(12.0001), '12')
  assert.equal(compactScore(NaN), '0')
})

test('clamp and percentNumber keep the finite-number contract', () => {
  assert.equal(clamp(NaN, 0, 100), 0)
  assert.equal(clamp(150, 0, 100), 100)
  assert.equal(clamp(-5, 0, 100), 0)
  assert.equal(percentNumber(0.756), 76)
  // A rate of exactly 1 is already a ratio, so it becomes 100 percent.
  assert.equal(percentNumber(1), 100)
  assert.equal(percentNumber(0.5), 50)
  assert.equal(percentNumber(76), 76)
  assert.equal(percentNumber(NaN), 0)
})

test('normalizeName collapses whitespace and shortName truncates with an ellipsis', () => {
  assert.equal(normalizeName('  a   b  ', 'fallback'), 'a b')
  assert.equal(normalizeName('', 'fallback'), 'fallback')
  assert.equal(normalizeName(undefined, undefined), '未命名知识点')
  assert.equal(shortName('一二三四五六七八九十十一', 8), '一二三四五六七…')
  assert.equal(shortName('abcdef', 4), 'abc…')
})

test('masteryTag maps accuracy bands and treats invalid input as weakest', () => {
  assert.deepEqual(masteryTag(85), { label: '优秀', tone: 'excellent' })
  assert.deepEqual(masteryTag(70), { label: '良好', tone: 'good' })
  assert.deepEqual(masteryTag(69), { label: '待提升', tone: 'weak' })
  assert.deepEqual(masteryTag(NaN), { label: '待提升', tone: 'weak' })
})

test('encouragement uses the higher of score rate and accuracy', () => {
  assert.equal(encouragement(90, 0), '状态很棒！')
  assert.equal(encouragement(80, 0), '表现不错！')
  assert.equal(encouragement(60, 0), '继续保持！')
  assert.equal(encouragement(10, 20), '再接再厉！')
})

test('encouragementTail prefers wrong answers over unanswered ones', () => {
  assert.equal(encouragementTail(2, 3), '，继续查漏补缺')
  assert.equal(encouragementTail(0, 3), '，还有 3 道题未作答')
  assert.equal(encouragementTail(0, 0), '，继续保持！')
})

test('firstWrongIdByQuestion only accepts positive ids', () => {
  assert.equal(firstWrongIdByQuestion({ wrong_question_id: 7 }), 7)
  assert.equal(firstWrongIdByQuestion({ wrong_question_id: '9' }), 9)
  assert.equal(firstWrongIdByQuestion({ wrong_question_id: 0 }), 0)
  assert.equal(firstWrongIdByQuestion({ wrong_question_id: -3 }), 0)
  assert.equal(firstWrongIdByQuestion(null), 0)
})

test('buildKnowledgeStats aggregates per knowledge point and keeps the first wrong id', () => {
  const questions = [
    { id: 1, wrong_question_id: 7, knowledge_points: ['同', '同'], status: 'wrong' },
    { id: 2, wrong_question_id: 0, knowledge_points: ['同'], status: 'correct' },
  ]
  assert.deepEqual([...buildKnowledgeStats(questions).entries()], [[
    '同',
    { name: '同', questionCount: 2, correctCount: 1, wrongQuestionId: 7, source: 'knowledge' },
  ]])
  // The original page implementation reads the array directly, so null still throws.
  assert.throws(() => buildKnowledgeStats(null), TypeError)
})

test('sortAndSliceMetrics ranks by question count, accuracy and name, then caps at five', () => {
  const stats = new Map([
    ['a', { name: 'a', questionCount: 1, correctCount: 0 }],
    ['b', { name: 'b', questionCount: 3, correctCount: 1 }],
    ['c', { name: 'c', questionCount: 3, correctCount: 3 }],
    ['d', { name: 'd', questionCount: 2, correctCount: 2 }],
    ['e', { name: 'e', questionCount: 2, correctCount: 1 }],
    ['f', { name: 'f', questionCount: 1, correctCount: 1 }],
  ])
  const metrics = sortAndSliceMetrics(stats)
  assert.deepEqual(metrics.map(item => item.name), ['c', 'b', 'd', 'e', 'f'])
  assert.deepEqual(metrics.map(item => item.accuracyPct), [100, 33, 100, 50, 100])
  assert.deepEqual(sortAndSliceMetrics(new Map()), [])
})

test('buildKnowledgeMetrics fills overall and fallback dimensions to the radar size', () => {
  const metrics = buildKnowledgeMetrics({ score: 20, total_score: 30, accuracy: 0.66, duration_sec: 600, questions: [] })
  assert.equal(metrics.length, 5)
  assert.deepEqual(metrics.map(item => item.name), ['综合表现', '能力维度2', '能力维度3', '能力维度4', '能力维度5'])
  assert.ok(metrics.every(item => item.source === 'overall' || item.source === 'fallback'))
  assert.equal(metrics[0].accuracyPct, 66)
  assert.deepEqual(buildKnowledgeMetrics(null).map(item => item.name),
    ['综合表现', '能力维度2', '能力维度3', '能力维度4', '能力维度5'])
})

test('buildTopItems filters fallbacks, ranks at most three and adds display fields', () => {
  const items = buildTopItems([
    { name: 'a', accuracyPct: 10, questionCount: 1, source: 'knowledge' },
    { name: 'b', accuracyPct: 90, questionCount: 2, source: 'knowledge' },
    { name: '综合表现', accuracyPct: 66, questionCount: 0, source: 'overall' },
    { name: '能力维度5', accuracyPct: 66, questionCount: 0, source: 'fallback' },
    { name: 'c', accuracyPct: 90, questionCount: 3, source: 'knowledge' },
    { name: 'd', accuracyPct: 50, questionCount: 1, source: 'knowledge' },
  ])
  assert.deepEqual(items.map(item => item.name), ['c', 'b', '综合表现'])
  assert.deepEqual(items.map(item => item.rank), [1, 2, 3])
  assert.deepEqual(items.map(item => item.progressPct), [90, 90, 66])
  // Equal accuracy and question count fall back to a locale-aware name order.
  assert.deepEqual(buildTopItems([
    { name: 'beta', accuracyPct: 50, questionCount: 2, source: 'knowledge' },
    { name: 'alpha', accuracyPct: 50, questionCount: 2, source: 'knowledge' },
    { name: 'g', accuracyPct: 50, questionCount: 2, source: 'knowledge' },
  ]).map(item => item.name), ['alpha', 'beta', 'g'])
  assert.deepEqual(buildTopItems([]), [])
  assert.deepEqual(buildTopItems(), [])
})

test('buildRadar projects item coordinates and keeps the polygon contract', () => {
  const metrics = buildKnowledgeMetrics({ score: 20, total_score: 30, accuracy: 0.66, duration_sec: 600, questions: [] })
  const radar = buildRadar(metrics)
  assert.equal(radar.radarItems.length, 5)
  assert.equal(radar.radarEdges.length, 5)
  const first = radar.radarItems[0]
  assert.equal(first.name, '\u7efc\u5408\u8868\u73b0')
  assert.equal(first.pointX, 50)
  assert.equal(first.pointY, 21.95)
  assert.equal(first.pointStyle, 'left:50.00%;top:21.95%;')
  assert.equal(first.index, 0)
  assert.deepEqual([first.tagLabel, first.tagTone], ['\u5f85\u63d0\u5347', 'weak'])
  assert.deepEqual(first, {
    name: '\u7efc\u5408\u8868\u73b0', questionCount: 0, correctCount: 0, accuracyPct: 66,
    wrongQuestionId: 0, source: 'overall', index: 0, displayName: '\u7efc\u5408\u8868\u73b0',
    tagLabel: '\u5f85\u63d0\u5347', tagTone: 'weak', pointX: 50, pointY: 21.95,
    pointStyle: 'left:50.00%;top:21.95%;',
  })
  assert.equal(radar.radarEdges[0].style,
    'left:50.00%;top:21.95%;width:32.97%;transform:rotate(36.00deg);')
  assert.equal(radar.radarPolygonStyle.split('clip-path:')[1].split(';')[0],
    'polygon(50.00% 21.95%,76.68% 41.33%,66.49% 72.69%,33.51% 72.69%,23.32% 41.33%)')
  assert.equal(buildRadar([]).radarPolygonStyle, 'clip-path:polygon();-webkit-clip-path:polygon();')
  assert.deepEqual(buildRadar(undefined).radarItems, [])
})

test('buildScoreRing only shows caps for partial scores', () => {
  assert.deepEqual(buildScoreRing(0), { showScoreRingCaps: false, scoreRingEndStyle: '' })
  assert.deepEqual(buildScoreRing(100), { showScoreRingCaps: false, scoreRingEndStyle: '' })
  assert.deepEqual(buildScoreRing(NaN), { showScoreRingCaps: false, scoreRingEndStyle: '' })
  assert.deepEqual(buildScoreRing(50), { showScoreRingCaps: true, scoreRingEndStyle: 'left:50.00%;top:96.30%;' })
})

test('collectWrongIds keeps positive ids once, in first-seen order', () => {
  assert.deepEqual(collectWrongIds({
    questions: [
      { wrong_question_id: 5 }, { wrong_question_id: 5 }, { wrong_question_id: '5' },
      { wrong_question_id: 0 }, { wrong_question_id: null }, { wrong_question_id: -1 },
      { wrong_question_id: 12 },
    ],
  }), [5, 12])
  assert.deepEqual(collectWrongIds({}), [])
})
