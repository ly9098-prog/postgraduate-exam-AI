const { buildDateViewState } = require('./date-view-state')
const overviewMapping = require('./overview-mapping')

function buildDateRequestPageCapabilities(page, dependencies) {
  const { api } = dependencies
  return {
    ...buildDateRequestStateCapabilities(page),
    ...buildDateRequestNetworkCapabilities(page, api),
    ...buildDateRequestViewCapabilities(page),
  }
}

function buildDateRequestStateCapabilities(page) {
  return {
    isAlive: () => page._alive,
    isVisible: () => page._isVisible,
    getDateRequestSeq: () => page._dateRequestSeq,
    incrementDateRequestSeq: () => {
      page._dateRequestSeq = (page._dateRequestSeq || 0) + 1
    },
    getSelectedDate: () => page.data.selectedDate,
    getTodayDate: () => page.data._todayDate,
    getDistributionPeriod: () => page.data.distributionPeriod,
    setData: patch => page.setData(patch),
  }
}

function buildDateRequestNetworkCapabilities(page, api) {
  return {
    getInitialResponses: (requestDate, viewingToday) => Promise.all([
      // Viewing today omits date so the backend returns the authoritative study day.
      api.get('/pomodoro/daily-summary', viewingToday ? {} : { date: requestDate }),
      api.get('/pomodoro/history', { page: 1, page_size: 20, date: requestDate }),
    ]),
    getHistory: date => api.get('/pomodoro/history', {
      page: 1,
      page_size: 20,
      date,
    }),
    reconcileFromServer: (stats, summary) => page._reconcileFromServer(stats, summary),
    logError: (message, error) => console.error(message, error),
  }
}

function buildDateRequestViewCapabilities(page) {
  return {
    buildDateViewState: overrides => buildDateViewState({
      ...overrides,
      currentDisplayDurationSec: page._displayTodayDurationSec,
      currentRawDurationSec: page._rawTodayDur,
      currentDisplaySessions: page.data._dispTodaySessions,
      currentSubjects: page.data.subjects,
      currentDistributionHasData: page.data.distributionHasData,
      currentRangeStart: page.data.distributionRangeStart,
      currentRangeEnd: page.data.distributionRangeEnd,
      hasCrossDayBleedInSubjects: overviewMapping.hasCrossDayBleedInSubjects,
      buildSubjectItems: subjects => page._buildSubjectItems(subjects),
      hasDistributionData: subjects => page._hasDistributionData(subjects),
      formatMin: sec => page._fmtMin(sec),
      formatSelectedDurationLabel: date => page._formatSelectedDurationLabel(date),
      formatSession: item => page._formatSession(item),
      formatPieDateLabel: date => page._formatPieDateLabel(date),
    }),
    setRawTodayDuration: value => { page._rawTodayDur = value },
    setDaySubjectsRaw: value => { page._daySubjectsRaw = value },
    resetPieCache: () => page._resetPieCache(),
    commitDate: (viewState, context) => {
      page._getDateCommitController().commit(viewState, context)
    },
    handleDateFailure: (error, context) => {
      page._getDateFailureController().handle(error, context)
    },
  }
}

module.exports = {
  buildDateRequestPageCapabilities,
}
