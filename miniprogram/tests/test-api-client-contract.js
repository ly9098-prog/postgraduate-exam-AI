/**
 * Mini Program API client contract.
 *
 * Pins the public surface of `utils/api.js`: error shape, correlation ids,
 * expiry normalization, auth refresh/redirect behavior, request retry, upload
 * retry and the server-clock offset.
 *
 * Run: node --test tests/test-api-client-contract.js
 */

const assert = require('node:assert/strict')
const { test } = require('node:test')

const memory = new Map()
const calls = { requests: [], uploads: [], toasts: [], relaunches: [], logins: [] }
let routes = new Map()
let queues = new Map()
let offline = new Set()

const config = require('../config')

function normalizeUrl(url) {
  const text = String(url)
  return text.startsWith(config.BASE_URL) ? text.slice(config.BASE_URL.length) : text
}

function routeKey(method, url) {
  return `${method} ${normalizeUrl(url)}`
}

function respond(options, key) {
  calls.requests.push({
    method: options.method,
    url: normalizeUrl(options.url),
    data: options.data && typeof options.data === 'object' ? { ...options.data } : options.data,
    header: { ...options.header },
    timeout: options.timeout,
  })
  if (offline.has(key)) {
    options.fail({ errMsg: 'request:fail network' })
    return
  }
  const queue = queues.get(key)
  if (queue && queue.length) {
    options.success(queue.shift())
    return
  }
  const response = routes.get(key) || { statusCode: 200, data: { ok: true }, header: {} }
  options.success(response)
}

global.wx = {
  getStorageSync(key) {
    return memory.has(key) ? memory.get(key) : ''
  },
  setStorageSync(key, value) {
    memory.set(key, value)
  },
  removeStorageSync(key) {
    memory.delete(key)
  },
  getStorageInfoSync() {
    return { keys: Array.from(memory.keys()) }
  },
  showToast(value) {
    calls.toasts.push(value)
  },
  reLaunch(value) {
    calls.relaunches.push(value)
  },
  login(value) {
    calls.logins.push(value)
    value.success({ code: 'wx-code' })
  },
  request(options) {
    respond(options, routeKey(options.method, options.url))
  },
  uploadFile(options) {
    calls.uploads.push({
      url: normalizeUrl(options.url),
      filePath: options.filePath,
      name: options.name,
      formData: options.formData,
      header: options.header,
      timeout: options.timeout,
    })
    const key = routeKey('UPLOAD', options.url)
    if (offline.has(key)) {
      options.fail({ errMsg: 'uploadFile:fail network' })
      return
    }
    const queue = queues.get(key)
    if (queue && queue.length) {
      options.success(queue.shift())
      return
    }
    const response = routes.get(key) || { statusCode: 200, data: '{"ok":true}', header: {} }
    options.success(response)
  },
}

const storage = require('../utils/storage')
const api = require('../utils/api')
const auth = require('../utils/auth')

function reset(entries = {}, options = {}) {
  memory.clear()
  calls.requests.length = 0
  calls.uploads.length = 0
  calls.toasts.length = 0
  calls.relaunches.length = 0
  calls.logins.length = 0
  routes = new Map(Object.entries(options.routes || {}))
  queues = new Map(Object.entries(options.queues || {}))
  offline = new Set(options.offline || [])
  Object.entries(entries).forEach(([key, value]) => memory.set(key, value))
  api.resetRedirecting()
}

function authed(extra = {}) {
  return {
    token: 'token-1',
    refresh_token: 'refresh-1',
    token_expires_at: Math.floor(Date.now() / 1000) + 86400,
    ...extra,
  }
}

test('api client exports keep their names and order', () => {
  assert.deepEqual(Object.keys(api), [
    'get', 'post', 'put', 'del', 'resetRedirecting', 'ensureValidToken',
    'forceRefreshToken', 'uploadFile', 'request', 'ApiError', 'getErrorMessage',
    'normalizeExpiresAt', 'createTraceId', 'createRequestId', 'createClientStartId', 'now',
  ])
})

test('ApiError keeps message, code, status and correlation fallbacks', () => {
  const error = new api.ApiError('安全文案', { code: 'VALIDATION_ERROR', statusCode: 422, raw: { x: 1 } })
  assert.ok(error instanceof Error)
  assert.equal(error.name, 'ApiError')
  assert.equal(error.message, '安全文案')
  assert.equal(error.code, 'VALIDATION_ERROR')
  assert.equal(error.statusCode, 422)
  assert.equal(error.requestId, undefined)
  assert.equal(error.traceId, undefined)
  const enriched = new api.ApiError('文案', {
    detail: { requestId: 'req_1', traceId: 'tr_1' }, requestId: 'req_2', traceId: 'tr_2',
  })
  assert.equal(enriched.requestId, 'req_2')
  assert.equal(enriched.traceId, 'tr_2')
  const fromDetail = new api.ApiError('文案', { detail: { requestId: 'req_3', traceId: 'tr_3' } })
  assert.equal(fromDetail.requestId, 'req_3')
  assert.equal(fromDetail.traceId, 'tr_3')
  assert.equal(api.getErrorMessage(error), '安全文案')
  assert.equal(api.getErrorMessage(new Error('raw')), '请求失败，请稍后重试')
})

test('correlation ids and expiry normalization keep their shapes', () => {
  for (const [create, prefix] of [[api.createTraceId, 'tr_'], [api.createRequestId, 'req_'],
    [api.createClientStartId, 'pstart_']]) {
    const value = create()
    assert.ok(value.startsWith(prefix), value)
    assert.ok(value.length <= 64, value)
    assert.match(value, /^[A-Za-z0-9._:-]+$/)
    assert.notEqual(create(), value)
  }
  assert.equal(api.normalizeExpiresAt(null), null)
  assert.equal(api.normalizeExpiresAt('abc'), null)
  assert.equal(api.normalizeExpiresAt({}), null)
  assert.equal(api.normalizeExpiresAt(1700000000), 1700000000)
  assert.equal(api.normalizeExpiresAt(1700000000000), 1700000000)
  assert.equal(api.normalizeExpiresAt('1700000000'), 1700000000)
  assert.equal(api.normalizeExpiresAt('2026-10-14T12:00:00+08:00'), 1791950400)
})

test('request keeps auth headers, trace propagation and 401 retry order', async () => {
  reset(authed(), {
    routes: { 'POST /auth/refresh': { statusCode: 200, data: {
      access_token: 'token-2', refresh_token: 'refresh-2', expires_at: 1791950400,
      user: { id: 9 },
    }, header: {} } },
    queues: { 'POST /practice/start': [
      { statusCode: 401, data: { error: { code: 'TOKEN_EXPIRED' } }, header: {} },
      { statusCode: 200, data: { batch: 1 }, header: {} },
    ] },
  })
  assert.deepEqual(await api.post('/practice/start', { _traceId: 'tr_custom', subject: 'ds' }),
    { batch: 1 })
  assert.deepEqual(calls.requests.map(call => `${call.method} ${call.url}`), [
    'POST /practice/start', 'POST /auth/refresh', 'POST /practice/start',
  ])
  assert.equal(calls.requests[0].data.subject, 'ds')
  assert.equal('_traceId' in calls.requests[0].data, false)
  assert.equal(calls.requests[0].header['X-Trace-ID'], 'tr_custom')
  assert.equal(calls.requests[0].header.Authorization, 'Bearer token-1')
  assert.equal(calls.requests[1].data.refresh_token, 'refresh-1')
  assert.deepEqual(calls.requests[1].data, { refresh_token: 'refresh-1' })
  assert.equal(calls.requests[2].header.Authorization, 'Bearer token-2')
  assert.notEqual(calls.requests[2].header['X-Request-ID'], calls.requests[0].header['X-Request-ID'])
  assert.equal(calls.requests[2].header['X-Trace-ID'], 'tr_custom')
  assert.equal(memory.get('token'), 'token-2')
  assert.equal(memory.get('refresh_token'), 'refresh-2')
  assert.equal(memory.get('token_expires_at'), 1791950400)
  assert.deepEqual(memory.get('user'), { id: 9 })
})

test('request maps errors, toasts and auth redirect only once', async () => {
  reset({ token: 'token-1', token_expires_at: Math.floor(Date.now() / 1000) + 86400 }, {
    routes: {
      'GET /wrong-book': { statusCode: 403, data: {
        error: { code: 'FORBIDDEN', request_id: 'req_srv', trace_id: 'tr_srv' },
      }, header: {} },
    },
    offline: ['GET /offline'],
  })
  await assert.rejects(api.get('/wrong-book'), error => {
    assert.equal(error.code, 'FORBIDDEN')
    assert.equal(error.statusCode, 403)
    assert.equal(error.message, '没有权限执行此操作')
    assert.equal(error.requestId, 'req_srv')
    assert.equal(error.traceId, 'tr_srv')
    return true
  })
  await assert.rejects(api.get('/offline'), error => {
    assert.equal(error.code, 'NETWORK_ERROR')
    assert.equal(error.statusCode, 0)
    assert.equal(error.message, '网络连接失败，请检查网络后重试')
    return true
  })
  assert.equal(calls.toasts.length, 1)
  reset({ token: 'token-1', token_expires_at: Math.floor(Date.now() / 1000) + 86400 },
    { offline: ['GET /offline'] })
  await assert.rejects(api.get('/offline', {}, { suppressNetworkToast: true }),
    error => error.code === 'NETWORK_ERROR')
  assert.deepEqual(calls.toasts, [])
  reset({ token: 'token-1', token_expires_at: Math.floor(Date.now() / 1000) + 86400,
    privacy_acceptance: 'accepted' }, {
    routes: { 'GET /secret': { statusCode: 401, data: { error: { code: 'TOKEN_EXPIRED' } }, header: {} } },
  })
  await assert.rejects(api.get('/secret'), error => error.code === 'AUTH_REQUIRED')
  assert.equal(calls.relaunches.length, 1)
  assert.deepEqual(calls.relaunches[0], { url: '/pages/login/login' })
  assert.equal(memory.has('token'), false)
  assert.equal(memory.get('privacy_acceptance'), 'accepted')
  await assert.rejects(api.get('/secret'), error => error.code === 'AUTH_REQUIRED')
  // Without a stored token the client fails fast and does not redirect again.
  assert.equal(calls.relaunches.length, 1)
  api.resetRedirecting()
  memory.set('token', 'token-1')
  memory.set('token_expires_at', Math.floor(Date.now() / 1000) + 86400)
  await assert.rejects(api.get('/secret'), error => error.code === 'AUTH_REQUIRED')
  assert.equal(calls.relaunches.length, 2)
})

test('proactive refresh keeps its threshold, dedup and login bypass rules', async () => {
  reset(authed({ token_expires_at: Math.floor(Date.now() / 1000) + 60 }), {
    routes: { 'POST /auth/refresh': { statusCode: 200, data: {
      access_token: 'token-2', expires_at: Math.floor(Date.now() / 1000) + 86400,
    }, header: {} } },
  })
  assert.equal(await api.ensureValidToken(), true)
  assert.deepEqual(calls.requests.map(call => call.url), ['/auth/refresh'])
  assert.equal(memory.get('token'), 'token-2')
  assert.equal(memory.get('refresh_token'), 'refresh-1')
  reset(authed({ token_expires_at: Math.floor(Date.now() / 1000) + 10 }), { routes: {
    'GET /pair': { statusCode: 200, data: { ok: 1 }, header: {} },
    'POST /auth/refresh': { statusCode: 200, data: { access_token: 'token-2' }, header: {} },
  } })
  const [first, second] = await Promise.all([api.forceRefreshToken(), api.forceRefreshToken()])
  assert.equal(first, 'token-2')
  assert.equal(second, 'token-2')
  assert.equal(calls.requests.filter(call => call.url === '/auth/refresh').length, 1)
  reset(authed({ token_expires_at: Math.floor(Date.now() / 1000) + 10 }), {
    routes: { 'POST /auth/login': { statusCode: 200, data: { token: 'x' }, header: {} } },
  })
  assert.deepEqual(await api.post('/auth/login', { code: 'c' }), { token: 'x' })
  assert.deepEqual(calls.requests.map(call => call.url), ['/auth/login'])
  assert.equal(memory.get('token'), 'token-1')
})

test('uploadFile keeps multipart headers and maps HTTP/network errors', async () => {
  reset(authed(), {
    routes: {
      'UPLOAD /import/ocr': { statusCode: 200, data: '{"task":7}', header: {} },
      'POST /auth/refresh': { statusCode: 200, data: { access_token: 'token-2' }, header: {} },
    },
  })
  assert.deepEqual(await api.uploadFile('/import/ocr', '/tmp/a.png', {
    name: 'file', formData: { kind: 'ocr' }, traceId: 'tr_upload', timeout: 5000,
  }), { task: 7 })
  assert.equal(calls.uploads[0].name, 'file')
  assert.deepEqual(calls.uploads[0].formData, { kind: 'ocr' })
  assert.equal(calls.uploads[0].timeout, 5000)
  assert.equal(calls.uploads[0].header['X-Trace-ID'], 'tr_upload')
  assert.equal(calls.uploads[0].header.Authorization, 'Bearer token-1')
  assert.equal('Content-Type' in calls.uploads[0].header, false)
  reset(authed(), {
    routes: {
      'POST /auth/refresh': { statusCode: 200, data: { access_token: 'token-2' }, header: {} },
      'UPLOAD /import/ocr': { statusCode: 400, data: { error: { code: 'BAD_FILE' } }, header: {} },
    },
  })
  await assert.rejects(api.uploadFile('/import/ocr', '/tmp/a.png'),
    error => error.code === 'BAD_FILE' && error.statusCode === 400)
  reset(authed(), {
    routes: { 'POST /auth/refresh': { statusCode: 200, data: { access_token: 'token-2' }, header: {} } },
    offline: ['UPLOAD /import/ocr'],
  })
  await assert.rejects(api.uploadFile('/import/ocr', '/tmp/a.png'),
    error => error.code === 'NETWORK_ERROR' && error.statusCode === 0)
  assert.equal('Content-Type' in calls.uploads[0].header, false)
})

test('upload 401 retries once with the same trace and a fresh request id', async () => {
  reset(authed(), {
    routes: { 'POST /auth/refresh': { statusCode: 200, data: {
      access_token: 'token-2',
    }, header: {} } },
    queues: { 'UPLOAD /users/me/avatar': [
      { statusCode: 401, data: '{"code":"TOKEN_EXPIRED"}', header: {} },
      { statusCode: 401, data: '{"code":"STILL_UNAUTHORIZED"}', header: {} },
    ] },
  })
  await assert.rejects(api.uploadFile('/users/me/avatar', '/tmp/avatar.png', {
    traceId: 'tr_avatar', name: 'image', formData: { kind: 'avatar' }, timeout: 4567,
  }), error => error.statusCode === 401 && error.code === 'STILL_UNAUTHORIZED')
  assert.equal(calls.uploads.length, 2)
  assert.equal(calls.requests.filter(call => call.url === '/auth/refresh').length, 1)
  const [first, second] = calls.uploads
  assert.equal(first.header.Authorization, 'Bearer token-1')
  assert.equal(second.header.Authorization, 'Bearer token-2')
  assert.equal(first.header['X-Trace-ID'], 'tr_avatar')
  assert.equal(second.header['X-Trace-ID'], 'tr_avatar')
  assert.notEqual(first.header['X-Request-ID'], second.header['X-Request-ID'])
  for (const attempt of calls.uploads) {
    assert.equal('Content-Type' in attempt.header, false)
    assert.equal(attempt.filePath, '/tmp/avatar.png')
    assert.equal(attempt.name, 'image')
    assert.deepEqual(attempt.formData, { kind: 'avatar' })
    assert.equal(attempt.timeout, 4567)
  }
})

test('HTTP second 401 is returned as an error without another refresh', async () => {
  reset(authed(), {
    routes: { 'POST /auth/refresh': { statusCode: 200, data: {
      access_token: 'token-2',
    }, header: {} } },
    queues: { 'GET /protected': [
      { statusCode: 401, data: { code: 'TOKEN_EXPIRED' }, header: {} },
      { statusCode: 401, data: { code: 'STILL_UNAUTHORIZED' }, header: {} },
    ] },
  })
  await assert.rejects(api.get('/protected'), error =>
    error.statusCode === 401 && error.code === 'STILL_UNAUTHORIZED')
  assert.deepEqual(calls.requests.map(call => call.url), [
    '/protected', '/auth/refresh', '/protected',
  ])
})

test('proactive refresh retries one network failure then blocks the HTTP request', async () => {
  reset(authed({ token_expires_at: Math.floor(Date.now() / 1000) + 60 }), {
    offline: ['POST /auth/refresh'],
  })
  const originalSetTimeout = global.setTimeout
  const delays = []
  global.setTimeout = (callback, delay, ...args) => {
    if (delay !== 1500) return originalSetTimeout(callback, delay, ...args)
    delays.push(delay)
    callback(...args)
    return 0
  }
  try {
    await assert.rejects(api.get('/blocked'), error => error.code === 'AUTH_REQUIRED')
    assert.deepEqual(delays, [1500])
    assert.deepEqual(calls.requests.map(call => call.url), ['/auth/refresh', '/auth/refresh'])
    assert.equal(calls.relaunches.length, 0)
  } finally {
    global.setTimeout = originalSetTimeout
  }
})

test('server clock offset applies to now() from body samples', async () => {
  reset(authed(), {
    routes: { 'GET /clock': { statusCode: 200, data: {
      ok: 1, server_now: new Date(Date.now() + 60 * 60 * 1000).toISOString().replace('Z', '+00:00'),
    }, header: {} } },
  })
  const before = api.now()
  await api.get('/clock')
  const after = api.now()
  const offset = after - before
  assert.ok(offset > 55 * 60 * 1000, `offset ${offset} should track the server body sample`)
  assert.ok(offset < 65 * 60 * 1000, `offset ${offset} should stay close to one hour`)
  assert.ok(Math.abs(after - Date.now()) > 55 * 60 * 1000)
})

test('expired clock sample accepts Date header fallback without server_now', async () => {
  const originalNow = Date.now
  const clientNow = originalNow() + 11 * 60 * 1000
  Date.now = () => clientNow
  try {
    const serverNow = clientNow + 2 * 60 * 60 * 1000
    reset(authed(), {
      routes: { 'GET /clock-header': { statusCode: 200, data: { ok: 1 },
        header: { Date: new Date(serverNow).toUTCString() } } },
    })
    await api.get('/clock-header')
    assert.ok(Math.abs(api.now() - serverNow) < 1000)
  } finally {
    Date.now = originalNow
  }
})

test('WeChat login persists the complete session after the code exchange', async () => {
  reset({}, { routes: { 'POST /auth/login': { statusCode: 200, data: {
    access_token: 'login-access', refresh_token: 'login-refresh',
    expires_at: 1900000000, user: { id: 17, nickname: 'Learner' },
  }, header: {} } } })
  const originalLogin = wx.login
  wx.login = async () => ({ code: 'test-wechat-code' })
  try {
    const user = await auth.wechatLogin()
    assert.deepEqual(calls.requests.map(call => call.url), ['/auth/login'])
    assert.deepEqual(calls.requests[0].data, { code: 'test-wechat-code' })
    assert.equal(user.id, 17)
    assert.equal(memory.get('token'), 'login-access')
    assert.equal(memory.get('refresh_token'), 'login-refresh')
    assert.equal(memory.get('token_expires_at'), 1900000000)
    assert.equal(memory.get('user').id, 17)
  } finally {
    wx.login = originalLogin
  }
})

test('failed session persistence rolls back all four auth keys', () => {
  reset({ privacy_acceptance: 'keep' })
  const originalWrite = wx.setStorageSync
  wx.setStorageSync = (key, value) => {
    if (key === 'user') throw new Error('synthetic quota failure')
    originalWrite(key, value)
  }
  try {
    assert.throws(() => auth.loginDirect('access', { id: 17 }, 1900000000, 'refresh'),
      /登录信息保存失败/)
    for (const key of ['token', 'refresh_token', 'token_expires_at', 'user']) {
      assert.equal(memory.has(key), false, key)
    }
    assert.equal(memory.get('privacy_acceptance'), 'keep')
  } finally {
    wx.setStorageSync = originalWrite
  }
})

test('profile uploads avatar before nickname and retains the uploaded URL', async () => {
  reset(authed(), { routes: {
    'UPLOAD /users/me/avatar': { statusCode: 200,
      data: '{"id":17,"avatar_url":"new-avatar"}', header: {} },
    'PUT /users/me': { statusCode: 200,
      data: { id: 17, nickname: 'Learner', avatar_url: 'stale-avatar' }, header: {} },
  } })
  const events = []
  const originalUpload = wx.uploadFile
  const originalRequest = wx.request
  wx.uploadFile = options => { events.push('upload'); originalUpload(options) }
  wx.request = options => { events.push(options.method); originalRequest(options) }
  try {
    const user = await auth.updateProfile({ nickname: '  New   Name ', avatarPath: '/tmp/avatar.png' })
    assert.deepEqual(events, ['upload', 'PUT'])
    assert.equal(calls.uploads[0].name, 'file')
    assert.equal(calls.uploads[0].timeout, 30000)
    assert.deepEqual(calls.requests[0].data, { nickname: 'New Name' })
    assert.equal(user.avatar_url, 'new-avatar')
    assert.equal(memory.get('user').avatar_url, 'new-avatar')
  } finally {
    wx.uploadFile = originalUpload
    wx.request = originalRequest
  }
})

test('avatar failure stops profile update and keeps the cached user', async () => {
  const old = { id: 17, nickname: 'Old', avatar_url: 'old-avatar' }
  reset(authed({ user: old }), { routes: {
    'UPLOAD /users/me/avatar': { statusCode: 503, data: '{}', header: {} },
  } })
  await assert.rejects(auth.updateProfile({ nickname: 'New', avatarPath: '/tmp/avatar.png' }),
    error => error.statusCode === 503)
  assert.equal(calls.uploads.length, 1)
  assert.equal(calls.requests.length, 0)
  assert.equal(memory.get('user'), old)
})

test('logout waits for the revoke attempt then clears session even on network failure', async () => {
  reset(authed({ user: { id: 17 }, privacy_acceptance: 'accepted', unrelated: 'keep' }))
  const originalRequest = wx.request
  let pending
  wx.request = options => { pending = options }
  try {
    const completion = auth.logout()
    await new Promise(resolve => setImmediate(resolve))
    assert.ok(pending)
    assert.equal(memory.get('token'), 'token-1')
    assert.equal(memory.get('privacy_acceptance'), 'accepted')
    pending.fail({ errMsg: 'synthetic offline' })
    await completion
    for (const key of ['token', 'refresh_token', 'token_expires_at', 'user', 'privacy_acceptance']) {
      assert.equal(memory.has(key), false, key)
    }
    assert.equal(memory.get('unrelated'), 'keep')
  } finally {
    wx.request = originalRequest
  }
})

function loginPage() {
  const modulePath = require.resolve('../pages/login/login')
  const originalPage = global.Page
  let definition
  delete require.cache[modulePath]
  global.Page = value => { definition = value }
  try {
    require(modulePath)
  } finally {
    if (originalPage === undefined) delete global.Page
    else global.Page = originalPage
  }
  return {
    ...definition,
    data: { ...definition.data, agreed: true },
    setData(values) { Object.assign(this.data, values) },
  }
}

test('login page rolls authentication back when consent persistence fails', async () => {
  reset({}, { routes: { 'POST /auth/login': { statusCode: 200, data: {
    access_token: 'login-access', refresh_token: 'login-refresh',
    expires_at: 1900000000, user: { id: 17 },
  }, header: {} } } })
  const originalLogin = wx.login
  const originalWrite = wx.setStorageSync
  wx.login = async () => ({ code: 'test-wechat-code' })
  wx.setStorageSync = (key, value) => {
    if (key === 'privacy_acceptance') throw new Error('synthetic consent write failure')
    originalWrite(key, value)
  }
  try {
    const page = loginPage()
    await page.onWechatLogin()
    assert.match(page.data.error, /协议确认记录保存失败/)
    assert.equal(page.data.loading, false)
    for (const key of ['token', 'refresh_token', 'token_expires_at', 'user']) {
      assert.equal(memory.has(key), false, key)
    }
    assert.equal(calls.relaunches.length, 0)
  } finally {
    wx.login = originalLogin
    wx.setStorageSync = originalWrite
  }
})

test('late login completion commits consent before the destroyed page returns', async () => {
  reset({}, { routes: { 'POST /auth/login': { statusCode: 200, data: {
    access_token: 'login-access', refresh_token: 'login-refresh',
    expires_at: 1900000000, user: { id: 17 },
  }, header: {} } } })
  const originalLogin = wx.login
  let completeLogin
  wx.login = () => new Promise(resolve => { completeLogin = resolve })
  try {
    const page = loginPage()
    const completion = page.onWechatLogin()
    assert.ok(completeLogin)
    page.onUnload()
    completeLogin({ code: 'test-wechat-code' })
    await completion
    assert.equal(memory.get('token'), 'login-access')
    assert.equal(memory.get('privacy_acceptance').privacy_version, '1.1')
    assert.equal(memory.get('privacy_acceptance').accepted_items.length, 3)
    assert.equal(calls.relaunches.length, 0)
    assert.equal(page._homeRedirectTimer, null)
  } finally {
    wx.login = originalLogin
  }
})
