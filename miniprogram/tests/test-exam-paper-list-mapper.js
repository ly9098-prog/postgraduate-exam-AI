const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  buildPapers,
  cleanUiLabel,
  minutes,
  typeHint,
  typeLabel,
} = require('../subpackages/exam/utils/paper-list-mapper')

test('minutes clamps positive durations to at least one minute and maps zero to zero', () => {
  assert.equal(minutes(0), 0)
  assert.equal(minutes(null), 0)
  assert.equal(minutes(undefined), 0)
  assert.equal(minutes('not-a-number'), 0)
  assert.equal(minutes(1), 1)
  assert.equal(minutes(30), 1)
  assert.equal(minutes(60), 1)
  assert.equal(minutes(90), 2)
  assert.equal(minutes(3600), 60)
})

test('cleanUiLabel strips 408, collapses spaces, trims and falls back', () => {
  assert.equal(cleanUiLabel('408 数据结构'), '数据结构')
  assert.equal(cleanUiLabel('  数据    结构  '), '数据 结构')
  assert.equal(cleanUiLabel(''), '')
  assert.equal(cleanUiLabel(null), '')
  assert.equal(cleanUiLabel(undefined, 'MemoGrad'), 'MemoGrad')
})

test('typeLabel and typeHint distinguish past exam and mock papers', () => {
  assert.equal(typeLabel('past_exam_choice'), '真题选择题')
  assert.equal(typeLabel('mock_choice'), '选择题模拟卷')
  assert.equal(typeHint('past_exam_choice'), '历年真题 · 只做适合手机作答的选择题')
  assert.equal(typeHint('mock_choice'), '模拟训练 · 只做适合手机作答的选择题')
})

test('buildPapers maps every display field and resume flag', () => {
  const papers = buildPapers([{
    id: '11',
    title: '408 2024 真题',
    source: 'MemoGrad 408',
    paper_type: 'past_exam_choice',
    duration_sec: 180,
    total_choice_score: 80,
    best_choice_score: 66.66,
    latest_attempt_status: 'in_progress',
    latest_attempt_id: 55,
    year: 2024,
  }], 11)

  assert.equal(papers.length, 1)
  const paper = papers[0]
  assert.equal(paper.title, '2024 真题')
  assert.equal(paper.source, 'MemoGrad')
  assert.equal(paper.typeLabel, '真题选择题')
  assert.equal(paper.typeHint, '历年真题 · 只做适合手机作答的选择题')
  assert.equal(paper.durationMinutes, 3)
  assert.equal(paper.scoreText, '80')
  assert.equal(paper.bestScoreText, '66.7')
  assert.equal(paper.canResume, true)
  assert.equal(paper.isSuggested, true)
  assert.equal(paper.isLatestYear, true)
})

test('buildPapers handles null best score, non-resume attempts and latest-year flags', () => {
  const papers = buildPapers([
    { id: 1, year: 2023, best_choice_score: null, latest_attempt_status: 'submitted' },
    { id: 2, year: 2024, best_choice_score: 90, latest_attempt_status: 'in_progress' },
  ], 2)

  assert.equal(papers[0].bestScoreText, '')
  assert.equal(papers[0].canResume, false)
  assert.equal(papers[0].isLatestYear, false)
  assert.equal(papers[1].bestScoreText, '90.0')
  assert.equal(papers[1].canResume, false) // no latest_attempt_id
  assert.equal(papers[1].isSuggested, true)
  assert.equal(papers[1].isLatestYear, true)
})

test('buildPapers accepts non-array rows as empty', () => {
  assert.deepEqual(buildPapers(null, 1), [])
  assert.deepEqual(buildPapers(undefined, 1), [])
  assert.deepEqual(buildPapers('bad', 1), [])
})
