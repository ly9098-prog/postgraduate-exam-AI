// ══════════════════════════════════════════════════════════════
//  本地 / 生产切换 — 修改这里即可
// ══════════════════════════════════════════════════════════════
//  true  → 本地开发（localhost:8000），仅开发者工具可用
//  false → 正式/体验/真机（https://xzshub.top）
const LOCAL_DEBUG = true

// ══════════════════════════════════════════════════════════════
//  以下代码无需手动修改
// ══════════════════════════════════════════════════════════════

const API_URLS = {
  local: 'http://localhost:8000/api/v1',
  trial: 'https://xzshub.top/api/v1',
  release: 'https://xzshub.top/api/v1',
}

// 发布前检查：发布时必须改 LOCAL_DEBUG = false
if (LOCAL_DEBUG) {
  const url = API_URLS.local
  if (!url.includes('localhost') && !url.includes('127.0.0.1')) {
    throw new Error('[config] LOCAL_DEBUG=true 时 BASE_URL 必须指向 localhost')
  }
}

// ── 运行时环境解析（纯函数，用于测试） ──
function resolveRuntimeConfig({ envVersion, platform, localDebug }) {
  if (envVersion === 'develop' && platform === 'devtools' && localDebug) return 'local'
  if (envVersion === 'trial') return 'trial'
  return 'release'
}

// ── 根据 LOCAL_DEBUG 确定目标环境 ──
var runtimeEnv
if (LOCAL_DEBUG) {
  runtimeEnv = 'local'
} else {
  try {
    const info = wx.getAccountInfoSync()
    runtimeEnv = info.miniProgram.envVersion === 'trial' ? 'trial' : 'release'
  } catch (_e) {
    runtimeEnv = 'release'
  }
}

const envConfig = {
  BASE_URL: API_URLS[runtimeEnv] || API_URLS.release,
  debug: runtimeEnv === 'local',
}

// 统一调试开关
var debugMode = envConfig.debug && false // 可临时改为 true 输出调试日志

module.exports = {
  ...envConfig,
  DEV: runtimeEnv === 'local',
  DEBUG_MODE: debugMode,
  debug: debugMode,
  DEBUG_QUESTION_ID: '',
  ENV: runtimeEnv,
  resolveRuntimeConfig,
  enableMathImage: false,
  // Wrong-book export entry for all users (backend capability check enabled).
  WRONG_BOOK_EXPORT_ENABLED: true,
  EXPORT_WS_ENABLED: true,
}
