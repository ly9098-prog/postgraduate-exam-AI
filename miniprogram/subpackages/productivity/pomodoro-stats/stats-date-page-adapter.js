function _getSelectDateController(page, dependencies) {
const { createSelectDateController } = dependencies
    if (!page._selectDateController) {
      page._selectDateController = createSelectDateController({
        getTodayDate: () => page.data._todayDate,
        getSelectedDate: () => page.data.selectedDate,
        getCustomRangeStartDate: () => page.data.customRangeStartDate,
        cancelDeferredHistory: () => page._cancelDeferredHistory(true),
        formatPieDateLabel: date => page._formatPieDateLabel(date),
        formatSelectedDurationLabel: date => page._formatSelectedDurationLabel(date),
        shiftDate: (date, delta) => page._shiftDate(date, delta),
        setData: (patch, callback) => page.setData(patch, callback),
        loadDateData: date => page.loadDateData(date),
      })
    }
    return page._selectDateController
  }

function _getDayStartEntryController(page, dependencies) {
const { chinaTime, createDayStartEntryController } = dependencies
    if (!page._dayStartEntryController) {
      page._dayStartEntryController = createDayStartEntryController({
        timeTextToMinute: timeText => chinaTime.timeTextToMinute(timeText),
        getDayStartMinute: () => page.data.dayStartMinute,
        saveDayStart: minute => page._saveDayStart(minute),
      })
    }
    return page._dayStartEntryController
  }

function _getSaveDayStartController(page, dependencies) {
const { api, chinaTime, createSaveDayStartController, getConsole, getPlatform } = dependencies
    if (!page._saveDayStartController) {
      page._saveDayStartController = createSaveDayStartController({
        isAlive: () => page._alive,
        isViewReady: () => page._viewReady,
        getSelectedDate: () => page.data.selectedDate,
        getCustomRangeStartDate: () => page.data.customRangeStartDate,
        markSettingsLoaded: () => { page._settingsLoaded = true },
        showLoading: () => { if (getPlatform().showLoading) getPlatform().showLoading({ title: '保存中', mask: true }) },
        hideLoading: () => { if (getPlatform().hideLoading) getPlatform().hideLoading() },
        showToast: title => { if (getPlatform().showToast) getPlatform().showToast({ title, icon: 'none' }) },
        logError: (message, e) => getConsole().error(message, e),
        saveSettings: minute => api.put('/pomodoro/settings', { day_start_minute: minute }),
        getChinaStudyDate: minute => chinaTime.getChinaStudyDate(minute),
        minuteToTimeText: minute => chinaTime.minuteToTimeText(minute),
        getStudyDayRangeText: minute => page._studyDayRangeText(minute),
        formatPieDateLabel: date => page._formatPieDateLabel(date),
        formatSelectedDurationLabel: date => page._formatSelectedDurationLabel(date),
        setData: (patch, callback) => page.setData(patch, callback),
        loadData: () => page.loadData(),
      })
    }
    return page._saveDayStartController
  }

function _getDateNavigationController(page, dependencies) {
const { createDateNavigationController } = dependencies
    if (!page._dateNavigationController) {
      page._dateNavigationController = createDateNavigationController({
        getTodayDate: () => page.data._todayDate,
        getSelectedDate: () => page.data.selectedDate,
        canGoNextDate: () => page.data.canGoNextDate,
        shiftDate: (date, delta) => page._shiftDate(date, delta),
        selectDate: date => page._selectDate(date),
      })
    }
    return page._dateNavigationController
  }

function _getDateCommitController(page, dependencies) {
const { buildDateCommitPageCapabilities, createDateCommitController } = dependencies
    if (!page._dateCommitController) {
      page._dateCommitController = createDateCommitController(
        buildDateCommitPageCapabilities(page)
      )
    }
    return page._dateCommitController
  }

function _getDateFailureController(page, dependencies) {
const { buildDateFailurePageCapabilities, createDateFailureController, getPlatform } = dependencies
    if (!page._dateFailureController) {
      page._dateFailureController = createDateFailureController(
        buildDateFailurePageCapabilities(page, { wx: getPlatform() })
      )
    }
    return page._dateFailureController
  }

function _getDateRequestController(page, dependencies) {
const { api, buildDateRequestPageCapabilities, createDateRequestController } = dependencies
    if (!page._dateRequestController) {
      page._dateRequestController = createDateRequestController(
        buildDateRequestPageCapabilities(page, { api })
      )
    }
    return page._dateRequestController
  }

function onDateChange(page, e) {
    const date = e && e.detail ? e.detail.value : ''
    page._selectDate(date)
  }

module.exports = { _getSelectDateController, _getDayStartEntryController, _getSaveDayStartController, _getDateNavigationController, _getDateCommitController, _getDateFailureController, _getDateRequestController, onDateChange }
