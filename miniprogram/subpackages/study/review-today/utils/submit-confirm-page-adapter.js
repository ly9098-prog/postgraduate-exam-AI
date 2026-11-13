// Single owner of the #submitConfirm selector and its page-level pending flag.
function createSubmitConfirmPort(page) {
  return {
    isPending: () => !!page._confirmDialogPending,
    setPending: value => { page._confirmDialogPending = value },
    show: options => {
      const confirm = page.selectComponent('#submitConfirm')
      if (!confirm || typeof confirm.show !== 'function') {
        wx.showToast({ title: '请稍后重试', icon: 'none' })
        return Promise.resolve(false)
      }
      return confirm.show(options)
    },
  }
}

module.exports = {
  createSubmitConfirmPort,
}
