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

test('regeneration continues after a shared probe without requiring a second click', async () => {
  const { page } = setup(), pending = deferred(), requests = []
  page.data.aiAvailabilityEnabled = false
  page.data.aiAvailabilityStatus = 'checking'
  page._refreshAiAvailability = async () => {
    await pending.promise
    page.data.aiAvailabilityEnabled = true
    return true
  }
  page._requestAiAnalysis = async (...args) => {
    requests.push(args)
    return { content: 'fresh' }
  }
  page._applyRegenerateResult = async () => {}
  const task = page.regenerateAiAnalysis()
  await page.regenerateAiAnalysis()
  pending.resolve()
  await task
  assert.deepEqual(requests, [[12, true]])
  assert.equal(page.data.aiAvailabilityPending, false)
})

test('first regeneration failure always renders an error instead of an empty review panel', async () => {
  const { page, api } = setup()
  page.data.aiRequested = true
  api.post = async () => { throw new ApiError('blocked', { statusCode: 503 }) }
  await page.regenerateAiAnalysis()
  assert.equal(page.data.aiFallback, true)
  assert.equal(page.data.aiCards, null)
  assert.equal(page.data.aiSkeletonVisible, false)
  assert.ok(page.data.aiErrorText)
})

test('regeneration guards identity, loading and regenerating without advancing requests', async () => {
  for (const state of ['missing', 'loading', 'regenerating']) {
    const f = setup(), { page } = f
    if (state === 'missing') page.data.wq = null
    if (state === 'loading') page.data.aiLoading = true
    if (state === 'regenerating') page.data.aiRegenerating = true
    await page.regenerateAiAnalysis()
    assert.equal(page._aiRequestId, 7)
    assert.deepEqual(f.calls, [])
  }
})

test('regeneration captures private identity and old values before request and resolves live result handler', async () => {
  const f = setup(), { page } = f, pending = deferred()
  const oldCards = { previous: true }, oldResult = { content: 'old' }
  page._currentWqId = 13
  page.data.wq.id = 13
  page.data.aiCards = oldCards
  page._aiResult = oldResult
  page._aiGenerationMarker = 'baseline'
  page._requestAiAnalysis = function (...args) {
    assert.equal(this, page)
    f.calls.push(['request', ...args])
    return pending.promise
  }
  const task = page.regenerateAiAnalysis()
  assert.equal(page._aiRequestId, 8)
  assert.deepEqual(plain(f.calls[0][1]), {
    aiRegenerating: true, aiSkeletonVisible: true, aiErrorText: '',
    aiRetryable: true, aiFallback: false, aiInlineNotice: '',
  })
  page.data.aiCards = 'changed'
  page._aiResult = 'changed'
  page._aiGenerationMarker = 'changed'
  page._applyRegenerateResult = function (...args) {
    assert.equal(this, page)
    f.calls.push(['late-apply', ...args])
  }
  const response = { content: 'new' }
  pending.resolve(response)
  await task
  assert.deepEqual(f.calls.slice(1), [
    ['request', 13, true],
    ['late-apply', response, 13, 8, 'baseline', oldCards, oldResult],
  ])
})

test('regeneration uses question fallback identity and ignores a stale response', async () => {
  const f = setup(), { page } = f, pending = deferred()
  page._requestAiAnalysis = (...args) => { f.calls.push(['request', ...args]); return pending.promise }
  page._applyRegenerateResult = () => { throw new Error('stale result applied') }
  const task = page.regenerateAiAnalysis()
  page._alive = false
  pending.resolve({})
  await task
  assert.deepEqual(f.calls[1], ['request', 12, true])
  assert.deepEqual(f.calls.map(call => call[0]), ['setData', 'request'])
})

test('regeneration awaits the current error handler for request and result errors', async () => {
  for (const phase of ['request', 'application']) {
    const f = setup(), { page } = f, pending = deferred(), entered = deferred()
    const error = new Error(phase)
    page.data.wq.ai_analysis_generated_at = 17
    page._requestAiAnalysis = async () => {
      if (phase === 'request') throw error
      return { content: 'new' }
    }
    page._applyRegenerateResult = () => { throw error }
    page._handleRegenerateError = function (...args) {
      assert.equal(this, page)
      f.calls.push(['handle', ...args])
      entered.resolve()
      return pending.promise
    }
    let settled = false
    const task = page.regenerateAiAnalysis().then(() => { settled = true })
    await entered.promise
    assert.equal(settled, false)
    assert.deepEqual(f.calls.at(-1), ['handle', error, 12, 8, '17', null, null])
    pending.resolve()
    await task
    assert.equal(settled, true)
  }
})

test('regeneration result priority preserves generating, cache, fallback, empty and success branches', async () => {
  for (const [response, expected] of [
    [{ model: 'generating', content: 'yes', cache_preserved: true, from_fallback: true }, 'generating'],
    [{ content: 'yes', cache_preserved: true, from_fallback: true }, 'cache'],
    [{ content: '', cache_preserved: true, from_fallback: true }, 'fallback'],
    [{ content: 'yes', from_fallback: true }, 'fallback'],
    [null, 'empty'],
    [{ content: 'yes' }, 'success'],
  ]) {
    const f = setup(), { page } = f
    for (const [method, label] of [
      ['_handleRegeneratingModel', 'generating'], ['_commitRegenerateCachePreserved', 'cache'],
      ['_handleRegenerateFallback', 'fallback'], ['_handleRegenerateEmpty', 'empty'],
      ['_commitRegenerateSuccess', 'success'],
    ]) page[method] = function (...args) {
      assert.equal(this, page)
      f.calls.push([label, ...args])
    }
    await page._applyRegenerateResult(response, 12, 7, 'baseline', 'old-cards', 'old-result')
    const args = {
      generating: [12, 7, 'baseline'],
      cache: [response, response, 12, 'baseline'],
      fallback: [(response && response.model) || '', response, 'old-cards'],
      empty: ['old-cards'],
      success: [response, response, 12],
    }
    assert.deepEqual(f.calls, [[expected, ...args[expected]]])
  }
})

test('generating branch awaits recovery with regeneration source then reads the current toast port', async () => {
  const f = setup(), { page } = f, pending = deferred(), recovered = { ready: true }
  page._pollPersistedAiAnalysis = (...args) => { f.calls.push(['poll', ...args]); return pending.promise }
  const task = page._handleRegeneratingModel(12, 7, 'baseline')
  page._applyRecoveredAiResult = function (value, options) {
    assert.equal(this, page)
    assert.equal(value, recovered)
    assert.deepEqual(plain(options), { fromRegeneration: true })
    f.calls.push(['recover'])
    return true
  }
  f.context.wx = { showToast: options => f.calls.push(['late-toast', options]) }
  pending.resolve(recovered)
  await task
  assert.deepEqual(plain(f.calls), [
    ['setData', { aiInlineNotice: 'AI 正在生成中，完成后会自动更新' }],
    ['poll', 12, 7, { requireNewGeneration: true, baselineGeneratedAt: 'baseline' }],
    ['recover'], ['late-toast', { title: '已重新生成', icon: 'success' }],
  ])
})

test('generating exhaustion writes only the current request and keeps current cards', async () => {
  for (const stale of [false, true]) {
    const f = setup(), { page } = f, oldCards = { old: true }
    page.data.aiCards = oldCards
    page._pollPersistedAiAnalysis = async () => { if (stale) page._aiRequestId++; return null }
    await page._handleRegeneratingModel(12, 7, 'baseline')
    assert.equal(page.data.aiCards, oldCards)
    assert.deepEqual(f.calls.map(call => call[0]),
      stale ? ['setData'] : ['setData', 'reset', 'setData', 'setData'])
    if (!stale) assert.equal(page.data.aiInlineNotice, 'AI 正在生成中，请稍后重试')
  }
})

test('cache-preserved writeback keeps marker fallback and reset/cache/view/toast order', () => {
  for (const [generatedAt, baseline, expected] of [
    ['new', 'old', 'new'], ['', 'old', 'old'], [0, '', ''],
  ]) {
    const f = setup(), { page } = f, normalized = { content: 'history' }
    page._aiGenerationMarker = 'ignored'
    page._syncWqCacheAi = function (...args) {
      assert.equal(this, page)
      assert.equal(page._aiResult, normalized)
      assert.equal(page._aiGenerationMarker, expected)
      f.calls.push(['cache', ...args])
    }
    page._commitRegenerateCachePreserved({ generated_at: generatedAt }, normalized, 12, baseline)
    assert.deepEqual(f.calls.map(call => call[0]), ['reset', 'setData', 'cache', 'setData', 'toast'])
    assert.deepEqual(f.calls[2], ['cache', 12, normalized, expected])
    assert.equal(page.data.aiFromCache, true)
    assert.equal(page.data.aiFallback, false)
    assert.equal(page.data.aiInlineNotice, '重新生成失败，已保留历史解析')
    assert.deepEqual(plain(f.calls.at(-1)[1]),
      { title: '重新生成失败，已保留历史解析', icon: 'none' })
  }
})

test('fallback preserves old cards and failure override order for falsey old cards', () => {
  for (const oldCards of [null, '', { previous: true }]) {
    const f = setup(), { page } = f, result = { error_code: 'bad' }
    page.data.aiCards = oldCards
    page._analysisFailureState = function (model, value) {
      assert.equal(this, page)
      assert.equal(value, result)
      assert.equal(model, 'timeout')
      f.calls.push(['failure'])
      return { aiFallback: false, aiErrorText: 'custom' }
    }
    page._handleRegenerateFallback('timeout', result, oldCards)
    assert.equal(page.data.aiCards, oldCards)
    assert.deepEqual(f.calls.map(call => call[0]),
      oldCards ? ['reset', 'setData', 'failure', 'setData', 'toast']
        : ['reset', 'setData', 'failure', 'setData'])
    assert.deepEqual(plain(f.calls[3][1]), oldCards
      ? { aiFallback: false, aiInlineNotice: 'custom' } : { aiFallback: false, aiErrorText: 'custom' })
  }
})

test('fallback missing error text and empty results preserve their distinct notices', () => {
  const f = setup(), { page } = f
  page._analysisFailureState = () => ({})
  page._handleRegenerateFallback('', {}, {})
  assert.equal(page.data.aiInlineNotice, '重新生成失败，已保留当前解析')
  f.calls.length = 0
  page._handleRegenerateEmpty({})
  assert.equal(page.data.aiInlineNotice, '返回内容为空，已保留当前解析')
  assert.deepEqual(f.calls.map(call => call[0]), ['reset', 'setData', 'setData', 'toast'])
  f.calls.length = 0
  page._handleRegenerateEmpty(null)
  assert.deepEqual(plain(f.calls.at(-1)[1]),
    { aiFallback: true, aiErrorText: 'AI 返回内容为空，请稍后重试' })
  assert.deepEqual(f.calls.map(call => call[0]), ['reset', 'setData', 'setData'])
})

test('successful regeneration preserves old marker on falsey generation and toasts after view', () => {
  const f = setup(), { page } = f, normalized = { content: 'new' }
  page._aiGenerationMarker = 'old'
  page._commitRegenerateSuccess({ generated_at: 0, from_cache: false }, normalized, 12)
  assert.equal(page._aiResult, normalized)
  assert.equal(page._aiGenerationMarker, 'old')
  assert.deepEqual(f.calls.map(call => call[0]), ['reset', 'setData', 'syncCache', 'setData', 'toast'])
  assert.deepEqual(f.calls[2], ['syncCache', 12, normalized, 'old'])
  assert.deepEqual(plain(f.calls.at(-1)[1]), { title: '已重新生成', icon: 'success' })
  assert.equal(page.data.aiFromCache, false)
  assert.equal(page.data.aiErrorText, '')
})

test('error dispatcher returns current recovery promise and ignores obsolete requests', () => {
  for (const stale of [false, true]) {
    const f = setup(), { page } = f, error = new Error('offline'), pending = deferred()
    page._alive = !stale
    page._handleRegenerateRecovery = function (...args) {
      assert.equal(this, page)
      f.calls.push(['recover', ...args])
      return pending.promise
    }
    assert.equal(page._handleRegenerateError(error, 12, 7, 'baseline', 'cards', 'result'),
      stale ? undefined : pending.promise)
    assert.equal(f.calls[0][2], error)
    assert.deepEqual(f.calls.map(call => call[0]), stale ? ['error'] : ['error', 'recover'])
    if (!stale) assert.deepEqual(f.calls[1], ['recover', error, 12, 7, 'baseline', 'cards', 'result'])
    pending.resolve()
  }
})

test('recovery enqueues without waiting then applies current helper before late toast', async () => {
  const f = setup(), { page } = f, pending = deferred(), error = new Error('timeout')
  page._enqueueAiRecovery = function (...args) {
    assert.equal(this, page)
    f.calls.push(['enqueue', ...args])
    return new Promise(() => {})
  }
  page._pollPersistedAiAnalysis = (...args) => { f.calls.push(['poll', ...args]); return pending.promise }
  const task = page._handleRegenerateRecovery(error, 12, 7, 'baseline', 'cards', 'result')
  page._applyRecoveredAiResult = function (value, options) {
    assert.equal(this, page)
    assert.deepEqual(value, { ready: true })
    assert.deepEqual(plain(options), { fromRegeneration: true })
    f.calls.push(['apply'])
    return true
  }
  f.context.wx = { showToast: options => f.calls.push(['late-toast', options]) }
  pending.resolve({ ready: true })
  await task
  assert.deepEqual(plain(f.calls), [
    ['setData', { aiInlineNotice: 'AI 正在继续重新生成，完成后会自动更新' }],
    ['enqueue', 12, true, 'baseline'],
    ['poll', 12, 7, { requireNewGeneration: true, baselineGeneratedAt: 'baseline' }],
    ['apply'], ['late-toast', { title: '已重新生成', icon: 'success' }],
  ])
})

test('recovery exhaustion calls current timeout handler only while request identity remains current', async () => {
  for (const stale of [false, true]) {
    const f = setup(), { page } = f, error = new ApiError('offline', { statusCode: 0 })
    page._enqueueAiRecovery = () => {}
    page._pollPersistedAiAnalysis = async () => { if (stale) page._aiRequestId++; return null }
    page._handleRegenerateTimeout = function (...args) {
      assert.equal(this, page)
      f.calls.push(['timeout', ...args])
    }
    await page._handleRegenerateRecovery(error, 12, 7, '', 'cards', 'result')
    assert.deepEqual(f.calls.map(call => call[0]), stale ? ['setData'] : ['setData', 'timeout'])
    if (!stale) assert.deepEqual(f.calls.at(-1), ['timeout', error, 'cards', 'result'])
  }
})

test('timeout restores old result only with old cards and preserves timeout/failure text', () => {
  for (const oldCards of [null, { old: true }]) for (const isTimeout of [false, true]) {
    const f = setup(), { page } = f, oldResult = { content: 'old' }, current = { content: 'current' }
    page._aiResult = current
    page._handleRegenerateTimeout(new Error(isTimeout ? 'timed out' : 'offline'), oldCards, oldResult)
    const title = isTimeout ? '重新生成超时' : '重新生成失败'
    assert.equal(page._aiResult, oldCards ? oldResult : current)
    assert.deepEqual(f.calls.map(call => call[0]),
      oldCards ? ['reset', 'setData', 'setData', 'toast'] : ['reset', 'setData', 'setData'])
    assert.deepEqual(plain(f.calls[2][1]), oldCards
      ? { aiCards: oldCards, aiFallback: false, aiInlineNotice: title + '，已保留历史解析' }
      : { aiFallback: true, aiRetryable: true, aiErrorText: isTimeout
        ? 'AI 分析生成超时，请稍后重试' : 'AI 服务暂时不可用，请稍后重试' })
    if (oldCards) assert.deepEqual(plain(f.calls.at(-1)[1]),
      { title: title + '，已保留历史解析', icon: 'none' })
  }
})

test('HTTP regeneration failures immediately stop the skeleton and preserve existing analysis', async () => {
  for (const statusCode of [401, 403, 409, 429, 500, 503]) {
    for (const oldCards of [null, { previous: true }]) {
      const f = setup(), { page } = f
      const oldResult = { content: 'previous analysis' }
      page.data.aiCards = oldCards
      page._aiResult = oldResult
      page._aiGenerationMarker = 'previous'
      f.api.post = async () => { throw new ApiError('request failed', { statusCode }) }
      page._enqueueAiRecovery = () => { f.calls.push(['enqueue']); return Promise.resolve(true) }
      page._pollPersistedAiAnalysis = async () => { f.calls.push(['poll']); return null }

      await page.regenerateAiAnalysis()

      assert.equal(page.data.aiRegenerating, false, `HTTP ${statusCode}`)
      assert.equal(page.data.aiSkeletonVisible, false)
      assert.equal(page.data.aiCards, oldCards)
      assert.equal(page._aiResult, oldResult)
      assert.equal(page._aiGenerationMarker, 'previous')
      assert.ok(oldCards ? page.data.aiInlineNotice : page.data.aiErrorText)
      if (!oldCards) assert.equal(page.data.aiFallback, true)
      assert.equal(f.calls.filter(call => ['enqueue', 'poll'].includes(call[0])).length, 0,
        `HTTP ${statusCode} must not retry regeneration`)
    }
  }
})

test('availability failure during regeneration preserves old analysis and does not retry', async () => {
  const f = setup(), { page } = f
  page._scheduleAiAvailabilityRetry = () => {}
  page.data.aiAvailabilityEnabled = true
  const oldCards = { previous: true }, oldResult = { content: 'old' }
  page.data.aiCards = oldCards
  page._aiResult = oldResult
  page._aiGenerationMarker = 'old'
  f.api.post = async () => { throw new ApiError('request failed', {
    statusCode: 503,
    detail: {
      code: 'ai_service_unavailable', status: 'unavailable', enabled: false,
      reason: 'configuration', message: 'AI 服务配置或权限异常，等待管理员处理',
      retry_after_ms: 300000,
    },
  }) }
  page._enqueueAiRecovery = () => { f.calls.push(['enqueue']); return Promise.resolve(true) }
  page._pollPersistedAiAnalysis = async () => { f.calls.push(['poll']); return null }
  await page.regenerateAiAnalysis()
  assert.equal(page.data.aiAvailabilityEnabled, false)
  assert.equal(page.data.aiAvailabilityReason, 'configuration')
  assert.equal(page.data.aiCards, oldCards)
  assert.equal(page._aiResult, oldResult)
  assert.equal(f.calls.filter(call => ['enqueue', 'poll'].includes(call[0])).length, 0)
})

test('regeneration fallback and preserved cache refresh only without shared state', async () => {
  for (const cachePreserved of [false, true]) {
    for (const shared of [null, { enabled: false, status: 'unavailable', reason: 'quota' }]) {
      const { page } = setup()
      const applied = [], refreshed = []
      page._applyAiAvailability = state => applied.push(state)
      page._refreshAiAvailability = options => refreshed.push(options)
      const result = {
        model: 'timeout', from_fallback: true,
        cache_preserved: cachePreserved, content: cachePreserved ? 'old' : '',
      }
      if (shared) result.availability = shared

      await page._applyRegenerateResult(result, 12, 7, '', null, null)

      assert.equal(applied.length, shared ? 1 : 0)
      assert.equal(refreshed.length, shared ? 0 : 1)
      if (shared) assert.equal(applied[0], shared)
    }
  }
})

test('structured regeneration error applies shared state without an extra refresh', async () => {
  const { page } = setup()
  const shared = { enabled: false, status: 'unavailable', reason: 'configuration' }
  const applied = [], refreshed = []
  page._availabilityFromAiError = () => shared
  page._applyAiAvailability = state => applied.push(state)
  page._refreshAiAvailability = options => refreshed.push(options)

  await page._handleRegenerateRecovery(
    new ApiError('blocked', { statusCode: 503 }), 12, 7, '', null, null)

  assert.deepEqual(applied, [shared])
  assert.deepEqual(refreshed, [])
})
