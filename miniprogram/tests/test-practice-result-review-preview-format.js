const assert = require('node:assert/strict')
const { test } = require('node:test')

const {
  formatMathPreviewText,
  formatAnswerPreview,
  normalizeReviewStatus,
  pad2,
  getQuestionTitle,
  normalizeKpList,
} = require('../subpackages/study/practice-result/utils/review-preview-format')

test('formatMathPreviewText strips markup and decodes entities', () => {
  assert.equal(formatMathPreviewText('<p>a<br/>b</p>'), 'a b')
  assert.equal(formatMathPreviewText(' x&nbsp;&amp;&lt;y&gt; '), 'x &<y>')
  assert.equal(formatMathPreviewText('a  b\tc'), 'a b c')
})

test('formatMathPreviewText renders inline math through the plain-text port', () => {
  assert.equal(formatMathPreviewText('\\(x^2\\)'), 'x²')
  assert.equal(formatMathPreviewText('$x^2$'), 'x²')
})

test('formatMathPreviewText keeps the empty and non-string contract', () => {
  assert.equal(formatMathPreviewText('   '), '')
  assert.equal(formatMathPreviewText(), '')
  assert.equal(formatMathPreviewText(123), '123')
})

test('formatAnswerPreview relabels numbered and circled blanks', () => {
  assert.equal(formatAnswerPreview('1：A;2：B'), '第1空：A；第2空：B')
  assert.equal(formatAnswerPreview('①：甲；②：乙'), '①：甲；②：乙')
})

test('formatAnswerPreview leaves mixed or plain answers untouched', () => {
  assert.equal(formatAnswerPreview('①：甲;plain'), '①：甲;plain')
  assert.equal(formatAnswerPreview('A;B'), 'A;B')
  assert.equal(formatAnswerPreview('AB'), 'AB')
  assert.equal(formatAnswerPreview(5), 5)
})

test('normalizeReviewStatus reads only status fields and falls back on correctness', () => {
  assert.equal(normalizeReviewStatus({ status: 'CORRECT' }, false), 'correct')
  assert.equal(normalizeReviewStatus({ answer_status: 'Wrong' }, true), 'wrong')
  assert.equal(normalizeReviewStatus({ status: ' Skipped ' }, true), 'skipped')
  assert.equal(normalizeReviewStatus({ status: 'mystery' }, true), 'correct')
  assert.equal(normalizeReviewStatus(undefined, false), 'wrong')
  // A bare string is not a status object, so the correctness fallback still wins.
  assert.equal(normalizeReviewStatus('partial', false), 'wrong')
})

test('pad2 clamps negatives and non-numbers to zero', () => {
  assert.equal(pad2(0), '00')
  assert.equal(pad2(5), '05')
  assert.equal(pad2(10), '10')
  assert.equal(pad2(-3), '00')
  assert.equal(pad2('7'), '07')
  assert.equal(pad2(NaN), '00')
})

test('getQuestionTitle prefers content text then stem before page-level fields', () => {
  assert.equal(getQuestionTitle({ content: { text: 'T' }, stem: 'S', title: 'K' }), 'T')
  assert.equal(getQuestionTitle({ content: { stem: 'S' }, stem: 'S2' }), 'S')
  assert.equal(getQuestionTitle({ stem: 'S2', text: 'X' }), 'S2')
  assert.equal(getQuestionTitle({ content: {}, stem: 'S3' }), 'S3')
  assert.equal(getQuestionTitle(null), '')
})

test('normalizeKpList understands arrays, objects and separated strings', () => {
  assert.deepEqual(
    normalizeKpList(['a', { name: 'n' }, { title: 't' }, { knowledge_point_name: 'k' }, { label: 'l' }, null, 1]),
    ['a', 'n', 't', 'k', 'l'],
  )
  assert.deepEqual(normalizeKpList(' a ， b 、 c, d '), ['a', 'b', 'c', 'd'])
  assert.deepEqual(normalizeKpList({ name: 'x' }), [])
  assert.deepEqual(normalizeKpList(''), [])
})
