const assert = require('node:assert/strict')
const { test } = require('node:test')
const { fixture, deferred } = require('./helpers/wrong-detail-ai-recovery-fixture')
const plain = value => JSON.parse(JSON.stringify(value))

test('analysis request preserves endpoint, payload booleans, timeout and current API receiver', async () => {
  for (const force of [false, true, '', 0, 'force']) {
    const f = fixture(), result = { response: true }
    f.api.post = function (...args) {
      assert.equal(this, f.api)
      f.calls.push(['post', ...args])
      return Promise.resolve(result)
    }
    assert.equal(await f.page._requestAiAnalysis(12, force), result)
    assert.deepEqual(plain(f.calls), [[
      'post', '/ai/error-analysis', { wrong_question_id: 12, force_regenerate: !!force },
      { timeout: 55000, suppressNetworkToast: true },
    ]])
  }
})

test('analysis request propagates sync failures and async rejections with error identity', async () => {
  for (const synchronous of [false, true]) {
    const f = fixture(), error = new Error('request failed')
    f.api.post = () => {
      if (synchronous) throw error
      return Promise.reject(error)
    }
    await assert.rejects(f.page._requestAiAnalysis(12, false), value => value === error)
  }
})

test('analysis request reads replacement API methods on later calls', async () => {
  const f = fixture()
  f.api.post = async () => 'first'
  assert.equal(await f.page._requestAiAnalysis(12, false), 'first')
  f.api.post = async function () { assert.equal(this, f.api); return 'second' }
  assert.equal(await f.page._requestAiAnalysis(12, false), 'second')
})

test('recovery enqueue includes baseline only for force and retains payload field order', async () => {
  for (const force of [false, true, 'force']) for (const baseline of [undefined, null, 0, '', 17]) {
    const f = fixture()
    f.api.post = async function (...args) {
      assert.equal(this, f.api)
      f.calls.push(['post', ...args])
      return { queued: true }
    }
    assert.equal(await f.page._enqueueAiRecovery(12, force, baseline), true)
    const expected = { wrong_question_id: 12, force_regenerate: !!force }
    if (force) expected.baseline_generated_at = String(baseline || '')
    assert.deepEqual(plain(f.calls), [[
      'post', '/ai/error-analysis/recover', expected,
      { timeout: 10000, suppressNetworkToast: true },
    ]])
    assert.deepEqual(Object.keys(f.calls[0][2]), Object.keys(expected))
  }
})

test('recovery enqueue awaits response and normalizes queued truthiness', async () => {
  for (const response of [null, {}, { queued: false }, { queued: 0 }, { queued: 'yes' }]) {
    const f = fixture(), pending = deferred()
    f.api.post = () => pending.promise
    let settled = false
    const task = f.page._enqueueAiRecovery(12, false, '').then(value => { settled = true; return value })
    await Promise.resolve()
    assert.equal(settled, false)
    pending.resolve(response)
    assert.equal(await task, !!(response && response.queued))
  }
})

test('recovery enqueue isolates sync, async, response and baseline conversion errors', async () => {
  for (const phase of ['sync', 'async', 'response', 'baseline']) {
    const f = fixture(), error = new Error(phase)
    f.context.console = { warn: (...args) => f.calls.push(['warn', ...args]) }
    f.api.post = () => {
      if (phase === 'sync') throw error
      if (phase === 'async') return Promise.reject(error)
      return { get queued() { throw error } }
    }
    const baseline = phase === 'baseline' ? { toString() { throw error } } : ''
    assert.equal(await f.page._enqueueAiRecovery(12, true, baseline), false)
    assert.equal(f.calls.length, 1)
    assert.equal(f.calls[0][0], 'warn')
    assert.equal(f.calls[0][1], 'AI 恢复任务入队失败，将继续轮询原请求结果')
    assert.equal(f.calls[0][2], error)
  }
})

test('cache sync guards missing cache, identity, value and entry', () => {
  for (const state of ['cache', 'identity', 'value', 'entry']) {
    const f = fixture(), { page, definition } = f
    const entry = { data: { old: true } }, value = { content: 'new' }
    page._wqCache = state === 'cache' ? null : { 12: entry }
    const before = JSON.stringify(page._wqCache)
    definition._syncWqCacheAi.call(page, state === 'identity' ? 0 : state === 'entry' ? 13 : 12,
      state === 'value' ? null : value, 'marker')
    assert.equal(JSON.stringify(page._wqCache), before)
    assert.deepEqual(f.calls, [])
  }
})

test('cache sync replaces only entry data and preserves marker omission and normalized identity', () => {
  for (const generatedAt of [undefined, null, 0, '', 17]) {
    const f = fixture(), { page, definition } = f
    const original = { before: true, ai_analysis_generated_at: 'old', ai_analysis_status: 'pending' }
    const entry = { data: original, timestamp: 99 }, normalized = { content: 'new' }
    const cache = { 12: entry, 13: { untouched: true } }
    page._wqCache = cache
    definition._syncWqCacheAi.call(page, 12, normalized, generatedAt)
    assert.equal(page._wqCache, cache)
    assert.equal(cache[12], entry)
    assert.notEqual(entry.data, original)
    assert.equal(entry.data.ai_analysis, normalized)
    assert.equal(entry.timestamp, 99)
    assert.equal(entry.data.ai_analysis_status, 'pending')
    assert.equal(entry.data.ai_analysis_generated_at, generatedAt === undefined ? 'old' : String(generatedAt || ''))
    assert.deepEqual(original, { before: true, ai_analysis_generated_at: 'old', ai_analysis_status: 'pending' })
    assert.deepEqual(Object.keys(entry.data), [
      'before', 'ai_analysis_generated_at', 'ai_analysis_status', 'ai_analysis',
    ])
    assert.deepEqual(f.calls, [])
  }
})

test('cache sync accepts an entry without existing data', () => {
  const f = fixture(), { page, definition } = f, normalized = { content: 'new' }
  page._wqCache = { 12: { timestamp: 3 } }
  definition._syncWqCacheAi.call(page, 12, normalized)
  assert.deepEqual(plain(page._wqCache), { 12: { timestamp: 3, data: { ai_analysis: normalized } } })
})

test('loading reset writes exactly its four fields without touching private request state', () => {
  const f = fixture(), { page, definition } = f
  page._aiRequestId = 17
  page._aiResult = 'keep'
  page.data.aiErrorText = 'keep'
  definition._resetAiLoadingState.call(page)
  assert.deepEqual(plain(f.calls), [['setData', {
    aiLoading: false, aiRegenerating: false, aiSkeletonVisible: false, aiInlineNotice: '',
  }]])
  assert.equal(page._aiRequestId, 17)
  assert.equal(page._aiResult, 'keep')
  assert.equal(page.data.aiErrorText, 'keep')
})

test('failure state uses provider code precedence and strict false retryability', () => {
  const f = fixture()
  for (const [model, response, text, retryable] of [
    ['timeout', { error_code: 'ai_provider_auth_failed' }, 'AI 分析服务鉴权失败，请联系管理员检查模型 API Key', true],
    ['timeout', { retryable: false }, 'AI 分析生成超时，请稍后重试', false],
    ['', { retryable: false }, 'AI 服务配置异常，请联系管理员检查模型设置', false],
    ['', { retryable: 0 }, 'AI 服务暂时不可用，请稍后重试', true],
    ['', null, 'AI 服务暂时不可用，请稍后重试', true],
  ]) {
    const state = f.page._analysisFailureState(model, response)
    assert.deepEqual(plain(state), { aiErrorText: text, aiRetryable: retryable })
    assert.deepEqual(Object.keys(state), ['aiErrorText', 'aiRetryable'])
  }
})

test('tap ignores busy state and missing identity uses the current toast receiver', () => {
  for (const busy of ['loading', 'regenerating']) {
    const f = fixture()
    f.page.data[busy === 'loading' ? 'aiLoading' : 'aiRegenerating'] = true
    f.page.onTapAiAnalysis()
    assert.deepEqual(f.calls, [])
  }
  const f = fixture()
  f.page.data.wq = null
  const wx = { showToast(options) {
    assert.equal(this, wx)
    f.calls.push(['late-toast', options])
  } }
  f.context.wx = wx
  assert.equal(f.page.onTapAiAnalysis(), undefined)
  assert.deepEqual(plain(f.calls), [['late-toast', { title: '缺少错题ID', icon: 'none' }]])
})

test('tap prefers private identity and calls the current loader without returning its promise', () => {
  for (const privateId of [0, 13]) {
    const f = fixture(), { page } = f, pending = deferred()
    page._currentWqId = privateId
    page.loadAiAnalysis = function (...args) {
      assert.equal(this, page)
      f.calls.push(['load', ...args])
      return pending.promise
    }
    assert.equal(page.onTapAiAnalysis(), undefined)
    assert.deepEqual(f.calls, [['load', privateId || 12]])
    pending.resolve()
  }
})
