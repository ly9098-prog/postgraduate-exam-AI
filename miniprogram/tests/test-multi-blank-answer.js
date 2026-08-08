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

/* ==================== Summary ==================== */

console.log('\n====================')
console.log('Passed:', passed)
console.log('Failed:', failed)
if (failed > 0) process.exit(1)
