const assert = require('node:assert/strict')
const { test } = require('node:test')
const { fixture, deferred, flush } = require('./helpers/wrong-book-ai-request-fixture')
const plain = value => JSON.parse(JSON.stringify(value))

test('AI diagnosis check keeps destroyed/stats-loaded guards before empty-count cache clearing', async () => {
  const f = fixture(), old = { summary: 'old' }
  f.page.data.aiDiagnosis = old; f.page.data.stats = { total: 0 }
  f.page._destroyed = true
  assert.equal(await f.page._checkAiDiagnosis(), null); assert.equal(f.calls.length, 0)
  f.page._destroyed = false
  assert.equal(await f.page._checkAiDiagnosis(), old); assert.equal(f.calls.length, 0)
  f.page._aiStatsLoaded = true
  f.page._getUserId = () => 'user'
  await f.page._checkAiDiagnosis()
  assert.equal(f.calls[0][0], 'clearCache'); assert.equal(f.calls[0][1], 'user')
  assert.equal(f.page.data.aiDiagnosis, null)
  assert.deepEqual(Object.keys(f.calls[1][1]), [
    'aiDiagnosis', 'aiDiagnosisLoading', 'aiDiagnosisRefreshing', 'aiDiagnosisCacheTimeLabel',
    'aiDiagnosisCacheStale', 'aiDiagnosisError', 'aiInsightExpanded', 'aiInsightHasDetails',
    'aiInsightWeakPoints', 'aiInsightSuggestions',
  ])
  f.calls.length = 0
  await f.page._checkAiDiagnosis()
  assert.deepEqual(plain(f.calls), [['setData', { aiDiagnosisLoading: false }]])
})

test('AI diagnosis check uses strict zero and current non-awaited analysis result', async () => {
  const f = fixture(), result = { summary: 'result' }
  f.page._aiStatsLoaded = true; f.page.data.stats = { total: '0' }
  f.page.ensureAiDiagnosis = function (options) {
    assert.equal(this, f.page); assert.deepEqual(plain(options), { background: true, refreshOnChange: true })
    return Promise.resolve(result)
  }
  assert.equal(await f.page._checkAiDiagnosis(), null)
  f.page.data.autoAiInsightEnabled = true
  assert.equal(await f.page._checkAiDiagnosis(), result)
})

test('ensure gives strict-zero stats guard precedence over existing promise and force', async () => {
  const f = fixture(), result = { summary: 'in-flight' }
  f.page._aiStatsLoaded = true; f.page.data.stats = { total: 0 }
  f.page._aiDiagnosisPromise = Promise.resolve(result)
  f.page._requestAiDiagnosis = () => assert.fail('unexpected request')
  assert.equal(await f.page.ensureAiDiagnosis({ force: true }), null)
  f.page.data.stats.total = '0'
  assert.equal(await f.page.ensureAiDiagnosis({ force: true }), result)
})

test('ensure force passes only force while existing foreground data bypasses cache reads', async () => {
  const f = fixture(), old = { summary: 'old' }
  f.page.data.aiDiagnosis = old
  f.page._requestAiDiagnosis = function (options) {
    assert.equal(this, f.page); assert.deepEqual(plain(options), { force: true }); return Promise.resolve('forced')
  }
  assert.equal(await f.page.ensureAiDiagnosis({ force: true, refresh: true, background: true }), 'forced')
  f.aiCache.isExpired = () => assert.fail('unexpected expiry')
  assert.equal(await f.page.ensureAiDiagnosis({}), old)
})

test('ensure missing or stale data requests background without source-change refresh', async () => {
  for (const mode of ['missing', 'flag', 'expired']) {
    const f = fixture(), old = { summary: 'old' }
    f.page.data.aiDiagnosis = mode === 'missing' ? null : old
    f.page.data.aiDiagnosisCacheStale = mode === 'flag'
    f.aiCache.isExpired = function (time, diagnosis) {
      assert.equal(this, f.aiCache); assert.equal(mode, 'expired'); assert.equal(diagnosis, old); return true
    }
    f.page._buildAiDiagnosisSourceSignature = () => assert.fail('unexpected signature')
    f.page._requestAiDiagnosis = function (options) {
      assert.equal(this, f.page); assert.deepEqual(plain(options), { background: true, refresh: false }); return 'request'
    }
    assert.equal(await f.page.ensureAiDiagnosis({ background: true }), 'request')
  }
})

test('ensure source-signature mismatch preserves refresh-on-change/cooldown short-circuit and current cache receiver', async () => {
  for (const refreshOnChange of [false, true]) for (const canRefresh of [false, true]) {
    const f = fixture(), old = { summary: 'old' }
    f.page.data.aiDiagnosis = old; f.page._aiDiagnosisCachedAt = 12
    f.page._buildAiDiagnosisSourceSignature = () => 'current'
    f.page._getUserId = () => 'user'
    f.aiCache.restore = function (user) { assert.equal(this, f.aiCache); assert.equal(user, 'user'); return { signature: 'old' } }
    f.aiCache.canRefresh = function (time) { assert.equal(this, f.aiCache); assert.equal(time, 12); assert.equal(refreshOnChange, false); return canRefresh }
    f.page._requestAiDiagnosis = options => {
      assert.deepEqual(plain(options), { background: true, refresh: true }); return 'refresh'
    }
    assert.equal(await f.page.ensureAiDiagnosis({ background: true, refreshOnChange }), refreshOnChange || canRefresh ? 'refresh' : old)
  }
})

test('request setup captures existing-data state and assigns the current executor promise after patch', async () => {
  for (const hasData of [false, true]) {
    const f = fixture(), pending = deferred(), options = { force: true }
    f.page.data.aiDiagnosis = hasData ? { summary: 'old' } : null
    f.page._aiDiagnosisRequestId = 4
    f.page._executeAiDiagnosisRequest = function (opts, hadData, id) {
      assert.equal(this, f.page); assert.equal(opts, options); assert.equal(hadData, hasData); assert.equal(id, 5)
      assert.equal(f.page.data[hasData ? 'aiDiagnosisRefreshing' : 'aiDiagnosisLoading'], true)
      return pending.promise
    }
    const work = f.page._requestAiDiagnosis(options)
    assert.equal(f.page._aiDiagnosisPromise, pending.promise)
    pending.resolve('result'); assert.equal(await work, 'result')
  }
  const f = fixture(), error = Error('patch')
  f.page.setData = () => { throw error }
  await assert.rejects(f.page._requestAiDiagnosis(null), value => value === error)
  assert.equal(f.page._aiDiagnosisRequestId, 1); assert.equal(f.page._aiDiagnosisPromise, null)
})

test('executor resolves current application helper after await and clears promise before adopting its return', async () => {
  const f = fixture(), fetch = deferred(), application = deferred(), diagnosis = { summary: 'new' }
  f.page._aiDiagnosisRequestId = 3
  f.page._fetchAiDiagnosisData = () => fetch.promise
  const work = f.page._executeAiDiagnosisRequest({}, false, 3)
  const newer = Promise.resolve('newer')
  f.page._aiDiagnosisPromise = newer
  f.page._applyAiDiagnosisResult = function (raw, hasData) {
    assert.equal(this, f.page); assert.equal(raw, diagnosis); assert.equal(hasData, false)
    return application.promise
  }
  fetch.resolve(diagnosis); await flush()
  assert.equal(f.page._aiDiagnosisPromise, null)
  let done = false; work.then(() => { done = true }); await flush(); assert.equal(done, false)
  application.resolve('applied'); assert.equal(await work, 'applied')
})

test('executor stale/hidden results return current data and finally clears even a newer stored promise', async () => {
  for (const stale of [false, true]) {
    const f = fixture(), fetch = deferred(), current = { summary: 'current' }
    f.page._fetchAiDiagnosisData = () => fetch.promise
    f.page._applyAiDiagnosisResult = () => assert.fail('unexpected apply')
    const work = f.page._executeAiDiagnosisRequest({}, false, 0)
    if (stale) f.page._aiDiagnosisRequestId++
    else f.page._alive = false
    f.page.data.aiDiagnosis = current; f.page._aiDiagnosisPromise = Promise.resolve('newer')
    fetch.resolve({ summary: 'late' })
    assert.equal(await work, current); assert.equal(f.page._aiDiagnosisPromise, null)
  }
})

test('executor catches fetch/application errors using current handler and clears promise when handler throws', async () => {
  for (const throwsHandler of [false, true]) {
    const f = fixture(), error = Error('fetch'), handlerError = Error('handler'), options = {}
    f.page._fetchAiDiagnosisData = async () => { throw error }
    f.page._handleAiDiagnosisError = function (e, opts, hasData, id) {
      assert.equal(this, f.page); assert.equal(e, error); assert.equal(opts, options); assert.equal(hasData, true); assert.equal(id, 2)
      if (throwsHandler) throw handlerError
      return 'handled'
    }
    const work = f.page._executeAiDiagnosisRequest(options, true, 2)
    if (throwsHandler) await assert.rejects(work, value => value === handlerError)
    else assert.equal(await work, 'handled')
    assert.equal(f.page._aiDiagnosisPromise, null)
  }
})

test('fetch keeps refresh payload/timeout/API receiver and uses current pending/poll helpers after await', async () => {
  for (const options of [{}, { force: true }, { refresh: true }]) {
    const f = fixture(), request = deferred(), pending = { status: 'pending' }, result = { summary: 'done' }
    f.api.get = function (path, params, opts) {
      assert.equal(this, f.api); assert.equal(path, '/stats/ai-diagnosis')
      assert.deepEqual(plain(params), options.force || options.refresh ? { refresh: true } : {})
      assert.deepEqual(plain(opts), { timeout: 55000 }); return request.promise
    }
    const work = f.page._fetchAiDiagnosisData(options, 7)
    f.page._pollAiDiagnosis = function (value, id) { assert.equal(this, f.page); assert.equal(value, pending); assert.equal(id, 7); return Promise.resolve(result) }
    request.resolve(pending); assert.equal(await work, result)
  }
  const f = fixture()
  f.api.get = async () => ({ status: 'pending', detail: 'still pending' })
  f.page._pollAiDiagnosis = async value => value
  await assert.rejects(f.page._fetchAiDiagnosisData({}, 0), error => error.message === 'still pending')
})

test('poll keeps four delay/request attempts and returns a still-pending fourth response without an added final guard', async () => {
  const f = fixture(), pending = { status: 'pending' }, delays = []
  f.page._delay = function (ms) { assert.equal(this, f.page); delays.push(ms); return Promise.resolve() }
  let requests = 0
  f.api.get = function (path, params, options) {
    assert.equal(this, f.api); assert.equal(path, '/stats/ai-diagnosis')
    assert.deepEqual(plain(params), {}); assert.deepEqual(plain(options), { timeout: 55000 })
    requests++
    if (requests === 4) { f.page._alive = false; f.page._aiDiagnosisRequestId++ }
    return Promise.resolve(pending)
  }
  assert.equal(await f.page._pollAiDiagnosis(pending, 0), pending)
  assert.deepEqual(delays, [1200, 1550, 1900, 2250]); assert.equal(requests, 4)
})

test('poll checks sequence/alive only after delay and resolves API method live before each request', async () => {
  for (const stale of [false, true]) {
    const f = fixture(), delay = deferred(), pending = { status: 'pending' }
    f.page._delay = () => delay.promise
    f.api.get = () => assert.fail('unexpected request')
    const work = f.page._pollAiDiagnosis(pending, 0)
    if (stale) f.page._aiDiagnosisRequestId++
    else f.page._alive = false
    delay.resolve(); assert.equal(await work, null)
  }
  const f = fixture(), delay = deferred(), result = { summary: 'done' }
  f.page._delay = () => delay.promise
  const work = f.page._pollAiDiagnosis({ status: 'pending' }, 0)
  f.api.get = function () { assert.equal(this, f.api); return Promise.resolve(result) }
  delay.resolve(); assert.equal(await work, result)
})

test('delay uses the exact requested timeout and resolves only after the scheduled callback', async () => {
  const f = fixture()
  let done = false
  const work = f.page._delay(123).then(() => { done = true })
  const [id, timer] = [...f.timers][0]
  assert.equal(timer.delay, 123); await flush(); assert.equal(done, false)
  f.fire(id); await work; assert.equal(done, true)
})

test('result application uses current normalizer/content/commit and retains old or empty fallback patches', () => {
  const f = fixture(), raw = {}, normalized = {}, committed = {}
  f.page._normalizeAiDiagnosis = function (value) { assert.equal(this, f.page); assert.equal(value, raw); return normalized }
  f.page._hasAiDiagnosisContent = value => { assert.equal(value, normalized); return true }
  f.page._commitAiDiagnosisContent = value => { assert.equal(value, normalized); return committed }
  assert.equal(f.page._applyAiDiagnosisResult(raw, false), committed)
  f.page._hasAiDiagnosisContent = () => false
  const current = { summary: 'old' }; f.page.data.aiDiagnosis = current
  assert.equal(f.page._applyAiDiagnosisResult(raw, true), current)
  assert.deepEqual(plain(f.calls.at(-1)[1]), { aiDiagnosisLoading: false, aiDiagnosisRefreshing: false })
  assert.equal(f.page._applyAiDiagnosisResult(raw, false), null)
  assert.equal(f.page.data.aiDiagnosisError, true)
})

test('AI error handling logs before guards, preserves old data and only force+hasData toasts', () => {
  for (const alive of [false, true]) for (const hasData of [false, true]) for (const force of [false, true]) {
    const f = fixture(), old = { summary: 'old' }, error = { message: 9 }
    f.page.data.aiDiagnosis = old; f.page._alive = alive
    const value = f.page._handleAiDiagnosisError(error, { force }, hasData, 0)
    assert.equal(f.calls[0][0], 'error')
    assert.equal(value, !alive || hasData ? old : null)
    assert.equal(f.calls.some(c => c[0] === 'toast'), alive && hasData && force)
    if (alive && hasData && force) assert.equal(f.calls.at(-1)[1].title, '更新失败，请稍后重试')
  }
})

test('insight toggle collapse precedes busy guard and available data opens without a request', async () => {
  const f = fixture()
  f.page.data.aiInsightExpanded = true; f.page.data.aiDiagnosisLoading = true
  await f.page.toggleAiInsight(); assert.equal(f.page.data.aiInsightExpanded, false)
  await f.page.toggleAiInsight(); assert.equal(f.calls.at(-1)[0], 'toast')
  f.page.data.aiDiagnosisLoading = false; f.page.data.aiDiagnosis = { summary: 'cached' }
  f.page.ensureAiDiagnosis = () => assert.fail('unexpected request')
  await f.page.toggleAiInsight(); assert.equal(f.page.data.aiInsightExpanded, true)
})

test('insight generation keeps loading outside try, late platform hide in finally and original no-alive-guard expansion', async () => {
  for (const outcome of ['value', 'empty', 'reject']) {
    const f = fixture(), request = deferred(), error = Error('analysis')
    f.page.ensureAiDiagnosis = function (opts) { assert.equal(this, f.page); assert.deepEqual(plain(opts), { force: false }); return request.promise }
    const work = f.page.toggleAiInsight()
    assert.equal(f.calls[0][0], 'loading')
    f.context.wx.hideLoading = () => f.calls.push(['lateHide'])
    f.page._alive = false; f.page._destroyed = true
    if (outcome === 'reject') request.reject(error)
    else request.resolve(outcome === 'value' ? { summary: 'result' } : null)
    if (outcome === 'reject') await assert.rejects(work, value => value === error)
    else await work
    assert.ok(f.calls.some(c => c[0] === 'lateHide'))
    assert.equal(f.page.data.aiInsightExpanded, outcome === 'value')
    assert.equal(f.calls.some(c => c[0] === 'toast'), outcome === 'empty')
  }
})

test('refresh guards preserve busy-text priority, strict zero and non-awaited force dispatch', () => {
  const f = fixture()
  f.page._aiDiagnosisPromise = Promise.resolve()
  f.page.data.aiDiagnosisRefreshing = true
  f.page.refreshAiDiagnosis(); assert.equal(f.calls.at(-1)[1].title, '正在更新中...')
  f.page._aiDiagnosisPromise = null; f.page.data.aiDiagnosisRefreshing = false
  f.page._aiStatsLoaded = true; f.page.data.stats.total = 0
  f.page.refreshAiDiagnosis(); assert.equal(f.calls.at(-1)[1].title, '暂无错题数据')
  f.page.data.stats.total = '0'
  f.page.ensureAiDiagnosis = function (opts) { assert.equal(this, f.page); assert.deepEqual(plain(opts), { force: true }); f.calls.push(['ensure']); return new Promise(() => {}) }
  assert.equal(f.page.refreshAiDiagnosis(), undefined); assert.deepEqual(f.calls.at(-1), ['ensure'])
})

test('feedback keeps cancellation/fallback type, API receiver and success toast failures inside catch', async () => {
  for (const index of [-1, 1, 9]) {
    const f = fixture(), options = deferred()
    f.page._showAppOptions = input => { assert.equal(input.title, '反馈这次分析'); assert.equal(input.items.length, 4); return options.promise }
    const work = f.page.onAiFeedback()
    f.api.post = function (path, payload) {
      assert.equal(this, f.api); assert.equal(path, '/ai/feedback')
      assert.deepEqual(plain(payload), { source: 'wrong_book', feedback_type: index === 1 ? '遗漏薄弱点' : '其他问题' })
      f.calls.push(['post']); return Promise.resolve()
    }
    options.resolve(index); await work
    assert.equal(f.calls.some(c => c[0] === 'post'), index >= 0)
  }
  const f = fixture()
  f.page._showAppOptions = async () => 0
  f.context.wx.showToast = options => {
    if (options.icon === 'success') throw Error('toast')
    f.calls.push(['failureToast', options])
  }
  await f.page.onAiFeedback()
  assert.equal(f.calls.at(-1)[1].title, '反馈提交失败，请稍后重试')
})
