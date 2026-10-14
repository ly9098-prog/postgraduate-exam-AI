// Run: node miniprogram/tests/test-wrong-book-date-filter.js
const assert = require('assert')
const fs = require('fs')
const path = require('path')
const vm = require('vm')
const filter = require('../components/question-filter-panel/date-range')
const filename = path.resolve(__dirname, '../subpackages/study/wrong-book/wrong-book.js')
let now = Date.parse('2026-10-14T23:59:59+08:00')
const requests = []
const pending = []
let hold = false
let fail = false
const api = {
  now: () => now,
  getErrorMessage: () => '网络连接失败，请重试',
  get(url, params) {
    requests.push({ url, params: JSON.parse(JSON.stringify(params)) })
    if (fail) return Promise.reject(new Error('network'))
    if (hold) return new Promise(resolve => pending.push({ url, params, resolve }))
    return Promise.resolve(url.endsWith('task-flow')
      ? { summary: { total_count: 0 }, groups: [] }
      : { items: [], total: 0, total_pages: 0 })
  },
}
let definition
vm.runInNewContext(fs.readFileSync(filename, 'utf8'), {
  Page(value) { definition = value },
  require(name) {
    if (name === '../../../utils/api') return api
    if (name === '../../../config') return {}
    if (name === '../utils/export-capability' || name === '../utils/ai-diagnosis-cache') return {}
    return require(path.resolve(path.dirname(filename), name))
  },
  console: { error() {}, warn() {}, log() {} },
  setTimeout, clearTimeout, wx: {},
}, { filename })
let panelDefinition
const panelFilename = path.resolve(__dirname, '../components/question-filter-panel/index.js')
vm.runInNewContext(fs.readFileSync(panelFilename, 'utf8'), {
  Component(value) { panelDefinition = value },
  require(name) {
    if (name === '../../utils/api') return api
    return require(path.resolve(path.dirname(panelFilename), name))
  },
}, { filename: panelFilename })
function page() {
  const p = Object.assign({}, definition, {
    data: JSON.parse(JSON.stringify(definition.data)), _alive: true, _destroyed: false,
    setData(patch, callback) {
      Object.assign(this.data, patch)
      if (this.panel && ['selectedDatePreset', 'dateFrom', 'dateTo'].some(key => key in patch)) this.syncPanel()
      if (callback) callback()
    },
    syncPanel() {
      Object.assign(this.panel.data, { preset: this.data.selectedDatePreset, dateFrom: this.data.dateFrom, dateTo: this.data.dateTo })
      panelDefinition.observers['preset, dateFrom, dateTo'].call(this.panel, this.data.selectedDatePreset, this.data.dateFrom, this.data.dateTo)
    },
    _decorateItem: item => item,
    _buildAnalysis(stats) { this.analysisStats = stats; return {} },
    _buildTaskGroups: () => ({ groups: [], ungroupedCount: 0 }),
  })
  p.panel = Object.assign({}, panelDefinition.methods, {
    data: { ...JSON.parse(JSON.stringify(panelDefinition.data)), preset: '', dateFrom: '', dateTo: '' },
    setData(patch) { Object.assign(this.data, patch) },
    triggerEvent(name, detail) {
      const handler = { datechange: 'onDateFilterChange', subjectchange: 'selectSubject', errorchange: 'selectErrorType', reset: 'resetFilters', cleartopic: 'clearTopic', retrysubjects: 'loadSubjects' }[name]
      if (handler) p[handler]({ detail })
    },
  })
  p.syncPanel()
  panelDefinition.lifetimes.attached.call(p.panel)
  return p
}
const event = value => ({ currentTarget: { dataset: { value } } })
const tick = () => new Promise(resolve => setImmediate(resolve))
const clone = value => JSON.parse(JSON.stringify(value))

async function run() {
  assert.deepStrictEqual(filter.presetRange('today', now), { dateFrom: '2026-10-14', dateTo: '2026-10-14' })
  assert.deepStrictEqual(filter.presetRange('week', now), { dateFrom: '2026-10-08', dateTo: '2026-10-14' })
  assert.deepStrictEqual(filter.presetRange('month', now), { dateFrom: '2026-09-15', dateTo: '2026-10-14' })
  assert.strictEqual(filter.validateRange('2026-10-15', '2026-10-14'), '开始日期不能晚于结束日期')
  assert(filter.validateRange('2026-02-30', '2026-10-14'))
  assert.strictEqual(filter.validateRange('2028-02-29', '2028-03-01'), '')

  const p = page()
  p.setData({ selectedSubjectId: 17, selectedErrorType: 'careless', selectedTopic: '树' })
  p.panel.selectDatePreset(event('week'))
  await tick()
  assert.strictEqual(p.data.filterCount, 4)
  const listRequest = requests.find(item => item.url === '/wrong-questions')
  assert.deepStrictEqual(listRequest.params, {
    page: 1, page_size: 20, product_scope: 'exam408', subject_id: 17,
    error_type: 'careless', topic: '树', date_from: '2026-10-08', date_to: '2026-10-14',
  })
  const flowRequest = requests.find(item => item.url.endsWith('task-flow'))
  assert.strictEqual(flowRequest.params.date_from, listRequest.params.date_from)
  assert.strictEqual(flowRequest.params.date_to, listRequest.params.date_to)
  assert.deepStrictEqual(clone(p.analysisStats), {}, 'filtered analysis must not mix global statistics')

  p.setData({ hasMore: true })
  p.loadMore()
  await tick()
  assert.strictEqual(requests.at(-1).params.page, 2)
  assert.strictEqual(requests.at(-1).params.date_from, '2026-10-08')

  // Custom inputs are drafts: malformed/reversed ranges never cause a request.
  p.panel.selectDatePreset(event('custom'))
  const count = requests.length
  p.panel.onDateFromChange({ detail: { value: '2026-10-15' } })
  p.panel.onDateToChange({ detail: { value: '2026-10-14' } })
  p.panel.applyDateRange()
  assert.strictEqual(requests.length, count)
  assert.strictEqual(p.panel.data.dateFilterError, '开始日期不能晚于结束日期')
  p.panel.onDateFromChange({ detail: { value: '2026-10-01' } })
  p.panel.applyDateRange()
  await tick()
  assert.strictEqual(p.data.dateFrom, '2026-10-01')
  assert.strictEqual(p.panel.data.dateRangeText, '2026.10.01 - 2026.10.14')
  assert.strictEqual(p.panel.data.dateFilterError, '')

  now += 2000
  p._syncDateFilter()
  panelDefinition.pageLifetimes.show.call(p.panel)
  assert.strictEqual(p.panel.data.filterToday, '2026-10-15')
  assert.strictEqual(p.data.dateTo, '2026-10-14', 'custom dates remain fixed across midnight')
  p.panel.selectDatePreset(event('today'))
  await tick()
  assert.strictEqual(p.data.dateFrom, '2026-10-15')
  assert.strictEqual(p.data.dateTo, '2026-10-15')

  // A relative range changing across midnight restarts pagination instead of mixing days.
  p.setData({ list: [{ id: 99 }], page: 2, hasMore: true })
  now += 24 * 60 * 60 * 1000
  p.loadMore()
  await tick()
  const midnightList = requests.filter(item => item.url === '/wrong-questions').at(-1)
  assert.strictEqual(midnightList.params.page, 1)
  assert.strictEqual(midnightList.params.date_from, '2026-10-16')
  assert.strictEqual(p.data.list.length, 0)

  p.resetFilters()
  await tick()
  assert.strictEqual(p.data.filterCount, 0)
  assert.strictEqual(p.panel.data.dateRangeText, '')
  assert.strictEqual(p.panel.data.draftDateFrom, '')
  assert(!('date_from' in requests.at(-1).params))

  // Extracting the panel preserves the incumbent subject, cause and topic events.
  p.panel.selectSubject(event(17))
  await tick()
  assert.strictEqual(p.data.selectedSubjectId, 17)
  p.panel.selectErrorType(event('careless'))
  await tick()
  assert.strictEqual(p.data.selectedErrorType, 'careless')
  p.setData({ selectedTopic: '树' })
  p.panel.clearTopic()
  await tick()
  assert.strictEqual(p.data.selectedTopic, '')
  p.panel.reset()
  await tick()
  assert.strictEqual(p.data.filterCount, 0)

  // A slower response to the previous date must not overwrite a newer filter.
  hold = true
  const q = page()
  q.panel.selectDatePreset(event('week'))
  q.panel.selectDatePreset(event('today'))
  assert.strictEqual(pending.length, 2)
  pending[1].resolve({ items: [{ id: 2 }], total: 1, total_pages: 1 })
  await tick()
  pending[0].resolve({ items: [{ id: 1 }], total: 1, total_pages: 1 })
  await tick()
  assert.strictEqual(q.data.list[0].id, 2)
  assert.strictEqual(q.data.loading, false)
  pending[2].resolve({ summary: { total_count: 1 }, groups: [] })
  await tick()

  hold = false
  fail = true
  await q.loadList(true)
  assert.strictEqual(q.data.listError, '网络连接失败，请重试')
  assert.strictEqual(q.data.loading, false)
  fail = false
  await q.retryList()
  assert.strictEqual(q.data.listError, '')
  const wxml = fs.readFileSync(filename.replace(/\.js$/, '.wxml'), 'utf8')
  assert(wxml.includes('!showFilter && filterCount === 0 && !listError'), 'empty-page overflow lock must not clip filters or error recovery')
  console.log('PASS: wrong-book date presets, custom range, paging, reset, races and errors')
}
run().catch(error => { console.error(error); process.exitCode = 1 })
