const assert = require('node:assert/strict')
const { test } = require('node:test')
const { fixture, deferred } = require('./helpers/wrong-detail-ai-recovery-fixture')

test('current request predicate requires matching generation, live page and question', () => {
  const { page, methods } = fixture()
  assert.equal(methods._isCurrentAiRequest.call(page, 7, 12), true)
  assert.equal(methods._isCurrentAiRequest.call(page, 6, 12), false)
  page._alive = false
  assert.equal(methods._isCurrentAiRequest.call(page, 7, 12), false)
  page._alive = true
  page.data.wq = null
  assert.equal(methods._isCurrentAiRequest.call(page, 7, 12), null)
  page.data.wq = { id: '13' }
  assert.equal(methods._isCurrentAiRequest.call(page, 7, 12), false)
  page.data.wq = { id: '12' }
  assert.equal(methods._isCurrentAiRequest.call(page, 7, 12), true)
})

test('poll reads current API and returns normalized ready content with current question snapshot', async () => {
  const f = fixture(), { page } = f
  const pending = deferred(), content = { content: 'answer' }
  f.api.get = (...args) => { f.calls.push(['current-get', ...args]); return pending.promise }
  const request = page._pollPersistedAiAnalysis(12, 7, {})
  page.data.wq = { id: 12, latest: true }
  pending.resolve({ ready: true, generated_at: 77, content })
  const result = await request
  assert.equal(f.calls[0][0], 'current-get')
  assert.equal(f.calls[0][1], '/ai/error-analysis/status/12')
  assert.deepEqual({ ...f.calls[0][2] }, {})
  assert.deepEqual({ ...f.calls[0][3] }, {
    timeout: 10000, suppressNetworkToast: true,
  })
  assert.equal(result.normalized, content)
  assert.equal(result.generatedAt, '77')
  assert.deepEqual({ ...result.latestWq }, {
    id: 12, latest: true, ai_analysis: content,
    ai_analysis_status: 'ready', ai_analysis_generated_at: '77',
  })
})

test('poll requires a new generation and preserves falsey baseline normalization', async () => {
  const f = fixture(), { page } = f
  const responses = [
    { ready: true, generated_at: 'baseline', content: { content: 'old' } },
    { ready: true, generated_at: '', content: { content: 'empty marker' } },
  ]
  f.api.get = async (...args) => {
    f.calls.push(['current-get', ...args])
    return responses.shift()
  }
  const result = await page._pollPersistedAiAnalysis(12, 7, {
    requireNewGeneration: true, baselineGeneratedAt: 'baseline',
  })
  assert.equal(result.generatedAt, '')
  assert.equal(result.normalized.content, 'empty marker')
  assert.deepEqual(f.sleeps, [2000])
})

test('poll skips unready and empty payloads before accepting the first usable result', async () => {
  const f = fixture(), responses = [
    null, { ready: false, content: { content: 'pending' } },
    { ready: true, generated_at: '1', content: {} },
    { ready: true, generated_at: '2', content: { content: 'usable' } },
  ]
  f.api.get = async (...args) => {
    f.calls.push(['current-get', ...args])
    return responses.shift()
  }
  const result = await f.page._pollPersistedAiAnalysis(12, 7)
  assert.equal(result.generatedAt, '2')
  assert.equal(f.calls.filter(call => call[0] === 'current-get').length, 4)
  assert.deepEqual(f.sleeps, [2000, 2000, 2000])
})

test('poll aborts on stale identity before request, after delay and after response', async () => {
  {
    const f = fixture()
    f.page._aiRequestId++
    assert.equal(await f.page._pollPersistedAiAnalysis(12, 7), null)
    assert.equal(f.calls.length, 0)
  }
  {
    const f = fixture()
    f.api.get = async () => {
      f.page._aiRequestId++
      return { ready: true, content: { content: 'late' } }
    }
    assert.equal(await f.page._pollPersistedAiAnalysis(12, 7), null)
  }
  {
    const f = fixture(), pending = deferred()
    f.api.get = () => pending.promise
    const request = f.page._pollPersistedAiAnalysis(12, 7)
    f.page._alive = false
    pending.resolve({ ready: true, content: { content: 'late' } })
    assert.equal(await request, null)
  }
})

test('poll swallows status failures, exhausts the configured attempts, and keeps delay order', async () => {
  const f = fixture()
  f.api.get = async (...args) => {
    f.calls.push(['current-get', ...args])
    throw new Error('offline')
  }
  assert.equal(await f.page._pollPersistedAiAnalysis(12, 7), null)
  assert.equal(f.calls.filter(call => call[0] === 'current-get').length, 44)
  assert.equal(f.sleeps.length, 43)
  assert.deepEqual(f.sleeps.slice(0, 6), [2000, 2000, 2000, 2000, 2000, 3000])
  assert.deepEqual(f.sleeps.slice(13, 16), [3000, 3000, 5000])
})

test('recovered result applies through current page helpers and preserves cache order', () => {
  const f = fixture(), { page } = f
  const recovered = {
    normalized: { content: 'ready' }, generatedAt: '',
    latestWq: { id: 12, ai_analysis_generated_at: 'snapshot' },
  }
  page._resetAiLoadingState = () => f.calls.push(['current-reset'])
  page._syncWqCacheAi = (...args) => f.calls.push(['current-cache', ...args])
  page._normalizeAiResult = () => { throw new Error('must use lexical normalizer') }
  assert.equal(page._applyRecoveredAiResult(recovered), true)
  assert.equal(page._aiResult, recovered.normalized)
  assert.equal(page._aiGenerationMarker, 'snapshot')
  assert.deepEqual(f.calls.map(call => call[0]), [
    'current-reset', 'current-cache', 'setData',
  ])
  assert.deepEqual(JSON.parse(JSON.stringify(f.calls.at(-1)[1])), {
    wq: recovered.latestWq,
    aiCards: { mistakeDiagnosis: '', knowledgePatch: '', reviewTask: '', formatError: false },
    aiFallback: false,
    aiFromCache: true, aiFromQuestionAnalysis: false, aiErrorText: '',
    aiRetryable: true, aiInlineNotice: '',
  })
})

test('recovered content cannot replace a different question or an unloaded page', () => {
  const { page } = fixture()
  const result = { normalized: { content: 'old' }, latestWq: { id: 11 } }
  assert.equal(page._applyRecoveredAiResult(result), false)
  page._alive = false
  assert.equal(page._applyRecoveredAiResult({ ...result, latestWq: { id: 12 } }), false)
  assert.equal(page._aiResult, null)
})

test('recovery source flag, fallback question and missing results preserve distinctions', () => {
  const f = fixture(), { page } = f
  assert.equal(page._applyRecoveredAiResult(null), false)
  assert.equal(f.calls.length, 0)
  const normalized = { content: 'answer' }
  assert.equal(page._applyRecoveredAiResult({ normalized }, { fromRegeneration: true }), true)
  assert.equal(page._aiGenerationMarker, '')
  assert.equal(f.calls.at(-1)[1].wq.id, 12)
  assert.equal(f.calls.at(-1)[1].aiFromCache, false)
})

test('poll rechecks current page predicate after an actual suspended delay', async () => {
  const g = fixture(), entered = deferred()
  let release, calls = 0
  g.api.get = async () => { calls++; return null }
  g.context.setTimeout = callback => { release = callback; entered.resolve(); return 1 }
  const pending = g.page._pollPersistedAiAnalysis(12, 7)
  await entered.promise
  g.page._isCurrentAiRequest = function () {
    assert.equal(this, g.page)
    return false
  }
  release()
  assert.equal(await pending, null)
  assert.equal(calls, 1)
})

test('poll resolves a replacement API method at each retry and preserves its receiver', async () => {
  const f = fixture()
  f.api.get = async function () {
    assert.equal(this, f.api)
    f.api.get = async function () {
      assert.equal(this, f.api)
      return { ready: true, generated_at: 'new', content: { content: 'replacement' } }
    }
    return null
  }
  const result = await f.page._pollPersistedAiAnalysis(12, 7)
  assert.equal(result.normalized.content, 'replacement')
  assert.deepEqual(f.sleeps, [2000])
})

test('poll isolates malformed status failures and preserves falsey marker semantics', async () => {
  const f = fixture()
  const statuses = [
    { get ready() { throw new Error('invalid status') } },
    { ready: true, generated_at: 0, content: { content: 'zero' } },
    { ready: true, generated_at: 9, content: { content: 'next' } },
  ]
  f.api.get = async () => statuses.shift()
  const options = { requireNewGeneration: true, baselineGeneratedAt: false }
  const result = await f.page._pollPersistedAiAnalysis(12, 7, options)
  assert.equal(result.generatedAt, '9')
  assert.deepEqual(options, { requireNewGeneration: true, baselineGeneratedAt: false })
  assert.deepEqual(f.sleeps, [2000, 2000])
})

test('recovered result preserves helper receiver and mutation order before view construction', () => {
  const f = fixture(), { page } = f
  const normalized = { content: 'next' }
  const latestWq = { id: 12, ai_analysis_generated_at: 'latest' }
  page._resetAiLoadingState = function () {
    assert.equal(this, page)
    assert.notEqual(this._aiResult, normalized)
    f.calls.push(['reset'])
  }
  page._syncWqCacheAi = function (id, value, marker) {
    assert.equal(this, page)
    assert.equal(this._aiResult, normalized)
    assert.equal(this._aiGenerationMarker, 'latest')
    assert.equal(id, 12)
    assert.equal(value, normalized)
    assert.equal(marker, 'latest')
    f.calls.push(['cache'])
  }
  assert.equal(page._applyRecoveredAiResult({ normalized, latestWq }), true)
  assert.equal(f.calls.at(-1)[1].wq, latestWq)
  assert.deepEqual(f.calls.map(call => call[0]), ['reset', 'cache', 'setData'])
})
