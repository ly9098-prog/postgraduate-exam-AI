
const config = require('../config')

function _rawRequest(method, url, data, header, timeout) {
  return new Promise((resolve, reject) => {
    wx.request({
      url: `${config.BASE_URL}${url}`,
      method,
      data: data,
      header,
      timeout: timeout || 30000,
      success: resolve,
      fail: reject,
    })
  })
}

function _rawUploadFile(url, filePath, name, formData, header, timeout) {
  return new Promise((resolve, reject) => {
    wx.uploadFile({
      url: `${config.BASE_URL}${url}`,
      filePath,
      name: name || 'file',
      formData: formData || {},
      header,
      timeout: timeout || 30000,
      success: resolve,
      fail: reject,
    })
  })
}

function _wxLogin() {
  return new Promise((resolve, reject) => {
    wx.login({
      success: (res) => {
        if (res.code) resolve(res.code)
        else reject(new Error('wx.login 获取 code 失败'))
      },
      fail: reject,
    })
  })
}

module.exports = {
  rawRequest: _rawRequest,
  rawUploadFile: _rawUploadFile,
  wxLogin: _wxLogin,
}
