const storage = require('../../../utils/storage')

const DEFAULT_THEME = 'light'
const THEMES = ['light', 'dark']
const STORAGE_PREFIX = 'pomodoro_theme:'

function normalizeTheme(value) {
  return THEMES.indexOf(value) >= 0 ? value : DEFAULT_THEME
}

function getUserScope() {
  const user = storage.get(storage.KEYS.USER) || {}
  const id = user.id != null
    ? user.id
    : user.user_id != null
      ? user.user_id
      : user.openid || 'guest'
  return encodeURIComponent(String(id))
}

function getStorageKey() {
  return STORAGE_PREFIX + getUserScope()
}

function getTheme() {
  return normalizeTheme(storage.get(getStorageKey()))
}

function setTheme(value) {
  const theme = normalizeTheme(value)
  storage.set(getStorageKey(), theme)
  return theme
}

function getNativeTheme(value) {
  const theme = normalizeTheme(value)
  if (theme === 'dark') {
    return {
      mode: theme,
      frontColor: '#ffffff',
      backgroundColor: '#0B1121',
      backgroundTextStyle: 'light',
    }
  }
  return {
    mode: theme,
    frontColor: '#000000',
    backgroundColor: '#F4F4EE',
    backgroundTextStyle: 'dark',
  }
}

function applyNativeTheme(value) {
  const meta = getNativeTheme(value)
  try {
    wx.setNavigationBarColor({
      frontColor: meta.frontColor,
      backgroundColor: meta.backgroundColor,
      animation: { duration: 360, timingFunc: 'easeInOut' },
    })
  } catch (_) {}
  try {
    if (wx.setBackgroundColor) {
      wx.setBackgroundColor({
        backgroundColor: meta.backgroundColor,
        backgroundColorTop: meta.backgroundColor,
        backgroundColorBottom: meta.backgroundColor,
      })
    }
  } catch (_) {}
  try {
    if (wx.setBackgroundTextStyle) {
      wx.setBackgroundTextStyle({ textStyle: meta.backgroundTextStyle })
    }
  } catch (_) {}
  return meta
}

module.exports = {
  DEFAULT_THEME,
  normalizeTheme,
  getTheme,
  setTheme,
  getNativeTheme,
  applyNativeTheme,
}
