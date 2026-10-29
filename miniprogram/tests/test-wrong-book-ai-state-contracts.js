const assert = require('node:assert/strict')
const { test } = require('node:test')
const { fixture, deferred, flush } = require('./helpers/wrong-book-ai-state-fixture')
const plain = value => JSON.parse(JSON.stringify(value))

test('AI user lookup preserves storage receiver/key, catches failures and resolves current user helper', () => {
  const f = fixture(), user = { id: 2, user_id: 3, openid: 'openid' }
  f.storage.get = function (key) { assert.equal(this, f.storage); assert.equal(key, 'user'); return user }
  assert.equal(f.page._getUser(), user)
  assert.equal(f.page._getUserId(), 2)
  f.page._getUser = function () { assert.equal(this, f.page); return { id: 0, user_id: 0, openid: 'openid' } }
  assert.equal(f.page._getUserId(), 'openid')
  f.page._getUser = f.methods._getUser
  f.storage.get = () => { throw Error('storage') }
  assert.equal(f.page._getUser(), null); assert.equal(f.page._getUserId(), null)
})

test('AI setting key and idle copy retain truthy user identity and exact storage prefix', () => {
  const f = fixture()
  for (const id of [null, '', 0, 'openid', 2]) {
    f.page._getUserId = function () { assert.equal(this, f.page); return id }
    assert.equal(f.page._getAiAutoSettingKey(), id ? 'ai_wrong_book_auto_v1_' + id : '')
  }
  assert.equal(f.page._getAiInsightIdleText(false), '自动分析已关闭，点击生成获取 AI 洞察')
  assert.equal(f.page._getAiInsightIdleText(true), '自动分析已开启，进入错题本时会生成最新洞察')
})

test('AI setting restore accepts only true, skips absent key and preserves existing diagnosis text', () => {
  for (const stored of [true, false, 'true', 1, undefined]) {
    const f = fixture()
    f.page._getAiAutoSettingKey = () => 'key'; f.values.set('key', stored)
    f.page._restoreAiAutoSetting()
    assert.equal(f.page.data.autoAiInsightEnabled, stored === true)
    assert.equal(f.page.data.aiInsightText, f.page._getAiInsightIdleText(stored === true))
  }
  const f = fixture()
  f.page._getAiAutoSettingKey = () => ''
  f.page.data.aiDiagnosis = {}; f.page.data.aiInsightText = 'retained'
  f.page._restoreAiAutoSetting()
  assert.deepEqual(f.calls.map(c => c[0]), ['setData'])
  assert.equal(f.page.data.aiInsightText, 'retained')
})

test('AI normalization deep-clones input and keeps mixed accuracy, suggestions and field order', () => {
  const f = fixture(), input = {
    summary: 'summary',
    weak_points: [null, 'bad', {}, { knowledge_point: 'a', accuracy: 0.25, suggestion: 1 },
      { knowledge_point: 'b', accuracy: 1.2 }, { knowledge_point: 'c', accuracy: 150 },
      { knowledge_point: 'd', accuracy: -2 }, { knowledge_point: 'e', accuracy: '0.9' }],
    strong_points: 'bad', learning_suggestions: [' ', 0, false, ' good ', { nested: true }],
    extra: { keep: true },
  }
  const before = JSON.stringify(input), normalized = f.page._normalizeAiDiagnosis(input)
  assert.equal(JSON.stringify(input), before); assert.notEqual(normalized, input)
  assert.notEqual(normalized.extra, input.extra)
  assert.deepEqual(plain(normalized.weak_points.map(p => p._accuracyPercent)), [25, 1, 100, 0, 0])
  assert.deepEqual(Object.keys(normalized.weak_points[0]), ['knowledge_point', 'accuracy', '_accuracyPercent', 'suggestion'])
  assert.deepEqual(plain(normalized.strong_points), [])
  assert.deepEqual(plain(normalized.learning_suggestions), [' good ', { nested: true }])
  assert.equal(f.page._normalizeAiDiagnosis(null), null)
  const cyclic = {}; cyclic.self = cyclic
  assert.throws(() => f.page._normalizeAiDiagnosis(cyclic), error => error.name === 'TypeError')
})

test('AI content detection calls the current normalizer and accepts any populated content channel', () => {
  const f = fixture()
  assert.equal(f.page._hasAiDiagnosisContent(null), false)
  assert.equal(f.page._hasAiDiagnosisContent('summary'), false)
  for (const normalized of [{ summary: '  ' }, { summary: 's' }, { weak_points: [1] },
    { strong_points: [1] }, { learning_suggestions: [1] }]) {
    f.page._normalizeAiDiagnosis = function (raw) { assert.equal(this, f.page); assert.equal(raw.marker, true); return normalized }
    assert.equal(f.page._hasAiDiagnosisContent({ marker: true }), normalized.summary === '  ' ? false : true)
  }
})

test('AI pending detection preserves field precedence, strict generating flag and message patterns', () => {
  const f = fixture()
  for (const raw of [
    { status: 'RUNNING' }, { state: 'queued' }, { generation_status: 'processing' },
    { generating: true }, { message: '正在生成中' }, { detail: 'queued result' },
  ]) assert.equal(f.page._isAiDiagnosisPending(raw), true)
  for (const raw of [null, 'pending', { status: 'done', state: 'pending' },
    { generating: 1 }, { message: 'done', detail: 'generating' }, {}]) {
    assert.equal(f.page._isAiDiagnosisPending(raw), false)
  }
})

test('AI detail projection keeps three-item limits, percentage precedence and existing coercion rules', () => {
  const f = fixture(), projected = f.page._buildAiInsightDetails({
    weak_points: [{ knowledge_point: 'a', _accuracyPercent: 120 }, null,
      { knowledge_point: 'c', accuracy: 2 }, { knowledge_point: 'ignored' }],
    learning_suggestions: [' a ', '', false, 0, 'b', 'c', 'd'],
  })
  assert.deepEqual(plain(projected), {
    aiInsightWeakPoints: [
      { name: 'a', accuracyPercent: 120, suggestion: '' },
      { name: '待识别薄弱点', accuracyPercent: 0, suggestion: '' },
      { name: 'c', accuracyPercent: 100, suggestion: '' },
    ],
    aiInsightSuggestions: ['a', 'b', 'c'], aiInsightHasDetails: true,
  })
  assert.equal(f.page._buildAiInsightDetails(null).aiInsightHasDetails, false)
})

test('AI signature preserves current stats/list identity and the original first-item read', () => {
  const f = fixture(), stats = { total: 2 }, first = { id: 1 }
  let reads = 0
  const list = new Proxy([first], { get(target, key) { if (key === '0') reads++; return target[key] } })
  f.page.data.stats = stats; f.page.data.list = list
  f.aiCache.buildSignature = function (s, l) { assert.equal(this, f.aiCache); assert.equal(s, stats); assert.equal(l, list); return 'live' }
  assert.equal(f.page._buildAiDiagnosisSourceSignature(), 'live'); assert.equal(reads, 1)
})

test('AI cache restoration uses user precedence and normalized/details identities with original field order', () => {
  const f = fixture(), raw = { summary: 'raw' }, normalized = { summary: 'normalized' }, detail = { aiInsightHasDetails: true }
  f.page._getUser = () => ({ id: 0, user_id: 7, openid: 'openid' })
  f.aiCache.restore = function (id) { assert.equal(this, f.aiCache); assert.equal(id, 7); return { status: 'stale', data: raw, cachedAt: 5 } }
  f.page._hasAiDiagnosisContent = value => { assert.equal(value, raw); return true }
  f.page._normalizeAiDiagnosis = value => { assert.equal(value, raw); return normalized }
  f.page._buildAiInsightDetails = value => { assert.equal(value, normalized); return detail }
  f.page._oneLineInsight = text => { assert.equal(text, 'raw'); return '' }
  f.page.data.aiInsightText = 'retained'
  f.page._restoreAiDiagnosisFromCache()
  assert.equal(f.page._aiDiagnosisCachedAt, 5); assert.equal(f.page.data.aiDiagnosis, normalized)
  assert.equal(f.page.data.aiDiagnosisCacheStale, true); assert.equal(f.page.data.aiInsightText, 'retained')
  assert.deepEqual(Object.keys(f.calls.at(-1)[1]), [
    'aiDiagnosis', 'aiDiagnosisCacheTimeLabel', 'aiDiagnosisCacheStale', 'aiDiagnosisError',
    'aiDiagnosisLoading', 'aiDiagnosisRefreshing', 'aiInsightText', 'aiInsightHasDetails',
  ])
})

test('AI cache miss skips content detection and empty content does not update cached time', () => {
  const f = fixture()
  f.page._hasAiDiagnosisContent = () => assert.fail('unexpected content check')
  f.page._restoreAiDiagnosisFromCache()
  assert.equal(f.calls.some(c => c[0] === 'setData'), false)
  f.aiCache.restore = () => ({ status: 'fresh', data: {} })
  f.page._hasAiDiagnosisContent = () => false
  f.page._restoreAiDiagnosisFromCache()
  assert.equal(f.page._aiDiagnosisCachedAt, 0)
})

test('AI cache commit captures signature/user/time, saves before current details and preserves result identity', () => {
  const f = fixture(), normalized = { summary: 'summary' }
  f.page._buildAiDiagnosisSourceSignature = () => { f.calls.push(['sig']); return 'sig' }
  f.page._getUserId = () => { f.calls.push(['user']); return 9 }
  f.aiCache.save = function (user, value, sig) {
    assert.equal(this, f.aiCache); assert.equal(user, 9); assert.equal(value, normalized); assert.equal(sig, 'sig')
    assert.equal(f.page._aiDiagnosisCachedAt, 12345)
    f.calls.push(['save']); f.page._buildAiInsightDetails = value => {
      assert.equal(value, normalized); f.calls.push(['lateDetails']); return { aiInsightHasDetails: true }
    }
  }
  assert.equal(f.page._commitAiDiagnosisContent(normalized), normalized)
  assert.equal(f.page.data.aiDiagnosis, normalized)
  assert.deepEqual(f.calls.map(c => c[0]), ['sig', 'user', 'save', 'lateDetails', 'formatTime', 'setData'])
  assert.equal(f.page.data.aiDiagnosisCacheStale, false)
})

test('AI persistence failures keep the original partial state and propagate outside a local catch', () => {
  const f = fixture(), error = Error('persist')
  f.page._getAiAutoSettingKey = () => 'key'
  f.storage.set = () => { throw error }
  assert.throws(() => f.page.toggleAiAutoAnalysis(), value => value === error)
  assert.equal(f.page.data.autoAiInsightEnabled, false); assert.equal(f.timers.size, 0)
  f.aiCache.save = () => { throw error }
  assert.throws(() => f.page._commitAiDiagnosisContent({ summary: 's' }), value => value === error)
  assert.equal(f.page._aiDiagnosisCachedAt, 12345); assert.equal(f.page.data.aiDiagnosis, null)
})

test('disabling auto analysis keeps write/timer/patch/toast order and invalidates only active requests', () => {
  for (const loading of [false, true]) {
    const f = fixture()
    f.page.data.autoAiInsightEnabled = true; f.page.data.aiDiagnosisLoading = loading
    f.page._aiAutoSwitchTimer = 90; f.page._aiDiagnosisRequestId = 4
    f.page._getAiAutoSettingKey = () => 'key'
    assert.equal(f.page.toggleAiAutoAnalysis(), undefined)
    assert.equal(f.values.get('key'), false); assert.equal(f.page._aiDiagnosisRequestId, loading ? 5 : 4)
    assert.equal(f.page.data.autoAiInsightEnabled, false)
    assert.deepEqual(f.calls.slice(0, 4).map(c => c[0]), ['set', 'clear', 'setData', 'timer'])
    assert.equal(f.calls.at(-1)[1].title, '已切换为手动分析')
    const timer = f.page._aiAutoSwitchTimer
    assert.equal(f.timers.get(timer).delay, 420)
    f.page._alive = false; f.fire(timer)
    assert.equal(f.page.data.aiAutoSwitchPulse, true); assert.equal(f.page._aiAutoSwitchTimer, null)
  }
})

test('enabling auto analysis dispatches current helper without await only when alive and stats ready', () => {
  for (const loaded of [false, true]) for (const alive of [false, true]) {
    const f = fixture()
    f.page._aiStatsLoaded = loaded; f.page._alive = alive; f.page.data.stats = { total: '2' }
    f.page.ensureAiDiagnosis = function (options) {
      assert.equal(this, f.page); assert.deepEqual(plain(options), { background: true, refreshOnChange: true })
      f.calls.push(['ensure']); return new Promise(() => {})
    }
    assert.equal(f.page.toggleAiAutoAnalysis(), undefined)
    assert.equal(f.calls.some(c => c[0] === 'ensure'), loaded && alive)
    f.page._alive = true; f.fire(f.page._aiAutoSwitchTimer)
    assert.equal(f.page.data.aiAutoSwitchPulse, false)
  }
})

test('auto analysis waits for existing work and its finally callback reads current alive/setting/helper', async () => {
  for (const allowed of [false, true]) {
    const f = fixture(), pending = deferred()
    f.page._aiStatsLoaded = true; f.page.data.stats = { total: 2 }; f.page._aiDiagnosisPromise = pending.promise
    f.page.toggleAiAutoAnalysis()
    f.page.ensureAiDiagnosis = function () { assert.equal(this, f.page); f.calls.push(['lateEnsure']) }
    f.page.data.autoAiInsightEnabled = allowed
    pending.resolve(); await flush()
    assert.equal(f.calls.some(c => c[0] === 'lateEnsure'), allowed)
  }
})
