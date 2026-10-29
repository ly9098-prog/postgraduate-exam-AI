function _getSubjectMetaController(page, dependencies) {
const { api, createSubjectMetaController, getConsole } = dependencies
    if (!page._subjectMetaController) {
      page._subjectMetaController = createSubjectMetaController({
        isLoaded: () => page._subjectMetaLoaded,
        getMeta: () => page._subjectMeta,
        setMeta: value => { page._subjectMeta = value },
        getPromise: () => page._subjectMetaPromise,
        setPromise: value => { page._subjectMetaPromise = value },
        markLoaded: () => { page._subjectMetaLoaded = true },
        getSubjectTree: () => api.get('/practice/subjects'),
        buildSubjectMeta: tree => page._buildSubjectMeta(tree),
        logError: (message, error) => getConsole().error(message, error),
      })
    }
    return page._subjectMetaController
  }

function _getCumulativeRefreshController(page, dependencies) {
const { api, createCumulativeRefreshController, getConsole, getPlatform } = dependencies
    if (!page._cumulativeRefreshController) {
      page._cumulativeRefreshController = createCumulativeRefreshController({
        isAlive: () => page._alive,
        getTodayDate: () => page.data._todayDate,
        getCumulativeStartDate: () => page.data.cumulativeStartDate,
        getRequestSeq: () => page._cumulativeRequestSeq,
        setRequestSeq: value => { page._cumulativeRequestSeq = value },
        getRangeSummary: (start, end) => api.get('/pomodoro/range-summary', { start_date: start, end_date: end }),
        buildSummaryPatch: (summary, start) => page._cumulativeSummaryPatch(summary, start),
        setData: patch => page.setData(patch),
        showToast: title => { if (getPlatform().showToast) getPlatform().showToast({ title, icon: 'none' }) },
        logError: (message, e) => getConsole().error(message, e),
      })
    }
    return page._cumulativeRefreshController
  }

function _getCumulativeStartController(page, dependencies) {
const { createCumulativeStartController } = dependencies
    if (!page._cumulativeStartController) {
      page._cumulativeStartController = createCumulativeStartController({
        getTodayDate: () => page.data._todayDate,
        getPickerStartDate: () => page.data.cumulativePickerStartDate,
        getCumulativeStartDate: () => page.data.cumulativeStartDate,
        shiftDate: (date, delta) => page._shiftDate(date, delta),
        markCustomized: () => { page._cumulativeCustomized = true },
        setData: (patch, callback) => page.setData(patch, callback),
        refreshCumulativeSummary: (date, silent) => page._refreshCumulativeSummary(date, silent),
      })
    }
    return page._cumulativeStartController
  }

function _getDistributionCommitController(page, dependencies) {
const { createDistributionCommitController } = dependencies
    if (!page._distributionCommitController) {
      page._distributionCommitController = createDistributionCommitController({
        isAlive: () => page._alive,
        isVisible: () => page._isVisible,
        getChartMode: () => page.data.chartMode,
        setRawSubjects: subjects => { page._distributionRawSubjects = subjects },
        resetPieCache: () => page._resetPieCache(),
        buildSubjectItems: subjects => page._buildSubjectItems(subjects),
        hasDistributionData: subjects => page._hasDistributionData(subjects),
        setData: (patch, callback) => page.setData(patch, callback),
        initCanvases: callback => page._initCanvases(callback),
        animatePieOnly: () => page._animatePieOnly(),
        renderPie: (progress, includeLabels) => page._renderPieChart(progress, includeLabels),
      })
    }
    return page._distributionCommitController
  }

function _getDistributionLoadController(page, dependencies) {
const { api, createDistributionLoadController, getConsole, getPlatform } = dependencies
    if (!page._distributionLoadController) {
      page._distributionLoadController = createDistributionLoadController({
        isAlive: () => page._alive,
        getSelectedDate: () => page.data.selectedDate,
        getDaySubjectsRaw: () => page._daySubjectsRaw || [],
        getDistributionPeriod: () => page.data.distributionPeriod,
        getDistributionRangeStart: () => page.data.distributionRangeStart,
        getDistributionRangeEnd: () => page.data.distributionRangeEnd,
        getRequestSeq: () => page._distributionRequestSeq,
        setRequestSeq: value => { page._distributionRequestSeq = value },
        resolveDistributionRange: (period, anchor) => page._resolveDistributionRange(period, anchor),
        ensureSubjectMeta: () => page._ensureSubjectMeta(),
        getRangeSummary: (start, end) => api.get('/pomodoro/range-summary', { start_date: start, end_date: end }),
        commitDistributionSubjects: (subjects, animate) => page._commitDistributionSubjects(subjects, animate),
        setData: patch => page.setData(patch),
        showToast: title => { if (getPlatform().showToast) getPlatform().showToast({ title, icon: 'none' }) },
        logError: (message, e) => getConsole().error(message, e),
      })
    }
    return page._distributionLoadController
  }

function _getDistributionEntryController(page, dependencies) {
const { createDistributionEntryController } = dependencies
    if (!page._distributionEntryController) {
      page._distributionEntryController = createDistributionEntryController({
        getSelectedDate: () => page.data.selectedDate,
        getTodayDate: () => page.data._todayDate,
        getDistributionPeriod: () => page.data.distributionPeriod,
        getCustomRangePickerStartDate: () => page.data.customRangePickerStartDate,
        shiftDate: (date, delta) => page._shiftDate(date, delta),
        setData: (patch, callback) => page.setData(patch, callback),
        loadDistributionForPeriod: (period, animate) => page._loadDistributionForPeriod(period, animate),
      })
    }
    return page._distributionEntryController
  }

module.exports = { _getSubjectMetaController, _getCumulativeRefreshController, _getCumulativeStartController, _getDistributionCommitController, _getDistributionLoadController, _getDistributionEntryController }
