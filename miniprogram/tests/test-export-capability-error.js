/**
 * Tests for export capability detection — getExportCapabilityErrorMessage.
 *
 * Run: cd miniprogram && node tests/test-export-capability-error.js
 *
 * 校验 study 子包（subpackages/study/utils/export-capability.js）与 export 子包
 * （subpackages/export/services/export.js）两份能力检测实现行为一致。
 * 因微信禁止跨独立子包 require，两份实现有意重复；本测试防止它们漂移。
 */

// Mock wx globals before requiring modules (needed for config/api)
global.wx = {
  getAccountInfoSync: () => ({ miniProgram: { envVersion: 'release' } }),
  getSystemInfoSync: () => ({ platform: 'devtools' }),
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

var studyCap = require('../subpackages/study/utils/export-capability')
var exportApi = require('../subpackages/export/services/export')

var fns = {
  study: studyCap.getExportCapabilityErrorMessage,
  export: exportApi.getExportCapabilityErrorMessage,
}

var cases = [
  // [args, expected]
  [[null, { reason_code: 'feature_disabled' }], '导出功能当前已关闭'],
  [[null, { reason_code: 'user_not_allowed' }], '当前账号暂未获得导出权限'],
  [[{ code: 'NETWORK_ERROR', message: 'request:fail' }, null], '无法连接导出服务，请检查网络和小程序环境配置'],
  [[{ code: 'AUTH_REQUIRED', message: '登录已过期' }, null], '无法连接导出服务，请检查网络和小程序环境配置'],
  [[null, { export_enabled: false, reason_code: null }], '获取导出能力失败，请稍后重试'],
  [[{ code: 'INTERNAL_ERROR', message: '服务器繁忙，请稍后重试' }, null], '服务器繁忙，请稍后重试'],
  [[{ code: 500, message: '请求失败' }, null], '获取导出能力失败，请稍后重试'],
  [[null, null], '获取导出能力失败，请稍后重试'],
  [[{ code: 500, message: '' }, null], '获取导出能力失败，请稍后重试'],
]

console.log('\n--- getExportCapabilityErrorMessage (study vs export) ---')

cases.forEach(function (c, i) {
  var args = c[0]
  var expected = c[1]
  var studyOut = fns.study(args[0], args[1])
  var exportOut = fns.export(args[0], args[1])
  assertEqual(studyOut, expected, 'case ' + (i + 1) + ' study 实现')
  assertEqual(exportOut, expected, 'case ' + (i + 1) + ' export 实现')
  assertEqual(studyOut, exportOut, 'case ' + (i + 1) + ' 两侧实现一致')
})

console.log('\n============================')
console.log('Tests:', passed + failed + ', passed:', passed + ', failed:', failed)
console.log('============================\n')

process.exit(failed > 0 ? 1 : 0)
