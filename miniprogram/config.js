// API 基础配置
//
// 上传体验版/正式版前请通过以下方式切换：
// 方案 A：将 __BUILD_ENV__ 替换为项目构建脚本注入的环境变量
// 方案 B：直接在微信开发者工具中修改此处为 production
//
// 注意：DEV = true 时 BASE_URL 为 localhost，真机体验版/正式版
// 会请求手机自己的 localhost 导致所有接口失败。
const DEV = false

const CONFIG = {
  development: {
    BASE_URL: 'http://localhost:8000/api/v1',
  },
  production: {
    BASE_URL: 'https://xzshub.top/api/v1',
  },
}

const env = DEV ? 'development' : 'production'
module.exports = {
  ...CONFIG[env],
  DEV,
  DEBUG_MODE: DEV,
  DEBUG_QUESTION_ID: '',
  enableMathImage: false,
  // 微信公众平台申请的"番茄钟完成"订阅消息模板 ID。
  // 字段：thing1（打卡活动）+ character_string2（打卡进度）
  POMODORO_SUBSCRIBE_TMPL_ID: 'Dc2tD7nbZn4FQi9nYOXZCtpmK3KUbcG_vrJ57UokMUQ',
}
