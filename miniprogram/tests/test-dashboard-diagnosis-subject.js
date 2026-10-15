// Run: node miniprogram/tests/test-dashboard-diagnosis-subject.js
const assert = require('assert')
const fs = require('fs')
const path = require('path')
const vm = require('vm')
const { buildDiagnosisSubjectOptions } = require('../pages/dashboard/dashboard.diagnosis')
const filename = path.resolve(__dirname, '../pages/dashboard/dashboard.js')
const catalog = [{ subject_id: 900, subject_code: 'exam408', children: [
  { subject_id: 301, subject_code: 'data_structure', subject_name: '数据结构' },
  { subject_id: 302, subject_code: 'computer_organization', subject_name: '计算机组成原理' },
  { subject_id: 303, subject_code: 'operating_system', subject_name: '操作系统' },
  { subject_id: 304, subject_code: 'computer_network', subject_name: '计算机网络' },
  { subject_id: 305, subject_code: 'english', subject_name: '英语' },
] }]
const clone = value => JSON.parse(JSON.stringify(value))
function diagnosis(id, empty = false) {
  return {
    subject_id: id, subject_name: `学科${id}`, period_days: 30,
    primary_recommendation: empty ? null : {
      knowledge_point_id: id * 10, title: `章节${id}`, reason: '优先巩固薄弱章节',
      route_params: { count: 12, include_descendants: 1 },
    },
    recommendations: [], report: { session_count: 3 },
  }
}
function harness(options = {}) {
  let definition
  const calls = []
  const pending = []
  const navigation = []
  const patches = []
  const timers = new Map()
  let timerId = 0
  let now = Date.now()
  let bodyHeight = 245
  let hold = false
  let fail = false
  let empty = false
  const api = {
    async get(url, params) {
      calls.push({ url, params })
      if (fail) throw new Error('network')
      if (hold) return new Promise(resolve => pending.push({ url, params, resolve }))
      return url === '/practice/subjects' ? catalog : diagnosis(params.subject_id, empty)
    },
  }
  vm.runInNewContext(fs.readFileSync(filename, 'utf8'), {
    Page(value) { definition = value },
    require(name) {
      if (name === '../../utils/api') return api
      return require(path.resolve(path.dirname(filename), name))
    },
    setTimeout(fn, ms) { const id = ++timerId; timers.set(id, { fn, at: now + ms }); return id },
    clearTimeout(id) { timers.delete(id) },
    Date: class extends Date { static now() { return now } },
    wx: { navigateTo: value => navigation.push(value.url), showToast() {} },
    console: { warn() {}, error() {}, log() {} },
  }, { filename })
  const page = Object.assign({}, definition, {
    data: clone(definition.data), _alive: true, _visible: true,
    setData(patch, callback) {
      patches.push(clone(patch))
      Object.assign(this.data, patch)
      if (callback) callback()
    },
    createSelectorQuery() {
      let callback
      return {
        select() { return this },
        boundingClientRect(fn) { callback = fn; return this },
        exec() { callback({ height: bodyHeight }) },
      }
    },
  })
  page.onLoad(options)
  page.data.subjects = { focusItem: { subjectId: 302 } }
  return {
    page, calls, pending, navigation, patches,
    now() { return now },
    advance(ms) {
      now += ms
      for (const [id, timer] of timers) {
        if (timer.at <= now) { timers.delete(id); timer.fn() }
      }
    },
    bodyHeight(value) { bodyHeight = value },
    hold(value) { hold = value }, fail(value) { fail = value }, empty(value) { empty = value },
  }
}
const select = subjectId => ({ currentTarget: { dataset: { subjectId } } })
const tick = () => new Promise(resolve => setImmediate(resolve))
async function choose(h, id) {
  const result = h.page.selectKnowledgeDiagnosisSubject(select(id))
  h.advance(180)
  return result
}

async function run() {
  const opts = buildDiagnosisSubjectOptions(catalog)
  assert.deepStrictEqual(opts.map(item => item.subjectId), [301, 302, 303, 304])
  assert(!opts.some(item => item.subjectId === 900 || item.subjectId === 305))
  opts.forEach(item => {
    for (const icon of [item.icon, item.selectedIcon]) {
      assert(fs.existsSync(path.resolve(__dirname, '..', '.' + icon)), `subject icon exists: ${icon}`)
    }
  })
  assert.strictEqual(buildDiagnosisSubjectOptions([{ subject_id: 900, is_active: false, children: catalog[0].children }]).length, 0)

  const early = harness()
  await early.page.loadKnowledgeDiagnosis(302)
  const beforeCatalog = early.calls.length
  await early.page.loadKnowledgeDiagnosisSubjects()
  assert.strictEqual(early.page.data.knowledgeDiagnosisSubjectName, '计算机组成原理', 'catalog supplies entry name even when diagnosis arrived first')
  assert.strictEqual(early.calls.length, beforeCatalog + 1, 'catalog name update reuses the cached diagnosis')

  let h = harness({ focus_subject_id: '301' })
  h.page.openKnowledgeSubjectSheet()
  assert.strictEqual(h.page.data.knowledgeSubjectSheetVisible, false, 'cannot open before subjects are available')
  await h.page.loadKnowledgeDiagnosisSubjects()
  assert.strictEqual(h.page.data.knowledgeDiagnosisSubjectId, 301, 'route focus takes precedence initially')
  assert.strictEqual(h.page.data.knowledgeDiagnosisSubjectName, '数据结构')
  assert.strictEqual(h.page.data.knowledgeDiagnosisSubjects.length, 4, 'include subjects without practice history')
  const beforeCancel = h.calls.length
  h.page.openKnowledgeSubjectSheet()
  assert.strictEqual(h.page.data.knowledgeSubjectSheetVisible, true)
  h.page.closeKnowledgeSubjectSheet()
  assert.strictEqual(h.page.data.knowledgeSubjectSheetClosing, true, 'dismissal plays exit before unmounting')
  h.advance(180)
  assert.strictEqual(h.page.data.knowledgeSubjectSheetVisible, false)
  assert.strictEqual(h.page.data.knowledgeDiagnosisSubjectId, 301, 'dismissing the sheet preserves selection')
  assert.strictEqual(h.calls.length, beforeCancel, 'opening and dismissing must not request new recommendations')
  h.page.openKnowledgeSubjectSheet()
  await choose(h, 301)
  assert.strictEqual(h.page.data.knowledgeSubjectSheetVisible, false, 'selecting current subject also dismisses the sheet')
  assert.strictEqual(h.calls.length, beforeCancel, 'selecting current cached subject does not refetch')
  h.page.openKnowledgeSubjectSheet()
  await h.page.selectKnowledgeDiagnosisSubject(select(900))
  assert.strictEqual(h.page.data.knowledgeSubjectSheetVisible, true, 'invalid subject does not dismiss or alter selection')
  const fastPatchesStart = h.patches.length
  await choose(h, 303)
  assert(!h.patches.slice(fastPatchesStart).some(patch => patch.knowledgeDiagnosisLoading === true),
    'a response received during sheet exit skips the skeleton')
  assert.strictEqual(h.page.data.knowledgeSubjectSheetVisible, false)
  assert.strictEqual(h.page.data.knowledgeDiagnosisSubjectName, '操作系统')
  assert.strictEqual(h.page.data.knowledgeDiagnosis.subjectId, 303)
  assert.strictEqual(h.page._preferredKnowledgeSubjectId({ focusItem: { subjectId: 301 } }), 303)
  const count = h.calls.length
  await h.page.selectKnowledgeDiagnosisSubject(select(900))
  assert.strictEqual(h.calls.length, count, 'the aggregate root cannot be selected for chapter diagnosis')
  h.page._processDashboard({ overview: { total_questions: 8 }, subjects: { items: [{ subject_id: 301, subject_code: 'data_structure', accuracy: 0.1, total_questions: 8 }] } }, 'silent')
  await tick()
  assert.strictEqual(h.calls.at(-1).params.subject_id, 303, 'dashboard refresh must retain manual subject selection')
  h.page.startKnowledgeDiagnosisPractice()
  const url = new URL('https://local.invalid' + h.navigation.at(-1))
  assert.strictEqual(url.searchParams.get('subject_id'), '303')
  assert.strictEqual(url.searchParams.get('knowledge_point_id'), '3030')
  assert.strictEqual(url.searchParams.get('count'), '12')
  assert.strictEqual(url.searchParams.get('include_descendants'), '1')
  assert(url.searchParams.get('return_to').includes('focus_subject_id=303'))

  h = harness()
  await h.page.loadKnowledgeDiagnosisSubjects()
  assert.strictEqual(h.page.data.knowledgeDiagnosisSubjectId, 302, 'default recommendation follows weak subject')
  h.hold(true)
  h.page.openKnowledgeSubjectSheet()
  const first = h.page.selectKnowledgeDiagnosisSubject(select(301))
  assert.strictEqual(h.page.data.knowledgeSubjectSheetSelectedId, 301, 'selected tile responds before exit ends')
  assert.strictEqual(h.page.data.knowledgeSubjectSheetClosing, true)
  assert.strictEqual(h.page.data.knowledgeDiagnosisSubjectId, 302, 'entry and content remain coherent during exit')
  assert.strictEqual(h.page.data.knowledgeDiagnosis.subjectId, 302)
  const beforeDoubleTap = h.calls.length
  h.page.selectKnowledgeDiagnosisSubject(select(304))
  assert.strictEqual(h.calls.length, beforeDoubleTap, 'repeated taps during exit do not start another switch')
  h.advance(179)
  assert.strictEqual(h.page.data.knowledgeSubjectSheetVisible, true)
  h.advance(1)
  await tick()
  const switchPatch = h.patches.at(-1)
  assert.strictEqual(switchPatch.knowledgeDiagnosisSubjectId, 301)
  assert.strictEqual(switchPatch.knowledgeDiagnosisLoading, true)
  assert.strictEqual(h.page.data.knowledgeDiagnosisBodyHeight, 245, 'loading preserves measured content height')
  assert.strictEqual(h.page.data.knowledgeSubjectSheetVisible, false, 'sheet closes before recommendation request resolves')
  assert.strictEqual(h.page.data.knowledgeDiagnosisSubjectName, '数据结构', 'entry updates immediately with the selected subject')
  assert.strictEqual(h.page.data.knowledgeDiagnosis, null, 'old recommendation cleared on subject switch')
  h.page.startKnowledgeDiagnosisPractice()
  assert.strictEqual(h.navigation.length, 0, 'cannot start stale-subject practice while loading')
  const second = h.page.selectKnowledgeDiagnosisSubject(select(304))
  h.pending[1].resolve(diagnosis(304))
  await second
  h.pending[0].resolve(diagnosis(301))
  await first
  assert.strictEqual(h.page.data.knowledgeDiagnosis.subjectId, 304, 'slower old response cannot overwrite latest choice')
  assert.strictEqual(h.page.data.knowledgeDiagnosisLoading, false)

  const beforeCached = h.calls.length
  const third = h.page.selectKnowledgeDiagnosisSubject(select(303))
  await h.page.selectKnowledgeDiagnosisSubject(select(302))
  assert.strictEqual(h.calls.length, beforeCached + 1, 'switching back to a fresh cached subject makes no request')
  assert.strictEqual(h.page.data.knowledgeDiagnosis.subjectId, 302)
  assert.strictEqual(h.page.data.knowledgeDiagnosisLoading, false, 'cache selection never enters skeleton state')
  h.pending.at(-1).resolve(diagnosis(303))
  await third
  assert.strictEqual(h.page.data.knowledgeDiagnosis.subjectId, 302, 'cache selection invalidates pending responses too')
  h.bodyHeight(180)
  h.page.openKnowledgeSubjectSheet()
  assert.strictEqual(h.page.data.knowledgeDiagnosisBodyHeight, 245, 'shorter content cannot collapse reserved height')
  await choose(h, 302)
  h.advance(30001)
  h.page.openKnowledgeSubjectSheet()
  const beforeCurrent = h.calls.length
  await choose(h, 302)
  assert.strictEqual(h.calls.length, beforeCurrent, 'current subject is dismissal only even after cache expiry')

  h.hold(false)
  h.fail(true)
  await h.page.selectKnowledgeDiagnosisSubject(select(303))
  assert.strictEqual(h.page.data.knowledgeDiagnosis, null)
  assert.strictEqual(h.page.data.knowledgeDiagnosisError, '章节诊断暂不可用')
  assert.strictEqual(h.page.data.knowledgeDiagnosisLoading, false)
  h.fail(false)
  await h.page.retryKnowledgeDiagnosis()
  assert.strictEqual(h.page.data.knowledgeDiagnosis.subjectId, 303)
  h.empty(true)
  await h.page.selectKnowledgeDiagnosisSubject(select(301))
  assert.strictEqual(h.page.data.knowledgeDiagnosis.primary, null, 'empty chapter recommendation remains a valid subject state')
  h.empty(false)

  h.advance(30001)
  h.hold(true)
  const hiddenRequest = h.page.selectKnowledgeDiagnosisSubject(select(304))
  h.page.openKnowledgeSubjectSheet()
  h.page.onHide()
  assert.strictEqual(h.page.data.knowledgeSubjectSheetVisible, false, 'leaving the page dismisses the sheet')
  h.pending.at(-1).resolve(diagnosis(304))
  await hiddenRequest
  assert.strictEqual(h.page.data.knowledgeDiagnosis, null)
  assert.strictEqual(h.page.data.knowledgeDiagnosisLoading, false)
  h.hold(false)
  h.page.data.pageReady = true
  h.page._lastLoadAt = h.now()
  h.page.onShow()
  await tick()
  assert.strictEqual(h.page.data.knowledgeDiagnosis.subjectId, 304, 'return within dashboard debounce restarts interrupted subject request')

  h = harness()
  await h.page.loadKnowledgeDiagnosisSubjects()
  h.page.openKnowledgeSubjectSheet()
  const interrupted = h.page.selectKnowledgeDiagnosisSubject(select(301))
  h.page.onHide()
  await interrupted
  h.advance(180)
  assert.strictEqual(h.page.data.knowledgeSubjectSheetClosing, false, 'hide cancels exit state and timer')
  assert.strictEqual(h.page.data.knowledgeSubjectSheetVisible, false)
  assert.strictEqual(h.page.data.knowledgeDiagnosis.subjectId, 302, 'hidden completion cannot commit a pending switch')
  h.page._alive = true
  h.page._visible = true
  h.page.openKnowledgeSubjectSheet()
  const dismiss = h.page.closeKnowledgeSubjectSheet()
  h.page.onUnload()
  await dismiss

  h = harness()
  await h.page.loadKnowledgeDiagnosisSubjects()
  await h.page.loadKnowledgeDiagnosis(301)
  h.page.openKnowledgeSubjectSheet()
  const cachePatchesStart = h.patches.length
  const cachedSwitch = h.page.selectKnowledgeDiagnosisSubject(select(302))
  assert.strictEqual(h.page.data.knowledgeDiagnosis.subjectId, 301, 'cache hit also respects sheet exit')
  h.advance(180)
  await cachedSwitch
  assert.strictEqual(h.page.data.knowledgeDiagnosis.subjectId, 302)
  assert(!h.patches.slice(cachePatchesStart).some(patch => patch.knowledgeDiagnosisLoading === true))
  h.fail(true)
  h.page.openKnowledgeSubjectSheet()
  const failedSwitch = h.page.selectKnowledgeDiagnosisSubject(select(303))
  await tick()
  assert.strictEqual(h.page.data.knowledgeDiagnosis.subjectId, 302, 'fast failure waits for sheet exit too')
  h.advance(180)
  await failedSwitch
  assert.strictEqual(h.page.data.knowledgeDiagnosisSubjectId, 303)
  assert.strictEqual(h.page.data.knowledgeDiagnosis, null, 'failure cannot leave another subject recommendation visible')
  assert.strictEqual(h.page.data.knowledgeDiagnosisError, '章节诊断暂不可用')

  h = harness()
  h.fail(true)
  await h.page.loadKnowledgeDiagnosisSubjects()
  assert.strictEqual(h.page.data.knowledgeDiagnosisSubjectsError, '学科加载失败，请重试')
  assert.strictEqual(h.page.data.knowledgeDiagnosisSubjectsLoading, false)
  h.fail(false)
  await h.page.loadKnowledgeDiagnosisSubjects()
  assert.strictEqual(h.page.data.knowledgeDiagnosisSubjectsError, '')
  assert.strictEqual(h.page.data.knowledgeDiagnosis.subjectId, 302)
  console.log('PASS: dashboard subject sheet, catalog, selection, refresh, races, empty/error and return-to-practice')
}
run().catch(error => { console.error(error); process.exitCode = 1 })
