/**
 * 导出能力检测（study 子包本地副本）。
 *
 * 因微信小程序禁止独立分包间互相引用，能力检测逻辑在 study 与 export 两个子包
 * 中各自持有一份有意重复的实现（export 侧在 subpackages/export/services/export.js）。
 * 请勿抽回主包——保持两处行为一致即可（一致性用例见 tests/test-export-capability-error.js）。
 *
 * 只包含 study 子包（wrong-book）实际需要的 getCapabilities / getExportCapabilityErrorMessage。
 */

const api = require('../../../utils/api')

function getCapabilities() {
  return api.get('/exports/capabilities')
}

function getExportCapabilityErrorMessage(error, capability) {
  // 与 subpackages/export/services/export.js 同名函数保持一致，勿单边改动。
  if (capability) {
    if (capability.reason_code === 'feature_disabled') {
      return '导出功能当前已关闭'
    }
    if (capability.reason_code === 'user_not_allowed') {
      return '当前账号暂未获得导出权限'
    }
  }

  if (error) {
    if (error.code === 'NETWORK_ERROR' || error.code === 'AUTH_REQUIRED') {
      return '无法连接导出服务，请检查网络和小程序环境配置'
    }
    if (error.message && !error.message.includes('请求失败')) {
      return error.message
    }
  }

  return '获取导出能力失败，请稍后重试'
}

module.exports = {
  getCapabilities,
  getExportCapabilityErrorMessage,
}
