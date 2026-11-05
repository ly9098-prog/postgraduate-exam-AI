const assert = require('node:assert/strict')
const { test } = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const miniRoot = path.join(__dirname, '..')
const memory = new Map()
let definition, mono = 10000
const requests = [], toasts = [], redirects = []
global.wx = {
  getStorageSync: key => memory.get(key),
  setStorageSync: (key, value) => memory.set(key, structuredClone(value)),
  removeStorageSync: key => memory.delete(key),
  getPerformance: () => ({ now: () => mono }),
  showToast: value => toasts.push(value), pageScrollTo() {},
  redirectTo: value => redirects.push(value.url),
}
global.getCurrentPages = () => []
global.Page = value => { definition = value }
require('../subpackages/study/practice/practice')
const api = require('../utils/api')
const store = require('../utils/launch-session-store')
const subjects = [{ subject_id: 9, subject_code: 'data_structure', display_name: '数据结构' }]
const questions = [
  { id: 1, subject_id: 9, question_version_id: 101, question_type: 'single_choice',
    content: { text: '选择题' }, options: { A: '甲', B: '乙' } },
  { id: 2, subject_id: 9, question_version_id: 102, question_type: 'fill_blank',
    content: { text: '填空题' } },
  { id: 3, subject_id: 9, question_version_id: 103, question_type: 'subjective',
    content: { text: '论述题' } },
]
function batch() {
  return { questions: structuredClone(questions), batch_token: 'guest-batch',
    expires_at: Math.floor(Date.now() / 1000) + 86400 }
}
function reset() {
  memory.clear()
  requests.length = toasts.length = redirects.length = 0
  api.get = async (url, params, options) => {
    requests.push({ url, params, options })
    return url.endsWith('/subjects') ? { items: subjects } : batch()
  }
  api.post = async (url, body, options) => {
    requests.push({ url, body, options })
    return { objective_correct: 2, objective_total: 2, objective_incorrect: 0,
      subjective_total: 1, skipped_total: 0,
      items: [
        { question_id: 1, is_correct: true, correct_answer: 'A' },
        { question_id: 2, is_correct: true, correct_answer: 'stack' },
        { question_id: 3, reference_only: true, correct_answer: '参考思路', analysis: '解析' },
      ] }
  }
}
function page(options = { guest: '1' }) {
  const instance = { ...definition, data: structuredClone(definition.data) }
  instance.setData = (patch, callback) => {
    for (const [key, value] of Object.entries(patch)) {
      const match = /^questions\[(\d+)\]\._answered$/.exec(key)
      if (match) instance.data.questions[Number(match[1])]._answered = value
      else instance.data[key] = value
    }
    if (callback) callback()
  }
  instance._warmQuestionImages = () => {}
  instance._startTimer = () => { instance.timerStarted = true }
  instance._clearTimer = () => { instance.timerStarted = false }
  instance._showSubmitConfirm = async () => true
  instance._showSubmitConfirmPaused = async () => true
  instance.onLoad(options)
  return instance
}
async function started() {
  const instance = page()
  await instance.onReady()
  await instance.startPractice()
  return instance
}

test('home hero uses the existing practice route and no duplicate guest card or page', () => {
  const config = require('../app.json')
  assert.equal(config.pages[0], 'pages/home/home')
  const study = config.subPackages.find(item => item.name === 'study')
  assert.ok(study.pages.includes('practice/practice'))
  assert.ok(!study.pages.includes('trial/trial'))
  const template = fs.readFileSync(path.join(miniRoot, 'pages/home/home.wxml'), 'utf8')
  assert.ok(!template.includes('class="guest-entry'))
  assert.ok(template.includes("guestMode ? secondaryTaskAction"))
})

test('real shared page grades anonymously and redirects to the existing result page', async () => {
  reset()
  memory.set('user', { id: 42 })
  memory.set('token', 'existing-account')
  memory.set('practice_pending_submission_v1:42', { version: 1, status: 'pending',
    updatedAt: Date.now(), submission: { requestId: 'private' } })
  const instance = await started()
  assert.equal(instance.data.guestMode, true)
  assert.equal(instance.data.currentQuestion.id, 1)
  instance.selectOption({ detail: { option: 'A' } })
  instance.goNext({ detail: { index: 1 } })
  assert.equal(instance.data.needsTextAnswer, true)
  instance.onTextAnswer({ detail: { value: 'stack' } })
  instance.goNext({ detail: { index: 2 } })
  instance.onTextAnswer({ detail: { value: '我的思路' } })
  assert.equal(instance.data.answeredCount, 3)
  await instance.doSubmit()
  const submit = requests.at(-1)
  assert.equal(submit.url, '/guest/practice/evaluate')
  assert.deepEqual(submit.body.answers, [
    { question_id: 1, user_answer: 'A' }, { question_id: 2, user_answer: 'stack' },
    { question_id: 3, user_answer: '我的思路' },
  ])
  assert.deepEqual(redirects, ['/subpackages/study/practice-result/index?guest=1'])
  const guestResult = store.readGuestResult()
  assert.equal(guestResult.subject_name, '数据结构')
  assert.equal(guestResult.total_correct, 2)
  assert.equal(guestResult.total_partial, 1)
  assert.equal(guestResult.results.length, 3)
  assert.equal(store.readGuest().snapshot, null)
  assert.equal(store.readPractice(), null)
  assert.equal(memory.get('practice_pending_submission_v1:42').submission.requestId, 'private')
  assert.ok(requests.every(request => request.options.auth === 'none'))
  assert.ok([...memory.keys()].every(key => !key.startsWith('practice_resume_v1:')))
  await instance.startPractice()
  assert.equal(instance.data.submitted, false)
  assert.deepEqual(instance._practiceSession.answerMap, {})
})

test('guest result persists for the existing result page with bounded TTL and reference status', () => {
  const now = Date.now()
  assert.ok(store.saveGuestResult({
    questions: structuredClone(questions),
    results: [{ question_id: 3, reference_only: true, correct_answer: '参考思路' }],
  }, now))
  assert.ok(store.readGuestResult(now + 1000))
  assert.equal(store.readGuestResult(now + 24 * 60 * 60 * 1000), null)
  const { buildReviewItem } = require('../subpackages/study/practice-result/utils/review-item-builder')
  const helpers = {
    normalizeReviewStatus: () => 'wrong',
    pad2: value => String(value).padStart(2, '0'),
    getQuestionTitle: question => question.content.text,
    formatAnswerPreview: value => value,
    formatMathPreviewText: value => value,
    normalizeKpList: () => [],
  }
  const item = buildReviewItem(questions[2], { reference_only: true, correct_answer: '参考思路' },
    { user_answer: '我的思路' }, 2, helpers)
  assert.equal(item.status, 'partial')
  assert.equal(item.statusLabel, '参考自查')
  const resultTemplate = fs.readFileSync(
    path.join(miniRoot, 'subpackages/study/practice-result/index.wxml'), 'utf8')
  assert.ok(resultTemplate.includes('guestMode ? \'GUEST REPORT\''))
  assert.ok(resultTemplate.includes('bindtap="repeatGuestPractice"'))
  assert.ok(!resultTemplate.includes('guest-result-primary'))
})

test('guest interruptions restore in the shared page across login without merging into an account', async () => {
  reset()
  const instance = await started()
  instance.selectOption({ detail: { option: 'B' } })
  instance.goNext({ detail: { index: 1 } })
  instance.onTextAnswer({ detail: { value: 'draft' } })
  mono += 2000
  instance.onHide()
  const snapshot = store.readGuest().snapshot
  assert.ok(snapshot)
  memory.set('user', { id: 99 })
  memory.set('token', 'signed-in')
  const fresh = page()
  await fresh.onReady()
  assert.equal(fresh.data.guestMode, true)
  assert.equal(fresh.data.currentIndex, 1)
  assert.equal(fresh.data.textAnswer, 'draft')
  assert.deepEqual(fresh._practiceSession.answerMap, { 1: 'B', 2: 'draft' })
  assert.equal(store.readPractice(), null)
  assert.equal(store.readActive(), null)
  fresh.onHide()
  assert.equal(store.readGuest().snapshot.expiresAt, snapshot.expiresAt)
})

test('expired, corrupt and legacy guest drafts clear with a notice and do not expose account drafts', async () => {
  reset()
  const instance = await started()
  instance.onHide()
  const snapshot = store.readGuest().snapshot
  for (const value of [
    { ...snapshot, expiresAt: Date.now() - 1 },
    { ...snapshot, questions: [questions[0], questions[0]] },
    { ...snapshot, answerMap: { 999: 'A' } },
    { ...snapshot, answerMap: [] },
    { ...snapshot, currentIndex: 9 },
    { ...snapshot, elapsedMs: NaN },
    { ...snapshot, version: 1 },
  ]) {
    memory.set('guest_trial_draft_v1', value)
    const fresh = page()
    await fresh.onReady()
    assert.equal(fresh.data.started, false)
    assert.match(fresh.data.guestNotice, /过期或损坏/)
    assert.equal(store.readGuest().snapshot, null)
  }
})

test('guest subject failure retries in the existing setup page', async () => {
  reset()
  api.get = async () => { throw Error('offline') }
  const instance = page()
  await instance.onReady()
  assert.equal(instance.data.subjectsLoadFailed, true)
  reset()
  await instance.startPractice()
  assert.equal(instance.data.subjectsLoadFailed, false)
  assert.equal(instance.data.selectedSubjectId, 9)
  assert.equal(instance.data.started, false)
})

test('guest storage failure leaves answering usable and shows a notice', async () => {
  reset()
  const write = wx.setStorageSync
  wx.setStorageSync = () => { throw Error('quota') }
  try {
    const instance = await started()
    instance.selectOption({ detail: { option: 'A' } })
    assert.equal(instance._practiceSession.answerMap[1], 'A')
    assert.match(instance.data.guestNotice, /无法保存/)
  } finally { wx.setStorageSync = write }
})

test('late guest question response cannot populate an unloaded page', async () => {
  reset()
  const instance = page()
  await instance.onReady()
  let finish
  api.get = () => new Promise(resolve => { finish = resolve })
  const loading = instance.startPractice()
  instance.onUnload()
  finish(batch())
  await loading
  assert.equal(instance.data.currentQuestion, null)
  assert.equal(store.readGuest().snapshot, null)
})

test('guest batch arriving in background stays paused until shown', async () => {
  reset()
  const instance = page()
  await instance.onReady()
  let finish
  api.get = () => new Promise(resolve => { finish = resolve })
  const loading = instance.startPractice()
  instance.onHide()
  finish(batch())
  await loading
  assert.ok(instance._practiceSession._backgroundStartedMonoMs != null)
  assert.equal(instance._practiceSession.currentQuestionStartedMonoMs, 0)
  mono += 2000
  instance.onShow()
  assert.equal(instance._practiceSession._backgroundStartedMonoMs, null)
  assert.equal(instance._practiceSession.currentQuestionStartedMonoMs, mono)
})

test('guest invalid batch resets without formal submission or automatic retries', async () => {
  reset()
  const instance = await started()
  api.post = async () => { throw { statusCode: 400 } }
  await instance.doSubmit()
  assert.equal(instance.data.started, false)
  assert.match(instance.data.guestNotice, /失效/)
  assert.equal(store.readGuest().snapshot, null)
})

test('declining shared exit keeps answers; confirming exit keeps an isolated guest draft', async () => {
  reset()
  const instance = await started()
  instance.selectOption({ detail: { option: 'B' } })
  instance._showSubmitConfirmPaused = async () => false
  await instance.requestExitPractice()
  assert.equal(instance.data.started, true)
  instance._showSubmitConfirmPaused = async () => true
  await instance.requestExitPractice()
  assert.equal(instance.data.started, false)
  assert.equal(store.readGuest().snapshot.answerMap[1], 'B')
})

test('only an explicit guest practice route bypasses the personal route guard', async () => {
  let app, current, prompts = 0
  vm.runInNewContext(fs.readFileSync(path.join(miniRoot, 'app.js'), 'utf8'), {
    App: value => { app = value },
    require: name => ({
      './utils/auth': { isLoggedIn: () => false }, './utils/animation-loader': {},
      './utils/login-gate': { hasPromptedPage: () => false,
        promptLogin: async () => { prompts++; return true } },
    })[name],
    getCurrentPages: () => [current], wx: {}, console, Set,
  })
  current = { route: 'subpackages/study/practice/practice', options: { guest: '1' } }
  app._guardPersonalRoute()
  assert.equal(prompts, 0)
  current = { route: current.route, options: { guest: '0' } }
  app._guardPersonalRoute()
  await Promise.resolve()
  assert.equal(prompts, 1)
  current = { route: 'subpackages/study/practice-result/index', options: { guest: '1' } }
  app._guardPersonalRoute()
  assert.equal(prompts, 1)
  current = { route: 'subpackages/study/wrong-book/wrong-book', options: { guest: '1' } }
  app._guardPersonalRoute()
  assert.equal(prompts, 2)
})

function loginPage(stackSize) {
  let loginDefinition
  const calls = { logins: 0, relaunches: [], back: 0 }
  const mocks = {
    '../../utils/auth': { isLoggedIn: () => false, checkAndRefreshToken: async () => false },
    '../../utils/api': { normalizeExpiresAt: value => value, now: () => Date.now(), resetRedirecting() {} },
    '../../utils/storage': { KEYS: { TOKEN: 'token', TOKEN_EXPIRES_AT: 'expires', USER: 'user' }, get: () => '' },
    '../../utils/privacy': { hasAcceptedCurrentPrivacy: () => true, savePrivacyAcceptance() {} },
    '../../config': {},
    '../../utils/navigation': { getNavigationMetrics: () => ({}) },
    '../../utils/launch-resume': { createLoginResume: () => ({ resolve: async () => '/pages/home/home', complete() {} }) },
    '../../utils/launch-session-store': { userId: () => '' },
  }
  vm.runInNewContext(fs.readFileSync(path.join(miniRoot, 'pages/login/login.js'), 'utf8'), {
    Page: value => { loginDefinition = value }, require: name => mocks[name],
    getCurrentPages: () => new Array(stackSize).fill({ route: 'pages/home/home' }),
    wx: {
      login: () => { calls.logins++ },
      reLaunch: value => calls.relaunches.push(value.url),
      navigateBack: () => { calls.back++ },
    },
    setTimeout: () => 1, clearTimeout() {}, console, Date,
  })
  const instance = { ...loginDefinition, data: { ...loginDefinition.data, agreed: true },
    setData(values) { Object.assign(this.data, values) } }
  instance.onLoad()
  return { instance, calls }
}

test('opening login with stored agreement never calls wx.login automatically', () => {
  const { instance, calls } = loginPage(1)
  assert.equal(instance.data.entryPending, false)
  assert.equal(calls.logins, 0)
})

test('login cancellation returns to source or guest home for a single-page stack', () => {
  for (const size of [1, 2]) {
    const { instance, calls } = loginPage(size)
    instance.onGuestBrowse()
    assert.equal(calls.back, size === 2 ? 1 : 0)
    assert.deepEqual(calls.relaunches, size === 1 ? ['/pages/home/home'] : [])
  }
})

test('login gate retains the source route and query', () => {
  const urls = [], exported = { exports: {} }
  vm.runInNewContext(fs.readFileSync(path.join(miniRoot, 'utils/login-gate.js'), 'utf8'), {
    module: exported, require: () => ({ hasStoredToken: () => false }),
    getCurrentPages: () => [{ route: 'subpackages/formulas/reader/index', options: { id: '23' } }],
    wx: { navigateTo: options => urls.push(options.url), reLaunch() {} }, Promise,
  })
  exported.exports.openLogin()
  assert.equal(decodeURIComponent(urls[0].split('redirect=')[1]),
    '/subpackages/formulas/reader/index?id=23')
})

test('login gate prefers the page custom dialog over the native modal', async () => {
  const shown = []
  let modals = 0, navigations = 0
  const page = {
    route: 'pages/home/home', options: {},
    selectComponent: id => id === '#appDialog'
      ? { show: options => { shown.push(options); return Promise.resolve(false) } }
      : null,
  }
  const exported = { exports: {} }
  vm.runInNewContext(fs.readFileSync(path.join(miniRoot, 'utils/login-gate.js'), 'utf8'), {
    module: exported, require: () => ({ hasStoredToken: () => false }),
    getCurrentPages: () => [page],
    wx: { showModal() { modals++ }, navigateTo() { navigations++ }, reLaunch() {} },
    Promise, WeakSet,
  })
  const confirmed = await exported.exports.promptLogin({ content: '今日复习依赖你的学习记录' })
  assert.equal(confirmed, false)
  assert.equal(modals, 0)
  assert.equal(navigations, 0)
  assert.equal(shown.length, 1)
  assert.equal(shown[0].title, '登录后继续')
  assert.equal(shown[0].message, '今日复习依赖你的学习记录')
  assert.equal(shown[0].cancelText, '暂不登录')
  assert.equal(shown[0].confirmText, '去登录')
})

test('login gate without a custom dialog replaces the stack with the login page', async () => {
  let modals = 0, relaunches = []
  const exported = { exports: {} }
  vm.runInNewContext(fs.readFileSync(path.join(miniRoot, 'utils/login-gate.js'), 'utf8'), {
    module: exported, require: () => ({ hasStoredToken: () => false }),
    getCurrentPages: () => [{ route: 'subpackages/study/review-today/review-today', options: {} }],
    wx: { showModal() { modals++ }, navigateTo() {}, reLaunch: options => relaunches.push(options.url) },
    Promise, WeakSet,
  })
  const handled = await exported.exports.promptLogin({ content: '登录后继续' })
  assert.equal(handled, true)
  assert.equal(modals, 0)
  assert.match(relaunches[0], /^\/pages\/login\/login\?redirect=/)
})

test('guest home clears old account data and only checks an existing session', async () => {
  const exported = { exports: {} }
  let token = false, owner = 'first', validations = 0, destination
  const mocks = {
    '../../../utils/auth': {
      isLoggedIn: () => token,
      checkAndRefreshToken: async () => { validations++; return true },
    },
    '../../../utils/launch-session-store': { userId: () => owner },
  }
  vm.runInNewContext(fs.readFileSync(path.join(miniRoot, 'pages/home/utils/growth-page-controller.js'), 'utf8'), {
    module: exported, require: name => mocks[name] || {},
    wx: { navigateTo: options => { destination = options.url } },
  })
  const instance = { ...exported.exports.growthPageMethods, _growthSeq: 0, _clearAnimTimer() {},
    _lastDashboardSubjectStats: [{ private: true }], _hasGrowthSnapshot: true }
  await instance._validateHomeSession()
  assert.equal(validations, 0)
  assert.equal(instance._authed, false)
  assert.equal(instance._lastDashboardSubjectStats.length, 0)
  assert.equal(Object.keys(instance._guestBasePatch().user).length, 0)
  instance.startGuestTrial()
  assert.equal(destination, '/subpackages/study/practice/practice?guest=1')
  token = true
  await instance._validateHomeSession()
  assert.equal(validations, 1)
  instance._hasGrowthSnapshot = true
  owner = 'second'
  await instance._validateHomeSession()
  assert.equal(instance._hasGrowthSnapshot, false)
})

test('guest zero questions and failed replacement do not resurrect the previous draft', async () => {
  reset()
  const instance = await started()
  assert.ok(store.readGuest().snapshot)
  api.get = async () => ({ ...batch(), questions: [] })
  await instance.startPractice()
  assert.equal(instance.data.started, false)
  assert.equal(store.readGuest().snapshot, null)
  api.get = async () => { throw Error('network') }
  await instance.startPractice()
  assert.equal(instance.data.started, false)
  assert.equal(store.readGuest().snapshot, null)
})

test('guest batch rejects unsupported, duplicated, out-of-scope and oversized questions', async () => {
  reset()
  const instance = page()
  await instance.onReady()
  for (const invalid of [
    [questions[0], questions[0]],
    [{ ...questions[0], question_type: 'internal' }],
    [{ ...questions[0], subject_id: 999 }],
    Array.from({ length: 6 }, (_, index) => ({ ...questions[0], id: index + 1 })),
  ]) {
    api.get = async () => ({ ...batch(), questions: invalid })
    await instance.startPractice()
    assert.equal(instance.data.started, false)
    assert.equal(store.readGuest().snapshot, null)
  }
})

test('guest grading network failure preserves answers and never replays automatically', async () => {
  reset()
  const instance = await started()
  instance.selectOption({ detail: { option: 'B' } })
  let posts = 0
  api.post = async () => { posts++; throw Error('offline') }
  await instance.doSubmit()
  assert.equal(posts, 1)
  assert.equal(instance.data.submitting, false)
  assert.equal(instance._practiceSession.answerMap[1], 'B')
  instance.onHide()
  assert.equal(store.readGuest().snapshot.answerMap[1], 'B')
  instance.onShow()
  assert.equal(posts, 1)
})

test('cancelling login after expired formal submission does not trigger another route prompt', async () => {
  let app, listener, prompts = 0, homes = 0, modals = 0
  const practice = {
    route: 'subpackages/study/practice/practice',
    options: { resume: '1' },
    selectComponent: id => id === '#appDialog'
      ? { show: () => { prompts++; return Promise.resolve(true) } }
      : null,
  }
  const pages = [practice]
  const gate = { exports: {} }
  const platform = {
    showModal(options) {
      modals++
      queueMicrotask(() => { options.success({ confirm: true }); options.complete() })
    },
    navigateTo() { pages.push({ route: 'pages/login/login' }); listener() },
    navigateBack() { pages.pop(); listener() },
    reLaunch() { homes++ },
    onAppRouteDone(callback) { listener = callback },
  }
  vm.runInNewContext(fs.readFileSync(path.join(miniRoot, 'utils/login-gate.js'), 'utf8'), {
    module: gate, require: () => ({ hasStoredToken: () => false }),
    getCurrentPages: () => pages, wx: platform, Promise, WeakSet,
  })
  vm.runInNewContext(fs.readFileSync(path.join(miniRoot, 'app.js'), 'utf8'), {
    App: value => { app = value },
    require: name => ({
      './utils/auth': { isLoggedIn: () => false },
      './utils/login-gate': gate.exports, './utils/animation-loader': {},
    })[name], getCurrentPages: () => pages, wx: platform, console, Set,
  })
  app._startPreviewTempFileCleanup = () => {}
  app.onLaunch()
  await gate.exports.promptLogin()
  platform.navigateBack()
  await Promise.resolve()
  assert.equal(prompts, 1)
  assert.equal(modals, 0)
  assert.equal(homes, 0)
  assert.equal(pages.at(-1), practice)
})
