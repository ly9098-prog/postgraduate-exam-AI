/**
 * Tests for multi-blank choice answer utilities.
 *
 * Run: node tests/test-multi-blank-answer.js
 */

var {
  normalizeBlankAnswer,
  serializeBlankAnswer,
  isAnswerCorrect,
  isMultiBlankType,
  isMultiBlankMultipleType,
} = require('../subpackages/study/utils/answer')

var passed = 0
var failed = 0

function assert(condition, msg) {
  if (condition) { passed++; return }
  failed++
  console.error('  FAIL:', msg)
}

function assertEq(actual, expected, msg) {
  if (actual === expected) { passed++; return }
  failed++
  console.error('  FAIL:', msg)
  console.error('    expected:', JSON.stringify(expected))
  console.error('    actual:  ', JSON.stringify(actual))
}

function assertDeepEq(actual, expected, msg) {
  var a = JSON.stringify(actual)
  var e = JSON.stringify(expected)
  if (a === e) { passed++; return }
  failed++
  console.error('  FAIL:', msg)
  console.error('    expected:', e)
  console.error('    actual:  ', a)
}

/* ==================== normalizeBlankAnswer ==================== */

console.log('\n=== normalizeBlankAnswer ===')

// Canonical format
assertDeepEq(normalizeBlankAnswer('①:B;②:D'), { '①': 'B', '②': 'D' }, 'canonical format')
assertDeepEq(normalizeBlankAnswer('①:B'), { '①': 'B' }, 'single blank canonical')
assertDeepEq(normalizeBlankAnswer(''), {}, 'empty string')
assertDeepEq(normalizeBlankAnswer(null), {}, 'null')
assertDeepEq(normalizeBlankAnswer(undefined), {}, 'undefined')
assertDeepEq(normalizeBlankAnswer({ a: 'B' }), { a: 'B' }, 'object passthrough')

// Chinese separator variants
assertDeepEq(normalizeBlankAnswer('①:B；②:D'), { '①': 'B', '②': 'D' }, 'Chinese semicolon')
assertDeepEq(normalizeBlankAnswer('①:B，②:D'), { '①': 'B', '②': 'D' }, 'Chinese comma')

// Lowercase → uppercase
assertDeepEq(normalizeBlankAnswer('①:b;②:d'), { '①': 'B', '②': 'D' }, 'lowercase to uppercase')

// Space tolerance
assertDeepEq(normalizeBlankAnswer('① : B ; ② : D'), { '①': 'B', '②': 'D' }, 'spaces around colon')

// Multi-character option keys (e.g. Roman numerals VII, III)
assertDeepEq(normalizeBlankAnswer('①:VII;②:III'), { '①': 'VII', '②': 'III' }, 'multi-char canonical')
assertDeepEq(normalizeBlankAnswer('①:VII;②:I'), { '①': 'VII', '②': 'I' }, 'mixed single+multi char')
assertDeepEq(normalizeBlankAnswer('①:V;②:VII'), { '①': 'V', '②': 'VII' }, 'V+VII multi-char')

// Unicode Roman numeral option keys
assertDeepEq(normalizeBlankAnswer('①:Ⅴ;②:Ⅶ'), { '①': 'Ⅴ', '②': 'Ⅶ' }, 'Unicode Roman numerals')
assertDeepEq(normalizeBlankAnswer('①:Ⅳ'), { '①': 'Ⅳ' }, 'single Unicode Roman IV')

// Non-canonical formats (fix for BUG-003)
assertDeepEq(normalizeBlankAnswer('①B、②D'), { '①': 'B', '②': 'D' }, 'Chinese comma circled format')
assertDeepEq(normalizeBlankAnswer('①B，②D'), { '①': 'B', '②': 'D' }, 'Chinese comma fullwidth')
assertDeepEq(normalizeBlankAnswer('（1）B、（2）D'), { '1': 'B', '2': 'D' }, 'parenthesized digits')
assertDeepEq(normalizeBlankAnswer('(1)B、(2)D'), { '1': 'B', '2': 'D' }, 'halfwidth paren digits')
assertDeepEq(normalizeBlankAnswer('第1空B，第2空D'), { '1': 'B', '2': 'D' }, 'Chinese natural language')

/* ==================== serializeBlankAnswer ==================== */

console.log('\n=== serializeBlankAnswer ===')

var groups = [
  { id: '①', options: [{ key: 'A' }, { key: 'B' }, { key: 'C' }, { key: 'D' }] },
  { id: '②', options: [{ key: 'A' }, { key: 'B' }, { key: 'C' }, { key: 'D' }] },
]

assertEq(serializeBlankAnswer(groups, { '①': 'B', '②': 'D' }), '①:B;②:D', 'serialize two blanks')
assertEq(serializeBlankAnswer(groups, { '①': 'B' }), '①:B', 'serialize one blank')
assertEq(serializeBlankAnswer(groups, {}), '', 'serialize empty map')
assertEq(serializeBlankAnswer(groups, null), '', 'serialize null map')
assertEq(serializeBlankAnswer([], { '①': 'B' }), '', 'serialize with empty groups')

// Multi-character option keys
assertEq(serializeBlankAnswer(groups, { '①': 'VII' }), '①:VII', 'serialize multi-char key')
assertEq(serializeBlankAnswer(groups, { '①': 'VII', '②': 'III' }), '①:VII;②:III', 'serialize two multi-char keys')

// Round-trip: serialize then normalize returns original map
var rtGroups = [
  { id: '①', options: [{ key: 'I' }, { key: 'II' }, { key: 'III' }, { key: 'IV' }, { key: 'V' }, { key: 'VI' }, { key: 'VII' }] },
  { id: '②', options: [{ key: 'I' }, { key: 'II' }, { key: 'III' }, { key: 'IV' }, { key: 'V' }, { key: 'VI' }, { key: 'VII' }] },
]
var rtSerialized = serializeBlankAnswer(rtGroups, { '①': 'VII', '②': 'III' })
assertEq(rtSerialized, '①:VII;②:III', 'round-trip serialize multi-char')
var rtParsed = normalizeBlankAnswer(rtSerialized)
assertDeepEq(rtParsed, { '①': 'VII', '②': 'III' }, 'round-trip normalize multi-char')

// Round-trip: mixed single + multi char
var rtMixed = serializeBlankAnswer(rtGroups, { '①': 'V', '②': 'VII' })
assertEq(rtMixed, '①:V;②:VII', 'round-trip serialize mixed char')
var rtMixedParsed = normalizeBlankAnswer(rtMixed)
assertDeepEq(rtMixedParsed, { '①': 'V', '②': 'VII' }, 'round-trip normalize mixed char')

// Same option on multiple blanks
assertEq(serializeBlankAnswer(groups, { '①': 'B', '②': 'B' }), '①:B;②:B', 'same option for both blanks')

// Order follows groups order
var reversedGroups = [
  { id: '②', options: [{ key: 'A' }, { key: 'B' }, { key: 'C' }, { key: 'D' }] },
  { id: '①', options: [{ key: 'A' }, { key: 'B' }, { key: 'C' }, { key: 'D' }] },
]
assertEq(serializeBlankAnswer(reversedGroups, { '①': 'B', '②': 'D' }), '②:D;①:B', 'serialize follows group order')

/* ==================== isAnswerCorrect (multi_blank_choice) ==================== */

console.log('\n=== isAnswerCorrect (multi_blank_choice) ===')

// All correct
assertEq(isAnswerCorrect('①:B;②:D', '①:B;②:D', 'multi_blank_choice'), true, 'all correct canonical')
// Order independent
assertEq(isAnswerCorrect('②:D;①:B', '①:B;②:D', 'multi_blank_choice'), true, 'order independent')
// Wrong value
assertEq(isAnswerCorrect('①:B;②:C', '①:B;②:D', 'multi_blank_choice'), false, 'wrong value for slot')
// Missing slot
assertEq(isAnswerCorrect('①:B', '①:B;②:D', 'multi_blank_choice'), false, 'missing slot')
// Empty user answer
assertEq(isAnswerCorrect('', '①:B;②:D', 'multi_blank_choice'), null, 'empty user answer')
// Empty standard answer
assertEq(isAnswerCorrect('①:B;②:D', '', 'multi_blank_choice'), null, 'empty standard answer')
// Both empty
assertEq(isAnswerCorrect('', '', 'multi_blank_choice'), null, 'both empty')
// Case insensitive
assertEq(isAnswerCorrect('①:b;②:d', '①:B;②:D', 'multi_blank_choice'), true, 'case insensitive')
// Same option for both blanks (perfectly valid)
assertEq(isAnswerCorrect('①:B;②:B', '①:B;②:B', 'multi_blank_choice'), true, 'same option for both blanks')

// Non-canonical normalized user answers (circled digit variants)
assertEq(isAnswerCorrect('①B、②D', '①:B;②:D', 'multi_blank_choice'), true, 'non-canonical user: Chinese comma with circled')
assertEq(isAnswerCorrect('① B，② D', '①:B;②:D', 'multi_blank_choice'), true, 'non-canonical user: space+comma')

// Non-canonical standard answer (should still work)
assertEq(isAnswerCorrect('①:B;②:D', '①B、②D', 'multi_blank_choice'), true, 'non-canonical standard: Chinese comma')

// Extra slot - should reject
assertEq(isAnswerCorrect('①:B;②:D;③:A', '①:B;②:D', 'multi_blank_choice'), false, 'extra slot rejected')

// Standard with more slots than user — user has missing slot, returns false
assertEq(isAnswerCorrect('①:B;②:D', '①:B;②:D;③:A', 'multi_blank_choice'), false, 'standard has more slots than user')

// Non-blank types unaffected
assertEq(isAnswerCorrect('B', 'B', 'single_choice'), true, 'single_choice unaffected')
assertEq(isAnswerCorrect('A,C', 'A,C', 'multiple_choice'), true, 'multiple_choice unaffected')
assertEq(isAnswerCorrect('A', 'B', 'single_choice'), false, 'single_choice wrong')

// Multi-character option keys
assertEq(isAnswerCorrect('①:VII;②:III', '①:VII;②:III', 'multi_blank_choice'), true, 'multi-char correct')
assertEq(isAnswerCorrect('①:V;②:VII', '①:V;②:VII', 'multi_blank_choice'), true, 'mixed V+VII correct')
assertEq(isAnswerCorrect('①:VII;②:II', '①:VII;②:III', 'multi_blank_choice'), false, 'multi-char wrong value (II≠III)')
assertEq(isAnswerCorrect('①:V;②:VII', '①:VII;②:V', 'multi_blank_choice'), false, 'multi-char swapped slots')

/* ==================== isMultiBlankType ==================== */

console.log('\n=== isMultiBlankType ===')

assertEq(isMultiBlankType('multi_blank_choice'), true, 'detects multi_blank_choice')
assertEq(isMultiBlankType('single_choice'), false, 'rejects single_choice')
assertEq(isMultiBlankType('multiple_choice'), false, 'rejects multiple_choice')
assertEq(isMultiBlankType('true_false'), false, 'rejects true_false')
assertEq(isMultiBlankType(''), false, 'rejects empty')
assertEq(isMultiBlankType(null), false, 'rejects null')

/* ==================== 多空（多选）选择题 ==================== */

console.log('\n=== normalizeBlankAnswer (multi-select values) ===')

assertDeepEq(normalizeBlankAnswer('①:A,C;②:B'), { '①': 'A,C', '②': 'B' }, 'multi-select canonical')
assertDeepEq(normalizeBlankAnswer('①:C,A;②:B'), { '①': 'A,C', '②': 'B' }, 'multi-select sorted canonical')
assertDeepEq(normalizeBlankAnswer('①AC、②D'), { '①': 'AC', '②': 'D' }, 'run-together kept as one key (multi-char key safety)')
assertDeepEq(normalizeBlankAnswer('1:A,C;2:B,D'), { '1': 'A,C', '2': 'B,D' }, 'multi-select digit slots')
assertDeepEq(normalizeBlankAnswer('①:B;②:D'), { '①': 'B', '②': 'D' }, 'single value unchanged')

console.log('\n=== serializeBlankAnswer (multi-select values) ===')

assertEq(serializeBlankAnswer(groups, { '①': 'A,C', '②': 'B' }), '①:A,C;②:B', 'serialize multi-select value')
assertEq(serializeBlankAnswer(groups, { '①': 'C,A', '②': 'B' }), '①:A,C;②:B', 'serialize multi-select sorted')

console.log('\n=== isAnswerCorrect (multi_blank_multiple_choice) ===')

assertEq(isAnswerCorrect('①:A,C;②:B', '①:C,A;②:B', 'multi_blank_multiple_choice'), true, 'multi-select order independent')
assertEq(isAnswerCorrect('①:I,III;②:VII', '①:III,I;②:VII', 'multi_blank_multiple_choice'), true, 'multi-select multi-char set compare')
assertEq(isAnswerCorrect('①:A;②:B', '①:A,C;②:B', 'multi_blank_multiple_choice'), false, 'multi-select missing letter')
assertEq(isAnswerCorrect('①:A,C,D;②:B', '①:A,C;②:B', 'multi_blank_multiple_choice'), false, 'multi-select extra letter')
assertEq(isAnswerCorrect('①:A,C;②:D', '①:A,C;②:B', 'multi_blank_multiple_choice'), false, 'multi-select wrong slot value')
assertEq(isAnswerCorrect('①:A,C;②:B', '①:A,C;②:B', 'multi_blank_multiple_choice'), true, 'multi-select exact')
assertEq(isAnswerCorrect('①:I,III;②:VII', '①:III,I;②:VII', 'multi_blank_multiple_choice'), true, 'multi-select roman numeral keys')

console.log('\n=== isMultiBlankType family ===')

assertEq(isMultiBlankType('multi_blank_multiple_choice'), true, 'family includes multi_blank_multiple_choice')
assertEq(isMultiBlankMultipleType('multi_blank_multiple_choice'), true, 'isMultiBlankMultipleType positive')
assertEq(isMultiBlankMultipleType('multi_blank_choice'), false, 'isMultiBlankMultipleType negative')

/* ==================== Runner adapter contract ==================== */

// practice.js / review-today.js both gate the in-blank multi-select toggle on
// `typeof adapter.isMultiBlankMultipleChoice === 'function'`. The helper existed
// but was never added to module.exports, so the guard silently took the
// single-select branch and every tap replaced the blank's answer instead of
// accumulating letters. Guard the export itself so that cannot regress.
console.log('\n=== runner adapter multi-blank exports ===')

var studyAdapter = require('../subpackages/study/utils/question-runner-adapter')
var examAdapter = require('../subpackages/exam/utils/question-runner-adapter')

assertEq(typeof studyAdapter.isMultiBlankMultipleChoice, 'function', 'study adapter exports isMultiBlankMultipleChoice')
assertEq(typeof examAdapter.isMultiBlankMultipleChoice, 'function', 'exam adapter exports isMultiBlankMultipleChoice')

// Only exercise the predicate once the export exists, so a missing export
// reports the assertions above rather than a raw TypeError stack.
if (typeof studyAdapter.isMultiBlankMultipleChoice === 'function') {
  assertEq(studyAdapter.isMultiBlankMultipleChoice({ question_type: 'multi_blank_multiple_choice' }), true, 'study adapter detects multi_blank_multiple_choice')
  assertEq(studyAdapter.isMultiBlankMultipleChoice({ question_type: 'multi_blank_choice' }), false, 'study adapter rejects multi_blank_choice')
}

var multiQ = {
  id: 1,
  question_type: 'multi_blank_multiple_choice',
  content: {
    blank_option_groups: [
      { id: '①', options: [{ key: 'A', text: '甲' }, { key: 'B', text: '乙' }, { key: 'C', text: '丙' }] },
      { id: '②', options: [{ key: 'A', text: '丁' }, { key: 'B', text: '戊' }] },
    ],
  },
}

// Mirror practice.js selectBlankOption so the accumulate/toggle behaviour is
// pinned at the same level the page implements it — including the
// `typeof adapter.x === 'function'` guard that made the missing export fail
// silently rather than throwing.
function tapBlankOption(prevAnswer, blankId, opt) {
  var blankAnswers = studyAdapter.normalizeBlankAnswer(prevAnswer)
  if (typeof studyAdapter.isMultiBlankMultipleChoice === 'function' && studyAdapter.isMultiBlankMultipleChoice(multiQ)) {
    var current = String(blankAnswers[blankId] || '').split(',').filter(Boolean)
    var next = current.indexOf(opt) >= 0
      ? current.filter(function (k) { return k !== opt })
      : current.concat([opt]).sort()
    if (next.length > 0) blankAnswers[blankId] = next.join(',')
    else delete blankAnswers[blankId]
  } else if (blankAnswers[blankId] === opt) {
    delete blankAnswers[blankId]
  } else {
    blankAnswers[blankId] = opt
  }
  return studyAdapter.serializeBlankAnswer(studyAdapter.getBlankOptionGroups(multiQ), blankAnswers)
}

var tapped = tapBlankOption('', '①', 'A')
tapped = tapBlankOption(tapped, '①', 'C')
assertEq(tapped, '①:A,C', 'second tap in the same blank accumulates instead of replacing')

tapped = tapBlankOption(tapped, '②', 'B')
assertEq(tapped, '①:A,C;②:B', 'independent blanks keep their own selections')

tapped = tapBlankOption(tapped, '①', 'A')
assertEq(tapped, '①:C;②:B', 're-tapping a selected letter deselects only that letter')

var enriched = studyAdapter.enrichBlankOptionGroups(studyAdapter.getBlankOptionGroups(multiQ), '①:A,C;②:B')
assertEq(enriched[0].options.filter(function (o) { return o._selected }).map(function (o) { return o.key }).join(''), 'AC', 'both letters in a multi-select blank render selected')
assertEq(enriched[1].options.filter(function (o) { return o._selected }).map(function (o) { return o.key }).join(''), 'B', 'sibling blank keeps a single selection')

/* ==================== Summary ==================== */

console.log('\n====================')
console.log('Passed:', passed)
console.log('Failed:', failed)
if (failed > 0) process.exit(1)
