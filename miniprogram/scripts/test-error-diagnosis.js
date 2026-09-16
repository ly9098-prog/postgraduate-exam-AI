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

const diagnosis = require('../subpackages/study/utils/error-diagnosis')

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

// Persisted diagnosis compatibility: direct, wrapped, legacy, and empty response shapes.
const wrapped = diagnosis.normalizeDiagnosis({
  diagnosis: { id: 18, primary_type: 'misread', user_confirmed: true, effective_source: 'user' },
})
assert.strictEqual(wrapped.id, 18)
assert.strictEqual(wrapped.primaryType, 'misread')
assert.strictEqual(wrapped.userConfirmed, true)

const dataWrapped = diagnosis.normalizeDiagnosis({
  data: { id: 19, primary_type: 'calculation', effective_source: 'user' },
})
assert.strictEqual(dataWrapped.primaryType, 'calculation_error')
assert.strictEqual(dataWrapped.userConfirmed, true)

const legacySaved = diagnosis.normalizeDiagnosis({ id: 20, primary_type: 'concept_mistake' })
assert.strictEqual(legacySaved.primaryType, 'concept_confusion')
assert.strictEqual(legacySaved.userConfirmed, true)

const userSourcedFalseFlag = diagnosis.normalizeDiagnosis({
  id: 21, primary_type: 'careless', user_confirmed: false, effective_source: 'user',
})
assert.strictEqual(userSourcedFalseFlag.userConfirmed, true)

const aiOnly = diagnosis.normalizeDiagnosis({
  id: 22, primary_type: 'concept_confusion', user_confirmed: false, effective_source: 'ai',
})
assert.strictEqual(aiOnly.userConfirmed, false)
assert.strictEqual(diagnosis.normalizeDiagnosis({ success: true }), null)

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
assert.ok(wrongDetail.includes('_refreshDiagnosisFromServer'), '错因详情应从持久化 diagnosis 接口回显')
assert.ok(wrongDetail.includes('/wrong-questions/${id}/diagnosis'), '错因详情应读取 occurrence 级 diagnosis')
assert.ok(!wrongDetail.includes('/diagnosis/suggest'), '我的错因区域不应再发起 AI 推荐请求')
assert.ok(!wrongDetail.includes('enableDiagnosisAi()'), '我的错因区域不应再暴露 AI 推荐开关')
const wrongDetailWxml = source('subpackages/study/wrong-detail/wrong-detail.wxml')
assert.ok(!wrongDetailWxml.includes('AI 推荐'), '我的错因 UI 不应再展示 AI 推荐')
assert.ok(wrongDetailWxml.includes('circle-question-mark.svg'), '未记录错因应使用问号状态图标')
assert.ok(wrongDetailWxml.includes('badge-check.svg'), '已记录错因应使用确认状态图标')
assert.ok(wrongDetailWxml.includes('circle-arrow-right.svg'), 'Next Action 应使用图标入口')
const backendPath = path.resolve(__dirname, '..', '..', 'backend/app/services/practice_service.py')
if (fs.existsSync(backendPath)) {
  const backendPractice = fs.readFileSync(backendPath, 'utf8')
  assert.ok(backendPractice.includes('queue_ai=False'), '新错题不应默认排队 AI 错因分析')
}

console.log('error-diagnosis miniprogram regression checks passed')
