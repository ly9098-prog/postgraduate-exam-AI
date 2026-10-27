// Run: node miniprogram/tests/test-study-plan-save.js
const assert = require('assert')
const fs = require('fs')
const path = require('path')
const vm = require('vm')
const { getChinaDate } = require('../utils/china-time')
const root = path.resolve(__dirname, '..')
const DEFAULT_NOW = Date.parse('2026-10-14T12:00:00+08:00')

function harness(options = {}) {
  let deviceNow = options.deviceNow || DEFAULT_NOW
  let serverNow = options.serverNow || DEFAULT_NOW
  class Clock extends Date {
    constructor(...args) { super(...(args.length ? args : [deviceNow])) }
    static now() { return deviceNow }
  }
  const values = new Map([['token', 'test-token']])
  const requests = []
  const toasts = []
  const wx = {
    getStorageSync: key => values.get(key),
    setStorageSync: (key, value) => values.set(key, value),
    showToast: value => toasts.push(value),
    request(request) {
      requests.push({ method: request.method, url: request.url, data: request.data })
      if (request.method === 'PUT' && options.putAdvanceMs) {
        deviceNow += options.putAdvanceMs
        serverNow += options.putAdvanceMs
      }
      const today = getChinaDate(0, serverNow)
      let statusCode = 200
      let data = { configured: false, date: today }
      if (request.method === 'GET' && options.targetDate) {
        data = {
          configured: true,
          date: today,
          plan: { target_date: options.targetDate, daily_minutes: 90, weekly_days: 6, priority_mode: 'balanced' },
        }
      }
      if (request.method === 'PUT') {
        // Match the backend's calendar-date guard, without exposing server detail.
        statusCode = request.data.target_date < today ? 422 : 200
        data = statusCode === 422 ? { error: { code: 'VALIDATION_ERROR' } } : request.data
      }
      if (options.putError && request.method === 'PUT') {
        statusCode = options.putError
        data = { error: { code: 'VALIDATION_ERROR' } }
      }
      request.success({ statusCode, data, header: { Date: new Date(serverNow).toUTCString() } })
    },
  }
  // Every utility module a loaded file reaches stays inside this vm context so the
  // fake wx/clock are shared, exactly like the Mini Program runtime.
  const loaded = new Map()
  function load(relative, dependencies = {}) {
    return loadFile(path.join(root, relative), dependencies)
  }
  function loadFile(filename, dependencies = {}) {
    if (loaded.has(filename)) return loaded.get(filename).exports
    const module = { exports: {} }
    loaded.set(filename, module)
    vm.runInNewContext(fs.readFileSync(filename, 'utf8'), {
      module, exports: module.exports, wx, Date: Clock, console,
      require(name) {
        if (dependencies[name]) return dependencies[name]
        return loadFile(path.resolve(path.dirname(filename), `${name}.js`))
      },
    }, { filename })
    return module.exports
  }
  const storage = load('utils/storage.js')
  const api = load('utils/api.js', {
    '../config': { BASE_URL: 'http://localhost:8000/api/v1' },
    './storage': storage,
    './debug': { debugLog() {}, saveDebugSnapshot() {} },
  })
  let definition
  const filename = path.join(root, 'subpackages/study/study-plan/index.js')
  vm.runInNewContext(fs.readFileSync(filename, 'utf8'), {
    Page(value) { definition = value }, wx, Date: Clock, console, setTimeout, clearTimeout,
    require(name) {
      if (name === '../../../utils/api') return api
      if (name === '../../../utils/storage') return storage
      return require(path.resolve(path.dirname(filename), name))
    },
  }, { filename })
  const page = Object.assign({}, definition, {
    data: JSON.parse(JSON.stringify(definition.data)),
    setData(patch) { Object.assign(this.data, patch) },
  })
  page._loadStudyStrategy()
  return {
    page, requests, toasts, values, storage,
    puts: () => requests.filter(item => item.method === 'PUT'),
    advance(ms) { deviceNow += ms; serverNow += ms },
  }
}

async function run() {
  // Editing an existing expired plan must not send the PUT that the API rejects.
  let h = harness({ targetDate: '2026-10-13' })
  await h.page.loadOverview()
  await h.page.savePlan()
  assert.strictEqual(h.puts().length, 0, 'expired target date must be stopped before PUT /study-plan returns 422')
  assert.strictEqual(h.toasts.at(-1).title, '目标日期已过期，请重新选择')
  assert.strictEqual(h.page.data.minDate, '2026-10-14')
  assert(h.values.has(h.storage.studyStrategy.STORAGE_KEY), 'local four-subject strategy must still be saved')
  h.page.onTargetDateChange({ detail: { value: '2026-12-20' } })
  await h.page.savePlan()
  assert.strictEqual(h.puts().length, 1, 'a corrected target date can be saved immediately')
  assert.strictEqual(h.page.data.saving, false)

  // Today and future dates retain the existing raw JSON request contract.
  for (const targetDate of ['2026-10-14', '2026-12-20', '2028-02-29']) {
    h = harness()
    await h.page.loadOverview()
    h.page.onTargetDateChange({ detail: { value: targetDate } })
    h.page.onDailyChange({ detail: { value: '7' } })
    h.page.onWeeklyChange({ detail: { value: '4' } })
    h.page.onPriorityChange({ detail: { value: '4' } })
    await h.page.savePlan()
    assert.strictEqual(h.puts().length, 1)
    assert.strictEqual(h.puts()[0].url, 'http://localhost:8000/api/v1/study-plan')
    assert.deepStrictEqual(JSON.parse(JSON.stringify(h.puts()[0].data)), {
      target_date: targetDate, daily_minutes: 240, weekly_days: 7, priority_mode: 'exam',
    })
    assert(h.toasts.some(item => item.title === '计划已创建'))
    assert.strictEqual(h.page.data.saving, false)
  }

  // Use the API's synchronized server clock, not an incorrect device clock.
  for (const deviceNow of [Date.parse('2026-10-13T12:00:00+08:00'), Date.parse('2026-10-15T12:00:00+08:00')]) {
    h = harness({ deviceNow })
    await h.page.loadOverview()
    assert.strictEqual(h.page.data.minDate, '2026-10-14')
    h.page.onTargetDateChange({ detail: { value: '2026-10-14' } })
    await h.page.savePlan()
    assert.strictEqual(h.puts().length, 1, 'server today remains valid when device clock is wrong')
  }

  // A page left open across Shanghai midnight must refresh the date bound.
  h = harness({ deviceNow: Date.parse('2026-10-14T23:59:59+08:00'), serverNow: Date.parse('2026-10-14T23:59:59+08:00') })
  await h.page.loadOverview()
  h.page.onTargetDateChange({ detail: { value: '2026-10-14' } })
  h.advance(2000)
  await h.page.savePlan()
  assert.strictEqual(h.puts().length, 0)
  assert.strictEqual(h.page.data.minDate, '2026-10-15')

  // Midnight can also pass while the request is in flight: retain an actionable error.
  h = harness({
    deviceNow: Date.parse('2026-10-14T23:59:59+08:00'),
    serverNow: Date.parse('2026-10-14T23:59:59+08:00'),
    putAdvanceMs: 2000,
  })
  await h.page.loadOverview()
  h.page.onTargetDateChange({ detail: { value: '2026-10-14' } })
  await h.page.savePlan()
  assert.strictEqual(h.puts().length, 1)
  assert.strictEqual(h.toasts.at(-1).title, '目标日期已过期，请重新选择')
  assert.strictEqual(h.page.data.minDate, '2026-10-15')
  assert.strictEqual(h.page.data.saving, false)

  // Malformed or impossible dates must not reach Pydantic date validation.
  for (const targetDate of ['2026-02-30', '2027-02-29', '2026-13-01', '2026-10-14T00:00:00Z']) {
    h = harness()
    h.page.onTargetDateChange({ detail: { value: targetDate } })
    await h.page.savePlan()
    assert.strictEqual(h.puts().length, 0, `invalid date ${targetDate} must not be submitted`)
    assert.strictEqual(h.toasts.at(-1).title, '请选择有效的目标日期')
  }

  h = harness()
  await h.page.savePlan()
  assert.strictEqual(h.puts().length, 0, 'no target date still saves only the local strategy')
  assert.strictEqual(h.toasts.at(-1).title, '四科策略已保存')

  h = harness({ putError: 422 })
  h.page.onTargetDateChange({ detail: { value: '2026-12-20' } })
  await h.page.savePlan()
  assert.strictEqual(h.puts().length, 1)
  assert.strictEqual(h.page.data.saving, false, 'failed requests must release the saving guard')
  assert(h.values.has(h.storage.studyStrategy.STORAGE_KEY))
  assert(h.toasts.at(-1).title.includes('四科策略已保留'))
  console.log('PASS: study-plan save, expired/invalid dates, server clock, midnight and error recovery')
}
run().catch(error => { console.error(error); process.exitCode = 1 })
