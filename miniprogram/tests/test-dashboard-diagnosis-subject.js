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
    setTimeout: () => 1, clearTimeout() {},
    wx: { navigateTo: value => navigation.push(value.url), showToast() {} },
    console: { warn() {}, error() {}, log() {} },
  }, { filename })
  const page = Object.assign({}, definition, {
    data: clone(definition.data), _alive: true, _visible: true,
    setData(patch, callback) { Object.assign(this.data, patch); if (callback) callback() },
  })
  page.onLoad(options)
  page.data.subjects = { focusItem: { subjectId: 302 } }
  return {
    page, calls, pending, navigation,
    hold(value) { hold = value }, fail(value) { fail = value }, empty(value) { empty = value },
  }
}
const select = subjectId => ({ currentTarget: { dataset: { subjectId } } })
const tick = () => new Promise(resolve => setImmediate(resolve))

async function run() {
  const opts = buildDiagnosisSubjectOptions(catalog)
  assert.deepStrictEqual(opts.map(item => item.subjectId), [301, 302, 303, 304])
  assert(!opts.some(item => item.subjectId === 900 || item.subjectId === 305))
  assert.strictEqual(buildDiagnosisSubjectOptions([{ subject_id: 900, is_active: false, children: catalog[0].children }]).length, 0)

  let h = harness({ focus_subject_id: '301' })
  await h.page.loadKnowledgeDiagnosisSubjects()
  assert.strictEqual(h.page.data.knowledgeDiagnosisSubjectId, 301, 'route focus takes precedence initially')
  assert.strictEqual(h.page.data.knowledgeDiagnosisSubjects.length, 4, 'include subjects without practice history')
  await h.page.selectKnowledgeDiagnosisSubject(select(303))
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
  const first = h.page.selectKnowledgeDiagnosisSubject(select(301))
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

  h.hold(true)
  const hiddenRequest = h.page.selectKnowledgeDiagnosisSubject(select(304))
  h.page.onHide()
  h.pending.at(-1).resolve(diagnosis(304))
  await hiddenRequest
  assert.strictEqual(h.page.data.knowledgeDiagnosis, null)
  assert.strictEqual(h.page.data.knowledgeDiagnosisLoading, false)
  h.hold(false)
  h.page.data.pageReady = true
  h.page._lastLoadAt = Date.now()
  h.page.onShow()
  await tick()
  assert.strictEqual(h.page.data.knowledgeDiagnosis.subjectId, 304, 'return within dashboard debounce restarts interrupted subject request')

  h = harness()
  h.fail(true)
  await h.page.loadKnowledgeDiagnosisSubjects()
  assert.strictEqual(h.page.data.knowledgeDiagnosisSubjectsError, '学科加载失败，请重试')
  assert.strictEqual(h.page.data.knowledgeDiagnosisSubjectsLoading, false)
  h.fail(false)
  await h.page.loadKnowledgeDiagnosisSubjects()
  assert.strictEqual(h.page.data.knowledgeDiagnosisSubjectsError, '')
  assert.strictEqual(h.page.data.knowledgeDiagnosis.subjectId, 302)
  console.log('PASS: dashboard subject catalog, selection, refresh, races, empty/error and return-to-practice')
}
run().catch(error => { console.error(error); process.exitCode = 1 })
