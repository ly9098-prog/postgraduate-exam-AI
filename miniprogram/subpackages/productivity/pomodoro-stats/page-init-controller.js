function createPageInitController(options) {
  return {
    initialize() {
      const internal = {
        _alive: true,
        _isVisible: false,
        _requestId: 0,
        _dynamicRefreshTimer: null,
        _statsLoadInFlight: 0,
        _viewReady: false,
        _hasData: false,
        _settingsLoaded: false,
        _finalDrawn: false,
        _displayTodayDurationSec: 0,
        _durationAnimationToken: 0,
        _durationAnimationTimer: null,
        _deferredHistoryTimer: null,
        _pendingHistoryCommit: null,
        _canvasInitPending: false,
        _canvasInitCallbacks: [],
        _barInitPending: false,
        _barInitCallbacks: [],
        _barAnimationToken: 0,
        _barRenderedOnce: false,
        _cumulativeCustomized: false,
        _cumulativeRequestSeq: 0,
        _distributionRequestSeq: 0,
        _daySubjectsRaw: [],
        _distributionRawSubjects: [],
        _subjectMetaLoaded: false,
        _subjectMeta: null,
        _shadeColorCache: options.createShadeColorCache(),
        _pieRenderCache: options.createPieRenderCache(),
        _subjectMetaPromise: null,
      }

      const themeMode = options.getTheme()
      options.applyNativeTheme(themeMode)
      const today = options.getChinaStudyDate(options.getDefaultDayStartMinute())
      const data = {
        selectedDate: today,
        _todayDate: today,
        pieDateLabel: '今日',
        canGoNextDate: false,
        cumulativePickerStartDate: options.shiftDate(today, -365),
        customRangePickerStartDate: options.shiftDate(today, -365),
        customRangeStartDate: today,
        distributionRangeStart: today,
        distributionRangeEnd: today,
        themeMode,
      }
      return { internal, data }
    },
  }
}

module.exports = {
  createPageInitController,
}
