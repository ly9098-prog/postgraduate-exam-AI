function createDistributionLoadController(options) {
  let seq = 0
  return {
    async load(period, animate = true) {
      const normalized = ['day', 'week', 'month', 'custom'].includes(period) ? period : 'day'
      const range = options.resolveDistributionRange(normalized, options.getSelectedDate())
      if (!range.start || !range.end) return

      if (normalized === 'day') {
        options.setData({
          distributionPeriod: 'day',
          distributionRangeStart: range.start,
          distributionRangeEnd: range.end,
        })
        options.commitDistributionSubjects(options.getDaySubjectsRaw(), animate)
        return
      }

      const current = (seq += 1)
      options.setRequestSeq(current)
      options.setData({
        distributionPeriod: normalized,
        distributionRangeStart: range.start,
        distributionRangeEnd: range.end,
        pieLoading: true,
        selectedSubjectDetail: null,
        _selectedSubject: null,
      })
      try {
        await options.ensureSubjectMeta().catch(() => null)
        const summary = await options.getRangeSummary(range.start, range.end)
        if (
          !options.isAlive() ||
          current !== options.getRequestSeq() ||
          normalized !== options.getDistributionPeriod() ||
          range.start !== options.getDistributionRangeStart() ||
          range.end !== options.getDistributionRangeEnd()
        ) return
        options.commitDistributionSubjects((summary && summary.subjects) || [], animate)
      } catch (e) {
        if (!options.isAlive() || current !== options.getRequestSeq()) return
        options.logError('加载区间专注分布失败', e)
        options.setData({ pieLoading: false })
        options.showToast('分布统计加载失败')
      }
    },
  }
}

module.exports = {
  createDistributionLoadController,
}
