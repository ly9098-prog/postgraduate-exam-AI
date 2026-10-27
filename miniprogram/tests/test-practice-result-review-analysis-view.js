const assert = require('node:assert/strict')
const { test } = require('node:test')

const {
  looksLikeStructuredReviewAnalysis,
  containsRawAnalysisJson,
  formatReviewAnalysisText,
  buildReadableReviewParagraphs,
  extractGenericReviewAnalysis,
  buildReviewAnalysisView,
} = require('../subpackages/study/practice-result/utils/review-analysis-view')

test('looksLikeStructuredReviewAnalysis detects objects, fences and known keys', () => {
  assert.equal(looksLikeStructuredReviewAnalysis({ mistake_diagnosis: 'x' }), true)
  assert.equal(looksLikeStructuredReviewAnalysis('{"a":1}'), true)
  assert.equal(looksLikeStructuredReviewAnalysis('```json\n{"a":1}\n```'), true)
  assert.equal(looksLikeStructuredReviewAnalysis('"mistake_diagnosis": 错因'), true)
  assert.equal(looksLikeStructuredReviewAnalysis([{ a: 1 }]), true)
  assert.equal(looksLikeStructuredReviewAnalysis('普通解析文本'), false)
  assert.equal(looksLikeStructuredReviewAnalysis('[1,2]'), false)
})

test('containsRawAnalysisJson only matches serialised analysis payloads', () => {
  assert.equal(containsRawAnalysisJson('{"mistake_diagnosis":"x"}'), true)
  assert.equal(containsRawAnalysisJson('"错因诊断":需要复习'), true)
  assert.equal(containsRawAnalysisJson('普通解析'), false)
  assert.equal(containsRawAnalysisJson({ mistake_diagnosis: 'x' }), false)
})

test('formatReviewAnalysisText drops raw payloads and formats readable lines', () => {
  assert.equal(formatReviewAnalysisText('{"mistake_diagnosis":"x"}'), '')
  assert.equal(formatReviewAnalysisText('第一行\n第二行'), '第一行\n第二行')
  assert.equal(formatReviewAnalysisText('\\(x^2\\)'), 'x²')
  assert.equal(formatReviewAnalysisText('  '), '')
  assert.equal(formatReviewAnalysisText(42), '42')
  assert.equal(
    formatReviewAnalysisText('```json\n{"analysis":"解析"}\n```'),
    '```json\n{"analysis":"解析"}\n```',
  )
})

test('buildReadableReviewParagraphs splits long paragraphs on sentence boundaries', () => {
  assert.deepEqual(buildReadableReviewParagraphs('短句。'), ['短句。'])
  assert.deepEqual(buildReadableReviewParagraphs('第一段\n第二段'), ['第一段', '第二段'])
  const paragraphs = buildReadableReviewParagraphs(
    '这是一个较长的段落，用于检查自动分段行为是否保持原样。'.repeat(6),
  )
  assert.equal(paragraphs.length, 3)
  assert.equal(paragraphs[0].length, 54)
  assert.deepEqual(buildReadableReviewParagraphs(''), [])
  assert.deepEqual(buildReadableReviewParagraphs(null), [])
})

test('extractGenericReviewAnalysis walks known keys, arrays and fenced JSON', () => {
  assert.equal(extractGenericReviewAnalysis({ analysis: '解析内容' }), '解析内容')
  assert.equal(extractGenericReviewAnalysis({ explanation: '解释' }), '解释')
  assert.equal(extractGenericReviewAnalysis({ nested: { analysis: '深层解析' } }), '')
  assert.equal(extractGenericReviewAnalysis(['一', { analysis: '二' }]), '一\n二')
  assert.equal(extractGenericReviewAnalysis('{"analysis":"围栏外"}'), '围栏外')
  assert.equal(extractGenericReviewAnalysis('```json\n{"analysis":"围栏内"}\n```'), '围栏内')
  assert.equal(extractGenericReviewAnalysis('普通文本'), '')
})

test('extractGenericReviewAnalysis stops below the depth guard', () => {
  const deep = { analysis: { analysis: { analysis: { analysis: { analysis: '太深' } } } } }
  assert.equal(extractGenericReviewAnalysis(deep, 0), '太深')
  assert.equal(extractGenericReviewAnalysis(deep, 5), '')
})

test('buildReviewAnalysisView keeps the structured section order and tones', () => {
  assert.deepEqual(
    buildReviewAnalysisView({ mistake_diagnosis: '错因', knowledge_patch: '补漏', review_task: '复练' }),
    {
      sections: [
        { key: 'mistake_diagnosis', title: '解析要点', tone: 'primary', text: '错因', paragraphs: [{ key: 'mistake_diagnosis-0', text: '错因' }] },
        { key: 'knowledge_patch', title: '知识补充', tone: 'knowledge', text: '补漏', paragraphs: [{ key: 'knowledge_patch-0', text: '补漏' }] },
        { key: 'review_task', title: '复习建议', tone: 'task', text: '复练', paragraphs: [{ key: 'review_task-0', text: '复练' }] },
      ],
      formatError: false,
    },
  )
})

test('buildReviewAnalysisView falls back to a single analysis section for plain text', () => {
  assert.deepEqual(buildReviewAnalysisView('普通解析文本'), {
    sections: [{
      key: 'analysis',
      title: '题目解析',
      tone: 'primary',
      text: '普通解析文本',
      paragraphs: [{ key: 'analysis-0', text: '普通解析文本' }],
    }],
    formatError: false,
  })
  assert.deepEqual(buildReviewAnalysisView(''), { sections: [], formatError: false })
  assert.deepEqual(buildReviewAnalysisView(null), { sections: [], formatError: false })
})

test('buildReviewAnalysisView reports a format error when structured content is empty', () => {
  assert.deepEqual(buildReviewAnalysisView({ mistake_diagnosis: '' }), { sections: [], formatError: true })
  assert.deepEqual(buildReviewAnalysisView({ formatError: true }), { sections: [], formatError: true })
  assert.deepEqual(buildReviewAnalysisView([{ analysis: '' }]), { sections: [], formatError: true })
})
