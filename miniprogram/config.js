// API 基础配置
// 本地调试用 true，上传正式版前改为 false
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
module.exports = { ...CONFIG[env], DEV, enableMathImage: false }
