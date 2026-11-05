const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const { test } = require('node:test')

const root = path.resolve(__dirname, '../subpackages/study/wrong-detail')
const helpers = ['_aiPollDelayMs', '_isTimeoutError', '_generationMarker',
  '_fallbackMessage', '_processWqData', '_hasStoredAnalysisValue',
  '_detectAiCache', '_resolvePreferredAnalysis', '_isWqMastered']
const clone = value => JSON.parse(JSON.stringify(value))

function fixture() {
  let definition
  const calls = []
  const api = { post: (...args) => { calls.push(['post', ...args]); return Promise.resolve({}) } }
  const config = { DEV: true }
  const stem = { buildRenderModel: (...args) => { calls.push(['render', ...args]); return { mode: 'PLAIN' } } }
  const cache = new Map()
  const context = vm.createContext({
    Page: value => { definition = value },
    console, setTimeout, clearTimeout,
    wx: { showToast: options => calls.push(['toast', options]) },
  })
  function load(filename) {
    if (cache.has(filename)) return cache.get(filename).exports
    const module = { exports: {} }
    cache.set(filename, module)
    const required = request => {
      if (request === '../../../utils/api') return api
      if (request === '../../../config') return config
      if (request === '../utils/stem-render') return stem
      const resolved = require.resolve(path.resolve(path.dirname(filename), request))
      return resolved.startsWith(root + path.sep) ? load(resolved) : require(resolved)
    }
    let source = fs.readFileSync(filename, 'utf8')
    if (filename === path.join(root, 'wrong-detail.js')) {
      source += `\nglobalThis.rules = { ${helpers.join(', ')} }\n`
    }
    vm.runInContext(`(function(require,module,exports) {\n${source}\n})`,
      context, { filename })(required, module, module.exports)
    return module.exports
  }
  load(path.join(root, 'wrong-detail.js'))
  const makePage = () => {
    const page = Object.assign({}, definition, {
      data: clone(definition.data),
      setData(patch) { Object.assign(this.data, patch) },
    })
    page.data.aiAvailabilityEnabled = true
    return page
  }
  return { rules: context.rules, page: makePage(), makePage, calls, api, config, context }
}

test('AI cache rejects primitive-looking strings and non-ready generations', () => {
  const { rules } = fixture()
  for (const value of [null, undefined, '', ' ', 'null', 'TRUE', 'false', '[]', '{}', '-1.2']) {
    assert.equal(rules._hasStoredAnalysisValue(value), false, String(value))
  }
  assert.equal(rules._hasStoredAnalysisValue('legacy prose'), true)
  assert.equal(rules._detectAiCache({ ai_analysis: 'legacy prose' }), true)
  assert.equal(rules._detectAiCache({
    ai_analysis_status: 'generating', ai_analysis: 'legacy prose',
  }), false)
  assert.equal(rules._detectAiCache({
    ai_analysis_status: 'ready', ai_analysis: 'legacy prose',
  }), true)
})

test('preferred analysis keeps AI-first and question fallback sources', () => {
  const { rules } = fixture()
  assert.equal(rules._resolvePreferredAnalysis(null), null)
  assert.equal(rules._resolvePreferredAnalysis({
    ai_analysis: 'AI explanation', analysis: 'question explanation',
  }).source, 'ai')
  assert.equal(rules._resolvePreferredAnalysis({
    ai_analysis_status: 'generating', ai_analysis: 'old', analysis: 'question explanation',
  }).source, 'question')
  assert.equal(rules._resolvePreferredAnalysis({ ai_analysis: '{}' }), null)
})

test('poll delays timeout errors and mastery aliases keep their boundaries', () => {
  const { rules } = fixture()
  assert.deepEqual([1, 5, 6, 15, 16].map(rules._aiPollDelayMs), [2000, 2000, 3000, 3000, 5000])
  assert.equal(rules._isTimeoutError({ raw: { errMsg: 'request:fail TIMEOUT' } }), true)
  assert.equal(rules._isTimeoutError({ message: 'timed out' }), true)
  assert.equal(rules._isTimeoutError({ message: 'network' }), false)
  assert.equal(rules._generationMarker({ ai_analysis_generated_at: 123 }), '123')
  assert.equal(rules._fallbackMessage('', 'ai_provider_auth_failed', true),
    'AI 服务连接异常，待服务恢复后可重试')
  assert.equal(rules._fallbackMessage('timeout', '', false), 'AI 分析生成超时，请稍后重试')
  assert.equal(rules._isWqMastered({ review_status: 'mastered' }), true)
  assert.equal(rules._isWqMastered({ is_mastered: false }), false)
})

test('question rendering keeps true-false defaults and live config safe-mode flags', () => {
  const { rules, calls, config } = fixture()
  const question = { id: 1, question_type: 'true_false', answer: 'A', wrong_answer: 'B' }
  const result = rules._processWqData(question, false)
  assert.equal(result.wq, question)
  assert.deepEqual(clone(result._opts), { A: '正确', B: '错误' })
  assert.deepEqual(clone(calls[0][3]), { enableMathImage: false, DEV: true })
  config.DEV = false
  rules._processWqData(question, true)
  assert.deepEqual(clone(calls[1][3]), { enableMathImage: false, DEV: false, SAFE_MODE: true })
  assert.equal(question.options, undefined)
})

test('teacher controller stays lazy per page and reads current page fields and methods', () => {
  const { page, makePage, calls, context } = fixture()
  const controller = page._teacherActionController()
  assert.equal(controller, page._teacherActionController())
  assert.notEqual(controller, makePage()._teacherActionController())
  context.wx = { showToast: options => calls.push(['replacement-toast', options]) }
  page.data.aiLoading = true
  controller.run({ currentTarget: { dataset: { action: 'explain_correct' } } })
  assert.equal(calls.at(-1)[0], 'replacement-toast')
  assert.equal(calls.at(-1)[1].title, 'AI 复盘生成中，请稍后')
  assert.equal(calls.filter(item => item[0] === 'post').length, 0)
})

test('teacher request preserves version diagnosis payload and cached feedback', async () => {
  const { page, api, calls } = fixture()
  page._alive = true
  page.data.wq = { id: 1, question_id: 7, question_version_id: 9, wrong_answer: 'B' }
  page.data.errorDiagnosis = { id: 3, question_version_id: 11 }
  page._teacherCacheKeyForWrong = () => 'live-key'
  api.post = (...args) => {
    calls.push(['post', ...args])
    return Promise.resolve({ action: 'explain_correct', summary: 'explanation' })
  }
  const event = { currentTarget: { dataset: { action: 'explain_correct' } } }
  await page.run408TeacherAction(event)
  assert.deepEqual(clone(calls[0]), ['post', '/ai/408-teacher', {
    question_id: 7, action: 'explain_correct', question_version_id: 11,
    diagnosis_id: 3, user_answer: 'B',
  }, { timeout: 55000 }])
  assert.equal(page.data.teacherResult.summary, 'explanation')
  assert.equal(page._activeTeacherCacheKey, 'live-key')
  assert.equal(page._teacherInflight['live-key'], undefined)
  page._teacherFeedbackCache = { 'live-key': 'helpful' }
  await page.run408TeacherAction(event)
  assert.equal(calls.length, 1)
  assert.equal(page.data.teacherFeedbackSent, 'helpful')
})

test('late teacher response cannot replace the next question or clear a newer inflight', async () => {
  const { page, api } = fixture()
  page._alive = true
  page.data.wq = { id: 1, question_id: 7 }
  page._teacherCacheKeyForWrong = () => 'key'
  let resolve
  api.post = () => new Promise(done => { resolve = done })
  const pending = page.run408TeacherAction({
    currentTarget: { dataset: { action: 'explain_correct' } },
  })
  const newer = Promise.resolve('newer request')
  page._teacherInflight.key = newer
  page.data.wq = { id: 2, question_id: 8 }
  resolve({ action: 'explain_correct', summary: 'old explanation' })
  await pending
  assert.equal(page.data.teacherResult, null)
  assert.equal(page.data.teacherLoadingAction, '')
  assert.equal(page._teacherInflight.key, newer)
  assert.equal(page._teacherCache.key.summary, 'old explanation')
})

test('teacher error cannot write view state after unload', async () => {
  const { page, api } = fixture()
  page._alive = true
  page.data.wq = { id: 1, question_id: 7 }
  let reject
  api.post = () => new Promise((resolve, fail) => { reject = fail })
  const pending = page.run408TeacherAction({
    currentTarget: { dataset: { action: 'explain_correct' } },
  })
  page._alive = false
  let writes = 0
  page.setData = () => { writes++ }
  reject(new Error('network'))
  await pending
  assert.equal(writes, 0)
})

test('teacher availability failure disables actions and shows the exact reason', async () => {
  const { page, api, calls } = fixture()
  page._alive = true
  page.data.wq = { id: 1, question_id: 7 }
  page._teacherCacheKeyForWrong = () => 'availability-key'
  page._scheduleAiAvailabilityRetry = () => {}
  api.post = async () => {
    throw new (require('../utils/api-error').ApiError)('request failed', {
      statusCode: 503,
      detail: {
        code: 'ai_service_unavailable', status: 'unavailable', enabled: false,
        reason: 'configuration', message: 'AI 服务配置或权限异常，等待管理员处理',
        retry_after_ms: 300000,
      },
    })
  }

  await page.run408TeacherAction({
    currentTarget: { dataset: { action: 'explain_correct' } },
  })

  assert.equal(page.data.aiAvailabilityEnabled, false)
  assert.equal(page.data.aiAvailabilityReason, 'configuration')
  assert.equal(page.data.teacherErrorText, 'AI 服务配置或权限异常，等待管理员处理')
  assert.equal(page.data.teacherLoadingAction, '')
  assert.equal(page.data.teacherResult, null)
})
