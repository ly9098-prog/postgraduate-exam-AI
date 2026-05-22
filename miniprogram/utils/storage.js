const KEYS = {
  TOKEN: 'token',
  USER: 'user',
}

function get(key) {
  try {
    return wx.getStorageSync(key)
  } catch {
    return null
  }
}

function set(key, value) {
  try {
    wx.setStorageSync(key, value)
  } catch (e) {
    console.error('Storage set error:', e)
  }
}

function remove(key) {
  try {
    wx.removeStorageSync(key)
  } catch {
    // ignore
  }
}

module.exports = { KEYS, get, set, remove }
