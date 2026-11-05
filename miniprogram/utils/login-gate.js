const { hasStoredToken } = require('./api-auth')

const LOGIN_PAGE = '/pages/login/login'
const HOME_PAGE = '/pages/home/home'

let pending = null
const promptedPages = new WeakSet()

function hasPromptedPage(page) {
  return promptedPages.has(page)
}

function _currentRoute() {
  try {
    const pages = getCurrentPages()
    if (!pages || !pages.length) return ''
    const top = pages[pages.length - 1]
    const route = top && top.route ? String(top.route) : ''
    if (!route) return ''
    const query = Object.keys(top.options || {}).map(key =>
      `${encodeURIComponent(key)}=${encodeURIComponent(String(top.options[key]))}`).join('&')
    return `/${route}${query ? `?${query}` : ''}`
  } catch (_) {
    return ''
  }
}

function _stackSize() {
  try {
    const pages = getCurrentPages()
    return pages && pages.length ? pages.length : 0
  } catch (_) {
    return 0
  }
}

function _topPage() {
  try {
    const pages = getCurrentPages()
    return pages && pages.length ? pages[pages.length - 1] : null
  } catch (_) {
    return null
  }
}

function _customDialog(page) {
  if (!page || typeof page.selectComponent !== 'function') return null
  try {
    const dialog = page.selectComponent('#appDialog')
    return dialog && typeof dialog.show === 'function' ? dialog : null
  } catch (_) {
    return null
  }
}

function openLogin(options) {
  const opts = options || {}
  const redirect = opts.redirect || _currentRoute()
  const url = redirect && redirect !== LOGIN_PAGE
    ? `${LOGIN_PAGE}?redirect=${encodeURIComponent(redirect)}`
    : LOGIN_PAGE
  if (opts.replace) {
    wx.reLaunch({ url })
    return
  }
  if (_stackSize() >= 1 && _stackSize() < 10) {
    wx.navigateTo({ url })
    return
  }
  wx.reLaunch({ url })
}

function promptLogin(options) {
  const opts = options || {}
  if (hasStoredToken()) return Promise.resolve(true)
  const page = _topPage()
  if (page) promptedPages.add(page)
  if (pending) return pending
  const dialog = _customDialog(page)
  if (!dialog) {
    openLogin({ ...opts, replace: true })
    return Promise.resolve(true)
  }
  pending = dialog.show({
    scenario: 'info',
    eyebrow: 'SIGN IN',
    hideIcon: true,
    hideAccent: true,
    hideEyebrow: true,
    title: opts.title || '登录后继续',
    message: opts.content || '该功能需要保存学习记录。你可以先浏览体验，登录后继续使用。',
    confirmText: '去登录',
    cancelText: '暂不登录',
  }).then(confirmed => {
    pending = null
    if (confirmed) openLogin(opts)
    return confirmed
  }, () => {
    pending = null
    return false
  })
  return pending
}

function goHome() {
  wx.reLaunch({ url: HOME_PAGE })
}

module.exports = { promptLogin, hasPromptedPage, openLogin, goHome, LOGIN_PAGE, HOME_PAGE }
