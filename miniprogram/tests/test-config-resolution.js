/**
 * Tests for config.js — resolveRuntimeConfig + environment selection.
 *
 * Run: cd miniprogram && node tests/test-config-resolution.js
 *
 * These tests verify that different envVersion/platform/localDebug
 * combinations resolve to the correct API URL key.
 *
 * NOTE: The module-level config uses LOCAL_DEBUG=false (production default).
 * The resolveRuntimeConfig pure function tests cover all branches including
 * the LOCAL_DEBUG=true case.
 */

// Mock wx globals before requiring config
global.wx = {
  getAccountInfoSync: () => ({
    miniProgram: { envVersion: 'release' },
  }),
  getSystemInfoSync: () => ({ platform: 'devtools' }),
}

// Re-require fresh config for each test group
function freshConfig() {
  delete require.cache[require.resolve('../config')]
  return require('../config')
}

var passed = 0
var failed = 0

function assertEqual(actual, expected, msg) {
  if (actual === expected) { passed++; return }
  failed++
  console.error('  FAIL:', msg)
  console.error('    expected:', JSON.stringify(expected))
  console.error('    actual:', JSON.stringify(actual))
}

function assertNotEqual(actual, unexpected, msg) {
  if (actual !== unexpected) { passed++; return }
  failed++
  console.error('  FAIL:', msg)
  console.error('    should not be:', JSON.stringify(unexpected))
  console.error('    actual:', JSON.stringify(actual))
}

// ══════════════════════════════════════════════
// Test resolveRuntimeConfig directly (pure function)
// ══════════════════════════════════════════════

var resolveRuntimeConfig = freshConfig().resolveRuntimeConfig

console.log('\n--- resolveRuntimeConfig ---')

// 1. DevTools + develop + localDebug=true → local
assertEqual(
  resolveRuntimeConfig({ envVersion: 'develop', platform: 'devtools', localDebug: true }),
  'local',
  'DevTools + develop + localDebug → local'
)

// 2. DevTools + develop + localDebug=false → release (not localhost)
assertEqual(
  resolveRuntimeConfig({ envVersion: 'develop', platform: 'devtools', localDebug: false }),
  'release',
  'DevTools + develop + no localDebug → release'
)

// 3. Real device develop (not devtools) → release
assertEqual(
  resolveRuntimeConfig({ envVersion: 'develop', platform: 'ios', localDebug: false }),
  'release',
  'Real device develop → release'
)

assertEqual(
  resolveRuntimeConfig({ envVersion: 'develop', platform: 'android', localDebug: false }),
  'release',
  'Real Android develop → release'
)

// 4. Trial → trial (regardless of platform)
assertEqual(
  resolveRuntimeConfig({ envVersion: 'trial', platform: 'devtools', localDebug: false }),
  'trial',
  'Trial devtools → trial'
)

assertEqual(
  resolveRuntimeConfig({ envVersion: 'trial', platform: 'ios', localDebug: false }),
  'trial',
  'Trial real device → trial'
)

// 5. Release → release
assertEqual(
  resolveRuntimeConfig({ envVersion: 'release', platform: 'devtools', localDebug: false }),
  'release',
  'Release devtools → release'
)

assertEqual(
  resolveRuntimeConfig({ envVersion: 'release', platform: 'ios', localDebug: false }),
  'release',
  'Release real device → release'
)

// 6. Unknown env → release (safe default)
assertEqual(
  resolveRuntimeConfig({ envVersion: 'unknown', platform: 'devtools', localDebug: false }),
  'release',
  'Unknown env → release (safe default)'
)

assertEqual(
  resolveRuntimeConfig({ envVersion: '', platform: 'devtools', localDebug: false }),
  'release',
  'Empty env → release (safe default)'
)

// 7. Real device develop + localDebug=true should NOT use localhost
//    (localDebug only applies when platform=devtools)
assertEqual(
  resolveRuntimeConfig({ envVersion: 'develop', platform: 'ios', localDebug: true }),
  'release',
  'Real device develop + localDebug=true → release (safe)'
)

// ══════════════════════════════════════════════
// Test module-level config (LOCAL_DEBUG=true — current default for local dev)
// ══════════════════════════════════════════════
//
// NOTE: config.js has LOCAL_DEBUG=true for local development.
// The module-level config always routes to localhost in this mode.
// Production scenarios (LOCAL_DEBUG=false) are covered by the
// resolveRuntimeConfig pure-function tests above.

console.log('\n--- Module-level config (LOCAL_DEBUG=true) ---')

var config

// Any env → localhost (because LOCAL_DEBUG=true)
global.wx.getAccountInfoSync = () => ({ miniProgram: { envVersion: 'release' } })
global.wx.getSystemInfoSync = () => ({ platform: 'ios' })
config = freshConfig()
assertEqual(config.DEV, true, 'LOCAL_DEBUG=true → DEV=true')
assertEqual(config.BASE_URL, 'http://localhost:8000/api/v1', 'LOCAL_DEBUG=true → localhost')
assertEqual(config.BASE_URL.includes('localhost'), true, 'LOCAL_DEBUG=true URL must contain localhost')

global.wx.getAccountInfoSync = () => ({ miniProgram: { envVersion: 'trial' } })
config = freshConfig()
assertEqual(config.DEV, true, 'LOCAL_DEBUG=true trial → DEV=true')
assertEqual(config.BASE_URL, 'http://localhost:8000/api/v1', 'LOCAL_DEBUG=true trial → localhost')

global.wx.getAccountInfoSync = () => ({ miniProgram: { envVersion: 'develop' } })
config = freshConfig()
assertEqual(config.DEV, true, 'LOCAL_DEBUG=true develop → DEV=true')
assertEqual(config.BASE_URL, 'http://localhost:8000/api/v1', 'LOCAL_DEBUG=true develop → localhost')

// ══════════════════════════════════════════════
// Results
// ══════════════════════════════════════════════

console.log('\n============================')
console.log('Tests:', passed + failed + ', passed:', passed + ', failed:', failed)
console.log('============================\n')

process.exit(failed > 0 ? 1 : 0)
