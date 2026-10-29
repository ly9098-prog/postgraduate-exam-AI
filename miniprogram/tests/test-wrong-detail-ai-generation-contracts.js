const assert = require('node:assert/strict')
const { test } = require('node:test')
const { fixture, deferred } = require('./helpers/wrong-detail-ai-recovery-fixture')
const plain = value => JSON.parse(JSON.stringify(value))

function setup() {
  const f = fixture()
  f.context.console = { error: (...args) => f.calls.push(['error', ...args]) }
  return f
}

test('generation guards missing identity and current loading without side effects', async () => {
  const f = setup()
  await f.page.loadAiAnalysis(0)
  f.page.data.aiLoading = true
  await f.page.loadAiAnalysis(12)
  assert.equal(f.page._aiRequestId, 7)
  assert.deepEqual(f.calls, [])
})

test('generation captures baseline before loading and resolves response helpers after await', async () => {
  const f = setup(), pending = deferred(), { page } = f
  page._aiGenerationMarker = 'old'
  page._requestAiAnalysis = function (...args) {
    assert.equal(this, page)
    f.calls.push(['request', ...args])
    return pending.promise
  }
  const result = { content: 'response' }
  const request = page.loadAiAnalysis(12)
  assert.equal(page._aiRequestId, 8)
  assert.deepEqual(plain(f.calls[0][1]), {
    aiLoading: true, aiRequested: true, aiFallback: false,
    aiErrorText: '', aiRetryable: true, aiInlineNotice: '',
  })
  page._aiGenerationMarker = 'changed'
  page._applyAiAnalysisResult = function (...args) {
    assert.equal(this, page)
    f.calls.push(['late-apply', ...args])
  }
  pending.resolve(result)
  await request
  assert.deepEqual(f.calls.slice(1), [
    ['request', 12, false], ['late-apply', result, 12, 8, 'old'],
  ])
})

test('generation retains question marker fallback and stale-response loading reset', async () => {
  const f = setup(), pending = deferred(), { page } = f
  page.data.wq.ai_analysis_generated_at = 17
  page._requestAiAnalysis = () => pending.promise
  page._applyAiAnalysisResult = () => { throw new Error('stale response applied') }
  const request = page.loadAiAnalysis(12)
  page._alive = false
  pending.resolve({ content: 'late' })
  await request
  assert.deepEqual(f.calls.map(call => call[0]), ['setData', 'reset', 'setData'])
  assert.equal(page.data.aiLoading, false)
  assert.equal(page._aiRequestId, 8)
})

test('generation awaits current error handler for request and application failures', async () => {
  for (const phase of ['request', 'application']) {
    const f = setup(), pending = deferred(), entered = deferred(), { page } = f
    const error = new Error(phase)
    page.data.wq.ai_analysis_generated_at = 17
    page._requestAiAnalysis = async () => {
      if (phase === 'request') throw error
      return { content: 'ready' }
    }
    page._applyAiAnalysisResult = () => { throw error }
    page._handleAiAnalysisError = function (...args) {
      assert.equal(this, page)
      f.calls.push(['handle', ...args])
      entered.resolve()
      return pending.promise
    }
    let settled = false
    const request = page.loadAiAnalysis(12).then(() => { settled = true })
    await entered.promise
    assert.equal(settled, false)
    assert.deepEqual(f.calls.at(-1), ['handle', error, 12, 8, '17'])
    pending.resolve()
    await request
    assert.equal(settled, true)
  }
})

test('generating result prioritizes persisted recovery even when fallback is set', async () => {
  const f = setup(), { page } = f, recovered = { normalized: { content: 'ready' } }
  page._pollPersistedAiAnalysis = async (...args) => {
    f.calls.push(['poll', ...args])
    return recovered
  }
  page._applyRecoveredAiResult = value => {
    assert.equal(value, recovered)
    f.calls.push(['recover'])
    return true
  }
  await page._applyAiAnalysisResult({ model: 'generating', from_fallback: true }, 12, 7, 'old')
  assert.deepEqual(plain(f.calls), [
    ['poll', 12, 7, { requireNewGeneration: true, baselineGeneratedAt: 'old' }],
    ['recover'],
  ])
})

test('generating result exhaustion resets loading only for the current request', async () => {
  for (const stale of [false, true]) {
    const f = setup(), { page } = f
    page._pollPersistedAiAnalysis = async () => {
      if (stale) page._aiRequestId++
      return null
    }
    await page._applyAiAnalysisResult({ model: 'generating' }, 12, 7, '')
    assert.equal(f.calls.length, stale ? 0 : 3)
    if (!stale) assert.deepEqual(plain(f.calls.at(-1)), [
      'setData', { aiFallback: true, aiErrorText: 'AI 分析正在生成中，请稍后重试' },
    ])
  }
})

test('fallback result preserves failure helper receiver and patch override order', async () => {
  const f = setup(), { page } = f
  const result = { content: 'has content', model: 'timeout', from_fallback: true }
  page._analysisFailureState = function (model, value) {
    assert.equal(this, page)
    assert.equal(model, 'timeout')
    assert.equal(value, result)
    f.calls.push(['failure'])
    return { aiFallback: false, aiErrorText: 'custom', aiRetryable: false }
  }
  await page._applyAiAnalysisResult(result, 12, 7, '')
  assert.deepEqual(f.calls.map(call => call[0]), ['reset', 'setData', 'failure', 'setData'])
  assert.deepEqual(plain(f.calls.at(-1)[1]), {
    aiFallback: false, aiErrorText: 'custom', aiRetryable: false,
  })
})

test('empty result resets and reports empty while usable results call current commit helper', async () => {
  const f = setup(), { page } = f
  await page._applyAiAnalysisResult(null, 12, 7, '')
  assert.deepEqual(plain(f.calls.at(-1)[1]), {
    aiFallback: true, aiErrorText: 'AI 分析结果为空，请稍后重试',
  })
  const result = { content: 'ready' }
  page._commitAiAnalysisSuccess = function (...args) {
    assert.equal(this, page)
    f.calls.push(['commit', ...args])
  }
  await page._applyAiAnalysisResult(result, 12, 7, '')
  assert.deepEqual(f.calls.at(-1), ['commit', result, result, 12])
})

test('success preserves private state, marker fallback, cache order and card fields', () => {
  for (const generatedAt of ['', 0, 'new']) {
    const f = setup(), { page } = f, normalized = { content: 'ready' }
    page._aiGenerationMarker = 'old'
    page._syncWqCacheAi = function (...args) {
      assert.equal(this, page)
      assert.equal(this._aiResult, normalized)
      assert.equal(this._aiGenerationMarker, generatedAt || 'old')
      f.calls.push(['cache', ...args])
    }
    page._commitAiAnalysisSuccess({ generated_at: generatedAt, from_cache: true }, normalized, 12)
    assert.deepEqual(f.calls.map(call => call[0]), ['reset', 'setData', 'cache', 'setData'])
    assert.deepEqual(f.calls[2], ['cache', 12, normalized, generatedAt || 'old'])
    assert.deepEqual(plain(f.calls.at(-1)[1]), {
      aiCards: { mistakeDiagnosis: '', knowledgePatch: '', reviewTask: '', formatError: false },
      aiFallback: false, aiFromCache: true, aiFromQuestionAnalysis: false,
      aiErrorText: '', aiRetryable: true,
    })
  }
})

test('generation error enqueues without waiting and applies late recovery helper', async () => {
  const f = setup(), { page } = f, pending = deferred(), recovered = { content: 'ready' }
  const error = new Error('timeout')
  page._enqueueAiRecovery = function (...args) {
    assert.equal(this, page)
    f.calls.push(['enqueue', ...args])
    return new Promise(() => {})
  }
  page._pollPersistedAiAnalysis = (...args) => {
    f.calls.push(['poll', ...args])
    return pending.promise
  }
  const request = page._handleAiAnalysisError(error, 12, 7, 'baseline')
  page._applyRecoveredAiResult = function (value) {
    assert.equal(this, page)
    assert.equal(value, recovered)
    f.calls.push(['recovered'])
    return true
  }
  pending.resolve(recovered)
  await request
  assert.deepEqual(plain(f.calls.slice(1)), [
    ['setData', { aiInlineNotice: 'AI 正在继续生成，完成后会自动显示' }],
    ['enqueue', 12, false, ''],
    ['poll', 12, 7, { requireNewGeneration: true, baselineGeneratedAt: 'baseline' }],
    ['recovered'],
  ])
  assert.equal(f.calls[0][2], error)
})

test('generation error exhaustion chooses timeout text and suppresses stale final writes', async () => {
  for (const [error, stale, expected] of [
    [new Error('timed out'), false, 'AI 分析生成超时，请稍后重试'],
    [new Error('offline'), false, 'AI 分析生成失败，请稍后重试'],
    [new Error('offline'), true, null],
  ]) {
    const f = setup(), { page } = f
    page._enqueueAiRecovery = () => {}
    page._pollPersistedAiAnalysis = async () => { if (stale) page._alive = false; return null }
    await page._handleAiAnalysisError(error, 12, 7, '')
    if (expected) assert.deepEqual(plain(f.calls.at(-1)[1]), {
      aiFallback: true, aiErrorText: expected,
    })
    else assert.deepEqual(f.calls.map(call => call[0]), ['error', 'setData'])
  }
})

test('stale generation error only logs and error handler rejection propagates', async () => {
  const f = setup(), { page } = f
  page._alive = false
  await page._handleAiAnalysisError(new Error('old'), 12, 7, '')
  assert.deepEqual(f.calls.map(call => call[0]), ['error'])
  const fatal = new Error('handler failed')
  page._alive = true
  page._requestAiAnalysis = async () => { throw new Error('request failed') }
  page._handleAiAnalysisError = async () => { throw fatal }
  await assert.rejects(page.loadAiAnalysis(12), error => error === fatal)
})
