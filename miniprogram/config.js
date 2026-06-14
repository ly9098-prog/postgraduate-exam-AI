// API 基础配置
// 本地调试用 true，上传正式版前改为 false
const DEV = true

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
