function createCloseDetailController(options) {
  return {
    close() {
      options.setData({
        selectedSubjectDetail: null,
        _selectedSubject: null,
      }, () => {
        if (options.isAlive()) options.renderPie(1)
      })
    },
  }
}

module.exports = {
  createCloseDetailController,
}
