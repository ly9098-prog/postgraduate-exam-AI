const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const { test } = require('node:test')

const filename = path.resolve(__dirname, '../subpackages/study/wrong-book/wrong-book.js')
const clone = value => JSON.parse(JSON.stringify(value))

function fixture() {
  let definition
  vm.runInNewContext(fs.readFileSync(filename, 'utf8'), {
    Page(value) { definition = value },
    require(request) {
      if (['../../../utils/api', '../../../config', '../utils/ai-diagnosis-cache',
        '../utils/export-capability'].includes(request)) return {}
      return require(path.resolve(path.dirname(filename), request))
    },
    console, setTimeout, clearTimeout, wx: {},
  }, { filename })
  return Object.assign({}, definition, {
    data: clone(definition.data),
    setData(patch) { Object.assign(this.data, patch) },
  })
}

test('wrong-book values preserve fallback and zero-mastery behavior', () => {
  const page = fixture()
  assert.equal(page._positiveNumber(-1, 7), 7)
  assert.equal(page._positiveNumber('1.5', 0), 2)
  assert.deepEqual(clone(page._masteryProgress({ mastery_progress: 0 }, 2)),
    { percent: 40, label: '按复习次数估算' })
  assert.deepEqual(clone(page._masteryProgress({ mastery_progress: 0.39 }, 2)),
    { percent: 39, label: '待攻克' })
  assert.equal(page._masteryProgress({ is_mastered: true }, 0).percent, 100)
  assert.equal(page._errorTypeLabel('concept_mistake'), '概念错误')
})

test('subject options flatten active nested nodes and keep first duplicate', () => {
  const page = fixture()
  assert.deepEqual(clone(page._flattenSubjectOptions({ items: [
    { id: 1, name: 'root', children: [
      { subject_id: '2', subject_name: 'child' },
      { id: 3, name: 'inactive', is_active: false, children: [{ id: 4, name: 'hidden' }] },
    ] },
    { id: 2, name: 'duplicate' },
  ] })), [{ value: 1, label: 'root' }, { value: 2, label: 'child' }])
})

test('item projection reads current page helpers and leaves the input untouched', () => {
  const page = fixture()
  const item = { id: 1, wrong_count: 2, review_record_count: 0, review_count: 8,
    content: { text: 'question' }, image_url: ['image'], error_type: 'careless' }
  const before = clone(item)
  page._subjectLabel = () => 'injected subject'
  page._toCleanText = () => ''
  const decorated = page._decorateItem(item)
  assert.equal(decorated._subjectLabel, 'injected subject')
  assert.equal(decorated._cleanText, '图片题 · 点击查看完整题目')
  assert.equal(decorated._reviewCount, 0)
  assert.deepEqual(item, before)
  page._subjectLabel = () => 'replaced subject'
  assert.equal(page._decorateItem(item)._subjectLabel, 'replaced subject')
})

test('task groups deduplicate by id and prioritize due before high-frequency', () => {
  const page = fixture()
  const list = [
    { id: 1, _isTodayDue: true, _isOverdue: false, _wrongCount: 8 },
    { id: 2, _isTodayDue: true, _isOverdue: true, _wrongCount: 1 },
    { id: 1, _wrongCount: 9 },
    ...[3, 4, 5, 6].map(id => ({ id, _wrongCount: id })),
    { id: 7, _isMastered: true, _wrongCount: 20 },
  ]
  const result = page._buildTaskGroups(list)
  assert.deepEqual(clone(result.groups.map(group =>
    [group.key, group.total, group.items.map(item => item.id)])),
  [['today', 2, [2, 1]], ['high', 4, [6, 5, 4]], ['mastered', 1, [7]]])
  assert.equal(result.ungroupedCount, 2)
})

test('analysis supports alternate stats shapes and preserves live helper overrides', () => {
  const page = fixture()
  const stats = { by_error_type: { calculation: 2, careless: 4 },
    by_subject: [{ subject_id: 10, subject_name: 'DS', count: 3 }], unmastered: 0 }
  const analysis = page._buildAnalysis(stats, [])
  assert.equal(analysis.sourceLabel, '按错因统计')
  assert.equal(analysis.weaknessTags[0].key, 'careless')
  assert.equal(analysis.radarItems[0].percent, 100)
  assert.equal(analysis.summaryCards[0].value, 0)
  assert.equal(analysis.subjectItems[0].label, 'DS')
  page._errorTypeLabel = key => `override:${key}`
  assert.equal(page._buildAnalysis(stats, []).weaknessTags[0].label, 'override:careless')
})

test('list fallback analysis keeps counts and empty radar state', () => {
  const page = fixture()
  const rows = [{ id: 1, error_type: 'careless', subject_id: 10, subject_name: 'DS' }]
  assert.equal(page._buildAnalysis({}, rows).sourceLabel, '按当前列表统计')
  assert.deepEqual(clone(page._countsFromList(rows, 'error_type')),
    [{ key: 'careless', label: 'DS', count: 1 }])
  assert.equal(page._radarPolygonStyle([]), '')
  assert.equal(page._radarAxisText([]), '暂无能力图谱数据')
  assert.deepEqual(clone(page._buildActionPlan()), [])
})

test('view capability getters preserve page binding and live method replacement', () => {
  const {
    buildItemViewCapabilities, buildAnalysisViewCapabilities,
  } = require('../subpackages/study/wrong-book/utils/wrong-book-view-page-adapter')
  const page = fixture()
  const other = fixture()
  page.marker = 1
  other.marker = 2
  page._subjectLabel = other._subjectLabel = function () { return this.marker }
  const item = buildItemViewCapabilities(page)
  const analysis = buildAnalysisViewCapabilities(page)
  const captured = item.subjectLabel
  page._subjectLabel = function () { return this.marker + 10 }
  assert.equal(captured(), 1)
  assert.equal(item.subjectLabel(), 11)
  assert.equal(analysis.subjectLabel(), 11)
  assert.equal(buildItemViewCapabilities(other).subjectLabel(), 2)
})
