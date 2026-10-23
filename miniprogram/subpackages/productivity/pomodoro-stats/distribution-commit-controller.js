function createDistributionCommitController(options) {
  return {
    commit(rawSubjects, animate) {
      const subjects = Array.isArray(rawSubjects) ? rawSubjects.slice() : []
      options.setRawSubjects(subjects)
      options.resetPieCache()
      const subjectItems = options.buildSubjectItems(subjects)
      options.setData({
        subjects: subjectItems,
        distributionHasData: options.hasDistributionData(subjectItems),
        pieLoading: false,
        selectedSubjectDetail: null,
        _selectedSubject: null,
      }, () => {
        if (!options.isAlive() || !options.isVisible() || options.getChartMode() !== 'pie') return
        options.initCanvases(() => {
          if (!options.isAlive() || !options.isVisible() || options.getChartMode() !== 'pie') return
          if (animate) options.animatePieOnly()
          else options.renderPie(1, true)
        })
      })
    },
  }
}

module.exports = {
  createDistributionCommitController,
}
