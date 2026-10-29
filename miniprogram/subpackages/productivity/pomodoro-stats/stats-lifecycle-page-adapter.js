function onLoad(page) {
    const initialized = page._getPageInitController().initialize()
    Object.assign(page, initialized.internal)
    page.setData(initialized.data)
    page._init()
  }

async function _init(page, dependencies) {
const { getConsole } = dependencies
    await page._ensureSettings()
    page._ensureSubjectMeta().catch(err => {
      getConsole().warn('加载科目树失败，将使用原始分布数据', err)
    })
    // 首次加载由 onReady 的 loadData 完成（其内部 await _ensureSettings），
    // 此处不再重复触发，避免首屏并发两次 4 请求批次。
  }

function _getPageInitController(page, dependencies) {
const { chinaTime, createPageInitController, createShadeColorCache, pomodoroTheme } = dependencies
    if (!page._pageInitController) {
      page._pageInitController = createPageInitController({
        getTheme: () => pomodoroTheme.getTheme(),
        applyNativeTheme: themeMode => pomodoroTheme.applyNativeTheme(themeMode),
        getChinaStudyDate: minute => chinaTime.getChinaStudyDate(minute),
        getDefaultDayStartMinute: () => 0,
        shiftDate: (date, delta) => page._shiftDate(date, delta),
        createShadeColorCache,
        createPieRenderCache: () => ({ sectors: null, wallSteps: null, labelLayout: null }),
      })
    }
    return page._pageInitController
  }

function _getSettingsController(page, dependencies) {
const { api, chinaTime, createSettingsController, getConsole } = dependencies
    if (!page._settingsController) {
      page._settingsController = createSettingsController({
        isLoaded: () => page._settingsLoaded,
        markLoaded: () => { page._settingsLoaded = true },
        getSettings: () => api.get('/pomodoro/settings'),
        getTodayDate: () => page.data._todayDate,
        getSelectedDate: () => page.data.selectedDate,
        getCustomRangeStartDate: () => page.data.customRangeStartDate,
        getChinaStudyDate: minute => chinaTime.getChinaStudyDate(minute),
        minuteToTimeText: minute => chinaTime.minuteToTimeText(minute),
        getStudyDayRangeText: minute => page._studyDayRangeText(minute),
        shiftDate: (date, delta) => page._shiftDate(date, delta),
        setData: patch => page.setData(patch),
        logError: (message, e) => getConsole().error(message, e),
      })
    }
    return page._settingsController
  }

function _getLifecycleController(page, dependencies) {
const { createLifecycleController, getPlatform, getSetTimeout } = dependencies
    if (!page._lifecycleController) {
      page._lifecycleController = createLifecycleController({
        isAlive: () => page._alive,
        isVisible: () => page._isVisible,
        isViewReady: () => page._viewReady,
        setVisible: value => { page._isVisible = value },
        setViewReady: () => { page._viewReady = true },
        setAlive: value => { page._alive = value },
        incrementRequestId: () => { page._requestId++ },
        syncTheme: () => page._syncThemeFromStorage(),
        loadData: () => page.loadData(),
        scheduleDynamicRefresh: () => page._scheduleDynamicRefresh(),
        clearDynamicRefresh: () => page._clearDynamicRefresh(),
        cancelDurationAnimation: resetState => page._cancelDurationAnimation(resetState),
        cancelDeferredHistory: clearPending => page._cancelDeferredHistory(clearPending),
        cancelPendingWork: () => page._cancelPendingWork(),
        initCanvases: callback => page._initCanvases(callback),
        nextTick: callback => {
          if (getPlatform().nextTick) getPlatform().nextTick(callback)
          else getSetTimeout()(callback, 0)
        },
      })
    }
    return page._lifecycleController
  }

function _getDynamicRefreshController(page, dependencies) {
const { STATS_DYNAMIC_REFRESH_MS, createDynamicRefreshController, getClearTimeout, getSetTimeout } = dependencies
    if (!page._dynamicRefreshController) {
      page._dynamicRefreshController = createDynamicRefreshController({
        isAlive: () => page._alive,
        isVisible: () => page._isVisible,
        isViewReady: () => page._viewReady,
        getTimer: () => page._dynamicRefreshTimer,
        setTimer: timer => { page._dynamicRefreshTimer = timer },
        clearTimeout: getClearTimeout(),
        setTimeout: getSetTimeout(),
        getDefaultDelayMs: () => STATS_DYNAMIC_REFRESH_MS,
        getStatsLoadInFlight: () => page._statsLoadInFlight || 0,
        isCumulativeLoading: () => !!page.data.cumulativeLoading,
        incrementRequestId: () => { page._requestId++ },
        loadBackground: () => page.loadData({ background: true }),
        schedule: delay => page._scheduleDynamicRefresh(delay),
      })
    }
    return page._dynamicRefreshController
  }

function _getThemeSyncController(page, dependencies) {
const { createThemeSyncController, getPieSubjectColor, getPlatform, getSetTimeout, getSubjectColor, pomodoroTheme } = dependencies
    if (!page._themeSyncController) {
      page._themeSyncController = createThemeSyncController({
        getStoredTheme: () => pomodoroTheme.getTheme(),
        applyNativeTheme: themeMode => pomodoroTheme.applyNativeTheme(themeMode),
        getCurrentTheme: () => page.data.themeMode,
        getSubjects: () => page.data.subjects,
        getHistory: () => page.data.history,
        getPieSubjectColor: (key, themeMode) => getPieSubjectColor(key, themeMode),
        getSubjectColor: (key, themeMode) => getSubjectColor(key, themeMode),
        setData: (patch, callback) => page.setData(patch, callback),
        resetPieCache: () => page._resetPieCache(),
        isAlive: () => page._alive,
        isViewReady: () => page._viewReady,
        hasData: () => page._hasData,
        isVisible: () => page._isVisible,
        getChartMode: () => page.data.chartMode,
        renderPie: (progress, includeLabels) => page._renderPieChart(progress, includeLabels),
        isBarMounted: () => !!page.data.barCanvasMounted,
        hasTrendContext: () => !!page._trendCtx,
        renderTrendBars: progress => page._renderTrendBars(progress),
        nextTick: callback => {
          if (getPlatform().nextTick) getPlatform().nextTick(callback)
          else getSetTimeout()(callback, 0)
        },
      })
    }
    return page._themeSyncController
  }

module.exports = { onLoad, _init, _getPageInitController, _getSettingsController, _getLifecycleController, _getDynamicRefreshController, _getThemeSyncController }
