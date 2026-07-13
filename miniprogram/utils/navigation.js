/**
 * 统一计算微信小程序自定义导航栏尺寸。
 * 返回值单位为 px，可直接用于 WXML 行内样式。
 */
function getNavigationMetrics() {
  let statusBarHeight = 20
  let windowWidth = 375

  try {
    const info = wx.getWindowInfo ? wx.getWindowInfo() : wx.getSystemInfoSync()
    statusBarHeight = Number(info.statusBarHeight || 20)
    windowWidth = Number(info.windowWidth || info.screenWidth || 375)
  } catch (_) {}

  let menu = null
  try {
    menu = wx.getMenuButtonBoundingClientRect && wx.getMenuButtonBoundingClientRect()
  } catch (_) {}

  const menuTop = menu && menu.top ? Number(menu.top) : statusBarHeight + 6
  const menuHeight = menu && menu.height ? Number(menu.height) : 32
  const menuLeft = menu && menu.left ? Number(menu.left) : windowWidth - 100
  const verticalGap = Math.max(4, menuTop - statusBarHeight)
  const navContentHeight = menuHeight + verticalGap * 2

  return {
    statusBarHeight,
    navContentHeight,
    navHeight: statusBarHeight + navContentHeight,
    navRightPadding: Math.max(102, windowWidth - menuLeft + 8),
  }
}

module.exports = {
  getNavigationMetrics,
}
