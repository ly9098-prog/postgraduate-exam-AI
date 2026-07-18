/* eslint-disable no-console */
const assert = require('assert')

// Mock WeChat globals before requiring the page module
global.wx = global.wx || {
  getWindowInfo() { return { windowWidth: 375, pixelRatio: 2 } },
  getDeviceInfo() { return { system: 'Node.js regression test' } },
  setNavigationBarColor() {},
  getStorageSync() { return null },
  setStorageSync() {},
  createSelectorQuery() {
    return {
      in() { return this },
      select() { return this },
      fields() { return this },
      exec(cb) { cb && cb([]) },
    }
  },
}

// Mock the utility modules the page depends on
require.cache = require.cache || {}
var path = require('path')
var pagePath = path.join(__dirname, '../pages/pomodoro-stats/pomodoro-stats.js')

// The formatDuration function is exported as module.exports
// We need to load the page module with dependency mocks
var Module = require('module')
var originalRequire = Module.prototype.require

// We need to mock '../../utils/api' before the page module loads
var apiMockPath = path.resolve(__dirname, '../utils/api.js')
var storageMockPath = path.resolve(__dirname, '../utils/storage.js')
var configMockPath = path.resolve(__dirname, '../config.js')
var debugMockPath = path.resolve(__dirname, '../utils/debug.js')

// Pre-populate cache for utility modules
var apiMock = { get: function() { return Promise.resolve({}) }, post: function() { return Promise.resolve({}) } }
var storageMock = { KEYS: {}, get: function() { return null }, set: function() {} }
var configMock = {}
var debugMock = { debugLog: function() {}, isDebugMode: function() { return false }, saveDebugSnapshot: function() {} }

if (!require.cache) require.cache = {}
require.cache[apiMockPath] = { exports: apiMock }
require.cache[storageMockPath] = { exports: storageMock }
require.cache[configMockPath] = { exports: configMock }
require.cache[debugMockPath] = { exports: debugMock }

try {
  var pageModule = require(pagePath)
  var formatDuration = pageModule.formatDuration

  if (typeof formatDuration !== 'function') {
    throw new Error('formatDuration is not a function — module exports: ' + JSON.stringify(Object.keys(pageModule)))
  }

  // ── Test cases ──

  function assertFormat(seconds, expected, msg) {
    var actual = formatDuration(seconds)
    assert.strictEqual(actual, expected, msg || 'formatDuration(' + seconds + ') should be "' + expected + '", got "' + actual + '"')
  }

  // User acceptance examples
  assertFormat(15553, '4时19分', '15553 seconds -> 4时19分 (was 259分13秒)')
  assertFormat(59883, '16时38分', '59883 seconds -> 16时38分 (was 998分3秒)')
  assertFormat(2482, '41分钟', '2482 seconds -> 41分钟 (was 41分22秒, no seconds)')
  assertFormat(3600, '1时0分', '3600 seconds -> 1时0分')
  assertFormat(3661, '1时1分', '3661 seconds -> 1时1分')

  // Edge cases
  assertFormat(0, '0分钟', '0 seconds -> 0分钟')
  assertFormat(59, '0分钟', '59 seconds -> 0分钟 (floor to complete minutes)')
  assertFormat(60, '1分钟', '60 seconds -> 1分钟')
  assertFormat(3540, '59分钟', '3540 seconds -> 59分钟')
  assertFormat(3599, '59分钟', '3599 seconds -> 59分钟 (floor, not 60分钟)')
  assertFormat(7200, '2时0分', '7200 seconds -> 2时0分')

  // Free timer session durations (previously showed seconds)
  assertFormat(259 * 60 + 13, '4时19分', '259分13秒 must not contain "秒"')
  assertFormat(998 * 60 + 3, '16时38分', '998分3秒 must not contain "秒"')

  // No "秒" in any recent record duration
  var allResults = [
    formatDuration(15553),
    formatDuration(59883),
    formatDuration(2482),
    formatDuration(3600),
    formatDuration(3661),
    formatDuration(259 * 60 + 13),
    formatDuration(998 * 60 + 3),
  ]
  for (var i = 0; i < allResults.length; i++) {
    if (allResults[i].indexOf('秒') >= 0) {
      throw new Error('Duration "' + allResults[i] + '" must not contain "秒"')
    }
  }

  console.log('✓ Pomodoro duration format tests passed:')
  console.log('  15553 sec →', formatDuration(15553))
  console.log('  59883 sec →', formatDuration(59883))
  console.log('  2482 sec  →', formatDuration(2482))
  console.log('  3600 sec  →', formatDuration(3600))
  console.log('  3661 sec  →', formatDuration(3661))
  console.log('  0 sec     →', formatDuration(0))
  console.log('  59 sec    →', formatDuration(59))
  console.log('  3540 sec  →', formatDuration(3540))
  console.log('  7200 sec  →', formatDuration(7200))
  console.log('  All durations are free of "秒"')

} catch (e) {
  console.error('ERROR:', e.message)
  console.error('')
  console.error('Tip: If the module cannot be loaded, verify that wx global mock is complete.')
  process.exit(1)
}
