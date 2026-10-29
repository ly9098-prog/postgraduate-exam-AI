const assert = require('node:assert/strict')
const { test } = require('node:test')
const { fixture, deferred } = require('./helpers/wrong-detail-ai-recovery-fixture')
const realDiagnosis = require('../subpackages/study/utils/error-diagnosis')
const plain = value => JSON.parse(JSON.stringify(value))
const flush = () => new Promise(setImmediate)

function setup() {
  const diagnosis = { ...realDiagnosis }, f = fixture({ diagnosis, exposeDetailHelpers: true })
  const raw = {
    _optionList: ['option'], _optionKeys: ['A'], _opts: { A: 'option' },
    _blankOptionGroups: [], _hasBlankOptionGroups: false,
    _renderModel: { mode: 'PLAIN', renderTrace: ['trace'] },
    errorTypeLabelText: 'label', subjectLabelText: 'subject',
  }
  f.context.replaceDetailRenderer((wq, safeMode) => { f.calls.push(['render', wq, safeMode]); return raw })
  f.context.Date = { now: () => 1000 }
  f.context.console = { error: (...args) => f.calls.push(['error', ...args]) }
  f.page._diagnosisRequestSeq = 3
  f.page._teacherRequestSeq = 5
  f.page._refreshDiagnosisFromServer = function (...args) {
    assert.equal(this, f.page)
    f.calls.push(['refresh', ...args])
    return new Promise(() => {})
  }
  f.page._checkRenderInvariant = model => f.calls.push(['invariant', model])
  f.page._recordRenderTrace = trace => f.calls.push(['trace', trace])
  return { ...f, raw, diagnosis }
}

test('load initial patch preserves exact fields and insertion order', () => {
  const f = setup(), patch = f.page._loadDataInitialPatch()
  const expected = {
    loading: true, errorText: '', aiFallback: false, aiErrorText: '',
    aiRetryable: true, aiRequested: false, aiFromCache: false,
    aiFromQuestionAnalysis: false, masterConfirmVisible: false,
    unmasterConfirmVisible: false, moreMenuVisible: false,
    removeConfirmVisible: false, masterSubmitting: false,
    removeSubmitting: false, diagnosisSheetVisible: false,
    diagnosisSaving: false, diagnosisSyncing: false,
  }
  assert.deepEqual(plain(patch), expected)
  assert.deepEqual(Object.keys(patch), Object.keys(expected))
})

test('load sequences reset, request, cache, projection, writeback, diagnosis and render checks', async () => {
  const f = setup(), { page } = f, wq = { id: 12, error_diagnosis: { id: 44 } }
  f.api.get = function (...args) {
    assert.equal(this, f.api)
    f.calls.push(['get', ...args])
    assert.equal(page._aiRequestId, 8)
    assert.equal(page._diagnosisRequestSeq, 4)
    assert.equal(page._teacherRequestSeq, 6)
    return Promise.resolve(wq)
  }
  page._buildLoadedDataPatch = function (...args) {
    assert.equal(this, page)
    assert.deepEqual(args, [wq, 12, 8])
    assert.equal(page._wqCache[12].data, wq)
    assert.equal(page._wqCache[12].ts, 1000)
    f.calls.push(['build'])
    return { wq, currentQuestion: { _renderModel: f.raw._renderModel } }
  }
  await page.loadData(12)
  assert.deepEqual(f.calls.map(call => call[0]), [
    'reset', 'setData', 'setData', 'get', 'build', 'setData', 'refresh', 'invariant', 'trace',
  ])
  assert.equal(page._aiResult, null)
  assert.deepEqual(f.calls[6], ['refresh', 12, wq.error_diagnosis])
})

test('load resolves live projection and render helpers after response', async () => {
  const f = setup(), { page } = f, pending = deferred()
  f.api.get = () => pending.promise
  const task = page.loadData(12)
  page._buildLoadedDataPatch = function () {
    assert.equal(this, page)
    f.calls.push(['late-build'])
    return { currentQuestion: { _renderModel: { marker: 'late' } } }
  }
  page._checkLoadedRenderInvariant = function (data) {
    assert.equal(this, page)
    f.calls.push(['late-check', data])
  }
  pending.resolve({ id: 12 })
  await task
  assert.equal(f.calls.some(call => call[0] === 'late-build'), true)
  assert.equal(f.calls.at(-1)[0], 'late-check')
})

test('load resolves lexical renderer and preferred-analysis helper after the awaited request', async () => {
  const f = setup(), { page } = f, pending = deferred()
  f.api.get = () => pending.promise
  const task = page.loadData(12)
  f.context.replaceDetailRenderer((wq, safeMode) => {
    assert.equal(wq.id, 12)
    assert.equal(safeMode, false)
    return { ...f.raw, subjectLabelText: 'late subject' }
  })
  const normalized = { content: 'ready', knowledge_patch: '补漏重点：知识' }
  f.context.replacePreferredAnalysis(() => ({ normalized, source: 'question' }))
  pending.resolve({ id: 12 })
  await task
  assert.equal(page.data.subjectLabelText, 'late subject')
  assert.equal(page._aiResult, normalized)
  assert.equal(page.data.aiFromQuestionAnalysis, true)
  assert.equal(page.data.aiCards.knowledgePatch, '知识')
})

test('load discards stale responses before writing cache and rejects old requests during overlap', async () => {
  for (const stale of ['sequence', 'unloaded']) {
    const f = setup(), pending = deferred()
    f.api.get = () => pending.promise
    const task = f.page.loadData(12)
    if (stale === 'sequence') f.page._aiRequestId++
    else f.page._alive = false
    pending.resolve({ id: 12 })
    await task
    assert.deepEqual(f.page._wqCache, {})
    assert.equal(f.calls.some(call => call[0] === 'render'), false)
  }
  const f = setup(), first = deferred(), second = deferred()
  f.api.get = id => id.endsWith('/1') ? first.promise : second.promise
  const old = f.page.loadData(1), current = f.page.loadData(2)
  second.resolve({ id: 2 })
  await current
  first.resolve({ id: 1 })
  await old
  assert.equal(f.page.data.wq.id, 2)
  assert.deepEqual(Object.keys(f.page._wqCache), ['2'])
})

test('load missing response and thrown projection map through current error handler', async () => {
  for (const phase of ['missing', 'projection']) {
    const f = setup(), { page } = f
    f.api.get = async () => phase === 'missing' ? null : { id: 12 }
    page._buildLoadedDataPatch = () => { throw new Error('projection failed') }
    page._handleLoadDataError = function (error, sequence) {
      assert.equal(this, page)
      f.calls.push(['late-error', error.message, sequence])
    }
    await page.loadData(12)
    assert.deepEqual(f.calls.at(-1),
      ['late-error', phase === 'missing' ? 'not found' : 'projection failed', 8])
    assert.equal(!!page._wqCache[12], phase === 'projection')
  }
})

test('null projection ends load after cache write without diagnosis or render work', async () => {
  const f = setup(), wq = { id: 12 }
  f.api.get = async () => wq
  f.page._buildLoadedDataPatch = () => null
  await f.page.loadData(12)
  assert.equal(f.page._wqCache[12].data, wq)
  assert.deepEqual(f.calls.map(call => call[0]), ['reset', 'setData', 'setData'])
})

test('loaded projection retains raw references, progress placeholders and private updates before final guard', () => {
  for (const stale of [false, true]) {
    const f = setup(), { page, raw } = f, wq = { id: 12, ai_analysis_generated_at: 77 }
    page.data.totalQuestions = 2.5
    page.data.currentIdx = 1
    page._alive = !stale
    const patch = page._buildLoadedDataPatch(wq, 12, 7)
    assert.equal(page._currentWqId, 12)
    assert.equal(page._diagnosisRequestSeq, 4)
    assert.equal(page._teacherRequestSeq, 6)
    assert.equal(page._errorTypeLabelText, 'label')
    assert.equal(page._aiGenerationMarker, '77')
    assert.equal(page._aiResult, null)
    if (stale) assert.equal(patch, null)
    else {
      assert.equal(patch.wq, wq)
      assert.notEqual(patch.currentQuestion, wq)
      assert.equal(patch.currentQuestion._optionList, raw._optionList)
      assert.equal(patch.currentQuestion._renderModel, raw._renderModel)
      assert.equal(patch.wrongQuestions.length, 3)
      assert.deepEqual(plain(patch.wrongQuestions), [{ _answered: true }, { _answered: true }, { _answered: true }])
      assert.equal(patch.runnerProgressPercent, 80)
    }
  }
})

test('loaded field assembly preserves repeated diagnosis normalization and its evaluation order', () => {
  const f = setup(), { page } = f, wq = { id: 12, status: 'mastered', error_diagnosis: {} }
  let count = 0
  f.diagnosis.normalizeDiagnosis = function (raw) {
    assert.equal(this, f.diagnosis)
    assert.equal(raw, wq.error_diagnosis)
    f.calls.push(['normalize'])
    return { marker: ++count }
  }
  f.diagnosis.buildNextAction = function (value, normalized) {
    assert.equal(this, f.diagnosis)
    assert.equal(value, wq)
    f.calls.push(['next', normalized])
    return 'next'
  }
  const current = {}, placeholders = []
  const patch = page._buildLoadedDataFields(wq, current, placeholders, f.raw, 0)
  assert.equal(patch.wq, wq)
  assert.equal(patch.currentQuestion, current)
  assert.equal(patch.wrongQuestions, placeholders)
  assert.equal(patch.runnerProgressPercent, 0)
  assert.equal(patch.isCurrentMastered, true)
  assert.equal(patch.errorDiagnosis.marker, 1)
  assert.deepEqual(f.calls, [['normalize'], ['normalize'], ['next', { marker: 2 }]])
  assert.equal(patch.teacherFeedbackSent, '')
  assert.equal(patch.teacherActionsExpanded, false)
})

test('preferred analysis retains no-result, valid AI/question and invalid content branches', () => {
  for (const preferred of [
    null, { normalized: { content: 'yes', mistake_diagnosis: '错因诊断：原文' }, source: 'ai' },
    { normalized: { content: 'yes', review_task: '复练任务: 任务' }, source: 'question' },
    { normalized: { formatError: true }, source: 'ai' },
    { normalized: {}, source: 'question' },
  ]) {
    const f = setup(), { page } = f, patch = { keep: true }
    f.context.replacePreferredAnalysis(() => preferred)
    page._aiResult = 'previous'
    page._applyPreferredAnalysisToData(patch, {})
    if (!preferred) {
      assert.deepEqual(patch, { keep: true })
      assert.equal(page._aiResult, 'previous')
    } else if (preferred.normalized.content) {
      assert.equal(page._aiResult, preferred.normalized)
      assert.equal(patch.aiFromCache, preferred.source === 'ai')
      assert.equal(patch.aiFromQuestionAnalysis, preferred.source === 'question')
      assert.equal(patch.aiFallback, false)
      assert.equal(patch.aiErrorText, '')
      if (preferred.source === 'ai') assert.equal(patch.aiCards.mistakeDiagnosis, '原文')
    } else {
      assert.equal(page._aiResult, null)
      assert.equal(patch.aiRequested, true)
      assert.equal(patch.aiCards, null)
      assert.equal(patch.aiFallback, true)
      assert.equal(patch.aiErrorText, preferred.normalized.formatError
        ? 'AI 返回格式异常，请重新生成' : 'AI 分析结果为空，请重新生成')
    }
  }
})

test('render check calls current invariant before reading the current trace method', () => {
  const f = setup(), model = { renderTrace: ['initial'] }
  f.page._checkLoadedRenderInvariant({})
  assert.deepEqual(f.calls, [])
  f.page._checkRenderInvariant = function (value) {
    assert.equal(this, f.page)
    assert.equal(value, model)
    value.renderTrace = ['changed']
    this._recordRenderTrace = function (trace) {
      assert.equal(this, f.page)
      f.calls.push(['late-trace', trace])
    }
  }
  f.page._checkLoadedRenderInvariant({ currentQuestion: { _renderModel: model } })
  assert.deepEqual(f.calls, [['late-trace', ['changed']]])
})

test('load error writes only for matching sequence and live page', () => {
  for (const state of ['current', 'stale', 'unloaded']) {
    const f = setup(), { page } = f, error = new Error('offline')
    page._aiResult = 'old'
    if (state === 'stale') page._aiRequestId++
    if (state === 'unloaded') page._alive = false
    page._handleLoadDataError(error, 7)
    if (state === 'current') {
      assert.equal(page._aiResult, null)
      assert.deepEqual(plain(f.calls.at(-1)[1]), {
        loading: false, errorText: '错题不存在或已被移除', wq: null,
        aiLoading: false, aiFallback: false,
      })
      assert.equal(f.calls[0][2], error)
    } else {
      assert.equal(page._aiResult, 'old')
      assert.deepEqual(f.calls, [])
    }
  }
})

test('prefetch guards indices, missing identities and fresh cache using the original TTL boundary', async () => {
  for (const [index, ids, ts, shouldFetch] of [
    [-1, [12], null, false], [1, [12], null, false], [0, [0], null, false],
    [0, [12], 999, false], [0, [12], 2000, false],
    [0, [12], -299000, true], [0, [12], null, true],
  ]) {
    const f = setup(), { page } = f
    page.data.questionIds = ids
    if (ts !== null) page._wqCache[12] = { ts, data: {} }
    f.api.get = async function (...args) {
      assert.equal(this, f.api)
      f.calls.push(['get', ...args])
      return null
    }
    assert.equal(page._prefetchWrongQuestion(index), undefined)
    await flush()
    assert.equal(f.calls.length, shouldFetch ? 1 : 0)
  }
})

test('prefetch refuses stale or unloaded results and never overwrites a cache as new as request start', async () => {
  for (const state of ['latest', 'equal', 'unloaded', 'cleared', 'usable']) {
    const f = setup(), { page } = f, pending = deferred()
    page.data.questionIds = [12]
    f.api.get = () => pending.promise
    page._prefetchWrongQuestion(0)
    if (state === 'latest' || state === 'equal') page._wqCache[12] = {
      data: { current: true }, ts: state === 'latest' ? 1001 : 1000,
    }
    if (state === 'unloaded') page._alive = false
    if (state === 'cleared') page._wqCache = null
    f.context.Date = { now: () => 2000 }
    const wq = { id: 12, fetched: true }
    pending.resolve(wq)
    await flush()
    if (state === 'usable') {
      assert.equal(page._wqCache[12].data, wq)
      assert.equal(page._wqCache[12].ts, 2000)
    } else if (state === 'latest' || state === 'equal') assert.equal(page._wqCache[12].data.current, true)
    else assert.equal(page._wqCache && page._wqCache[12], state === 'cleared' ? null : undefined)
  }
})

test('prefetch swallows rejected promises but preserves synchronous request failure', async () => {
  const f = setup(), error = new Error('offline')
  f.page.data.questionIds = [12]
  f.api.get = () => Promise.reject(error)
  assert.equal(f.page._prefetchWrongQuestion(0), undefined)
  await flush()
  assert.deepEqual(f.page._wqCache, {})
  f.api.get = () => { throw error }
  assert.throws(() => f.page._prefetchWrongQuestion(0), value => value === error)
})
