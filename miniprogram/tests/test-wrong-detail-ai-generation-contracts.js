const assert = require('node:assert/strict')
const { test } = require('node:test')
const { fixture, deferred } = require('./helpers/wrong-detail-ai-recovery-fixture')
const { ApiError } = require('../utils/api-error')
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

test('explicit HTTP failures end loading without recovery jobs or status polling', async () => {
  for (const statusCode of [401, 403, 404, 409, 422, 429, 500, 503]) {
    const f = setup(), { page } = f
    const error = new ApiError('request failed', { statusCode })
    f.api.post = async () => { throw error }
    page._enqueueAiRecovery = () => { f.calls.push(['enqueue']); return Promise.resolve(true) }
    page._pollPersistedAiAnalysis = async () => { f.calls.push(['poll']); return null }

    await page.loadAiAnalysis(12)

    assert.equal(page.data.aiLoading, false, `HTTP ${statusCode}`)
    assert.equal(page.data.aiFallback, true, `HTTP ${statusCode}`)
    assert.equal(page.data.aiInlineNotice, '')
    assert.match(page.data.aiErrorText, /失败/)
    assert.equal(f.calls.filter(call => ['enqueue', 'poll'].includes(call[0])).length, 0,
      `HTTP ${statusCode} must not recover a completed failure`)
  }
})

test('lost responses and gateway timeouts retain persisted-result recovery', async () => {
  for (const statusCode of [0, 408, 502, 504]) {
    const f = setup(), { page } = f
    f.api.post = async () => { throw new ApiError('request failed', { statusCode }) }
    page._enqueueAiRecovery = () => { f.calls.push(['enqueue']); return Promise.resolve(true) }
    page._pollPersistedAiAnalysis = async () => {
      f.calls.push(['poll'])
      return { normalized: { content: 'recovered' }, generatedAt: 'new' }
    }

    await page.loadAiAnalysis(12)

    assert.equal(page.data.aiLoading, false)
    assert.equal(page.data.aiFallback, false)
    assert.equal(page._aiResult.content, 'recovered')
    assert.equal(f.calls.filter(call => call[0] === 'enqueue').length, 1)
    assert.equal(f.calls.filter(call => call[0] === 'poll').length, 1)
  }
})

const availability = require('../subpackages/study/wrong-detail/utils/wrong-detail-ai-availability')

function availabilityPage() {
  const data = { aiAvailabilityEnabled: false, aiAvailabilityMessage: 'blocked' }
  const page = {
    _alive: true, data,
    _aiAvailabilitySeq: 0, _aiAvailabilityRetryTimer: null,
    _clearAiAvailabilityRetry() {
      if (this._aiAvailabilityRetryTimer) clearTimeout(this._aiAvailabilityRetryTimer)
      this._aiAvailabilityRetryTimer = null
    },
    _scheduleAiAvailabilityRetry() {},
    setData(patch) { Object.assign(data, patch) },
  }
  return page
}

test('availability maps disabled state and all three user-facing reasons', () => {
  const page = availabilityPage()
  for (const [state, reason] of [
    [{ status: 'checking', enabled: false, message: '正在检查 AI 服务' }, 'checking'],
    [{ status: 'unavailable', enabled: false, reason: 'quota', message: 'AI 服务额度不足，暂不可用' }, 'quota'],
    [{ status: 'unavailable', enabled: false, reason: 'user_quota', message: '今日 AI 使用额度已用尽，可先查看已有解析' }, 'user_quota'],
  ]) {
    assert.equal(availability._applyAvailability(page, state, { silent: true }), false)
    assert.equal(page.data.aiAvailabilityEnabled, false)
    assert.equal(page.data.aiAvailabilityReason, reason)
    assert.equal(page.data.aiAvailabilityMessage, state.message)
  }
})

test('availability checking patch stays scoped to availability fields', () => {
  const patch = availability._checkingState()
  assert.deepEqual(Object.keys(patch).sort(), [
    'aiAvailabilityChecking',
    'aiAvailabilityEnabled',
    'aiAvailabilityMessage',
    'aiAvailabilityReason',
    'aiAvailabilityStatus',
  ])
})

test('availability success enables both analysis and teacher without changing existing cards', () => {
  const page = availabilityPage()
  page.data.aiCards = { existing: true }
  assert.equal(availability._applyAvailability(page, {
    status: 'available', enabled: true, reason: '', message: '', retry_after_ms: 30000,
  }, { silent: true }), true)
  assert.equal(page.data.aiAvailabilityEnabled, true)
  assert.equal(page.data.aiAvailabilityMessage, '')
  assert.deepEqual(page.data.aiCards, { existing: true })
})

test('checking responses schedule a short retry instead of leaving the page stuck', () => {
  const page = availabilityPage()
  const delays = []
  page._scheduleAiAvailabilityRetry = delay => delays.push(delay)
  availability._applyAvailability(page, {
    status: 'checking', enabled: false, reason: 'checking',
    message: '正在检查 AI 服务', retry_after_ms: 2000,
  }, { silent: true })
  assert.deepEqual(delays, [2000])
})

test('silent failed checks retain cooldown retries until a later successful probe', () => {
  const page = availabilityPage()
  const delays = []
  page._scheduleAiAvailabilityRetry = delay => delays.push(delay)
  for (let attempt = 0; attempt < 3; attempt++) {
    assert.equal(availability._applyAvailability(page, {
      status: 'unavailable', enabled: false, reason: 'quota',
      retry_after_ms: 300000,
    }, { silent: true }), false)
  }
  assert.deepEqual(delays, [300000, 300000, 300000])

  assert.equal(availability._applyAvailability(page, {
    status: 'available', enabled: true, reason: '', retry_after_ms: 30000,
  }, { silent: true }), true)
  assert.deepEqual(delays, [300000, 300000, 300000])
})

test('availability timeout ends the five-second check but keeps action disabled', async () => {
  const page = availabilityPage()
  page._aiAvailabilitySeq = 0
  page._alive = true
  const pending = new Promise(() => {})
  const result = await availability._refreshAiAvailability(page, {
    requestClient: { get: () => pending }, force: true, silent: true,
  })
  assert.equal(result, false)
  assert.equal(page.data.aiAvailabilityChecking, false)
  assert.equal(page.data.aiAvailabilityEnabled, false)
  assert.equal(page.data.aiAvailabilityMessage, 'AI 服务仍在检查，完成后将自动更新')
  page._alive = false
  availability._clearAiAvailabilityState(page)
})

test('availability transport failure is separate from a confirmed backend model failure', async () => {
  const page = availabilityPage()
  page._aiAvailabilitySeq = 0
  page._alive = true
  const result = await availability._refreshAiAvailability(page, {
    requestClient: { get: async () => { throw new Error('offline') } },
    force: true,
    silent: true,
  })
  assert.equal(result, false)
  assert.equal(page.data.aiAvailabilityReason, 'status_unavailable')
  assert.equal(page.data.aiAvailabilityMessage, '暂时无法检查 AI 服务，请稍后重试')
  page._alive = false
  availability._clearAiAvailabilityState(page)
})

test('backend model failure does not trigger generation recovery or polling', async () => {
  const f = setup(), { page } = f
  page._scheduleAiAvailabilityRetry = () => {}
  page.data.aiAvailabilityEnabled = true
  const error = new ApiError('request failed', {
    statusCode: 503,
    detail: {
      code: 'ai_service_unavailable', status: 'unavailable', enabled: false,
      reason: 'quota', message: 'AI 服务额度不足，暂不可用', retry_after_ms: 300000,
    },
  })
  f.api.post = async () => { throw error }
  page._enqueueAiRecovery = () => { f.calls.push(['enqueue']); return Promise.resolve(true) }
  page._pollPersistedAiAnalysis = async () => { f.calls.push(['poll']); return null }
  await page.loadAiAnalysis(12)
  assert.equal(page.data.aiLoading, false)
  assert.equal(page.data.aiAvailabilityEnabled, false)
  assert.equal(page.data.aiAvailabilityReason, 'quota')
  assert.equal(f.calls.filter(call => ['enqueue', 'poll'].includes(call[0])).length, 0)
})

test('user quota reason keeps global health semantics and teacher calls disabled', () => {
  const page = availabilityPage()
  availability._applyAvailability(page, {
    status: 'unavailable', enabled: false, reason: 'user_quota',
    message: '今日 AI 使用额度已用尽，可先查看已有解析', retry_after_ms: 30000,
  }, { silent: true })
  assert.equal(page.data.aiAvailabilityReason, 'user_quota')
  assert.equal(page.data.aiAvailabilityMessage, '今日 AI 使用额度已用尽，可先查看已有解析')
})

test('fallback refreshes availability only when the result has no shared state', async () => {
  for (const shared of [null, { enabled: false, status: 'unavailable', reason: 'quota' }]) {
    const { page } = setup()
    const applied = [], refreshed = []
    page._applyAiAvailability = state => applied.push(state)
    page._refreshAiAvailability = options => refreshed.push(options)
    const result = { model: 'timeout', from_fallback: true }
    if (shared) result.availability = shared

    await page._applyAiAnalysisResult(result, 12, 7, '')

    assert.equal(applied.length, shared ? 1 : 0)
    assert.equal(refreshed.length, shared ? 0 : 1)
    if (shared) assert.equal(applied[0], shared)
  }
})

test('structured generation error applies shared state without refreshing it again', async () => {
  const { page } = setup()
  const shared = { enabled: false, status: 'unavailable', reason: 'quota' }
  const applied = [], refreshed = []
  page._availabilityFromAiError = () => shared
  page._applyAiAvailability = state => applied.push(state)
  page._refreshAiAvailability = options => refreshed.push(options)

  await page._handleAiAnalysisError(new ApiError('blocked', { statusCode: 503 }), 12, 7, '')

  assert.deepEqual(applied, [shared])
  assert.deepEqual(refreshed, [])
})
