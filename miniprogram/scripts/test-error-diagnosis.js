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
assert.ok(!dashboard.includes("product_scope: 'exam408'"), '学习报告错因统计不应再硬编码单一产品范围')

const wrongDetail = source('subpackages/study/wrong-detail/wrong-detail.js')
assert.ok(wrongDetail.includes('diagnosisAiEnabled: false'), '错因 AI 默认应关闭')
assert.ok(wrongDetail.includes('enableDiagnosisAi()'), '错因 AI 应提供手动开启')
assert.ok(wrongDetail.includes('disableDiagnosisAi()'), '错因 AI 应提供手动关闭')
const backendPractice = fs.readFileSync(path.resolve(__dirname, '..', '..', 'backend/app/services/practice_service.py'), 'utf8')
assert.ok(backendPractice.includes('queue_ai=False'), '新错题不应默认排队 AI 错因分析')

console.log('error-diagnosis miniprogram regression checks passed')
