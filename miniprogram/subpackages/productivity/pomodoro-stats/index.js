const api = require('../../../utils/api')
const pomodoroTheme = require('../utils/pomodoro-theme')
const chinaTime = require('../utils/china-time')
const storage = require('../../../utils/storage')

const STATS_DYNAMIC_REFRESH_MS = 60 * 1000
const dateUtils = require('./date-utils')
const viewHelpers = require('./view-helpers')
const durationFormatter = require('./duration-formatter')
const subjectDistribution = require('./subject-distribution')
const sessionViewModel = require('./session-view-model')
const pieLabelLayout = require('./pie-label-layout')
const trendChart = require('./trend-chart')
const { createDurationAnimationController } = require('./duration-animation-controller')
const { createPieTapController } = require('./pie-tap-controller')
const { createStartAnimationsController } = require('./start-animations-controller')
const pieGeometry = require('./pie-geometry')
const { createShadeColorCache } = require('./shade-color-cache')
const canvasPalette = require('./canvas-palette')
const subjectItems = require('./subject-items')
const pieLabelRenderer = require('./pie-label-renderer')
const pieSectorBuilder = require('./pie-sector-builder')
const pieRenderer = require('./pie-renderer')
const { createDistributionCommitController } = require('./distribution-commit-controller')
const { createSaveDayStartController } = require('./save-day-start-controller')
const { createSettingsController } = require('./settings-controller')
const { reconcileFromServer } = require('./reconcile-controller')
const { buildCumulativeSummaryPatch } = require('./cumulative-summary-patch')
const { formatStudyDayRangeText } = require('./study-day-range-text')
const { createSelectDateController } = require('./select-date-controller')
const { createCumulativeRefreshController } = require('./cumulative-refresh-controller')
const { createDistributionLoadController } = require('./distribution-load-controller')
const { createTrendAnimationController } = require('./trend-animation-controller')
const { createPieAnimationController } = require('./pie-animation-controller')
const { createPieLabelRevealController } = require('./pie-label-reveal-controller')
const { createCancelWorkController } = require('./cancel-work-controller')
const overviewMapping = require('./overview-mapping')
const { buildLoadViewState } = require('./load-view-state')
const { buildDateViewState } = require('./date-view-state')
const { createStatsCanvasInitController } = require('./canvas-init-controller')
const { createThemeSyncController } = require('./theme-sync-controller')
const { createDeferredHistoryController } = require('./deferred-history-controller')
const { createLoadCommitController } = require('./load-commit-controller')
const { createDateCommitController } = require('./date-commit-controller')
const { createLoadFailureController } = require('./load-failure-controller')
const { createDateFailureController } = require('./date-failure-controller')
const { createDateRequestController } = require('./date-request-controller')
const { createChartModeController } = require('./chart-mode-controller')
const { createDynamicRefreshController } = require('./dynamic-refresh-controller')
const { createLoadRequestController } = require('./load-request-controller')
const { createLoadRequestControllerFactory } = require('./load-request-controller-factory')
const { createPageInitController } = require('./page-init-controller')

const {
  getSubjectColor,
  getPieSubjectColor,
} = subjectItems

var pageConfig = {
  data: {
    loading: true,
    contentReady: false,
    historyReady: false,
    themeMode: 'light',
    errorText: '',
    todaySessions: 0,
    todayDurationText: '0分钟',
    selectedDurationLabel: '今日学习',
    weekSessions: 0,
    weekDurationText: '0分钟',
    trends: [],
    trendHasData: false,
    subjects: [],
    distributionHasData: false,
    history: [],
    historyTotal: 0,

    // 累计专注摘要。默认使用 statistics-overview 的 lifetime_summary；
    // 用户主动修改起始日后，改用 range-summary 精确刷新。
    lifetimeStartDate: '',
    datePickerMinDate: '1970-01-01',
    cumulativePickerStartDate: '',
    customRangePickerStartDate: '',
    cumulativeStartDate: '',
    cumulativeSessions: 0,
    cumulativeDurationText: '0分钟',
    cumulativeAverageText: '0分钟',
    cumulativeActiveDays: 0,
    cumulativeLoading: false,

    // 统计日设置（后端为权威，此处为本地展示/计算缓存）
    dayStartMinute: 0,
    dayStartTime: '00:00',
    studyDayRangeText: '统计日从 00:00 开始',
    dayStartNoteText: '学习时长按统计日边界拆分，专注次数按开始时间归属',
    // 当日无"开始"记录但有时长（跨统计日 session 归属到本日）时用于空态文案
    _crossDayBleedIn: false,

    // 当日卡片的日期同时过滤最近记录，并作为周/月/自定义分布的锚点。
    selectedDate: '',
    _todayDate: '',
    pieDateLabel: '今日',
    pieLoading: false,
    canGoNextDate: false,

    // 分布图默认只挂载扇形图。柱状图 canvas 直到用户第一次点击切换才创建。
    chartMode: 'pie',
    barCanvasMounted: false,
    barRendering: false,
    distributionPeriod: 'day',
    customRangeStartDate: '',
    distributionRangeStart: '',
    distributionRangeEnd: '',

    // pie chart detail popup
    selectedSubjectDetail: null,
    _selectedSubject: null,
    pieTapped: false,

    // Animated display values
    _dispTodaySessions: 0,
    _dispTodayDurationText: '0分钟',
    _dispTodayDurationSegments: [{ type: 'num', text: '0' }, { type: 'unit', text: '分钟' }],
    durationValueAnimating: false,
    _dispWeekSessions: 0,
    _dispWeekDurationText: '0分钟',
  },

  onLoad() {
    const initialized = this._getPageInitController().initialize()
    Object.assign(this, initialized.internal)
    this.setData(initialized.data)
    this._init()
  },

  _getPageInitController() {
    if (!this._pageInitController) {
      this._pageInitController = createPageInitController({
        getTheme: () => pomodoroTheme.getTheme(),
        applyNativeTheme: themeMode => pomodoroTheme.applyNativeTheme(themeMode),
        getChinaStudyDate: minute => chinaTime.getChinaStudyDate(minute),
        getDefaultDayStartMinute: () => 0,
        shiftDate: (date, delta) => this._shiftDate(date, delta),
        createShadeColorCache,
        createPieRenderCache: () => ({ sectors: null, wallSteps: null, labelLayout: null }),
      })
    }
    return this._pageInitController
  },

  async _init() {
    await this._ensureSettings()
    this._ensureSubjectMeta().catch(err => {
      console.warn('加载科目树失败，将使用原始分布数据', err)
    })
    // 首次加载由 onReady 的 loadData 完成（其内部 await _ensureSettings），
    // 此处不再重复触发，避免首屏并发两次 4 请求批次。
  },

  /**
   * 获取统计日设置（后端权威），据此校正当前中国统计日 / selectedDate。
   * 幂等：请求进行中缓存同一 Promise，避免并发重复请求；成功后不再请求。
   * loadData 先 await 本方法再读取 selectedDate，保证首次加载就使用正确统计日。
   */
  _ensureSettings() {
    return this._getSettingsController().ensure()
  },

  _getSettingsController() {
    if (!this._settingsController) {
      this._settingsController = createSettingsController({
        isLoaded: () => this._settingsLoaded,
        markLoaded: () => { this._settingsLoaded = true },
        getSettings: () => api.get('/pomodoro/settings'),
        getTodayDate: () => this.data._todayDate,
        getSelectedDate: () => this.data.selectedDate,
        getCustomRangeStartDate: () => this.data.customRangeStartDate,
        getChinaStudyDate: minute => chinaTime.getChinaStudyDate(minute),
        minuteToTimeText: minute => chinaTime.minuteToTimeText(minute),
        getStudyDayRangeText: minute => this._studyDayRangeText(minute),
        shiftDate: (date, delta) => this._shiftDate(date, delta),
        setData: patch => this.setData(patch),
        logError: (message, e) => console.error(message, e),
      })
    }
    return this._settingsController
  },

  /**
   * 以后端返回的统计日（/pomodoro/stats.today_date 或今日 daily-summary.date）为唯一权威，
   * 校正客户端基于设备时钟/本地缓存计算的"今日"与 day_start，覆盖 settings 请求失败、
   * 设备时钟偏差导致的"今日"不一致。
   */
  _reconcileFromServer(stats, summary) {
    const result = reconcileFromServer({
      stats,
      summary,
      dayStartMinute: this.data.dayStartMinute,
      todayDate: this.data._todayDate,
      selectedDate: this.data.selectedDate,
      customRangeStartDate: this.data.customRangeStartDate,
      minuteToTimeText: minute => chinaTime.minuteToTimeText(minute),
      getStudyDayRangeText: minute => this._studyDayRangeText(minute),
      shiftDate: (date, delta) => this._shiftDate(date, delta),
    })
    if (stats && stats.day_start_minute != null) this._settingsLoaded = true
    if (Object.keys(result.patch).length) this.setData(result.patch)
    return {
      changedToday: result.changedToday,
      today: result.today,
      selectedDate: result.selectedDate,
    }
  },

  _studyDayRangeText(dsm) {
    return formatStudyDayRangeText(dsm, minute => chinaTime.minuteToTimeText(minute))
  },

  onShow() {
    this._isVisible = true
    this._syncThemeFromStorage()
    if (!this._viewReady) return
    this._requestId++
    this.loadData()
    this._scheduleDynamicRefresh()
  },

  onReady() {
    this._viewReady = true
    this._isVisible = true
    this._requestId++
    this.loadData()
    this._scheduleDynamicRefresh()
    const warmCanvases = () => {
      if (!this._alive || !this._isVisible) return
      this._initCanvases(() => {})
    }
    if (wx.nextTick) wx.nextTick(warmCanvases)
    else setTimeout(warmCanvases, 0)
  },

  onHide() {
    this._isVisible = false
    this._clearDynamicRefresh()
    this._cancelDurationAnimation(false)
    this._cancelDeferredHistory(true)
  },

  onUnload() {
    this._alive = false
    this._isVisible = false
    this._cancelPendingWork()
  },


  _clearDynamicRefresh() {
    this._getDynamicRefreshController().cancel()
  },

  _scheduleDynamicRefresh(delayMs) {
    this._getDynamicRefreshController().schedule(delayMs)
  },

  _getDynamicRefreshController() {
    if (!this._dynamicRefreshController) {
      this._dynamicRefreshController = createDynamicRefreshController({
        isAlive: () => this._alive,
        isVisible: () => this._isVisible,
        isViewReady: () => this._viewReady,
        getTimer: () => this._dynamicRefreshTimer,
        setTimer: timer => { this._dynamicRefreshTimer = timer },
        clearTimeout,
        setTimeout,
        getDefaultDelayMs: () => STATS_DYNAMIC_REFRESH_MS,
        getStatsLoadInFlight: () => this._statsLoadInFlight || 0,
        isCumulativeLoading: () => !!this.data.cumulativeLoading,
        incrementRequestId: () => { this._requestId++ },
        loadBackground: () => this.loadData({ background: true }),
        schedule: delay => this._scheduleDynamicRefresh(delay),
      })
    }
    return this._dynamicRefreshController
  },

  _syncThemeFromStorage() {
    return this._getThemeSyncController().sync()
  },

  _getThemeSyncController() {
    if (!this._themeSyncController) {
      this._themeSyncController = createThemeSyncController({
        getStoredTheme: () => pomodoroTheme.getTheme(),
        applyNativeTheme: themeMode => pomodoroTheme.applyNativeTheme(themeMode),
        getCurrentTheme: () => this.data.themeMode,
        getSubjects: () => this.data.subjects,
        getHistory: () => this.data.history,
        getPieSubjectColor: (key, themeMode) => getPieSubjectColor(key, themeMode),
        getSubjectColor: (key, themeMode) => getSubjectColor(key, themeMode),
        setData: (patch, callback) => this.setData(patch, callback),
        resetPieCache: () => this._resetPieCache(),
        isAlive: () => this._alive,
        isViewReady: () => this._viewReady,
        hasData: () => this._hasData,
        isVisible: () => this._isVisible,
        getChartMode: () => this.data.chartMode,
        renderPie: (progress, includeLabels) => this._renderPieChart(progress, includeLabels),
        isBarMounted: () => !!this.data.barCanvasMounted,
        hasTrendContext: () => !!this._trendCtx,
        renderTrendBars: progress => this._renderTrendBars(progress),
        nextTick: callback => {
          if (wx.nextTick) wx.nextTick(callback)
          else setTimeout(callback, 0)
        },
      })
    }
    return this._themeSyncController
  },

  _getCanvasPalette() {
    return canvasPalette.getCanvasPalette(this.data.themeMode)
  },

  /* ==================== Color Helpers ==================== */

  _easeOutCubic(t) {
    return viewHelpers.easeOutCubic(t)
  },

  _easeInOutCubic(t) {
    return viewHelpers.easeInOutCubic(t)
  },

  _parseDateStr(s) {
    return dateUtils.parseDateStr(s)
  },
  _formatDateParts(parts) {
    return dateUtils.formatDateParts(parts)
  },
  _shiftDate(value, deltaDays) {
    return dateUtils.shiftDate(value, deltaDays)
  },
  _startOfWeek(value) {
    return dateUtils.startOfWeek(value)
  },
  _monthStart(value) {
    return dateUtils.monthStart(value)
  },
  _monthEnd(value) {
    return dateUtils.monthEnd(value)
  },
  _minDate(a, b) {
    return dateUtils.minDate(a, b)
  },
  _resolveDistributionRange(period, anchorDate) {
    return dateUtils.resolveDistributionRange(period, anchorDate, {
      selectedDate: this.data.selectedDate,
      todayDate: this.data._todayDate,
      customRangeStartDate: this.data.customRangeStartDate,
    })
  },
  _formatPieDateLabel(value) {
    return viewHelpers.formatPieDateLabel(value, this.data._todayDate)
  },

  _formatSelectedDurationLabel(value) {
    return viewHelpers.formatSelectedDurationLabel(value, this.data._todayDate)
  },

  _hasDistributionData(subjects) {
    return viewHelpers.hasDistributionData(subjects)
  },


  _ensureSubjectMeta() {
    if (this._subjectMetaLoaded) return Promise.resolve(this._subjectMeta)
    if (this._subjectMetaPromise) return this._subjectMetaPromise
    this._subjectMetaPromise = this._loadSubjectMeta()
    return this._subjectMetaPromise
  },

  async _loadSubjectMeta() {
    try {
      const rawTree = await api.get('/practice/subjects')
      this._subjectMeta = this._buildSubjectMeta(rawTree)
      return this._subjectMeta
    } catch (e) {
      console.error('加载科目树失败', e)
      this._subjectMeta = null
      return null
    } finally {
      this._subjectMetaLoaded = true
      this._subjectMetaPromise = null
    }
  },

  _buildSubjectMeta(tree) {
    return subjectDistribution.buildSubjectMeta(tree)
  },

  _distributeAggregateValue(total, leafIds, currentTotals) {
    return subjectDistribution.distributeAggregateValue(total, leafIds, currentTotals)
  },

  _normalizeDistributionSubjects(subjects) {
    return subjectDistribution.normalizeDistributionSubjects(subjects, this._subjectMeta)
  },

  _buildSubjectItems(subjects) {
    return subjectItems.buildSubjectItems(subjects, this._subjectMeta, this.data.themeMode)
  },


  _cumulativeSummaryPatch(summary, requestedStart) {
    return buildCumulativeSummaryPatch(summary, requestedStart, this.data._todayDate, sec => this._fmtMin(sec))
  },

  async _refreshCumulativeSummary(startDate, silent) {
    await this._getCumulativeRefreshController().refresh(startDate, silent)
  },

  _getCumulativeRefreshController() {
    if (!this._cumulativeRefreshController) {
      this._cumulativeRefreshController = createCumulativeRefreshController({
        isAlive: () => this._alive,
        getTodayDate: () => this.data._todayDate,
        getCumulativeStartDate: () => this.data.cumulativeStartDate,
        getRequestSeq: () => this._cumulativeRequestSeq,
        setRequestSeq: value => { this._cumulativeRequestSeq = value },
        getRangeSummary: (start, end) => api.get('/pomodoro/range-summary', { start_date: start, end_date: end }),
        buildSummaryPatch: (summary, start) => this._cumulativeSummaryPatch(summary, start),
        setData: patch => this.setData(patch),
        showToast: title => { if (wx.showToast) wx.showToast({ title, icon: 'none' }) },
        logError: (message, e) => console.error(message, e),
      })
    }
    return this._cumulativeRefreshController
  },

  onCumulativeStartChange(e) {
    let date = e && e.detail ? String(e.detail.value || '') : ''
    if (!date) return
    const minDate = this.data.cumulativePickerStartDate || this._shiftDate(this.data._todayDate, -365)
    const maxDate = this.data._todayDate
    if (minDate && date < minDate) date = minDate
    if (maxDate && date > maxDate) date = maxDate
    if (date === this.data.cumulativeStartDate) return
    this._cumulativeCustomized = true
    this.setData({ cumulativeStartDate: date, cumulativeLoading: true }, () => {
      this._refreshCumulativeSummary(date, false)
    })
  },

  _commitDistributionSubjects(rawSubjects, animate) {
    this._getDistributionCommitController().commit(rawSubjects, animate)
  },

  _getDistributionCommitController() {
    if (!this._distributionCommitController) {
      this._distributionCommitController = createDistributionCommitController({
        isAlive: () => this._alive,
        isVisible: () => this._isVisible,
        getChartMode: () => this.data.chartMode,
        setRawSubjects: subjects => { this._distributionRawSubjects = subjects },
        resetPieCache: () => this._resetPieCache(),
        buildSubjectItems: subjects => this._buildSubjectItems(subjects),
        hasDistributionData: subjects => this._hasDistributionData(subjects),
        setData: (patch, callback) => this.setData(patch, callback),
        initCanvases: callback => this._initCanvases(callback),
        animatePieOnly: () => this._animatePieOnly(),
        renderPie: (progress, includeLabels) => this._renderPieChart(progress, includeLabels),
      })
    }
    return this._distributionCommitController
  },

  async _loadDistributionForPeriod(period, animate = true) {
    await this._getDistributionLoadController().load(period, animate)
  },

  _getDistributionLoadController() {
    if (!this._distributionLoadController) {
      this._distributionLoadController = createDistributionLoadController({
        isAlive: () => this._alive,
        getSelectedDate: () => this.data.selectedDate,
        getDaySubjectsRaw: () => this._daySubjectsRaw || [],
        getDistributionPeriod: () => this.data.distributionPeriod,
        getDistributionRangeStart: () => this.data.distributionRangeStart,
        getDistributionRangeEnd: () => this.data.distributionRangeEnd,
        getRequestSeq: () => this._distributionRequestSeq,
        setRequestSeq: value => { this._distributionRequestSeq = value },
        resolveDistributionRange: (period, anchor) => this._resolveDistributionRange(period, anchor),
        ensureSubjectMeta: () => this._ensureSubjectMeta(),
        getRangeSummary: (start, end) => api.get('/pomodoro/range-summary', { start_date: start, end_date: end }),
        commitDistributionSubjects: (subjects, animate) => this._commitDistributionSubjects(subjects, animate),
        setData: patch => this.setData(patch),
        showToast: title => { if (wx.showToast) wx.showToast({ title, icon: 'none' }) },
        logError: (message, e) => console.error(message, e),
      })
    }
    return this._distributionLoadController
  },

  onDistributionPeriodTap(e) {
    const period = e && e.currentTarget && e.currentTarget.dataset
      ? e.currentTarget.dataset.period
      : ''
    if (!period || period === this.data.distributionPeriod) return
    this._loadDistributionForPeriod(period, true)
  },

  onCustomRangeStartChange(e) {
    let date = e && e.detail ? String(e.detail.value || '') : ''
    if (!date) return
    const anchor = this.data.selectedDate || this.data._todayDate
    const minDate = this.data.customRangePickerStartDate || (anchor ? this._shiftDate(anchor, -365) : '')
    if (minDate && date < minDate) date = minDate
    if (anchor && date > anchor) date = anchor
    this.setData({ customRangeStartDate: date, distributionPeriod: 'custom' }, () => {
      this._loadDistributionForPeriod('custom', true)
    })
  },

  toggleChartMode() {
    this._getChartModeController().toggle()
  },

  _animateTrendOnly() {
    this._getTrendAnimationController().animate()
  },

  _getTrendAnimationController() {
    if (!this._trendAnimationController) {
      this._trendAnimationController = createTrendAnimationController({
        isAlive: () => this._alive,
        isVisible: () => this._isVisible,
        getChartMode: () => this.data.chartMode,
        getTrendCtx: () => this._trendCtx,
        getTrendBarsRect: () => this._trendBarsRect,
        getTrendCanvasNode: () => this._trendCanvasNode,
        getBarAnimationToken: () => this._barAnimationToken,
        incrementBarAnimationToken: () => { this._barAnimationToken = (this._barAnimationToken || 0) + 1; return this._barAnimationToken },
        setBarRafId: id => { this._barRafId = id },
        markBarRenderedOnce: () => { this._barRenderedOnce = true },
        now: () => Date.now(),
        setTimeout,
        setData: patch => this.setData(patch),
        renderTrendBars: progress => this._renderTrendBars(progress),
      })
    }
    return this._trendAnimationController
  },

  _getChartModeController() {
    if (!this._chartModeController) {
      this._chartModeController = createChartModeController({
        isAlive: () => this._alive,
        isVisible: () => this._isVisible,
        getChartMode: () => this.data.chartMode,
        isBarMounted: () => !!this.data.barCanvasMounted,
        isBarRenderedOnce: () => !!this._barRenderedOnce,
        incrementBarAnimationToken: () => {
          this._barAnimationToken = (this._barAnimationToken || 0) + 1
        },
        setData: (patch, callback) => this.setData(patch, callback),
        hasNextTick: () => !!wx.nextTick,
        nextTick: callback => wx.nextTick(callback),
        setTimeout,
        initCanvases: callback => this._initCanvases(callback),
        renderPie: (progress, includeLabels) => this._renderPieChart(progress, includeLabels),
        initTrendCanvas: callback => this._initTrendCanvas(callback),
        animateTrendOnly: () => this._animateTrendOnly(),
        renderTrendBars: progress => this._renderTrendBars(progress),
        isFirstMount: () => !this.data.barCanvasMounted,
      })
    }
    return this._chartModeController
  },

  _resetPieCache() {
    this._pieRenderCache = { sectors: null, wallSteps: null, labelLayout: null }
    if (this._shadeColorCache) this._shadeColorCache.reset()
  },

  _cancelDeferredHistory(clearPending) {
    this._getDeferredHistoryController().cancel(clearPending)
  },

  _queueDeferredHistory(reqId, dateSeq, selectedDate, sessions, total) {
    this._getDeferredHistoryController().queue(reqId, dateSeq, selectedDate, sessions, total)
  },

  _getDeferredHistoryController() {
    if (!this._deferredHistoryController) {
      this._deferredHistoryController = createDeferredHistoryController({
        getTimer: () => this._deferredHistoryTimer,
        setTimer: timer => { this._deferredHistoryTimer = timer },
        getPending: () => this._pendingHistoryCommit,
        setPending: value => { this._pendingHistoryCommit = value },
        clearTimeout,
        setTimeout,
        isAlive: () => this._alive,
        isVisible: () => this._isVisible,
        getRequestId: () => this._requestId,
        getDateRequestSeq: () => this._dateRequestSeq,
        getSelectedDate: () => this.data.selectedDate,
        formatSession: item => this._formatSession(item),
        setData: patch => this.setData(patch),
      })
    }
    return this._deferredHistoryController
  },

  _cancelDurationAnimation(resetState) {
    this._getDurationAnimationController().cancel(resetState)
  },

  _animateSelectedDuration(fromSec, toSec, fromSessions, toSessions) {
    this._getDurationAnimationController().animate(fromSec, toSec, fromSessions, toSessions)
  },

  _getDurationAnimationController() {
    if (!this._durationAnimationController) {
      this._durationAnimationController = createDurationAnimationController({
        isAlive: () => this._alive,
        isVisible: () => this._isVisible,
        getToken: () => this._durationAnimationToken,
        incrementToken: () => { this._durationAnimationToken = (this._durationAnimationToken || 0) + 1 },
        getTimer: () => this._durationAnimationTimer,
        setTimer: timer => { this._durationAnimationTimer = timer },
        clearTimeout,
        setTimeout,
        getDisplaySessions: () => this.data._dispTodaySessions,
        setDisplayDurationSec: value => { this._displayTodayDurationSec = value },
        getDurationDisplayPatch: text => this._getTodayDurationDisplayPatch(text),
        setData: patch => this.setData(patch),
      })
    }
    return this._durationAnimationController
  },

  /* ==================== Data Loading ==================== */

  async loadData(options) {
    return this._getLoadRequestController().load(!!(options && options.background))
  },

  _formatSession(s) {
    return sessionViewModel.formatSession(s, {
      getTaskTypeLabel: session => storage.pomodoroTaskTypes.labelForSession(session),
      getSubjectColor: key => getSubjectColor(key, this.data.themeMode),
    })
  },

  _getLoadCommitController() {
    if (!this._loadCommitController) {
      this._loadCommitController = createLoadCommitController({
        isAlive: () => this._alive,
        isVisible: () => this._isVisible,
        getRequestId: () => this._requestId,
        setDisplayTodayDurationSec: value => { this._displayTodayDurationSec = value },
        setDaySubjectsRaw: subjects => { this._daySubjectsRaw = subjects },
        setRawTodayDuration: value => { this._rawTodayDur = value },
        setRawWeekDuration: value => { this._rawWeekDur = value },
        setData: (patch, callback) => this.setData(patch, callback),
        queueDeferredHistory: (reqId, dateSeq, selectedDate, sessions, total) => {
          this._queueDeferredHistory(reqId, dateSeq, selectedDate, sessions, total)
        },
        isCumulativeCustomized: () => this._cumulativeCustomized,
        getCumulativeStartDate: () => this.data.cumulativeStartDate,
        refreshCumulativeSummary: (startDate, silent) => this._refreshCumulativeSummary(startDate, silent),
        getDistributionPeriod: () => this.data.distributionPeriod,
        loadDistributionForPeriod: (period, animate) => this._loadDistributionForPeriod(period, animate),
        getChartMode: () => this.data.chartMode,
        initCanvases: callback => this._initCanvases(callback),
        renderPie: (progress, includeLabels) => this._renderPieChart(progress, includeLabels),
        getPieCanvasNode: () => this._pieCanvasNode,
        setTimeout,
        startAnimations: reqId => this._startAnimations(reqId),
        isBarMounted: () => !!this.data.barCanvasMounted,
        initTrendCanvas: callback => this._initTrendCanvas(callback),
        renderTrendBars: progress => this._renderTrendBars(progress),
      })
    }
    return this._loadCommitController
  },

  _getLoadFailureController() {
    if (!this._loadFailureController) {
      this._loadFailureController = createLoadFailureController({
        isAlive: () => this._alive,
        getRequestId: () => this._requestId,
        getDateRequestSeq: () => this._dateRequestSeq,
        getSelectedDate: () => this.data.selectedDate,
        isContentReady: () => !!this.data.contentReady,
        logError: (message, e) => console.error(message, e),
        setData: patch => this.setData(patch),
      })
    }
    return this._loadFailureController
  },

  _createLoadRequestController() {
    return createLoadRequestControllerFactory({
      createLoadRequestController,
      isAlive: () => this._alive,
      ensureSettings: () => this._ensureSettings(),
      ensureSubjectMeta: () => this._ensureSubjectMeta(),
      getRequestId: () => this._requestId,
      getSelectedDate: () => this.data.selectedDate,
      getTodayDate: () => this.data._todayDate,
      incrementDateRequestSeq: () => { this._dateRequestSeq = (this._dateRequestSeq || 0) + 1 },
      getDateRequestSeq: () => this._dateRequestSeq,
      hasData: () => this._hasData,
      setHasData: value => { this._hasData = value },
      cancelDeferredHistory: clearPending => this._cancelDeferredHistory(clearPending),
      setData: patch => this.setData(patch),
      incrementStatsLoadInFlight: () => { this._statsLoadInFlight = (this._statsLoadInFlight || 0) + 1 },
      decrementStatsLoadInFlight: () => {
        this._statsLoadInFlight = Math.max(0, (this._statsLoadInFlight || 1) - 1)
      },
      getInitialResponses: (requestedDate, viewingToday) => Promise.all([
        // 首屏只请求组合接口 + 当前日 history；柱状图 canvas 不在这里挂载。
        api.get('/pomodoro/statistics-overview', viewingToday ? {} : { date: requestedDate }),
        api.get('/pomodoro/history', { page: 1, page_size: 20, date: requestedDate }),
      ]),
      getHistory: date => api.get('/pomodoro/history', { page: 1, page_size: 20, date }),
      normalizeOverview: response => overviewMapping.normalizeOverview(response),
      reconcileFromServer: (stats, summary) => this._reconcileFromServer(stats, summary),
      logError: (message, e) => console.error(message, e),
      getDistributionPeriod: () => this.data.distributionPeriod,
      resetPieCache: () => this._resetPieCache(),
      cancelDurationAnimation: resetState => this._cancelDurationAnimation(resetState),
      buildLoadViewState: overrides => buildLoadViewState({
        ...overrides,
        currentLifetimeStartDate: this.data.lifetimeStartDate,
        currentSubjects: this.data.subjects,
        currentDistributionHasData: this.data.distributionHasData,
        currentRangeStart: this.data.distributionRangeStart,
        currentRangeEnd: this.data.distributionRangeEnd,
        hasCrossDayBleedInSubjects: overviewMapping.hasCrossDayBleedInSubjects,
        formatSession: item => this._formatSession(item),
        formatMin: sec => this._fmtMin(sec),
        formatSelectedDurationLabel: date => this._formatSelectedDurationLabel(date),
        hasDistributionData: items => this._hasDistributionData(items),
        buildSubjectItems: subjects => this._buildSubjectItems(subjects),
        formatPieDateLabel: date => this._formatPieDateLabel(date),
        getDurationDisplayPatch: text => this._getTodayDurationDisplayPatch(text),
        buildCumulativePatch: (lifetimeSummary, lifetimeStart) => this._cumulativeCustomized
          ? { lifetimeStartDate: lifetimeStart }
          : {
              lifetimeStartDate: lifetimeStart,
              ...this._cumulativeSummaryPatch({
                ...lifetimeSummary,
                start_date: lifetimeStart,
              }, lifetimeStart),
            },
      }),
      commitLoad: (viewState, context) => this._getLoadCommitController().commit(viewState, context),
      handleLoadFailure: (error, context) => this._getLoadFailureController().handle(error, context),
    }).create()
  },

  _getLoadRequestController() {
    if (!this._loadRequestController) {
      this._loadRequestController = this._createLoadRequestController()
    }
    return this._loadRequestController
  },

  _selectDate(date) {
    this._getSelectDateController().select(date)
  },

  _getSelectDateController() {
    if (!this._selectDateController) {
      this._selectDateController = createSelectDateController({
        getTodayDate: () => this.data._todayDate,
        getSelectedDate: () => this.data.selectedDate,
        getCustomRangeStartDate: () => this.data.customRangeStartDate,
        cancelDeferredHistory: () => this._cancelDeferredHistory(true),
        formatPieDateLabel: date => this._formatPieDateLabel(date),
        formatSelectedDurationLabel: date => this._formatSelectedDurationLabel(date),
        shiftDate: (date, delta) => this._shiftDate(date, delta),
        setData: (patch, callback) => this.setData(patch, callback),
        loadDateData: date => this.loadDateData(date),
      })
    }
    return this._selectDateController
  },

  onDateChange(e) {
    const date = e && e.detail ? e.detail.value : ''
    this._selectDate(date)
  },

  goPrevDay() {
    const current = this.data.selectedDate || this.data._todayDate
    if (!current) return
    this._selectDate(this._shiftDate(current, -1))
  },

  goNextDay() {
    if (!this.data.canGoNextDate) return
    const current = this.data.selectedDate || this.data._todayDate
    const today = this.data._todayDate
    if (!current || !today) return
    const next = this._shiftDate(current, 1)
    this._selectDate(next > today ? today : next)
  },

  /* ==================== 统计日设置 ==================== */

  onDayStartChange(e) {
    const timeText = e && e.detail && e.detail.value
    if (typeof timeText !== 'string') return
    const minute = chinaTime.timeTextToMinute(timeText)
    if (minute === this.data.dayStartMinute) return
    this._saveDayStart(minute)
  },

  async _saveDayStart(minute) {
    await this._getSaveDayStartController().save(minute)
  },

  _getSaveDayStartController() {
    if (!this._saveDayStartController) {
      this._saveDayStartController = createSaveDayStartController({
        isAlive: () => this._alive,
        isViewReady: () => this._viewReady,
        getSelectedDate: () => this.data.selectedDate,
        getCustomRangeStartDate: () => this.data.customRangeStartDate,
        markSettingsLoaded: () => { this._settingsLoaded = true },
        showLoading: () => { if (wx.showLoading) wx.showLoading({ title: '保存中', mask: true }) },
        hideLoading: () => { if (wx.hideLoading) wx.hideLoading() },
        showToast: title => { if (wx.showToast) wx.showToast({ title, icon: 'none' }) },
        logError: (message, e) => console.error(message, e),
        saveSettings: minute => api.put('/pomodoro/settings', { day_start_minute: minute }),
        getChinaStudyDate: minute => chinaTime.getChinaStudyDate(minute),
        minuteToTimeText: minute => chinaTime.minuteToTimeText(minute),
        getStudyDayRangeText: minute => this._studyDayRangeText(minute),
        formatPieDateLabel: date => this._formatPieDateLabel(date),
        formatSelectedDurationLabel: date => this._formatSelectedDurationLabel(date),
        setData: (patch, callback) => this.setData(patch, callback),
        loadData: () => this.loadData(),
      })
    }
    return this._saveDayStartController
  },

  goToToday() {
    const today = this.data._todayDate
    if (!today || today === this.data.selectedDate) return
    this._selectDate(today)
  },

  async loadDateData(date) {
    return this._getDateRequestController().load(date)
  },

  _animatePieOnly() {
    this._getPieAnimationController().animate()
  },

  _getDateCommitController() {
    if (!this._dateCommitController) {
      this._dateCommitController = createDateCommitController({
        isAlive: () => this._alive,
        isVisible: () => this._isVisible,
        getDateRequestSeq: () => this._dateRequestSeq,
        setRawTodayDuration: value => { this._rawTodayDur = value },
        setDaySubjectsRaw: subjects => { this._daySubjectsRaw = subjects },
        resetPieCache: () => this._resetPieCache(),
        setData: (patch, callback) => this.setData(patch, callback),
        animateSelectedDuration: (fromSec, toSec, fromSessions, toSessions) => {
          this._animateSelectedDuration(fromSec, toSec, fromSessions, toSessions)
        },
        getDistributionPeriod: () => this.data.distributionPeriod,
        loadDistributionForPeriod: (period, animate) => this._loadDistributionForPeriod(period, animate),
        getChartMode: () => this.data.chartMode,
        isPieReady: () => !!(this._pieCtx && this._pieRect),
        initCanvases: callback => this._initCanvases(callback),
        animatePieOnly: () => this._animatePieOnly(),
      })
    }
    return this._dateCommitController
  },

  _getDateFailureController() {
    if (!this._dateFailureController) {
      this._dateFailureController = createDateFailureController({
        isAlive: () => this._alive,
        isVisible: () => this._isVisible,
        getDateRequestSeq: () => this._dateRequestSeq,
        logError: (message, e) => console.error(message, e),
        setData: patch => this.setData(patch),
        showToast: title => { if (wx.showToast) wx.showToast({ title, icon: 'none' }) },
      })
    }
    return this._dateFailureController
  },

  _getDateRequestController() {
    if (!this._dateRequestController) {
      this._dateRequestController = createDateRequestController({
        isAlive: () => this._alive,
        isVisible: () => this._isVisible,
        getDateRequestSeq: () => this._dateRequestSeq,
        incrementDateRequestSeq: () => { this._dateRequestSeq = (this._dateRequestSeq || 0) + 1 },
        getSelectedDate: () => this.data.selectedDate,
        getTodayDate: () => this.data._todayDate,
        getDistributionPeriod: () => this.data.distributionPeriod,
        setData: patch => this.setData(patch),
        getInitialResponses: (requestDate, viewingToday) => Promise.all([
          // 查看“今日”时不传 date，由后端返回权威当前学习日。
          api.get('/pomodoro/daily-summary', viewingToday ? {} : { date: requestDate }),
          api.get('/pomodoro/history', { page: 1, page_size: 20, date: requestDate }),
        ]),
        getHistory: date => api.get('/pomodoro/history', { page: 1, page_size: 20, date }),
        reconcileFromServer: (stats, summary) => this._reconcileFromServer(stats, summary),
        logError: (message, e) => console.error(message, e),
        buildDateViewState: overrides => buildDateViewState({
          ...overrides,
          currentDisplayDurationSec: this._displayTodayDurationSec,
          currentRawDurationSec: this._rawTodayDur,
          currentDisplaySessions: this.data._dispTodaySessions,
          currentSubjects: this.data.subjects,
          currentDistributionHasData: this.data.distributionHasData,
          currentRangeStart: this.data.distributionRangeStart,
          currentRangeEnd: this.data.distributionRangeEnd,
          hasCrossDayBleedInSubjects: overviewMapping.hasCrossDayBleedInSubjects,
          buildSubjectItems: subjects => this._buildSubjectItems(subjects),
          hasDistributionData: subjects => this._hasDistributionData(subjects),
          formatMin: sec => this._fmtMin(sec),
          formatSelectedDurationLabel: date => this._formatSelectedDurationLabel(date),
          formatSession: item => this._formatSession(item),
          formatPieDateLabel: date => this._formatPieDateLabel(date),
        }),
        setRawTodayDuration: value => { this._rawTodayDur = value },
        setDaySubjectsRaw: value => { this._daySubjectsRaw = value },
        resetPieCache: () => this._resetPieCache(),
        commitDate: (viewState, context) => this._getDateCommitController().commit(viewState, context),
        handleDateFailure: (error, context) => this._getDateFailureController().handle(error, context),
      })
    }
    return this._dateRequestController
  },

  _getPieAnimationController() {
    if (!this._pieAnimationController) {
      this._pieAnimationController = createPieAnimationController({
        isAlive: () => this._alive,
        isVisible: () => this._isVisible,
        getPieCtx: () => this._pieCtx,
        getPieRect: () => this._pieRect,
        getPieCanvasNode: () => this._pieCanvasNode,
        getPieAnimationToken: () => this._pieAnimationToken,
        incrementPieAnimationToken: () => { this._pieAnimationToken = (this._pieAnimationToken || 0) + 1; return this._pieAnimationToken },
        incrementPieLabelToken: () => { this._pieLabelToken = (this._pieLabelToken || 0) + 1 },
        setPieDateRafId: id => { this._pieDateRafId = id },
        now: () => Date.now(),
        setTimeout,
        renderPie: (progress, includeLabels) => this._renderPieChart(progress, includeLabels),
        revealPieLabelsIncrementally: () => this._revealPieLabelsIncrementally(),
      })
    }
    return this._pieAnimationController
  },

  _revealPieLabelsIncrementally() {
    this._getPieLabelRevealController().reveal()
  },

  _getPieLabelRevealController() {
    if (!this._pieLabelRevealController) {
      this._pieLabelRevealController = createPieLabelRevealController({
        isAlive: () => this._alive,
        isVisible: () => this._isVisible,
        getPieCtx: () => this._pieCtx,
        getPieRect: () => this._pieRect,
        getPieCanvasNode: () => this._pieCanvasNode,
        getLabelLayout: () => this._pieRenderCache.labelLayout,
        getPieLabelToken: () => this._pieLabelToken,
        incrementPieLabelToken: () => { this._pieLabelToken = (this._pieLabelToken || 0) + 1; return this._pieLabelToken },
        setPieLabelRafId: id => { this._pieLabelRafId = id },
        getGeometry: rect => this._getPieGeometry(rect),
        setTimeout,
        drawPieLabels: (ctx, geometry, layout, reveal, start, end) => this._drawPieLabels(ctx, geometry, layout, reveal, start, end),
      })
    }
    return this._pieLabelRevealController
  },

  /* ==================== Animation Control ==================== */

  _cancelPendingWork() {
    this._getCancelWorkController().cancel()
  },

  _getCancelWorkController() {
    if (!this._cancelWorkController) {
      this._cancelWorkController = createCancelWorkController({
        clearDynamicRefresh: () => this._clearDynamicRefresh(),
        cancelDurationAnimation: resetState => this._cancelDurationAnimation(resetState),
        cancelDeferredHistory: clearPending => this._cancelDeferredHistory(clearPending),
        setAnimActive: value => { this._animActive = value },
        setFinalDrawn: value => { this._finalDrawn = value },
        incrementRequestId: () => { this._requestId++ },
        getMainRafId: () => this._rafId,
        getPieDateRafId: () => this._pieDateRafId,
        getPieLabelRafId: () => this._pieLabelRafId,
        getBarRafId: () => this._barRafId,
        getPieCanvasNode: () => this._pieCanvasNode,
        getTrendCanvasNode: () => this._trendCanvasNode,
        cancelFrame: (id, node) => {
          if (id && node && node.cancelAnimationFrame) node.cancelAnimationFrame(id)
        },
        setMainRafId: id => { this._rafId = id },
        setPieDateRafId: id => { this._pieDateRafId = id },
        setPieLabelRafId: id => { this._pieLabelRafId = id },
        setBarRafId: id => { this._barRafId = id },
        incrementPieAnimationToken: () => { this._pieAnimationToken = (this._pieAnimationToken || 0) + 1 },
        incrementPieLabelToken: () => { this._pieLabelToken = (this._pieLabelToken || 0) + 1 },
        incrementBarAnimationToken: () => { this._barAnimationToken = (this._barAnimationToken || 0) + 1 },
        clearAnimTimer: () => {
          if (this._animTimer) {
            clearTimeout(this._animTimer)
            this._animTimer = null
          }
        },
      })
    }
    return this._cancelWorkController
  },

  _initCanvases(callback) {
    this._getStatsCanvasInitController().initPie(callback)
  },

  _initTrendCanvas(callback) {
    this._getStatsCanvasInitController().initTrend(callback)
  },

  _getStatsCanvasInitController() {
    if (!this._statsCanvasInitController) {
      this._statsCanvasInitController = createStatsCanvasInitController({
        isAlive: () => this._alive,
        getPage: () => this,
        createQuery: () => wx.createSelectorQuery(),
        getWindowInfo: () => (wx.getWindowInfo ? wx.getWindowInfo() : {}),
        pieSelector: () => '#pie-canvas',
        trendSelector: () => '#trend-bars-canvas',
        isPieReady: () => !!(this._pieCanvasNode && this._pieCtx && this._pieRect),
        isPiePending: () => !!this._canvasInitPending,
        setPiePending: value => { this._canvasInitPending = value },
        getPieCallbacks: () => this._canvasInitCallbacks,
        setPieCallbacks: value => { this._canvasInitCallbacks = value },
        addPieCallback: callback => this._canvasInitCallbacks.push(callback),
        commitPie: value => {
          this._pieCanvasNode = value.node
          this._pieCtx = value.ctx
          this._pieRect = value.rect
          this._pieDpr = value.dpr
        },
        isTrendMounted: () => !!this.data.barCanvasMounted,
        isTrendReady: () => !!(this._trendCanvasNode && this._trendCtx && this._trendBarsRect),
        isTrendPending: () => !!this._barInitPending,
        setTrendPending: value => { this._barInitPending = value },
        getTrendCallbacks: () => this._barInitCallbacks,
        setTrendCallbacks: value => { this._barInitCallbacks = value },
        addTrendCallback: callback => this._barInitCallbacks.push(callback),
        commitTrend: value => {
          this._trendCanvasNode = value.node
          this._trendCtx = value.ctx
          this._trendBarsRect = value.rect
        },
      })
    }
    return this._statsCanvasInitController
  },

  _shadeColorCached(hex, amount) {
    return this._shadeColorCache.shade(hex, amount)
  },

  _startAnimations(reqId) {
    this._getStartAnimationsController().start(reqId)
  },

  _getStartAnimationsController() {
    if (!this._startAnimationsController) {
      this._startAnimationsController = createStartAnimationsController({
        isAlive: () => this._alive,
        isVisible: () => this._isVisible,
        getRequestId: () => this._requestId,
        getChartMode: () => this.data.chartMode,
        getTodaySessions: () => this.data.todaySessions,
        getRawTodayDurationSec: () => this._rawTodayDur,
        getAnimActive: () => this._animActive,
        getFinalDrawn: () => this._finalDrawn,
        getPieCanvasNode: () => this._pieCanvasNode,
        setAnimActive: value => { this._animActive = value },
        setFinalDrawn: value => { this._finalDrawn = value },
        setDisplayDurationSec: value => { this._displayTodayDurationSec = value },
        setAnimTimer: timer => { this._animTimer = timer },
        setRafId: id => { this._rafId = id },
        incrementPieLabelToken: () => { this._pieLabelToken = (this._pieLabelToken || 0) + 1 },
        now: () => Date.now(),
        setTimeout,
        setData: patch => this.setData(patch),
        getDurationDisplayPatch: text => this._getTodayDurationDisplayPatch(text),
        formatMin: sec => this._fmtMin(sec),
        renderPie: (progress, includeLabels) => this._renderPieChart(progress, includeLabels),
        revealPieLabelsIncrementally: () => this._revealPieLabelsIncrementally(),
      })
    }
    return this._startAnimationsController
  },

  /* ==================== Trend Bars ==================== */

  _renderTrendBars(progress) {
    trendChart.renderTrendBars(this._trendCtx, {
      trends: this.data.trends,
      rect: this._trendBarsRect,
      progress,
      themeMode: this.data.themeMode,
      palette: this._getCanvasPalette(),
    })
  },

  /* ==================== Pie Chart ==================== */

  _shadeColor(hex, amount) {
    return viewHelpers.shadeColor(hex, amount)
  },

  _drawEllipticSector(ctx, cx, cy, radius, scaleY, startA, endA, fillStyle, strokeStyle, lineW) {
    pieGeometry.drawEllipticSector(ctx, cx, cy, radius, scaleY, startA, endA, fillStyle, strokeStyle, lineW)
  },

  _getPieGeometry(rect) {
    return pieGeometry.getPieGeometry(rect)
  },

  _roundRectPath(ctx, x, y, width, height, radius) {
    pieGeometry.roundRectPath(ctx, x, y, width, height, radius)
  },

  _buildPieLabelLayout(sectors, geometry) {
    return pieLabelLayout.buildPieLabelLayout(sectors, geometry)
  },

  _drawPieLabels(ctx, geometry, layout, reveal, startIndex = 0, endIndex = layout ? layout.length : 0) {
    pieLabelRenderer.drawPieLabels(ctx, layout, reveal, this._getCanvasPalette(), this._pieDpr, startIndex, endIndex)
  },

  _renderPieChart(progress, includeLabels = true) {
    pieRenderer.renderPieChart({
      ctx: this._pieCtx,
      rect: this._pieRect,
      subjects: this.data.subjects,
      themeMode: this.data.themeMode,
      dpr: this._pieDpr,
      selectedSubject: this.data._selectedSubject,
      progress,
      includeLabels,
      cache: this._pieRenderCache,
      palette: this._getCanvasPalette(),
      shade: (hex, amount) => this._shadeColorCached(hex, amount),
    })
  },

  /* ==================== Touch Interactions ==================== */

  onPieTap(e) {
    this._getPieTapController().handleTap(e)
  },

  _getPieTapController() {
    if (!this._pieTapController) {
      this._pieTapController = createPieTapController({
        isAlive: () => this._alive,
        hasDistributionData: () => this.data.distributionHasData,
        getSubjects: () => this.data.subjects,
        getSelectedSubjectDetail: () => this.data.selectedSubjectDetail,
        getGeometry: rect => this._getPieGeometry(rect),
        createSelectorQuery: () => wx.createSelectorQuery().in(this),
        setData: (patch, callback) => this.setData(patch, callback),
        renderPie: progress => this._renderPieChart(progress),
        setTimeout,
      })
    }
    return this._pieTapController
  },

  closeDetail() {
    this.setData({
      selectedSubjectDetail: null,
      _selectedSubject: null,
    }, () => { if (this._alive) this._renderPieChart(1) })
  },

  noop() {},

  _getTodayDurationDisplayPatch(text) {
    return {
      _dispTodayDurationText: text,
      _dispTodayDurationSegments: this._buildDurationSegments(text),
    }
  },

  _buildDurationSegments(text) {
    return durationFormatter.buildDurationSegments(text)
  },

  _fmtHourMinute(sec) {
    return durationFormatter.formatHourMinute(sec)
  },

  _fmtMin(sec) {
    return durationFormatter.formatMin(sec)
  },
}

if (typeof Page === 'function') Page(pageConfig)
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { formatDuration: durationFormatter.formatDuration }
}
