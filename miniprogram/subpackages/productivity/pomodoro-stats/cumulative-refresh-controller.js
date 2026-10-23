function createCumulativeRefreshController(options) {
  let seq = 0
  return {
    async refresh(startDate, silent) {
      const start = String(startDate || '').trim()
      const end = options.getTodayDate()
      if (!start || !end) return
      const current = (seq += 1)
      options.setRequestSeq(current)
      if (!silent) options.setData({ cumulativeLoading: true })
      try {
        const summary = await options.getRangeSummary(start, end)
        if (!options.isAlive() || current !== options.getRequestSeq() || start !== options.getCumulativeStartDate()) return
        options.setData(options.buildSummaryPatch(summary, start))
      } catch (e) {
        if (!options.isAlive() || current !== options.getRequestSeq()) return
        options.logError('加载累计专注失败', e)
        options.setData({ cumulativeLoading: false })
        if (!silent) options.showToast('累计统计加载失败')
      }
    },
  }
}

module.exports = {
  createCumulativeRefreshController,
}
