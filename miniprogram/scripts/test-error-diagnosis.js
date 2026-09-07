/**
 * 408-ERROR regression checks.
 *
 * Covers the stable V1 taxonomy and verifies that result/detail pages keep
 * occurrence-level diagnosis_id when confirming an error cause.
 */
/* eslint-disable no-console */
const assert = require('assert')
const fs = require('fs')
const path = require('path')

const diagnosis = require('../utils/error-diagnosis')

const EXPECTED_TYPES = [
  'knowledge_gap',
  'concept_confusion',
  'memory_error',
  'calculation_error',
  'misread',
  'reasoning_error',
  'time_pressure',
  'careless',
  'unknown',
]

assert.deepStrictEqual(diagnosis.TAXONOMY.map(item => item.type), EXPECTED_TYPES)
assert.strictEqual(diagnosis.normalizeType('concept_mistake'), 'concept_confusion')
assert.strictEqual(diagnosis.normalizeType('method'), 'reasoning_error')
assert.strictEqual(diagnosis.normalizeType('not-a-type'), 'unknown')

const normalized = diagnosis.normalizeDiagnosis({
  id: 17,
  primary_type: 'careless',
  secondary_types: ['misread', 'careless', 'unknown', 'misread'],
  ai_primary_type: 'concept_confusion',
  ai_secondary_types: ['memory_error'],
  ai_confidence: 0.84,
})
assert.strictEqual(normalized.id, 17)
assert.strictEqual(normalized.primaryType, 'careless')
assert.deepStrictEqual(normalized.secondaryTypes, ['misread'])
assert.strictEqual(normalized.aiPrimaryType, 'concept_confusion')
assert.strictEqual(normalized.aiConfidence, 84)

function source(rel) {
  return fs.readFileSync(path.resolve(__dirname, '..', rel), 'utf8')
}

for (const rel of [
  'subpackages/study/practice-result/index.js',
  'subpackages/exam/result/index.js',
  'subpackages/study/wrong-detail/wrong-detail.js',
]) {
  const text = source(rel)
  assert.ok(text.includes('/diagnosis'), `${rel} should call diagnosis API`)
  assert.ok(text.includes('diagnosis_id'), `${rel} should preserve occurrence diagnosis_id`)
}

const dashboard = source('pages/dashboard/dashboard.js')
assert.ok(dashboard.includes('/wrong-questions/diagnosis/stats'))
assert.ok(dashboard.includes("product_scope: 'exam408'"))

console.log('408-ERROR miniprogram regression checks passed')
