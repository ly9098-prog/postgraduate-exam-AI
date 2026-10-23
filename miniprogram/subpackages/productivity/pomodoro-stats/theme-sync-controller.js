function createThemeSyncController(options) {
  return {
    sync() {
      const themeMode = options.getStoredTheme()
      options.applyNativeTheme(themeMode)
      if (themeMode === options.getCurrentTheme()) return false

      const subjects = (options.getSubjects() || []).map(item => ({
        ...item,
        _color: options.getPieSubjectColor(
          item.subject_id != null
            ? String(item.subject_id)
            : (item.subject_code || item._label),
          themeMode
        ),
      }))
      const history = (options.getHistory() || []).map(item => ({
        ...item,
        _color: options.getSubjectColor(
          item.subject_id != null
            ? String(item.subject_id)
            : (item.subject_code || item._subjectLabel),
          themeMode
        ),
      }))

      options.setData({ themeMode, subjects, history }, () => {
        options.resetPieCache()
        if (!options.isAlive() || !options.isViewReady() || !options.hasData()) return
        const redraw = () => {
          if (!options.isAlive() || !options.isVisible()) return
          if (options.getChartMode() === 'pie') {
            options.renderPie(1, true)
          } else if (options.isBarMounted() && options.hasTrendContext()) {
            // Only a user-mounted bar canvas participates in theme redraw.
            options.renderTrendBars(1)
          }
        }
        options.nextTick(redraw)
      })
      return true
    },
  }
}

module.exports = {
  createThemeSyncController,
}
