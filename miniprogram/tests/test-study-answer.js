/**
 * Study-package answer normalization contract.
 *
 * Mirrors tests/test-exam-answer.js for the study copy owned by practice,
 * review-today, wrong-detail and the study question-runner adapter.
 *
 * Run: node --test tests/test-study-answer.js
 */
const assert = require('node:assert/strict')
const { test } = require('node:test')
const answer = require('../subpackages/study/utils/answer')

test('study answer exports retain their names and order', () => {
  assert.deepEqual(Object.keys(answer), [
    'normalizeChoiceAnswer', 'serializeChoiceAnswer', 'normalizeAnswerSet',
    'isMultipleChoiceType', 'isTrueFalseType', 'isMultiBlankType',
    'isMultiBlankMultipleType', 'normalizeTrueFalseAnswer', 'normalizeBlankAnswer',
    'serializeBlankAnswer', 'isAnswerCorrect',
  ])
})

test('blank normalization keeps falsy values empty and objects unchanged without reading them', () => {
  for (const value of [undefined, null, false, 0, NaN, '']) {
    assert.deepEqual(answer.normalizeBlankAnswer(value), {})
  }
  const opaque = new Proxy({}, { get() { throw new Error('unexpected property read') } })
  for (const value of [opaque, [], new String('1:A'), Object.create(null)]) {
    assert.equal(answer.normalizeBlankAnswer(value), value)
  }
})

const blankCases = [
  ['canonical continuation', '1:C,A;1:B;2:d', undefined, { 1: 'A,B,C', 2: 'D' }],
  ['canonical separators', '①＝B;②:C', undefined, { '②': 'C' }],
  ['canonical fullwidth', '①：b，c；②=Ⅶ', undefined, { '①': 'B,C', '②': 'Ⅶ' }],
  ['canonical reset at newline', 'x:A\nB;y:C', undefined, { x: 'A', y: 'C' }],
  ['canonical beats markers', '①B;x:C', undefined, { x: 'C' }],
  ['circled beats parenthesized', '①B、(1)D', undefined, { '①': 'B' }],
  ['parenthesized beats Chinese', '(1)B、第2空D', undefined, { 1: 'B' }],
  ['circled repeated slot overwrites', '①B、①D', undefined, { '①': 'D' }],
  ['circled multi keys', '①A,C、②Ⅶ', undefined, { '①': 'A,C', '②': 'Ⅶ' }],
  ['parenthesized forms', '（1）b、(2)D', undefined, { 1: 'B', 2: 'D' }],
  ['Chinese ordinal forms', '第一空B，第2空D', undefined, { '一': 'B', 2: 'D' }],
  ['multi-character key stays whole', '①AC、②VII', undefined, { '①': 'AC', '②': 'VII' }],
  ['positional explicit ids', 'b,d', [' x ', 'y'], { x: 'B', y: 'D' }],
  ['positional compact', 'BAD', ['1', '2', '3'], { 1: 'B', 2: 'A', 3: 'D' }],
  ['positional invalid compact', 'IX', ['1', '2'], {}],
  ['positional untrusted ids', 'A,B', '1,2', {}],
  ['positional filtered ids', 'A,B', ['', 0, 'x', ' y '], { x: 'A', y: 'B' }],
  ['positional duplicate ids overwrite', 'A,B', ['x', 'x'], { x: 'B' }],
  ['positional count mismatch', 'A', ['x', 'y'], {}],
  ['unrecognized colon blocks positional', 'x:', ['x'], {}],
]

for (const [name, input, ids, expected] of blankCases) {
  test(`blank normalization preserves ${name}`, () => {
    assert.deepEqual(answer.normalizeBlankAnswer(input, ids), expected)
  })
}

test('primitive coercion and callback failures preserve their original error objects', () => {
  assert.deepEqual(answer.normalizeBlankAnswer(12), {})
  assert.deepEqual(answer.normalizeBlankAnswer(Symbol('empty')), {})
  const failure = new Error('answer coercion')
  function input() {}
  input[Symbol.toPrimitive] = hint => {
    assert.equal(hint, 'string')
    throw failure
  }
  assert.throws(() => answer.normalizeBlankAnswer(input), error => error === failure)
  const ids = []
  Object.defineProperty(ids, 'map', { get() { throw failure } })
  assert.deepEqual(answer.normalizeBlankAnswer('x:A', ids), { x: 'A' })
  assert.deepEqual(answer.normalizeBlankAnswer('①B', ids), { '①': 'B' })
  assert.throws(() => answer.normalizeBlankAnswer('unrecognized', ids), error => error === failure)
})

test('positional ids keep callback receiver, conversion order and exceptions', () => {
  const events = []
  const ids = ['x', { toString() { events.push('coerce'); return ' y ' } }]
  ids.map = function (callback) {
    assert.equal(this, ids)
    events.push('map')
    return Array.prototype.map.call(this, callback)
  }
  assert.deepEqual(answer.normalizeBlankAnswer('B,A', ids), { x: 'B', y: 'A' })
  assert.deepEqual(events, ['map', 'coerce'])
  const failure = new Error('slot coercion')
  ids[1] = { toString() { throw failure } }
  assert.throws(() => answer.normalizeBlankAnswer('B,A', ids), error => error === failure)
})

test('ordinary object prototype behavior remains intact for special slot names', () => {
  const result = answer.normalizeBlankAnswer('__proto__:A;constructor:B')
  assert.equal(Object.getPrototypeOf(result), Object.prototype)
  assert.equal(Object.hasOwn(result, '__proto__'), false)
  assert.match(result.constructor, /^B,FUNCTION OBJECT/)
})

test('serialization order and local grading ignore exported normalizer replacement', t => {
  const original = answer.normalizeBlankAnswer
  t.after(() => { answer.normalizeBlankAnswer = original })
  const calls = []
  answer.normalizeBlankAnswer = (...args) => { calls.push(args); return { x: ' a ' } }
  assert.equal(answer.isAnswerCorrect('1:A', '1:A', 'multi_blank_choice'), true)
  assert.deepEqual(calls, [])
  const adapter = require('../subpackages/study/utils/question-runner-adapter')
  const ids = ['x']
  assert.deepEqual(adapter.normalizeBlankAnswer('raw', ids), { x: 'A' })
  assert.deepEqual(calls, [['raw', ids]])
  assert.equal(calls[0][1], ids)
  assert.equal(answer.serializeBlankAnswer([{ id: 'y' }, { id: 'x' }],
    { x: 'c,a', y: 'b' }), 'y:B;x:A,C')
})

test('grading keeps null, multi-select equality, extra-slot and true-false rules', () => {
  assert.equal(answer.isAnswerCorrect('', 'A', 'single_choice'), null)
  assert.equal(answer.isAnswerCorrect('1:C,A', '1:A,C', 'multi_blank_multiple_choice'), true)
  assert.equal(answer.isAnswerCorrect('1:A;2:B', '1:A', 'multi_blank_choice'), false)
  assert.equal(answer.isAnswerCorrect('1:A', '1:A,C', 'multi_blank_multiple_choice'), false)
  assert.equal(answer.isAnswerCorrect('yes', 'A', 'true_false'), true)
  assert.equal(answer.serializeChoiceAnswer('CBAC'), 'A,B,C')
})
