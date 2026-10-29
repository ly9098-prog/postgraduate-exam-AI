const { fixture: stateFixture, deferred, flush } = require('./wrong-book-ai-state-fixture')

function fixture() {
  const f = stateFixture(), api = f.stubs['../../../utils/api']
  f.page._checkAiDiagnosis = f.methods._checkAiDiagnosis
  f.context.console.error = (...args) => f.calls.push(['error', ...args])
  Object.assign(api, {
    get(...args) { f.calls.push(['getApi', ...args]); return Promise.resolve({ summary: 'result' }) },
    post(...args) { f.calls.push(['postApi', ...args]); return Promise.resolve({}) },
  })
  Object.assign(f.aiCache, {
    clear(user) { f.calls.push(['clearCache', user]) },
    isExpired(...args) { f.calls.push(['expired', ...args]); return false },
    canRefresh(time) { f.calls.push(['canRefresh', time]); return false },
  })
  Object.assign(f.context.wx, {
    showLoading(options) { f.calls.push(['loading', options]) },
    hideLoading() { f.calls.push(['hideLoading']) },
  })
  return Object.assign(f, { api })
}

module.exports = { fixture, deferred, flush }
