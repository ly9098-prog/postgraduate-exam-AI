const assert = require('assert')
const {
  normalizeAiAnalysisPayload,
  hasAiAnalysisContent,
} = require('../subpackages/study/utils/ai-analysis-normalizer')

function assertFields(actual, expected, message) {
  assert.strictEqual(actual.mistake_diagnosis, expected.mistake_diagnosis, message + ': diagnosis')
  assert.strictEqual(actual.knowledge_patch, expected.knowledge_patch, message + ': knowledge')
  assert.strictEqual(actual.review_task, expected.review_task, message + ': task')
  if (expected.formatError) {
    assert.strictEqual(actual.formatError, true, message + ': expected formatError')
  } else {
    assert.ok(!actual.formatError, message + ': should not set formatError')
  }
  if (expected.hasContent !== false) {
    assert.strictEqual(hasAiAnalysisContent(actual), true, message + ': has content')
  } else {
    assert.strictEqual(hasAiAnalysisContent(actual), false, message + ': empty content')
  }
}

const diagnosis = '把最坏时间复杂度写成了 $O(n)$，忽略了最内层循环。'
const knowledge = '两层循环且与输入规模线性相关时，复杂度是 $O(n^2)$。'
const task = '默写该算法的循环不变式，并再做一题同类复杂度证明。'

// 1. Standard FastAPI AiResponse with content wrapper and _meta.
const aiResponse = {
  session_type: 'error_analysis',
  content: {
    mistake_diagnosis: diagnosis,
    knowledge_patch: knowledge,
    review_task: task,
    _meta: {
      model: 'qwen3.8-max',
      generated_at: '2026-09-16T12:51:21Z',
      input_mode: 'text',
    },
  },
  model: 'qwen3.8-max',
  tokens_used: 88,
  from_cache: false,
  from_fallback: false,
  generated_at: '2026-09-16T12:51:21Z',
}
assertFields(normalizeAiAnalysisPayload(aiResponse), {
  mistake_diagnosis: diagnosis,
  knowledge_patch: knowledge,
  review_task: task,
}, 'standard AiResponse')

// 2. Stored wrong-question ai_analysis dict with LaTeX.
const stored = {
  mistake_diagnosis: '漏掉了哈希冲突链，误以为查找一定是 $O(1)$。',
  knowledge_patch: '拉链法平均 $O(1)$，最坏仍可能到 $O(n)$。',
  review_task: '画一张冲突链，标出成功/失败查找的比较次数。',
  _meta: { model: 'cache', generated_at: '2026-09-16T10:00:00Z' },
}
assertFields(normalizeAiAnalysisPayload(stored), {
  mistake_diagnosis: stored.mistake_diagnosis,
  knowledge_patch: stored.knowledge_patch,
  review_task: stored.review_task,
}, 'stored wq.ai_analysis')

// 3. Prose that happens to contain quoted analysis keys must not be emptied.
const quotedProse = {
  mistake_diagnosis: '把进程和线程的 "task": 概念当成了 JSON 字段。',
  knowledge_patch: '教材里的 "knowledge": 调度队列只是术语，不是响应体。',
  review_task: '对照 "diagnosis": 无关的 PCB 字段，写清进程/线程差异。',
}
assertFields(normalizeAiAnalysisPayload(quotedProse), quotedProse, 'quoted analysis keys in prose')
assertFields(normalizeAiAnalysisPayload(quotedProse.mistake_diagnosis), {
  mistake_diagnosis: quotedProse.mistake_diagnosis,
  knowledge_patch: '',
  review_task: '',
}, 'string payload with quoted key')

// 4. Set notation / leading brace that is not valid JSON.
const setNotation = '{1,2,3} 表示集合，不是 JSON 对象。'
assertFields(normalizeAiAnalysisPayload({
  mistake_diagnosis: setNotation,
  knowledge_patch: '集合用花括号，对象才用键值对。',
  review_task: '写出 {a,b} 与 {"a":1} 的区别。',
}), {
  mistake_diagnosis: setNotation,
  knowledge_patch: '集合用花括号，对象才用键值对。',
  review_task: '写出 {a,b} 与 {"a":1} 的区别。',
}, 'set notation fields')
assertFields(normalizeAiAnalysisPayload(setNotation), {
  mistake_diagnosis: setNotation,
  knowledge_patch: '',
  review_task: '',
}, 'set notation string payload')

// 5. Truncated fenced analysis JSON should be a format error, not fake prose.
const truncated = '```json\n{ "mistake_diagnosis": "只写了一半'
const truncatedResult = normalizeAiAnalysisPayload(truncated)
assertFields(truncatedResult, {
  mistake_diagnosis: '',
  knowledge_patch: '',
  review_task: '',
  formatError: true,
  hasContent: false,
}, 'truncated fenced analysis JSON')

// 6. Double-encoded full analysis JSON inside one field.
const nestedJson = JSON.stringify({
  mistake_diagnosis: diagnosis,
  knowledge_patch: knowledge,
  review_task: task,
})
assertFields(normalizeAiAnalysisPayload({
  mistake_diagnosis: '```json\n' + nestedJson + '\n```',
}), {
  mistake_diagnosis: diagnosis,
  knowledge_patch: knowledge,
  review_task: task,
}, 'double-encoded analysis JSON in one field')

// 7. Extra content wrapper must not steal parent analysis fields.
assertFields(normalizeAiAnalysisPayload({
  mistake_diagnosis: diagnosis,
  knowledge_patch: knowledge,
  review_task: task,
  content: { text: '这段摘要不该覆盖三字段' },
}), {
  mistake_diagnosis: diagnosis,
  knowledge_patch: knowledge,
  review_task: task,
}, 'parent fields win over extra content wrapper')

assertFields(normalizeAiAnalysisPayload({
  content: { text: '只有包装层正文' },
}), {
  mistake_diagnosis: '只有包装层正文',
  knowledge_patch: '',
  review_task: '',
}, 'text wrapper fallback')

// 8. Array payload and fenced JSON.
assertFields(normalizeAiAnalysisPayload([
  { note: 'ignore' },
  { mistake_diagnosis: diagnosis, knowledge_patch: knowledge, review_task: task },
]), {
  mistake_diagnosis: diagnosis,
  knowledge_patch: knowledge,
  review_task: task,
}, 'array payload picks analysis object')

assertFields(normalizeAiAnalysisPayload(['先看循环层数', '再写复杂度']), {
  mistake_diagnosis: '先看循环层数\n再写复杂度',
  knowledge_patch: '',
  review_task: '',
}, 'array of prose')

assertFields(normalizeAiAnalysisPayload('```json\n' + nestedJson + '\n```'), {
  mistake_diagnosis: diagnosis,
  knowledge_patch: knowledge,
  review_task: task,
}, 'fenced JSON string')

// 9. Old API-spec aliases.
assertFields(normalizeAiAnalysisPayload({
  error_analysis: diagnosis,
  knowledge_weakness: knowledge,
  suggestion: task,
}), {
  mistake_diagnosis: diagnosis,
  knowledge_patch: knowledge,
  review_task: task,
}, 'legacy aliases')

// JSON snippet inside prose must stay as diagnosis text, not be wiped.
const snippetProse = '复杂度不是 {"n": 1} 这种写法，而是 $O(n)$。'
assertFields(normalizeAiAnalysisPayload({
  mistake_diagnosis: snippetProse,
  knowledge_patch: knowledge,
  review_task: task,
}), {
  mistake_diagnosis: snippetProse,
  knowledge_patch: knowledge,
  review_task: task,
}, 'JSON snippet inside prose')

console.log('✓ AI analysis normalizer regression tests passed')
