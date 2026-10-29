const lifecyclePage = require('./stats-lifecycle-page-adapter')
const distributionPage = require('./stats-distribution-page-adapter')
const datePage = require('./stats-date-page-adapter')
const animationPage = require('./stats-animation-page-adapter')
const canvasPage = require('./stats-canvas-page-adapter')
const loadViewFlow = require('./stats-load-view-flow')
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
const { createCumulativeStartController } = require('./cumulative-start-controller')
const { createDistributionLoadController } = require('./distribution-load-controller')
const { createDistributionEntryController } = require('./distribution-entry-controller')
const { createCloseDetailController } = require('./close-detail-controller')
const { createDayStartEntryController } = require('./day-start-entry-controller')
const { createSubjectMetaController } = require('./subject-meta-controller')
const { createTrendAnimationController } = require('./trend-animation-controller')
const { createPieAnimationController } = require('./pie-animation-controller')
const { createPieLabelRevealController } = require('./pie-label-reveal-controller')
const { createCancelWorkController } = require('./cancel-work-controller')
const overviewMapping = require('./overview-mapping')
const { buildLoadViewState } = require('./load-view-state')
const { createStatsCanvasInitController } = require('./canvas-init-controller')
const { createThemeSyncController } = require('./theme-sync-controller')
const { createDeferredHistoryController } = require('./deferred-history-controller')
const { createLoadCommitController } = require('./load-commit-controller')
const { createDateCommitController } = require('./date-commit-controller')
const { createLoadFailureController } = require('./load-failure-controller')
const { createDateFailureController } = require('./date-failure-controller')
const { createDateRequestController } = require('./date-request-controller')
const { createDateNavigationController } = require('./date-navigation-controller')
const { createChartModeController } = require('./chart-mode-controller')
const { createDynamicRefreshController } = require('./dynamic-refresh-controller')
const { createLoadRequestController } = require('./load-request-controller')
const { createLoadRequestControllerFactory } = require('./load-request-controller-factory')
const { buildLoadRequestControllerCapabilities } = require('./load-request-controller-capabilities')
const {
  buildLoadRequestPageCapabilities,
} = require('./load-request-page-adapter')
const {
  buildLoadCommitPageCapabilities,
} = require('./load-commit-page-adapter')
const {
  buildLoadFailurePageCapabilities,
} = require('./load-failure-page-adapter')
const {
  buildDateCommitPageCapabilities,
} = require('./date-commit-page-adapter')
const {
  buildDateFailurePageCapabilities,
} = require('./date-failure-page-adapter')
const {
  buildDateRequestPageCapabilities,
} = require('./date-request-page-adapter')
const {
  buildStatsCanvasInitPageCapabilities,
} = require('./stats-canvas-init-page-adapter')
const { buildPieRenderCapabilities } = require('./pie-render-capabilities')
const { createPageInitController } = require('./page-init-controller')
const { createLifecycleController } = require('./lifecycle-controller')

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
return lifecyclePage.onLoad(this)
},

  _getPageInitController() {
return lifecyclePage._getPageInitController(this, { chinaTime, createPageInitController, createShadeColorCache, pomodoroTheme })
},

  async _init() {
return lifecyclePage._init(this, { getConsole: () => console })
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
return lifecyclePage._getSettingsController(this, { api, chinaTime, createSettingsController, getConsole: () => console })
},

  /**
   * 以后端返回的统计日（/pomodoro/stats.today_date 或今日 daily-summary.date）为唯一权威，
   * 校正客户端基于设备时钟/本地缓存计算的"今日"与 day_start，覆盖 settings 请求失败、
   * 设备时钟偏差导致的"今日"不一致。
   */
  _reconcileFromServer(stats, summary) {
return loadViewFlow._reconcileFromServer(this, stats, summary, { chinaTime, reconcileFromServer })
},

  _studyDayRangeText(dsm) {
    return formatStudyDayRangeText(dsm, minute => chinaTime.minuteToTimeText(minute))
  },

  onShow() {
    this._getLifecycleController().show()
  },

  onReady() {
    this._getLifecycleController().ready()
  },

  onHide() {
    this._getLifecycleController().hide()
  },

  onUnload() {
    this._getLifecycleController().unload()
  },

  _getLifecycleController() {
return lifecyclePage._getLifecycleController(this, { createLifecycleController, getPlatform: () => wx, getSetTimeout: () => setTimeout })
},


  _clearDynamicRefresh() {
    this._getDynamicRefreshController().cancel()
  },

  _scheduleDynamicRefresh(delayMs) {
    this._getDynamicRefreshController().schedule(delayMs)
  },

  _getDynamicRefreshController() {
return lifecyclePage._getDynamicRefreshController(this, { STATS_DYNAMIC_REFRESH_MS, createDynamicRefreshController, getClearTimeout: () => clearTimeout, getSetTimeout: () => setTimeout })
},

  _syncThemeFromStorage() {
    return this._getThemeSyncController().sync()
  },

  _getThemeSyncController() {
return lifecyclePage._getThemeSyncController(this, { createThemeSyncController, getPieSubjectColor, getPlatform: () => wx, getSetTimeout: () => setTimeout, getSubjectColor, pomodoroTheme })
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
    return this._getSubjectMetaController().ensure()
  },

  _getSubjectMetaController() {
return distributionPage._getSubjectMetaController(this, { api, createSubjectMetaController, getConsole: () => console })
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
return loadViewFlow._cumulativeSummaryPatch(this, summary, requestedStart, { buildCumulativeSummaryPatch })
},

  async _refreshCumulativeSummary(startDate, silent) {
    await this._getCumulativeRefreshController().refresh(startDate, silent)
  },

  _getCumulativeRefreshController() {
return distributionPage._getCumulativeRefreshController(this, { api, createCumulativeRefreshController, getConsole: () => console, getPlatform: () => wx })
},

  onCumulativeStartChange(e) {
    this._getCumulativeStartController().change(e)
  },

  _getCumulativeStartController() {
return distributionPage._getCumulativeStartController(this, { createCumulativeStartController })
},

  _commitDistributionSubjects(rawSubjects, animate) {
    this._getDistributionCommitController().commit(rawSubjects, animate)
  },

  _getDistributionCommitController() {
return distributionPage._getDistributionCommitController(this, { createDistributionCommitController })
},

  async _loadDistributionForPeriod(period, animate = true) {
    await this._getDistributionLoadController().load(period, animate)
  },

  _getDistributionLoadController() {
return distributionPage._getDistributionLoadController(this, { api, createDistributionLoadController, getConsole: () => console, getPlatform: () => wx })
},

  onDistributionPeriodTap(e) {
    this._getDistributionEntryController().tapPeriod(e)
  },

  onCustomRangeStartChange(e) {
    this._getDistributionEntryController().changeCustomStart(e)
  },

  _getDistributionEntryController() {
return distributionPage._getDistributionEntryController(this, { createDistributionEntryController })
},

  toggleChartMode() {
    this._getChartModeController().toggle()
  },

  _animateTrendOnly() {
    this._getTrendAnimationController().animate()
  },

  _getTrendAnimationController() {
return animationPage._getTrendAnimationController(this, { createTrendAnimationController, getDate: () => Date, getSetTimeout: () => setTimeout })
},

  _getChartModeController() {
return animationPage._getChartModeController(this, { createChartModeController, getPlatform: () => wx, getSetTimeout: () => setTimeout })
},

  _resetPieCache() {
return canvasPage._resetPieCache(this)
},

  _cancelDeferredHistory(clearPending) {
    this._getDeferredHistoryController().cancel(clearPending)
  },

  _queueDeferredHistory(reqId, dateSeq, selectedDate, sessions, total) {
    this._getDeferredHistoryController().queue(reqId, dateSeq, selectedDate, sessions, total)
  },

  _getDeferredHistoryController() {
return animationPage._getDeferredHistoryController(this, { createDeferredHistoryController, getClearTimeout: () => clearTimeout, getSetTimeout: () => setTimeout })
},

  _cancelDurationAnimation(resetState) {
    this._getDurationAnimationController().cancel(resetState)
  },

  _animateSelectedDuration(fromSec, toSec, fromSessions, toSessions) {
    this._getDurationAnimationController().animate(fromSec, toSec, fromSessions, toSessions)
  },

  _getDurationAnimationController() {
return animationPage._getDurationAnimationController(this, { createDurationAnimationController, getClearTimeout: () => clearTimeout, getSetTimeout: () => setTimeout })
},

  /* ==================== Data Loading ==================== */

  async loadData(options) {
    return this._getLoadRequestController().load(!!(options && options.background))
  },

  _formatSession(s) {
return loadViewFlow._formatSession(this, s, { getSubjectColor, sessionViewModel, storage })
},

  _getLoadCommitController() {
return loadViewFlow._getLoadCommitController(this, { buildLoadCommitPageCapabilities, createLoadCommitController })
},

  _getLoadFailureController() {
return loadViewFlow._getLoadFailureController(this, { buildLoadFailurePageCapabilities, createLoadFailureController })
},

  _createLoadRequestController() {
return loadViewFlow._createLoadRequestController(this, { createLoadRequestControllerFactory })
},

  _loadRequestControllerConfig() {
return loadViewFlow._loadRequestControllerConfig(this, { buildLoadRequestControllerCapabilities, createLoadRequestController })
},

  _loadRequestControllerCapabilities() {
return loadViewFlow._loadRequestControllerCapabilities(this, { api, buildLoadRequestPageCapabilities, overviewMapping })
},

  _buildLoadViewState(overrides) {
return loadViewFlow._buildLoadViewState(this, overrides, { buildLoadViewState, overviewMapping })
},

  _buildCumulativePatch(lifetimeSummary, lifetimeStart) {
return loadViewFlow._buildCumulativePatch(this, lifetimeSummary, lifetimeStart)
},

  _getLoadRequestController() {
return loadViewFlow._getLoadRequestController(this)
},

  _selectDate(date) {
    this._getSelectDateController().select(date)
  },

  _getSelectDateController() {
return datePage._getSelectDateController(this, { createSelectDateController })
},

  onDateChange(e) {
return datePage.onDateChange(this, e)
},

  goPrevDay() {
    this._getDateNavigationController().previous()
  },

  goNextDay() {
    this._getDateNavigationController().next()
  },

  /* ==================== 统计日设置 ==================== */

  onDayStartChange(e) {
    this._getDayStartEntryController().change(e)
  },

  _getDayStartEntryController() {
return datePage._getDayStartEntryController(this, { chinaTime, createDayStartEntryController })
},

  async _saveDayStart(minute) {
    await this._getSaveDayStartController().save(minute)
  },

  _getSaveDayStartController() {
return datePage._getSaveDayStartController(this, { api, chinaTime, createSaveDayStartController, getConsole: () => console, getPlatform: () => wx })
},

  goToToday() {
    this._getDateNavigationController().today()
  },

  _getDateNavigationController() {
return datePage._getDateNavigationController(this, { createDateNavigationController })
},

  async loadDateData(date) {
    return this._getDateRequestController().load(date)
  },

  _animatePieOnly() {
    this._getPieAnimationController().animate()
  },

  _getDateCommitController() {
return datePage._getDateCommitController(this, { buildDateCommitPageCapabilities, createDateCommitController })
},

  _getDateFailureController() {
return datePage._getDateFailureController(this, { buildDateFailurePageCapabilities, createDateFailureController, getPlatform: () => wx })
},

  _getDateRequestController() {
return datePage._getDateRequestController(this, { api, buildDateRequestPageCapabilities, createDateRequestController })
},

  _getPieAnimationController() {
return animationPage._getPieAnimationController(this, { createPieAnimationController, getDate: () => Date, getSetTimeout: () => setTimeout })
},

  _revealPieLabelsIncrementally() {
    this._getPieLabelRevealController().reveal()
  },

  _getPieLabelRevealController() {
return animationPage._getPieLabelRevealController(this, { createPieLabelRevealController, getSetTimeout: () => setTimeout })
},

  /* ==================== Animation Control ==================== */

  _cancelPendingWork() {
    this._getCancelWorkController().cancel()
  },

  _getCancelWorkController() {
return canvasPage._getCancelWorkController(this, { createCancelWorkController, getClearTimeout: () => clearTimeout })
},

  _initCanvases(callback) {
    this._getStatsCanvasInitController().initPie(callback)
  },

  _initTrendCanvas(callback) {
    this._getStatsCanvasInitController().initTrend(callback)
  },

  _getStatsCanvasInitController() {
return canvasPage._getStatsCanvasInitController(this, { buildStatsCanvasInitPageCapabilities, createStatsCanvasInitController, getPlatform: () => wx })
},

  _shadeColorCached(hex, amount) {
    return this._shadeColorCache.shade(hex, amount)
  },

  _startAnimations(reqId) {
    this._getStartAnimationsController().start(reqId)
  },

  _getStartAnimationsController() {
return animationPage._getStartAnimationsController(this, { createStartAnimationsController, getDate: () => Date, getSetTimeout: () => setTimeout })
},

  /* ==================== Trend Bars ==================== */

  _renderTrendBars(progress) {
return canvasPage._renderTrendBars(this, progress, { trendChart })
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
return canvasPage._renderPieChart(this, progress, includeLabels, { buildPieRenderCapabilities, pieRenderer })
},

  /* ==================== Touch Interactions ==================== */

  onPieTap(e) {
    this._getPieTapController().handleTap(e)
  },

  _getPieTapController() {
return canvasPage._getPieTapController(this, { createPieTapController, getPlatform: () => wx, getSetTimeout: () => setTimeout })
},

  closeDetail() {
    this._getCloseDetailController().close()
  },

  _getCloseDetailController() {
return canvasPage._getCloseDetailController(this, { createCloseDetailController })
},

  noop() {},

  _getTodayDurationDisplayPatch(text) {
return loadViewFlow._getTodayDurationDisplayPatch(this, text)
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
