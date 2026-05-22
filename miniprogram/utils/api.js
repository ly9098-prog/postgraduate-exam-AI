const config = require('../config')
const storage = require('./storage')

const { KEYS } = storage

let _redirecting = false

function request(method, url, data = {}) {
  return new Promise((resolve, reject) => {
    const token = storage.get(KEYS.TOKEN)
    const header = { 'Content-Type': 'application/json' }
    if (token) header['Authorization'] = `Bearer ${token}`

    wx.request({
      url: `${config.BASE_URL}${url}`,
      method,
      data,
      header,
      timeout: 30000,
      success(res) {
        // token 过期，跳转登录（只跳一次，避免重复跳转）
        if (res.statusCode === 401) {
          storage.remove(KEYS.TOKEN)
          storage.remove(KEYS.USER)
          if (!_redirecting) {
            _redirecting = true
            wx.redirectTo({ url: '/pages/login/login' })
          }
          // 不 reject/resolve，wx.redirectTo 销毁当前页面后 promise 自动回收
          return
        }
        // 业务错误
        if (res.statusCode >= 400) {
          reject({ code: res.statusCode, message: res.data?.detail || '请求失败' })
          return
        }
        resolve(res.data)
      },
      fail(err) {
        wx.showToast({ title: '网络异常', icon: 'none' })
        reject(err)
      },
    })
  })
}

module.exports = {
  get: (url, data) => request('GET', url, data),
  post: (url, data) => request('POST', url, data),
  put: (url, data) => request('PUT', url, data),
  del: (url) => request('DELETE', url),
}
