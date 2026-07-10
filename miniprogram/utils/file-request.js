/**
 * 带 Token 刷新能力的文件上传/下载工具
 *
 * 提供：
 *   authUploadFile(options)   — 带 Token 鉴权的上传
 *   authDownloadFile(options) — 带 Token 鉴权的下载
 *   validateFile(options)     — 文件校验（扩展名、大小、类型）
 *
 * Token 过期时自动刷新并重试一次，刷新失败则跳转登录页。
 */

const api = require('./api')
const auth = require('./auth')
const config = require('../config')

// 默认文件大小限制：50MB
const MAX_FILE_SIZE = 50 * 1024 * 1024

const SUPPORTED_EXTENSIONS = {
  image: ['jpg', 'jpeg', 'png', 'webp', 'gif'],
  document: ['pdf', 'xlsx', 'xls', 'txt', 'csv'],
  all: ['xlsx', 'xls', 'pdf', 'txt', 'jpg', 'jpeg', 'png', 'webp', 'csv', 'gif'],
}

const SUPPORTED_MIME_TYPES = {
  pdf: 'application/pdf',
  xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  xls: 'application/vnd.ms-excel',
  txt: 'text/plain',
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  png: 'image/png',
  webp: 'image/webp',
  gif: 'image/gif',
  csv: 'text/csv',
}

/**
 * 校验文件（前端基础校验）
 *
 * 注意：前端仅检查扩展名和大小，不能验证文件真实内容。
 * 后端务必验证：
 *   - 文件魔数（Magic Number）
 *   - MIME 类型（Content-Type）
 *   - Office/ZIP 解压后体积
 *   - PDF 页数
 *   - 图片像素
 *   - Excel 单元格数量
 *   - 病毒/恶意文件扫描
 *
 * SUPPORTED_MIME_TYPES 定义在此供后端参考，前端暂不使用。
 *
 * @param {object} options
 * @param {string} options.path - 文件路径
 * @param {string} [options.name] - 文件名
 * @param {number} [options.size] - 文件大小（字节）
 * @param {string[]} [options.allowedExtensions] - 允许的扩展名列表
 * @param {number} [options.maxSize] - 最大文件大小（字节）
 * @returns {{ valid: boolean, error?: string }}
 */
function validateFile(options) {
  const name = (options.name || options.path || '').toLowerCase()
  const parts = name.split('.')
  const ext = parts.length > 1 ? parts.pop().toLowerCase() : ''
  const allowedExts = options.allowedExtensions || SUPPORTED_EXTENSIONS.all
  const maxSize = options.maxSize || MAX_FILE_SIZE

  if (!ext) {
    return { valid: false, error: '无法识别文件类型' }
  }
  if (!allowedExts.includes(ext)) {
    return { valid: false, error: `不支持 ${ext} 格式，仅支持 ${allowedExts.join('/')}` }
  }
  // 仅当明确传入 size 时才校验文件大小
  if (options.size !== undefined) {
    const size = options.size
    if (size <= 0) {
      return { valid: false, error: '文件为空' }
    }
    if (size > maxSize) {
      const mb = Math.round(maxSize / 1024 / 1024)
      return { valid: false, error: `文件过大，最大支持 ${mb}MB` }
    }
  }

  return { valid: true }
}

/**
 * 确保 Token 有效
 * 无效时尝试刷新，刷新失败则跳转登录页
 */
async function ensureValidToken() {
  const token = auth.getToken()
  if (!token) {
    auth.redirectToLogin()
    throw new api.ApiError('未登录', { code: 401 })
  }
  const valid = await api.ensureValidToken()
  if (!valid) {
    auth.redirectToLogin()
    throw new api.ApiError('登录已过期', { code: 401 })
  }
  return auth.getToken()
}

/**
 * 带 Token 鉴权的文件上传
 * 支持 Token 过期自动刷新并重试一次
 */
async function authUploadFile(options, retried) {
  if (retried === undefined) retried = false
  let token
  try {
    token = await ensureValidToken()
  } catch (e) {
    throw e
  }

  return new Promise(function (resolve, reject) {
    wx.uploadFile({
      url: options.url,
      filePath: options.filePath,
      name: options.name || 'file',
      header: Object.assign({}, options.header || {}, {
        Authorization: 'Bearer ' + token,
      }),
      formData: options.formData,
      success: function (res) {
        if (res.statusCode === 401 && !retried) {
          // Token 过期 → 强制刷新（不依赖本地过期时间）后重试一次
          api.forceRefreshToken()
            .then(function () {
              authUploadFile(options, true).then(resolve).catch(reject)
            })
            .catch(function () {
              auth.redirectToLogin()
              reject(new api.ApiError('登录已过期', { code: 401 }))
            })
          return
        }

        var body
        try {
          body = JSON.parse(res.data)
        } catch (_) {
          body = null
        }

        if (res.statusCode >= 400) {
          reject(new api.ApiError(
            (body && (body.detail || body.message)) || '上传失败 (HTTP ' + res.statusCode + ')',
            {
              code: res.statusCode,
              statusCode: res.statusCode,
              detail: body && (body.detail || body.message),
              raw: res,
            }
          ))
          return
        }

        resolve(body || res.data)
      },
      fail: function (err) {
        // 上传不自动重试：网络错误时服务器可能已收到文件，盲目重试会导致重复导入任务
        reject(new api.ApiError(err && err.errMsg || '上传网络异常', {
          code: 'UPLOAD_NETWORK_ERROR',
          raw: err,
        }))
      },
    })
  })
}

/**
 * 带 Token 鉴权的文件下载
 * 支持 Token 过期自动刷新并重试一次
 */
async function authDownloadFile(options, retried) {
  if (retried === undefined) retried = false
  let token
  try {
    token = await ensureValidToken()
  } catch (e) {
    throw e
  }

  return new Promise(function (resolve, reject) {
    wx.downloadFile({
      url: options.url,
      header: Object.assign({}, options.header || {}, {
        Authorization: 'Bearer ' + token,
      }),
      filePath: options.filePath,
      success: function (res) {
        if (res.statusCode === 401 && !retried) {
          // Token 过期 → 强制刷新（不依赖本地过期时间）后重试一次
          api.forceRefreshToken()
            .then(function () {
              authDownloadFile(options, true).then(resolve).catch(reject)
            })
            .catch(function () {
              auth.redirectToLogin()
              reject(new api.ApiError('登录已过期', { code: 401 }))
            })
          return
        }
        if (res.statusCode >= 400) {
          reject(new api.ApiError('下载失败', {
            code: res.statusCode,
            statusCode: res.statusCode,
            raw: res,
          }))
          return
        }
        resolve(res)
      },
      fail: function (err) {
        if (!retried) {
          authDownloadFile(options, true).then(resolve).catch(reject)
          return
        }
        reject(new api.ApiError(err && err.errMsg || '下载网络异常', {
          code: 'DOWNLOAD_NETWORK_ERROR',
          raw: err,
        }))
      },
    })
  })
}

module.exports = {
  authUploadFile,
  authDownloadFile,
  validateFile,
  SUPPORTED_EXTENSIONS,
  MAX_FILE_SIZE,
}
