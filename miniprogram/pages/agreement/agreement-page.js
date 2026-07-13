const { getNavigationMetrics } = require('../../utils/navigation')

function createAgreementPage() {
  return {
    data: {
      navHeight: 88,
      statusBarHeight: 20,
      navContentHeight: 44,
      navRightPadding: 116,
    },

    onLoad() {
      this.setData(getNavigationMetrics())
    },

    goBack() {
      const pages = getCurrentPages()
      if (pages && pages.length > 1) {
        wx.navigateBack({ delta: 1 })
        return
      }
      wx.reLaunch({ url: '/pages/login/login' })
    },
  }
}

module.exports = {
  createAgreementPage,
}
