const assert = require('node:assert/strict')
const { test } = require('node:test')
const { fixture, deferred, plain } = require('./helpers/wrong-detail-navigation-fixture')

test('successive next and previous gestures commit the runner index with each question', async () => {
  const f = fixture(), { page } = f
  page.data.questionIds = [1, 2, 3]
  page.data.totalQuestions = 3
  page._aiRequestId = 8
  page._teacherRequestSeq = 2
  page._diagnosisRequestSeq = 4
  page._waitForContentSwitchOut = async () => {}
  page._armSwitchWatchdog = () => {}
  page._finishContentSwitchTransition = () => { page._switching = false }
  page._refreshDiagnosisFromServer = () => {}
  page._prefetchWrongQuestion = () => {}
  f.api.get = async url => ({ id: Number(url.split('/').pop()) })
  for (const index of [1, 2, 1, 0]) {
    await page._navigateTo(index, 150)
    assert.equal(page.data.currentIdx, index)
    assert.equal(page.data.currentQuestion.id, page.data.questionIds[index])
    assert.equal(page.data.showSwitchMask, false)
    f.callbacks.shift()()
  }
  assert.equal(page._aiRequestId, 12)
  assert.equal(page._teacherRequestSeq, 6)
  assert.equal(page._diagnosisRequestSeq, 8)
})

test('fast navigation never flashes a loading overlay or fabricates animation start time', async () => {
  const f = fixture(), { page } = f
  page._wqCache[2] = { data: { id: 2 }, ts: 1000 }
  page._waitForContentSwitchOut = () => {
    assert.equal(page._contentTransitionStartedAt || 0, 0)
    assert.equal(page.data.showSwitchMask, false)
    return Promise.resolve()
  }
  page._armSwitchWatchdog = () => {}
  await page._navigateTo(1, 150, 'left')
  assert.equal(f.calls.some(call => call[0] === 'patch' && call[1].showSwitchMask === true), false)
})

test('slow navigation keeps current content and only shows a delayed switching hint', async () => {
  const f = fixture(), { page } = f, pending = deferred(), timers = new Map()
  page.data.wq = { id: 1 }
  page.data.loading = false
  let timerId = 0
  f.context.setTimeout = (fn, delay) => { timers.set(++timerId, { fn, delay }); return timerId }
  f.context.clearTimeout = id => timers.delete(id)
  page._armSwitchWatchdog = () => {}
  page._waitForContentSwitchOut = async () => {}
  f.api.get = () => pending.promise
  const task = page._navigateTo(1, 150)
  assert.equal(page.data.wq.id, 1)
  assert.equal(page.data.loading, false)
  assert.equal(page.data.showSwitchMask, false)
  assert.equal(timers.get(1).delay, 350)
  timers.get(1).fn()
  assert.equal(page.data.showSwitchMask, true)
  pending.resolve({ id: 2 })
  await task
  assert.equal(page.data.wq.id, 2)
  assert.equal(page.data.showSwitchMask, false)
  assert.equal(timers.size, 0)
})

test('expired question cache is refreshed before the next question is committed', async () => {
  const f = fixture(), { page } = f
  page._wqCache[2] = { data: { id: 2, content: 'old' }, ts: -400000 }
  f.api.get = async () => ({ id: 2, content: 'current' })
  const result = await page._prepareNavigationData(1, 3)
  assert.equal(result.nextData.wq.content, 'current')
  assert.equal(page._wqCache[2].ts, 1000)
})

test('a delayed render callback cannot restart animation or diagnosis after unload', async () => {
  const f = fixture(), { page } = f
  page._waitForContentSwitchOut = async () => {}
  page._armSwitchWatchdog = () => {}
  page._checkRenderInvariant = () => {}
  await page._commitNavigation({
    wqId: 2, wq: { id: 2 }, raw: {}, nextData: {}, nextAiResult: null,
  }, 'left', 150, 3)
  page._alive = false
  page._finishContentSwitchTransition = () => assert.fail('unloaded animation')
  page._refreshDiagnosisFromServer = () => assert.fail('unloaded diagnosis')
  f.callbacks[0]()
})

test('invalid and unchanged navigation leave the page unlocked without fetching', async () => {
  const f = fixture(), { page } = f
  assert.equal(await page._prepareNavigationData(-1, 3), null)
  assert.equal(await page._prepareNavigationData(2, 3), null)
  await page._navigateTo(10, 150)
  await page._navigateTo(0, 150)
  assert.equal(page._navigationSeq, 3)
  assert.equal(page._switching, false)
  assert.equal(page.data.showSwitchMask, false)
  assert.equal(page._contentTransitionStartedAt || 0, 0)
  assert.equal(f.calls.some(call => call[0] === 'get'), false)
})

test('cached navigation retains identity, AI priority and cache timestamp', async () => {
  const f = fixture(), { page } = f
  const wq = { id: 2, ai_analysis: 'AI analysis', analysis: 'question analysis' }
  page._wqCache[2] = { data: wq, ts: 5 }
  const result = await page._prepareNavigationData(1, 3)
  assert.equal(result.wq, wq)
  assert.equal(result.nextData.wq, wq)
  assert.equal(result.nextData.currentQuestion.id, 2)
  assert.notEqual(result.nextData.currentQuestion, wq)
  assert.equal(result.navigationSeq, 3)
  assert.equal(result.nextData.aiFromCache, true)
  assert.equal(result.nextData.aiFromQuestionAnalysis, false)
  assert.equal(result.nextData.aiRequested, true)
  assert.equal(result.nextData.runnerProgressPercent, 100)
  assert.equal(page._wqCache[2].ts, 5)
  assert.equal(f.calls.some(call => call[0] === 'get'), false)
})

test('fresh response uses current API and renders only after the sequence guard', async () => {
  const f = fixture(), { page } = f
  const pending = deferred()
  f.api.get = url => { f.calls.push(['current-get', url]); return pending.promise }
  const request = page._prepareNavigationData(1, 3)
  assert.deepEqual(f.calls, [['current-get', '/wrong-questions/2']])
  const wq = { id: 2, question_type: 'true_false', answer: 'A', wrong_answer: 'B' }
  pending.resolve(wq)
  const result = await request
  assert.equal(page._wqCache[2].data, wq)
  assert.equal(page._wqCache[2].ts, 1000)
  assert.deepEqual(plain(result.raw._opts), { A: '正确', B: '错误' })
  assert.equal(result.nextData.aiRequested, false)
  assert.equal(result.nextAiResult, null)
})

test('late response after sequence change or unload never populates the cache', async () => {
  for (const invalidate of [
    page => { page._navigationSeq++ }, page => { page._alive = false },
  ]) {
    const f = fixture(), pending = deferred()
    f.api.get = () => pending.promise
    const request = f.page._prepareNavigationData(1, 3)
    invalidate(f.page)
    pending.resolve({ id: 2 })
    assert.equal(await request, null)
    assert.deepEqual(f.page._wqCache, {})
    assert.deepEqual(f.calls, [])
  }
})

test('missing response rejects and pending AI uses the question analysis fallback', async () => {
  const f = fixture()
  f.api.get = async () => null
  await assert.rejects(f.page._prepareNavigationData(1, 3), /not found/)
  assert.deepEqual(f.page._wqCache, {})
  f.api.get = async () => ({
    id: 2, ai_analysis_status: 'generating', ai_analysis: 'old', analysis: 'question analysis',
  })
  const result = await f.page._prepareNavigationData(1, 3)
  assert.equal(result.nextData.aiFromCache, false)
  assert.equal(result.nextData.aiFromQuestionAnalysis, true)
  assert.equal(result.nextData.aiFallback, false)
})

test('navigation view preserves independent normalization, resets and raw references', () => {
  const f = fixture(), { page } = f
  const wq = { id: 2, status: 'mastered', error_diagnosis: { id: 9 } }
  const raw = { _optionList: [], _optionKeys: [], _opts: {}, _blankOptionGroups: [],
    _hasBlankOptionGroups: false, _renderModel: { mode: 'PLAIN' }, subjectLabelText: '408' }
  const patch = page._buildNavigateDataPatch(wq, raw, 1)
  assert.equal(patch.wq, wq)
  assert.equal(patch.currentQuestion._renderModel, raw._renderModel)
  assert.equal(patch.currentQuestion._opts, raw._opts)
  assert.equal(patch.errorDiagnosis, wq.error_diagnosis)
  assert.equal(patch.isCurrentMastered, true)
  assert.equal(patch.runnerProgressPercent, 100)
  assert.deepEqual(plain(patch.wrongQuestions), [{ _answered: true }, { _answered: true }])
  for (const name of ['aiLoading', 'aiRegenerating', 'masterSubmitting', 'removeSubmitting',
    'diagnosisSheetVisible', 'diagnosisSaving', 'diagnosisSyncing', 'teacherSheetVisible',
    'teacherActionsExpanded']) assert.equal(patch[name], false, name)
  assert.deepEqual(f.calls.map(call => call[0]), ['normalize', 'normalize', 'next'])
  page.data.totalQuestions = 0
  assert.equal(page._buildNavigateDataPatch(wq, raw, 0).runnerProgressPercent, 100)
})

test('commit awaits outgoing animation then retains patch callback and render order', async () => {
  const f = fixture(), { page } = f, wait = deferred()
  const wq = { id: 2, error_diagnosis: { id: 9 } }, raw = { errorTypeLabelText: 'label', _renderModel: {} }
  const ctx = { wqId: 2, wq, raw, nextData: { currentIdx: 1 }, nextAiResult: { marker: 'AI' } }
  page._waitForContentSwitchOut = (...args) => { f.calls.push(['wait', ...args]); return wait.promise }
  page._armSwitchWatchdog = ms => f.calls.push(['watchdog', ms])
  page._checkRenderInvariant = model => f.calls.push(['invariant', model])
  page._prefetchWrongQuestion = () => {}
  const request = page._commitNavigation(ctx, 'left', 80, 3)
  assert.deepEqual(f.calls, [['clearTimeout', undefined], ['wait', 'left', 80]])
  assert.equal(page._currentWqId, null)
  wait.resolve()
  await request
  assert.equal(page._currentWqId, 2)
  assert.equal(page._aiResult, ctx.nextAiResult)
  assert.deepEqual(f.calls.map(call => call[0]), ['clearTimeout', 'wait', 'watchdog', 'patch', 'invariant'])
  assert.equal(f.calls[2][1], 5000)
  assert.deepEqual(f.calls[3][1], { showSwitchMask: false, currentIdx: 1 })
  page._finishContentSwitchTransition = dir => f.calls.push(['finish-current', dir])
  page._refreshDiagnosisFromServer = (...args) => f.calls.push(['refresh-current', ...args])
  wq.error_diagnosis = { id: 10 }
  f.callbacks[0]()
  assert.deepEqual(f.calls.slice(-2), [['finish-current', 'left'], ['refresh-current', 2, { id: 10 }]])
})

test('commit guard after animation rejects stale and unloaded navigation', async () => {
  for (const invalid of [page => { page._navigationSeq++ }, page => { page._alive = false }]) {
    const f = fixture(), wait = deferred()
    f.page._waitForContentSwitchOut = () => wait.promise
    const request = f.page._commitNavigation({ wqId: 2, wq: {}, raw: {} }, 'left', 80, 3)
    invalid(f.page)
    wait.resolve()
    await request
    assert.equal(f.page._currentWqId, null)
    assert.deepEqual(f.calls, [['clearTimeout', undefined]])
  }
})

test('repeated navigation during a pending switch does not duplicate requests', async () => {
  const f = fixture(), pending = deferred()
  let requests = 0
  f.api.get = () => { requests++; return pending.promise }
  f.page._waitForContentSwitchOut = async () => {}
  f.page._armSwitchWatchdog = () => {}
  const first = f.page._navigateTo(1, 150)
  const second = f.page._navigateTo(1, 150)
  pending.resolve({ id: 2 })
  await second
  await first
  assert.equal(f.page._currentWqId, 2)
  assert.equal(f.page._navigationSeq, 4)
  assert.equal(requests, 1)
  assert.equal(f.callbacks.length, 1)
  assert.equal(f.page._wqCache[1], undefined)
})

test('navigation failures drop the requested item and ignore obsolete requests', () => {
  for (const status of [404, 410, 500]) {
    const f = fixture(), { page } = f
    page._switching = true
    page._pendingNavigationWqId = 2
    page._dropQuestionFromNavigation = id => f.calls.push(['drop', id])
    page._handleNavigateError({ statusCode: status }, 3)
    assert.equal(page._switching, false)
    assert.equal(page.data.showSwitchMask, false)
    const drop = f.calls.filter(call => call[0] === 'drop')
    assert.deepEqual(drop, status === 500 ? [] : [['drop', 2]])
    assert.equal(f.calls.find(call => call[0] === 'toast')[1].title,
      status === 500 ? '加载失败' : '该错题已被移除，已更新题目列表')
    const count = f.calls.length
    page._handleNavigateError({ status: 404 }, 2)
    page._alive = false
    page._handleNavigateError({ status: 404 }, 3)
    assert.equal(f.calls.length, count)
  }
})

test('dropping a navigation item preserves current id and swallows storage errors', () => {
  const f = fixture(), { page } = f
  page.data.questionIds = ['1', 2, 3]
  page._currentWqId = 3
  page._wqCache[2] = { data: { id: 2 } }
  assert.equal(page._dropQuestionFromNavigation('2'), true)
  assert.equal(page._wqCache[2], undefined)
  assert.equal(page.data.currentIdx, 1)
  assert.equal(page.data.runnerProgressPercent, 100)
  assert.deepEqual(f.calls[0].slice(0, 2), ['storage', 'wrong_detail_nav'])
  assert.deepEqual(plain(f.calls[0][2]), { ids: ['1', 3], ts: 1000 })
  f.context.wx = { setStorageSync: () => { throw new Error('full') } }
  assert.equal(page._dropQuestionFromNavigation(3), true)
  assert.equal(page.data.currentIdx, 0)
  assert.equal(page.data.runnerProgressPercent, 100)
  assert.equal(page._dropQuestionFromNavigation(1), true)
  assert.equal(page.data.runnerProgressPercent, 0)
  const count = f.calls.length
  assert.equal(page._dropQuestionFromNavigation(999), false)
  assert.equal(f.calls.length, count)
})

test('fetch rejection flows through the navigation error boundary', async () => {
  const f = fixture(), error = new Error('offline')
  f.api.get = async () => { throw error }
  await f.page._navigateTo(1, 80, 'left')
  assert.equal(f.page._navigationSeq, 4)
  assert.equal(f.page._switching, false)
  assert.equal(f.page.data.showSwitchMask, false)
  assert.equal(f.calls.find(call => call[0] === 'error')[2], error)
  assert.equal(f.calls.find(call => call[0] === 'toast')[1].title, '加载失败')
  assert.equal(f.callbacks.length, 0)
})

test('data preparation resolves the renderer and page flags after the pending request', async () => {
  const f = fixture(), pending = deferred()
  f.api.get = () => pending.promise
  const request = f.page._prepareNavigationData(1, 3)
  const raw = { marker: 'current' }
  f.context.replaceNavigationRenderer((wq, safeMode) => {
    f.calls.push(['current-render', wq, safeMode])
    return raw
  })
  f.page._buildNavigateDataPatch = (wq, actual, idx) => {
    assert.equal(actual, raw)
    f.calls.push(['current-patch', idx])
    return {}
  }
  f.page.data.safeModeActive = true
  const wq = { id: 2 }
  pending.resolve(wq)
  const result = await request
  assert.equal(result.raw, raw)
  assert.deepEqual(f.calls, [['current-render', wq, true], ['current-patch', 1]])
})
