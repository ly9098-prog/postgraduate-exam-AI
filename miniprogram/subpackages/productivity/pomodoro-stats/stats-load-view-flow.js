function _getLoadCommitController(page, dependencies) {
const { buildLoadCommitPageCapabilities, createLoadCommitController } = dependencies
    if (!page._loadCommitController) {
      page._loadCommitController = createLoadCommitController(
        buildLoadCommitPageCapabilities(page)
      )
    }
    return page._loadCommitController
  }

function _getLoadFailureController(page, dependencies) {
const { buildLoadFailurePageCapabilities, createLoadFailureController } = dependencies
    if (!page._loadFailureController) {
      page._loadFailureController = createLoadFailureController(
        buildLoadFailurePageCapabilities(page)
      )
    }
    return page._loadFailureController
  }

function _createLoadRequestController(page, dependencies) {
const { createLoadRequestControllerFactory } = dependencies
    return createLoadRequestControllerFactory(
      page._loadRequestControllerConfig()
    ).create()
  }

function _loadRequestControllerConfig(page, dependencies) {
const { buildLoadRequestControllerCapabilities, createLoadRequestController } = dependencies
    return {
      createLoadRequestController,
      ...buildLoadRequestControllerCapabilities(
        page._loadRequestControllerCapabilities()
      ),
    }
  }

function _loadRequestControllerCapabilities(page, dependencies) {
const { api, buildLoadRequestPageCapabilities, overviewMapping } = dependencies
    return buildLoadRequestPageCapabilities(page, {
      api,
      normalizeOverview: overviewMapping.normalizeOverview,
    })
  }

function _getLoadRequestController(page) {
    if (!page._loadRequestController) {
      page._loadRequestController = page._createLoadRequestController()
    }
    return page._loadRequestController
  }

function _buildLoadViewState(page, overrides, dependencies) {
const { buildLoadViewState, overviewMapping } = dependencies
    return buildLoadViewState({
      ...overrides,
      currentLifetimeStartDate: page.data.lifetimeStartDate,
      currentSubjects: page.data.subjects,
      currentDistributionHasData: page.data.distributionHasData,
      currentRangeStart: page.data.distributionRangeStart,
      currentRangeEnd: page.data.distributionRangeEnd,
      hasCrossDayBleedInSubjects: overviewMapping.hasCrossDayBleedInSubjects,
      formatSession: item => page._formatSession(item),
      formatMin: sec => page._fmtMin(sec),
      formatSelectedDurationLabel: date => page._formatSelectedDurationLabel(date),
      hasDistributionData: items => page._hasDistributionData(items),
      buildSubjectItems: subjects => page._buildSubjectItems(subjects),
      formatPieDateLabel: date => page._formatPieDateLabel(date),
      getDurationDisplayPatch: text => page._getTodayDurationDisplayPatch(text),
      buildCumulativePatch: (lifetimeSummary, lifetimeStart) => page._buildCumulativePatch(lifetimeSummary, lifetimeStart),
    })
  }

function _buildCumulativePatch(page, lifetimeSummary, lifetimeStart) {
    if (page._cumulativeCustomized) return { lifetimeStartDate: lifetimeStart }
    return {
      lifetimeStartDate: lifetimeStart,
      ...page._cumulativeSummaryPatch({ ...lifetimeSummary, start_date: lifetimeStart }, lifetimeStart),
    }
  }

function _reconcileFromServer(page, stats, summary, dependencies) {
const { chinaTime, reconcileFromServer } = dependencies
    const result = reconcileFromServer({
      stats,
      summary,
      dayStartMinute: page.data.dayStartMinute,
      todayDate: page.data._todayDate,
      selectedDate: page.data.selectedDate,
      customRangeStartDate: page.data.customRangeStartDate,
      minuteToTimeText: minute => chinaTime.minuteToTimeText(minute),
      getStudyDayRangeText: minute => page._studyDayRangeText(minute),
      shiftDate: (date, delta) => page._shiftDate(date, delta),
    })
    if (stats && stats.day_start_minute != null) page._settingsLoaded = true
    if (Object.keys(result.patch).length) page.setData(result.patch)
    return {
      changedToday: result.changedToday,
      today: result.today,
      selectedDate: result.selectedDate,
    }
  }

function _formatSession(page, s, dependencies) {
const { getSubjectColor, sessionViewModel, storage } = dependencies
    return sessionViewModel.formatSession(s, {
      getTaskTypeLabel: session => storage.pomodoroTaskTypes.labelForSession(session),
      getSubjectColor: key => getSubjectColor(key, page.data.themeMode),
    })
  }

function _cumulativeSummaryPatch(page, summary, requestedStart, dependencies) {
const { buildCumulativeSummaryPatch } = dependencies
    return buildCumulativeSummaryPatch(summary, requestedStart, page.data._todayDate, sec => page._fmtMin(sec))
  }

function _getTodayDurationDisplayPatch(page, text) {
    return {
      _dispTodayDurationText: text,
      _dispTodayDurationSegments: page._buildDurationSegments(text),
    }
  }

module.exports = { _getLoadCommitController, _getLoadFailureController, _createLoadRequestController, _loadRequestControllerConfig, _loadRequestControllerCapabilities, _getLoadRequestController, _buildLoadViewState, _buildCumulativePatch, _reconcileFromServer, _formatSession, _cumulativeSummaryPatch, _getTodayDurationDisplayPatch }
