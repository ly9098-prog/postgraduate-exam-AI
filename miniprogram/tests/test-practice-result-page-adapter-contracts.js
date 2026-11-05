const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const { test } = require('node:test')

const root = path.resolve(__dirname, '../subpackages/study/practice-result')

function fixture() {
  let definition
  const calls = []
  const api = {
    get: (...args) => { calls.push(['get', ...args]); return Promise.resolve({}) },
    put: (...args) => { calls.push(['put', ...args]); return Promise.resolve({}) },
    post: (...args) => { calls.push(['post', ...args]); return Promise.resolve({}) },
  }
  const knowledgePracticeSync = {
    record: value => calls.push(['record', value]),
    consumeBaseline: (...args) => calls.push(['consume', ...args]),
  }
  const cache = new Map()
  const context = vm.createContext({
    console, setTimeout, clearTimeout,
    Page: value => { definition = value },
    wx: {
      showToast: value => calls.push(['toast', value]),
      navigateBack: value => calls.push(['back', value]),
      redirectTo: value => calls.push(['redirect', value]),
      reLaunch: value => calls.push(['reLaunch', value]),
    },
    getCurrentPages: () => [{ route: 'pages/home/home' }, { route: 'result' }],
  })
  function load(filename) {
    if (cache.has(filename)) return cache.get(filename).exports
    const module = { exports: {} }
    cache.set(filename, module)
    const requireModule = request => {
      if (request === '../../../utils/api') return api
      if (request === '../../../utils/storage') return { knowledgePracticeSync }
      const resolved = require.resolve(path.resolve(path.dirname(filename), request))
      if (resolved.startsWith(root + path.sep)) return load(resolved)
      return require(resolved)
    }
    const wrapper = vm.runInContext(
      `(function(require,module,exports) {\n${fs.readFileSync(filename, 'utf8')}\n})`, context,
      { filename },
    )
    wrapper(requireModule, module, module.exports)
    return module.exports
  }
  load(path.join(root, 'index.js'))
  const page = Object.assign({}, definition, {
    data: JSON.parse(JSON.stringify(definition.data)),
    _pageAlive: true, _resultVisible: true, _teacherRequestSeq: 0,
    _diagnosisRefreshSeq: 0, _dashboardLoadId: 1,
    setData(patch) { Object.assign(this.data, patch) },
  })
  const adapter = (name, builder, deps = {}) => load(
    path.join(root, 'utils', `practice-result-${name}-page-adapter.js`)
  )[builder](page, deps)
  return { page, calls, api, adapter, context }
}

test('guest repeat requests a fresh configuration once instead of restoring a draft', () => {
  const { page, calls } = fixture()
  page._guestMode = true
  page.repeatGuestPractice()
  page.repeatGuestPractice()
  assert.equal(calls.length, 1)
  assert.equal(calls[0][0], 'redirect')
  const navigation = calls[0][1]
  assert.equal(navigation.url, '/subpackages/study/practice/practice?guest=1&fresh=1')
  navigation.fail()
  assert.equal(page._navigationLocked, false)
  page.repeatGuestPractice()
  assert.equal(calls.length, 2)
})

test('result page memoizes controllers and payload ports per page instance', () => {
  const { page } = fixture()
  const other = fixture().page
  for (const method of ['_batchDiagnosisController', '_trendLoadController',
    '_review408TeacherController', '_backNavigationController',
    '_practicePayloadController', '_practicePayloadPorts']) {
    assert.equal(page[method](), page[method](), method)
    assert.notEqual(page[method](), other[method](), method)
  }
  assert.notEqual(page._practicePageState(), page._practicePageState())
})

test('payload state and cached ports read live page fields and page methods', () => {
  const { page, calls } = fixture()
  const ports = page._practicePayloadPorts()
  const state = page._practicePageState()
  page._launchSubjectId = 7
  assert.equal(ports.getLaunchSubjectId(), 7)
  page._launchSubjectId = 9
  assert.equal(ports.getLaunchSubjectId(), 9)
  page.buildReviewItem = (...args) => args
  assert.equal(ports.buildReviewItem(1, 2, 3, 4).join(','), '1,2,3,4')
  const payload = { marker: true }
  state.setSessionPayload(payload)
  assert.equal(page._sessionPayload, payload)
  state.incrementDiagnosisRefreshSeq()
  assert.equal(page._diagnosisRefreshSeq, 1)
  page._pageAlive = false
  assert.equal(state.isPageAlive(), false)
  ports.recordKnowledgePractice(payload)
  ports.consumeKnowledgeBaseline(9, 10)
  assert.deepEqual(calls, [['record', payload], ['consume', 9, 10]])
})

test('diagnosis adapter uses injected API and live selection and platform ports', async () => {
  const { page, adapter, calls, api, context } = fixture()
  const ports = adapter('diagnosis', 'buildBatchDiagnosisPageCapabilities', { api })
  page.data.batchSelectedMap = { 12: true }
  assert.equal(ports.getBatchSelectedMap(), page.data.batchSelectedMap)
  const payload = { primary_type: 'misread' }
  await ports.putDiagnosis(12, payload)
  assert.deepEqual(calls[0], ['put', '/wrong-questions/12/diagnosis', payload])
  const toast = { title: 'test' }
  context.wx = { showToast: value => calls.push(['new-toast', value]) }
  ports.showToast(toast)
  assert.deepEqual(calls[1], ['new-toast', toast])
})

test('trend controller reaches live page request port and drops late response', async () => {
  const { page } = fixture()
  page.data.trendAvailable = false
  const patches = []
  page.setData = patch => {
    patches.push(patch)
    Object.assign(page.data, patch)
  }
  const controller = page._trendLoadController()
  let resolve
  let request
  page.requestApi = (...args) => {
    request = args
    return new Promise(done => { resolve = done })
  }
  const pending = controller.load(1)
  assert.equal(request[0], '/api/v1/stats/trends')
  assert.equal(request[1].days, 7)
  page._dashboardLoadId = 2
  resolve([{ date: '2026-10-28', accuracy: 80, questions: 5 }])
  await pending
  assert.equal(page.data.trendAvailable, false)
  assert.equal(patches.length, 1, 'stale response must not commit success or final loading state')
  assert.equal(patches[0].trendLoading, true)
})

test('teacher ports preserve request contract, inflight identity and live caches', async () => {
  const { page, adapter, calls, api } = fixture()
  const ports = adapter('teacher', 'buildReview408TeacherPageCapabilities', { api })
  const promise = Promise.resolve('result')
  ports.setInflight('key', promise)
  assert.equal(ports.getInflight('key'), promise)
  ports.deleteInflight('key')
  assert.equal(ports.getInflight('key'), undefined)
  const result = { content: 'analysis' }
  ports.setCacheEntry('key', result)
  assert.equal(ports.getCacheEntry('key'), result)
  page._teacherCache = { key: 'replacement' }
  assert.equal(ports.getCacheEntry('key'), 'replacement')
  assert.equal(ports.nextRequestSequence(), 1)
  assert.equal(ports.getRequestSequence(), 1)
  const payload = { question_id: 4, action: 'core_concept' }
  await ports.postTeacher(payload)
  assert.equal(calls[0][0], 'post')
  assert.equal(calls[0][1], '/ai/408-teacher')
  assert.equal(calls[0][2], payload)
  assert.equal(calls[0][3].timeout, 55000)
})

test('back navigation preserves page lock and invokes runtime platform callbacks', () => {
  const { page, calls, context } = fixture()
  page._returnTo = '/pages/home/home'
  page.handleBack()
  assert.equal(page._navigationLocked, true)
  assert.equal(calls.length, 1)
  assert.equal(calls[0][0], 'back')
  assert.equal(calls[0][1].delta, 1)
  page.handleBack()
  assert.equal(calls.length, 1)
  page._navigationLocked = false
  context.wx.navigateBack = value => calls.push(['replacement', value])
  page.handleBack()
  assert.equal(calls[1][0], 'replacement')
})
