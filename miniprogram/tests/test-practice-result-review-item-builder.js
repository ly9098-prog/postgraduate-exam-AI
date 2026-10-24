const assert = require('node:assert/strict')
const { test } = require('node:test')
const { buildReviewItem, normalizeReviewItem } = require('../subpackages/study/practice-result/utils/review-item-builder')

const helpers = {
  normalizeReviewStatus: (source, isCorrect) => {
    const raw = String(source && (source.status || source.answer_status || '') || '').trim().toLowerCase()
    if (raw === 'correct') return 'correct'
    if (raw === 'wrong' || raw === 'incorrect') return 'wrong'
    if (raw === 'skipped') return 'skipped'
    if (raw === 'partial') return 'partial'
    return isCorrect ? 'correct' : 'wrong'
  },
  pad2: (n) => String(n).padStart(2, '0'),
  getQuestionTitle: (q) => (q && q.content && (q.content.text || q.content.stem)) || (q && q.stem) || (q && q.title) || '',
  formatAnswerPreview: (v) => String(v || ''),
  formatMathPreviewText: (v) => String(v || ''),
  normalizeKpList: (v) => { if (!v) return []; if (Array.isArray(v)) return v.map(i => typeof i === 'string' ? i : (i && i.name) || '').filter(Boolean); if (typeof v === 'string') return v.split(/[,，、]/).map(s => s.trim()).filter(Boolean); return []; },
}

test('buildReviewItem: builds from question+result+answer', () => {
  const item = buildReviewItem(
    { id: 1, content: { text: 'What is 2+2?' }, question_version_id: 'v1' },
    { is_correct: true, correct_answer: '4', question_version_id: 'v1', wrong_question_id: null },
    { user_answer: '4' },
    0,
    helpers
  )
  assert.equal(item.questionId, 1)
  assert.equal(item.title, 'What is 2+2?')
  assert.equal(item.status, 'correct')
  assert.equal(item.isCorrect, true)
  assert.equal(item.userAnswer, '4')
  assert.equal(item.correctAnswer, '4')
  assert.equal(item.displayIndex, '01')
})

test('buildReviewItem: falls back to index for questionId', () => {
  const item = buildReviewItem({}, {}, {}, 2, helpers)
  assert.equal(item.questionId, 3)
})

test('buildReviewItem: handles wrong answer', () => {
  const item = buildReviewItem(
    { id: 1, content: { text: 'Q' } },
    { is_correct: false, correct_answer: 'B' },
    { user_answer: 'A' },
    0,
    helpers
  )
  assert.equal(item.status, 'wrong')
  assert.equal(item.isCorrect, false)
})

test('buildReviewItem: defaults knowledgePoint when no KP', () => {
  const item = buildReviewItem({ id: 1, content: { text: 'Q' } }, {}, {}, 0, helpers)
  assert.equal(item.knowledgePoint, '未标注知识点')
})

test('normalizeReviewItem: normalizes from raw item', () => {
  const item = normalizeReviewItem(
    { questionId: 5, title: 'Question 5', status: 'correct', userAnswer: 'A', correctAnswer: 'A' },
    4,
    helpers
  )
  assert.equal(item.questionId, 5)
  assert.equal(item.displayIndex, '05')
  assert.equal(item.status, 'correct')
  assert.equal(item.isCorrect, true)
})

test('normalizeReviewItem: falls back to index for questionId', () => {
  const item = normalizeReviewItem({}, 3, helpers)
  assert.equal(item.questionId, 4)
  assert.equal(item.displayIndex, '04')
})

test('normalizeReviewItem: handles missing title', () => {
  const item = normalizeReviewItem({ questionId: 1 }, 0, helpers)
  assert.equal(item.title, '第 1 题')
})
