const assert = require('node:assert/strict')
const { test } = require('node:test')
const { fixture, deferred } = require('./helpers/wrong-detail-ai-recovery-fixture')
const realDiagnosis = require('../subpackages/study/utils/error-diagnosis')
const plain = value => JSON.parse(JSON.stringify(value))
const event = type => ({ currentTarget: { dataset: { type } } })

function setup() {
  const diagnosis = { ...realDiagnosis }, f = fixture({ diagnosis })
  f.page._currentWqId = 12
  f.page._diagnosisRequestSeq = 3
  f.context.Date = { now: () => 1000 }
  f.context.wx.navigateTo = options => f.calls.push(['navigate', options])
  return { ...f, diagnosis }
}

test('sheet builds primary and deduplicated secondary selection with defaults', () => {
  for (const diagnosis of [null, { primaryType: 'unknown' }, {
    primaryType: 'misread', secondaryTypes: ['', 'misread', 'careless', 'careless', 'memory_error'],
  }]) {
    const f = setup(), { page } = f
    page.data.errorDiagnosis = diagnosis
    page.openDiagnosisSheet()
    assert.deepEqual(plain(f.calls.at(-1)[1]), {
      diagnosisSheetVisible: true,
      diagnosisPrimary: diagnosis && diagnosis.primaryType === 'misread' ? 'misread' : 'knowledge_gap',
      diagnosisSecondaryMap: diagnosis && diagnosis.primaryType === 'misread'
        ? { careless: true, memory_error: true } : {},
    })
  }
})

test('sheet close guards saving and primary selection clones secondary state', () => {
  const f = setup(), { page } = f, original = { misread: true, careless: true }
  page.data.diagnosisSaving = true
  page.closeDiagnosisSheet()
  assert.deepEqual(f.calls, [])
  page.data.diagnosisSaving = false
  page.closeDiagnosisSheet()
  assert.equal(page.data.diagnosisSheetVisible, false)
  page.data.diagnosisSecondaryMap = original
  page.selectDiagnosisPrimary(event(''))
  page.selectDiagnosisPrimary(event('misread'))
  assert.equal(page.data.diagnosisPrimary, 'misread')
  assert.notEqual(page.data.diagnosisSecondaryMap, original)
  assert.deepEqual(original, { misread: true, careless: true })
  assert.deepEqual(plain(page.data.diagnosisSecondaryMap), { careless: true })
})

test('secondary selection guards primary and caps additions while allowing removals', () => {
  const f = setup(), { page } = f
  page.data.diagnosisPrimary = 'misread'
  const original = { careless: true, memory_error: true, knowledge_gap: true }
  page.data.diagnosisSecondaryMap = original
  page.toggleDiagnosisSecondary(event(''))
  page.toggleDiagnosisSecondary(event('misread'))
  assert.deepEqual(f.calls, [])
  page.toggleDiagnosisSecondary(event('reasoning_error'))
  assert.equal(page.data.diagnosisSecondaryMap, original)
  assert.deepEqual(plain(f.calls.at(-1)), [
    'toast', { title: '次级错因最多选择 3 个', icon: 'none' },
  ])
  page.toggleDiagnosisSecondary(event('careless'))
  page.toggleDiagnosisSecondary(event('reasoning_error'))
  assert.deepEqual(plain(page.data.diagnosisSecondaryMap),
    { memory_error: true, knowledge_gap: true, reasoning_error: true })
  assert.deepEqual(original, { careless: true, memory_error: true, knowledge_gap: true })
})

test('save guards missing identity and busy state without requests or writes', async () => {
  for (const mode of ['missing', 'busy']) {
    const f = setup()
    if (mode === 'missing') { f.page._currentWqId = 0; f.page.data.wq = null }
    else f.page.data.diagnosisSaving = true
    await f.page.saveDiagnosis()
    assert.deepEqual(f.calls, [])
  }
})

test('save captures choices and local confirmation fields while retaining data-envelope normalization', async () => {
  for (const response of [
    { id: 88, primary_type: 'careless', user_confirmed: false },
    { diagnosis: { id: 89, primary_type: 'careless', user_confirmed: false } },
    { data: { id: 90, primary_type: 'careless', user_confirmed: false } },
    { diagnosis_id: 91 }, null,
  ]) {
    const f = setup(), { page } = f
    page.data.errorDiagnosis = { id: '55' }
    page.data.diagnosisPrimary = 'misread'
    page.data.diagnosisSecondaryMap = { misread: true, careless: false, memory_error: true }
    const oldEntry = { data: { old: true }, ts: 3 }
    page._wqCache[12] = oldEntry
    f.api.put = async function (...args) {
      assert.equal(this, f.api)
      f.calls.push(['put', ...args])
      return response
    }
    await page.saveDiagnosis()
    assert.deepEqual(plain(f.calls[1]), ['put', '/wrong-questions/12/diagnosis', {
      diagnosis_id: 55, primary_type: 'misread', secondary_types: ['careless', 'memory_error'],
    }])
    const expectedId = response && (response.id || response.diagnosis_id || response.diagnosis?.id) || 55
    assert.equal(page.data.wq.error_diagnosis.id, expectedId)
    assert.equal(page.data.wq.error_diagnosis.user_confirmed, true)
    assert.equal(page.data.wq.error_diagnosis.effective_source, 'user')
    assert.equal(page.data.errorDiagnosis.userConfirmed, !response?.data)
    assert.equal(page.data.errorDiagnosis.primaryType, response?.data ? 'careless' : 'misread')
    assert.notEqual(page._wqCache[12], oldEntry)
    assert.equal(page._wqCache[12].data, page.data.wq)
    assert.equal(page._wqCache[12].ts, 1000)
    assert.equal(page.data.diagnosisSaving, false)
    assert.equal(page.data.diagnosisSheetVisible, false)
    assert.deepEqual(plain(f.calls.at(-1)), ['toast', { title: '错因已记录', icon: 'success' }])
  }
})

test('save resolves current helper methods, current occurrence ID and global clock after response', async () => {
  const f = setup(), { page } = f, pending = deferred()
  page.data.errorDiagnosis = { id: 1 }
  page.data.diagnosisPrimary = 'misread'
  page._wqCache[12] = { data: {} }
  f.api.put = () => pending.promise
  const task = page.saveDiagnosis()
  page.data.errorDiagnosis = { id: 77 }
  page.data.wq = { id: 12, latest: true }
  f.context.Date = { now: () => 9000 }
  const originalNormalize = f.diagnosis.normalizeDiagnosis
  f.diagnosis.normalizeDiagnosis = function (raw) {
    assert.equal(this, f.diagnosis)
    f.calls.push(['late-normalize', raw])
    return originalNormalize(raw)
  }
  f.diagnosis.buildNextAction = function (wq, normalized) {
    assert.equal(this, f.diagnosis)
    assert.equal(wq.latest, true)
    assert.equal(normalized.id, 77)
    return { late: true }
  }
  pending.resolve(null)
  await task
  assert.equal(page.data.errorDiagnosis.id, 77)
  assert.deepEqual(plain(page.data.nextErrorAction), { late: true })
  assert.equal(page._wqCache[12].ts, 9000)
  assert.equal(f.calls.filter(call => call[0] === 'late-normalize').length, 2)
})

test('save rejects stale responses without resetting their old loading state', async () => {
  for (const stale of ['unloaded', 'question']) {
    const f = setup(), pending = deferred()
    f.api.put = () => pending.promise
    const task = f.page.saveDiagnosis()
    if (stale === 'unloaded') f.page._alive = false
    else f.page._currentWqId = 13
    pending.resolve({ primary_type: 'misread' })
    await task
    assert.deepEqual(plain(f.calls), [['setData', { diagnosisSaving: true }]])
    assert.equal(f.page.data.diagnosisSaving, true)
  }
})

test('save failure uses live error formatter and preserves platform lookup before formatting', async () => {
  const f = setup(), error = new Error('offline'), { page } = f
  f.api.put = async () => { throw error }
  const oldWx = { showToast(options) {
    assert.equal(this, oldWx)
    f.calls.push(['original-toast', options])
  } }
  f.context.wx = oldWx
  f.api.getErrorMessage = function (value) {
    assert.equal(this, f.api)
    assert.equal(value, error)
    f.context.wx = { showToast() { throw new Error('platform lookup moved') } }
    return 'formatted'
  }
  await page.saveDiagnosis()
  assert.deepEqual(plain(f.calls), [
    ['setData', { diagnosisSaving: true }], ['setData', { diagnosisSaving: false }],
    ['original-toast', { title: 'formatted', icon: 'none' }],
  ])
})

test('save looks up the API method before occurrence payload getters run', async () => {
  const f = setup(), { page } = f
  const put = async function () { assert.equal(this, f.api); return null }
  Object.defineProperty(f.api, 'put', { get() { f.calls.push(['lookup-put']); return put } })
  let diagnosis = { id: 7 }
  Object.defineProperty(page.data, 'errorDiagnosis', { get() {
    f.calls.push(['lookup-diagnosis'])
    return diagnosis
  }, set(value) { diagnosis = value } })
  await page.saveDiagnosis()
  assert.equal(f.calls[1][0], 'lookup-put')
  assert.equal(f.calls[2][0], 'lookup-diagnosis')
})

test('next action resolves current sheet method and preserves route/query encoding', () => {
  for (const [route, expected] of [
    ['review_today', '/subpackages/study/review-today/review-today'],
    ['exam_list', '/subpackages/exam/paper-list/index'],
    ['knowledge_detail', '/subpackages/knowledge/knowledge-detail/index?a=0&b=false&c=%E4%B8%AD%20%26'],
    ['knowledge_subject', '/subpackages/knowledge/knowledge-subject/index?a=0&b=false&c=%E4%B8%AD%20%26'],
    ['practice', '/subpackages/study/practice/practice?a=0&b=false&c=%E4%B8%AD%20%26'],
  ]) {
    const f = setup()
    f.page.data.nextErrorAction = {
      route, routeParams: { a: 0, b: false, c: '中 &', d: '', e: null, f: undefined },
    }
    f.page.openNextErrorAction()
    assert.deepEqual(plain(f.calls), [['navigate', { url: expected }]])
  }
  const f = setup()
  f.page.openNextErrorAction()
  f.page.data.nextErrorAction = { route: 'unknown' }
  f.page.openNextErrorAction()
  assert.deepEqual(f.calls, [])
  f.page.openDiagnosisSheet = function () { assert.equal(this, f.page); f.calls.push(['sheet']) }
  f.page.data.nextErrorAction = { route: 'diagnosis' }
  f.page.openNextErrorAction()
  assert.deepEqual(f.calls, [['sheet']])
})

test('refresh guards invalid identity and applies embedded fallback before loading', async () => {
  const f = setup(), { page } = f, pending = deferred()
  await page._refreshDiagnosisFromServer(0, {})
  assert.equal(page._diagnosisRequestSeq, 3)
  assert.deepEqual(f.calls, [])
  const fallback = { id: 7, primary_type: 'misread', user_confirmed: true }
  f.api.get = function (...args) {
    assert.equal(this, f.api)
    f.calls.push(['get', ...args])
    return pending.promise
  }
  const task = page._refreshDiagnosisFromServer('12', fallback)
  assert.equal(page._diagnosisRequestSeq, 4)
  assert.equal(page.data.wq.error_diagnosis, fallback)
  assert.equal(page.data.errorDiagnosis.primaryType, 'misread')
  assert.equal(f.calls[0][0], 'setData')
  assert.deepEqual(plain(f.calls[1]), ['setData', { diagnosisSyncing: true }])
  assert.deepEqual(plain(f.calls[2]), [
    'get', '/wrong-questions/12/diagnosis', {}, { suppressNetworkToast: true },
  ])
  pending.resolve(null)
  await task
  assert.equal(page.data.diagnosisSyncing, false)
})

test('refresh keeps confirmed fallback when server is empty, unknown or unconfirmed', async () => {
  for (const response of [
    null, {}, { primary_type: 'unknown', user_confirmed: true },
    { primary_type: 'careless', user_confirmed: false, effective_source: 'ai' },
  ]) {
    const f = setup(), fallback = { primary_type: 'misread', user_confirmed: true }
    f.api.get = async () => response
    await f.page._refreshDiagnosisFromServer(12, fallback)
    assert.equal(f.page.data.wq.error_diagnosis, fallback)
    assert.equal(f.page.data.errorDiagnosis.primaryType, 'misread')
    assert.equal(f.page.data.diagnosisSyncing, false)
  }
})

test('refresh applies usable server state to latest view and existing cache independently', async () => {
  const f = setup(), { page } = f, pending = deferred()
  const original = { data: { id: 12, cacheOnly: true }, ts: 2 }, cache = { 12: original }
  page._wqCache = cache
  f.api.get = () => pending.promise
  const task = page._refreshDiagnosisFromServer(12, null)
  page.data.wq = { id: 12, latest: true }
  f.context.Date = { now: () => 8000 }
  const raw = { id: 33, primary_type: 'careless', user_confirmed: true }
  pending.resolve(raw)
  await task
  assert.equal(page.data.wq.latest, true)
  assert.equal(page.data.wq.cacheOnly, undefined)
  assert.equal(page.data.wq.error_diagnosis, raw)
  assert.equal(page._wqCache, cache)
  assert.notEqual(cache[12], original)
  assert.equal(cache[12].data.cacheOnly, true)
  assert.equal(cache[12].data.latest, undefined)
  assert.equal(cache[12].data.error_diagnosis, raw)
  assert.equal(cache[12].ts, 8000)
  assert.equal(page.data.errorDiagnosis.id, 33)
  assert.equal(f.calls.at(-1)[1].diagnosisSyncing, false)
})

test('refresh stale guards retain the distinct finally rule for sequence, lifetime and question', async () => {
  for (const stale of ['sequence', 'unloaded', 'question']) {
    const f = setup(), pending = deferred()
    f.api.get = () => pending.promise
    const task = f.page._refreshDiagnosisFromServer(12, null)
    if (stale === 'sequence') f.page._diagnosisRequestSeq++
    if (stale === 'unloaded') f.page._alive = false
    if (stale === 'question') f.page._currentWqId = 13
    pending.resolve({ primary_type: 'misread' })
    await task
    assert.deepEqual(plain(f.calls), stale === 'question'
      ? [['setData', { diagnosisSyncing: true }], ['setData', { diagnosisSyncing: false }]]
      : [['setData', { diagnosisSyncing: true }]])
    assert.equal(f.page.data.errorDiagnosis, null)
  }
})

test('refresh request and normalization failures keep fallback and still clear syncing', async () => {
  for (const failure of ['network', 'normalization']) {
    const f = setup(), fallback = { primary_type: 'misread', user_confirmed: true }
    f.api.get = async () => {
      if (failure === 'network') throw new Error('offline')
      f.diagnosis.normalizeDiagnosis = () => { throw new Error('invalid response') }
      return {}
    }
    await f.page._refreshDiagnosisFromServer(12, fallback)
    assert.equal(f.page.data.wq.error_diagnosis, fallback)
    assert.equal(f.page.data.diagnosisSyncing, false)
    assert.equal(f.calls.filter(call => call[0] === 'toast').length, 0)
  }
})
