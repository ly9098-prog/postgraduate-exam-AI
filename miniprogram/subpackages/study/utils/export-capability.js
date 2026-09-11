
const api = require('../../../utils/api')
function getCapabilities() {
return api.get('/exports/capabilities')
}
function getExportCapabilityErrorMessage(error, capability) {
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
