// Run: node miniprogram/tests/test-review-submit-completion.js
const assert = require('assert')
const fs = require('fs')
const path = require('path')
const vm = require('vm')
const root = path.resolve(__dirname, '..')
const pagePath = path.join(root, 'subpackages/study/review-today/review-today.js')
const adapter = require('../subpackages/study/utils/question-runner-adapter')
let definition
const apiCalls = []
vm.runInNewContext(fs.readFileSync(pagePath, 'utf8'), {
  Page(value) { definition = value },
  require(request) {
    if (request === '../../../utils/api') return { async post(url, payload) {
      apiCalls.push({ url, payload })
      return { results: [] }
    } }
    if (request === '../../../config' || request === '../../../utils/storage') return {}
    return require(path.resolve(path.dirname(pagePath), request))
  },
  wx: { showToast() {} }, console, setTimeout, clearTimeout, setInterval, clearInterval,
})
const questions = [
  { schedule_id: 1, question_id: 11, question_version_id: 21, occurrence_seq: 1 },
  { schedule_id: 2, question_id: 12, question_version_id: 22, occurrence_seq: 1 },
]
function page(answers = {}, choice = true) {
  const target = Object.assign({}, definition, {
    data: { groupQuestions: questions.slice(), phase: 'reviewing', submittingGroup: false },
    _alive: true, _reviewSession: { answers }, dialogs: [], jumps: [], clearCount: 0,
    setData(patch) { Object.assign(this.data, patch) },
    selectComponent() { return { show: async opts => { target.dialogs.push(opts); return choice } } },
    _showQuestion(index) { this.jumps.push(index) },
    _clearMasterUndo() { this.clearCount++ },
    async _syncReviewSessionDayIfNeeded() { return true },
    _getReviewRequestId(q) { return `test-${q.schedule_id}` },
    _buildReviewTimingSession() { return null },
  })
  return target
}
async function run() {
  let p = page()
  await p.submitGroup()
  assert.strictEqual(apiCalls.length, 0)
  assert.deepStrictEqual(p.jumps, [0])
  assert.strictEqual(p.dialogs[0].showCancel, false)
  assert.strictEqual(p.dialogs[0].layout, 'minimal')
  assert.strictEqual(p.dialogs[0].confirmText, '继续作答')
  assert.strictEqual(p.clearCount, 0)
  p = page({ 1: 'A' })
  await p.submitGroup()
  assert.deepStrictEqual(p.jumps, [1])
  assert.strictEqual(apiCalls.length, 0)
  p = page({}, false)
  await p.submitGroup()
  assert.strictEqual(p.jumps.length, 0)
  p = page({ 1: 'A', 2: 'B' }, false)
  await p.submitGroup()
  assert.strictEqual(apiCalls.length, 0)
  assert.strictEqual(p.dialogs[0].cancelText, '继续检查')
  p = page({ 1: 'A', 2: 'B' })
  await p.submitGroup()
  assert.strictEqual(apiCalls.length, 1)
  assert.strictEqual(apiCalls[0].url, '/review/grade-batch')
  assert.deepStrictEqual(Array.from(apiCalls[0].payload.reviews, r => r.user_answer), ['A', 'B'])
  assert.strictEqual(p.data.submittingGroup, false)
  p = page({ 1: 'A', 2: 'B' })
  p.selectComponent = () => ({ show: async () => { delete p._reviewSession.answers[2]; return true } })
  await p.submitGroup()
  assert.strictEqual(apiCalls.length, 1, 'must revalidate answers after dialog')
  p = page({ 1: 'A', 2: 'B' })
  p.selectComponent = () => ({ show: async () => { p.data.groupQuestions = []; return true } })
  await p.submitGroup()
  assert.strictEqual(apiCalls.length, 1, 'changed group cannot submit')
  p = page()
  let resolve
  p.selectComponent = () => ({ show: () => { p.dialogs.push({}); return new Promise(r => { resolve = r }) } })
  const pending = p.submitGroup()
  await p.submitGroup()
  assert.strictEqual(p.dialogs.length, 1, 'prevent double dialog/submission')
  resolve(false)
  await pending
  assert.strictEqual(p._submitConfirmPending, false)
  p = page()
  p.selectComponent = () => ({ show: async () => { throw new Error('closed') } })
  await p.submitGroup()
  assert.strictEqual(p._submitConfirmPending, false)
  p = page()
  p.data.groupQuestions = []
  await p.submitGroup()
  assert.strictEqual(p.dialogs.length, 0)
  const multi = { schedule_id: 3, question_type: 'multi_blank_choice', blank_option_groups: [{ id: '①', options: [{ key: 'A', text: '甲' }] }, { id: '②', options: [{ key: 'B', text: '乙' }] }] }
  assert.strictEqual(adapter.isQuestionAnswered(multi, { 3: '①:A' }, 'schedule_id'), false)
  assert.strictEqual(adapter.isQuestionAnswered(multi, { 3: '①:A;②:B' }, 'schedule_id'), true)
  p = page({ 3: '①:A' })
  p.data.groupQuestions = [multi]
  await p.submitGroup()
  assert.strictEqual(p.dialogs[0].scenario, 'unanswered')
  assert.deepStrictEqual(p.jumps, [0])
  assert.strictEqual(apiCalls.length, 1)
  const template = fs.readFileSync(path.join(root, 'subpackages/study/review-today/review-today.wxml'), 'utf8')
  assert(template.includes('<submit-confirm id="submitConfirm" theme="mint" />'))
  console.log('Review submit completion regression passed')
}
run().catch(error => { console.error(error); process.exitCode = 1 })
