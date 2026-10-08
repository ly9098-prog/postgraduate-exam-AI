// Run: node miniprogram/tests/test-practice-result-diagnosis.js
const assert = require('assert')
const fs = require('fs')
const path = require('path')
const vm = require('vm')
const root = path.resolve(__dirname, '..')
const file = path.join(root, 'subpackages/study/practice-result/index.js')
let definition
let get
vm.runInNewContext(fs.readFileSync(file, 'utf8'), {
  Page(value) { definition = value },
  require(request) {
    if (request === '../../../utils/api') return { get: (...args) => get(...args) }
    if (request === '../../../utils/storage') return {}
    return require(path.resolve(path.dirname(file), request))
  },
  wx: {}, console, setTimeout, clearTimeout,
})
const row = id => ({ wrongQuestionId: id, errorDiagnosisLabel: '暂未分类', status: 'wrong' })
function page() {
  const rows = [row(1), row(2), row(1), row(null)]
  return Object.assign({}, definition, {
    _pageAlive: true, _diagnosisRefreshSeq: 0,
    data: { reviewItems: rows, wrongReviewItems: rows, filteredReviewItems: [rows[1]],
      batchSelectedMap: { 2: true }, activeTab: 'wrong', accuracyPct: 60 },
    setData(patch) { Object.assign(this.data, patch) },
  })
}
async function run() {
  let p = page()
  const wrapped = { diagnosis: { primary_type: 'careless', user_confirmed: true } }
  assert.strictEqual(p.normalizeReviewItem({ errorDiagnosis: wrapped }, 0).errorDiagnosisLabel, '粗心')
  assert.strictEqual(p.buildReviewItem({ id: 10 }, { error_diagnosis: { primaryType: 'misread' } }, {}, 0).errorDiagnosisLabel, '审题错误')
  assert.strictEqual(p.normalizeReviewItem({ error_type: 'calculation' }, 0).errorDiagnosisLabel, '计算错误')
  const calls = []
  get = async (url, params, opts) => {
    calls.push(url)
    assert.strictEqual(opts.suppressNetworkToast, true)
    return url.includes('/1/') ? wrapped : { data: { primary_type: 'misread' } }
  }
  await p.refreshWrongDiagnoses()
  assert.deepStrictEqual(calls.sort(), ['/wrong-questions/1/diagnosis', '/wrong-questions/2/diagnosis'])
  assert.strictEqual(p.data.wrongReviewItems[0].errorDiagnosisLabel, '粗心')
  assert.strictEqual(p.data.wrongReviewItems[2].errorDiagnosisLabel, '粗心')
  assert.strictEqual(p.data.filteredReviewItems.length, 1)
  assert.strictEqual(p.data.filteredReviewItems[0].errorDiagnosisLabel, '审题错误')
  assert.strictEqual(p.data.reviewItems[3].errorDiagnosisLabel, '暂未分类')
  assert.strictEqual(p.data.batchSelectedMap[2], true)
  assert.strictEqual(p.data.accuracyPct, 60)
  get = async () => { throw new Error('offline') }
  await p.refreshWrongDiagnoses()
  assert.strictEqual(p.data.wrongReviewItems[0].errorDiagnosisLabel, '粗心', 'offline must preserve known diagnosis')
  const pending = []
  get = () => new Promise(resolve => pending.push(resolve))
  const old = p.refreshWrongDiagnoses()
  p.onHide()
  pending.forEach(resolve => resolve({ primary_type: 'unknown' }))
  await old
  assert.strictEqual(p.data.wrongReviewItems[0].errorDiagnosisLabel, '粗心', 'ignore stale hidden-page responses')
  p = page()
  const oldResolvers = []
  get = () => new Promise(resolve => oldResolvers.push(resolve))
  const oldRefresh = p.refreshWrongDiagnoses()
  get = async () => ({ primary_type: 'careless' })
  await p.refreshWrongDiagnoses()
  oldResolvers.forEach(resolve => resolve({ primary_type: 'unknown' }))
  await oldRefresh
  assert.strictEqual(p.data.reviewItems[0].errorDiagnosisLabel, '粗心', 'older requests cannot overwrite new diagnosis')
  p = page()
  let refreshed = 0
  p.refreshWrongDiagnoses = () => { refreshed++ }
  p.onShow()
  assert.strictEqual(refreshed, 1, 'returning to page refreshes diagnosis')
  assert.strictEqual(p._navigationLocked, false)
  p = page()
  p.data.batchDiagnosisSaving = true
  get = () => { throw new Error('must not refresh during batch save') }
  await p.refreshWrongDiagnoses()
  p = page()
  p._pageAlive = false
  await p.refreshWrongDiagnoses()
  console.log('Practice result diagnosis refresh regression passed')
}
run().catch(error => { console.error(error); process.exitCode = 1 })
