// API 基础配置
//
// 上传体验版/正式版前请通过以下方式切换：
// 方案 A：将 __BUILD_ENV__ 替换为项目构建脚本注入的环境变量
// 方案 B：直接在微信开发者工具中修改此处为 production
//
// 注意：DEV = true 时 BASE_URL 为 localhost，真机体验版/正式版
// 会请求手机自己的 localhost 导致所有接口失败。
// ═══════════════════════════════════════════════
// 环境配置
// 发布前检查：
//   1. ENV 必须为 'production'
//   2. BASE_URL 必须为正式域名，不可包含 localhost / 127.0.0.1
// ═══════════════════════════════════════════════

// 构建时注入或手动切换：'development' | 'production'
const ENV = 'production'

const CONFIG = {
  development: {
    BASE_URL: 'http://localhost:8000/api/v1',
    debug: true,
  },
  production: {
    BASE_URL: 'https://xzshub.top/api/v1',
    debug: false,
  },
}

// ── 发布保护 ──────────────────────────────────
if (ENV === 'production') {
  const url = CONFIG.production.BASE_URL
  if (/localhost|127\.0\.0\.1/i.test(url)) {
    throw new Error(
      '[config] Production build cannot use localhost/127.0.0.1. ' +
      'Set ENV to "development" only for local debugging.'
    )
  }
}

const envConfig = CONFIG[ENV] || CONFIG.production
// 统一调试开关：debug 与 DEBUG_MODE 始终一致
var debugMode = ENV === 'development' && false   // 可临时改为 true 调试

module.exports = {
  ...envConfig,
  DEV: ENV === 'development',
  DEBUG_MODE: debugMode,
  debug: debugMode,                              // 别名，与 DEBUG_MODE 保持一致
  DEBUG_QUESTION_ID: '',
  ENV,
  enableMathImage: false,
  // 导出功能实时状态推送（WebSocket 开关）
  EXPORT_WS_ENABLED: true,
  // 微信公众平台申请的"番茄钟完成"订阅消息模板 ID。
  // 字段：thing1（打卡活动）+ character_string2（打卡进度）
  POMODORO_SUBSCRIBE_TMPL_ID: 'Dc2tD7nbZn4FQi9nYOXZCtpmK3KUbcG_vrJ57UokMUQ',
}
