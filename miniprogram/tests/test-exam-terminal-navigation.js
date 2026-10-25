// Run: node miniprogram/tests/test-exam-terminal-navigation.js
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')

const root = path.resolve(__dirname, '..')
const pagePath = path.join(root, 'subpackages/exam/exam-runner/index.js')
let definition
let redirectOptions
const toasts = []

vm.runInNewContext(fs.readFileSync(pagePath, 'utf8'), {
  Page(value) { definition = value },
  require(request) {
    if (request === '../../../utils/api') return { now: () => 1, getErrorMessage: () => 'error' }
    if (request === '../utils/exam-attempt-cache') {
      return { cacheKey: id => `v3:${id}`, v2CacheKey: id => `v2:${id}`, legacyCacheKey: id => `v1:${id}` }
    }
    if (request === '../utils/exam-runner-view') return { buildRenderView() {}, buildAnswerState() {} }
    return require(path.resolve(path.dirname(pagePath), request))
  },
  wx: {
    redirectTo(options) { redirectOptions = options },
    showToast(options) { toasts.push(options) },
  },
  console,
  setTimeout,
  clearTimeout,
  setInterval,
  clearInterval,
})

function page() {
  const target = Object.assign({}, definition, {
    data: { attemptId: 12, submitting: true, resultRecoveryPending: false },
    _pageAlive: true,
    _terminalNavigation: false,
    _navigationLocked: false,
    _attemptTerminal: true,
    _clearTimer() {},
    setData(patch) { Object.assign(this.data, patch) },
  })
  return target
}

const target = page()
target._navigateToResult()
assert.equal(redirectOptions.url, '/subpackages/exam/result/index?attempt_id=12')
assert.equal(target._terminalNavigation, true)
assert.equal(target._navigationLocked, true)

redirectOptions.fail()
assert.equal(target._terminalNavigation, false)
assert.equal(target._navigationLocked, true, 'archived attempt must remain read-only')
assert.equal(target.data.submitting, false)
assert.equal(target.data.resultRecoveryPending, true)
assert.equal(toasts[0].title, '答卷已归档，请重新打开结果页')

target.retryResultNavigation()
assert.equal(redirectOptions.url, '/subpackages/exam/result/index?attempt_id=12')
assert.equal(target._navigationLocked, true)
assert.equal(target.data.resultRecoveryPending, false)

;(async () => {
  let submitted = false
  target._performSubmit = () => { submitted = true }
  assert.equal(await target.submitExam(), false)
  assert.equal(submitted, false, 'terminal navigation lock must reject another submit')

  const source = fs.readFileSync(pagePath, 'utf8')
  const template = fs.readFileSync(path.join(root, 'subpackages/exam/exam-runner/index.wxml'), 'utf8')
  assert(template.includes('readonly="{{timeExpired || submitting || resultRecoveryPending}}"'))
  assert(source.includes('isTimeExpired: () => this.data.timeExpired'))
  assert(source.includes('isSubmitting: () => this.data.submitting'))
  assert(source.includes('isNavigationLocked: () => this._navigationLocked'))
  assert(source.includes('if (this._attemptTerminal || this._navigationLocked) return false'))

  console.log('Exam terminal navigation regression passed')
})().catch((error) => {
  console.error(error)
  process.exitCode = 1
})
