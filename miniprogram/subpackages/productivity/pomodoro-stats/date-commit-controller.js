function createDateCommitController(options) {
  return {
    commit(viewState, context) {
      options.setRawTodayDuration(viewState.selectedDurationSec)
      options.setDaySubjectsRaw(viewState.subjectBreakdown)
      if (context.showDayDistribution) options.resetPieCache()

      options.setData(viewState.dataPatch, () => {
        if (!options.isAlive() || !options.isVisible() || context.seq !== options.getDateRequestSeq()) return
        options.animateSelectedDuration(
          viewState.previousDurationSec,
          viewState.selectedDurationSec,
          viewState.previousSessionCount,
          viewState.selectedSessionCount
        )

        if (!context.showDayDistribution) {
          options.loadDistributionForPeriod(options.getDistributionPeriod(), true)
          return
        }
        if (options.getChartMode() !== 'pie') return
        if (options.isPieReady()) options.animatePieOnly()
        else options.initCanvases(() => {
          if (options.isAlive() && options.isVisible() && options.getChartMode() === 'pie') {
            options.animatePieOnly()
          }
        })
      })
    },
  }
}

module.exports = {
  createDateCommitController,
}
