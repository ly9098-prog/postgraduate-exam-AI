const api = require('../../../utils/api')
const pomodoroTheme = require('../utils/pomodoro-theme')
const chinaTime = require('../utils/china-time')
const storage = require('../../../utils/storage')

const DARK_SUBJECT_COLORS = ['#3B82F6', '#F59E0B', '#10B981', '#06B6D4', '#F97316', '#2DD4BF', '#EA580C', '#8B5CF6', '#6366F1', '#EC4899']
const LIGHT_SUBJECT_COLORS = ['#2F6B4F', '#7A9B76', '#2B8C83', '#B59A38', '#C4773B', '#D96B5F', '#6685A3', '#718C45', '#B45E46', '#876F8F']
// A clearer jewel-toned palette used only by the light-mode pie chart.
// History accents and the trend chart keep their existing colors.
const LIGHT_PIE_COLORS = ['#E76F51', '#2A9D8F', '#457B9D', '#E9C46A', '#8E6BBE', '#F28482', '#6A994E', '#43AA8B', '#B56576', '#577590']
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

function getColorBySubject(subject, colors) {
  let hash = 0
  const str = subject || ''
  for (let i = 0; i < str.length; i++) {
    hash = str.charCodeAt(i) + ((hash << 5) - hash)
  }
  return colors[Math.abs(hash) % colors.length]
}

function getSubjectColor(subject, themeMode) {
  const colors = themeMode === 'light' ? LIGHT_SUBJECT_COLORS : DARK_SUBJECT_COLORS
  return getColorBySubject(subject, colors)
}

function getPieSubjectColor(subject, themeMode) {
  const colors = themeMode === 'light' ? LIGHT_PIE_COLORS : DARK_SUBJECT_COLORS
  return getColorBySubject(subject, colors)
}

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
    this._alive = true
    this._isVisible = false
    this._requestId = 0
    this._dynamicRefreshTimer = null
    this._statsLoadInFlight = 0
    this._viewReady = false
    this._hasData = false
    this._settingsLoaded = false
    this._finalDrawn = false
    this._displayTodayDurationSec = 0
    this._durationAnimationToken = 0
    this._durationAnimationTimer = null
    this._deferredHistoryTimer = null
    this._pendingHistoryCommit = null
    this._canvasInitPending = false
    this._canvasInitCallbacks = []
    this._barInitPending = false
    this._barInitCallbacks = []
    this._barAnimationToken = 0
    this._barRenderedOnce = false
    this._cumulativeCustomized = false
    this._cumulativeRequestSeq = 0
    this._distributionRequestSeq = 0
    this._daySubjectsRaw = []
    this._distributionRawSubjects = []
    this._subjectMetaLoaded = false
    this._subjectMeta = null
    this._subjectMetaPromise = null
    const themeMode = pomodoroTheme.getTheme()
    pomodoroTheme.applyNativeTheme(themeMode)
    // 先用默认 day_start=0 计算当前中国统计日，settings 加载后若 day_start 不同会校正。
    const today = chinaTime.getChinaStudyDate(0)
    this.setData({
      selectedDate: today,
      _todayDate: today,
      pieDateLabel: '今日',
      canGoNextDate: false,
      cumulativePickerStartDate: this._shiftDate(today, -365),
      customRangePickerStartDate: this._shiftDate(today, -365),
      customRangeStartDate: today,
      distributionRangeStart: today,
      distributionRangeEnd: today,
      themeMode,
    })
    this._init()
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
    if (this._settingsLoaded) return Promise.resolve()
    if (this._settingsPromise) return this._settingsPromise
    this._settingsPromise = this._loadSettings()
    return this._settingsPromise
  },

  async _loadSettings() {
    try {
      const settings = await api.get('/pomodoro/settings')
      // A concurrent _saveDayStart may have landed a newer day_start_minute while
      // this GET was in flight; applying the stale response here would revert the
      // just-saved setting (TOCTOU).  _saveDayStart sets _settingsLoaded before it
      // resolves, so bail out without clobbering the UI.
      if (this._settingsLoaded) return
      const raw = Number(settings && settings.day_start_minute)
      const dsm = Number.isFinite(raw) ? Math.max(0, Math.min(1439, raw)) : 0
      const prevToday = this.data._todayDate
      const today = chinaTime.getChinaStudyDate(dsm)
      const patch = {
        dayStartMinute: dsm,
        dayStartTime: chinaTime.minuteToTimeText(dsm),
        studyDayRangeText: this._studyDayRangeText(dsm),
        cumulativePickerStartDate: this._shiftDate(today, -365),
      }
      if (today !== prevToday) patch._todayDate = today
      // 用户停留在旧"今天"或原选中日期超过新最大日期时，跟随新的 today
      if (!this.data.selectedDate || this.data.selectedDate === prevToday || this.data.selectedDate > today) {
        patch.selectedDate = today
        patch.pieDateLabel = '今日'
        patch.selectedDurationLabel = '今日学习'
      }
      const nextSelected = patch.selectedDate || this.data.selectedDate
      patch.canGoNextDate = !!(nextSelected && today && nextSelected < today)
      if (nextSelected) {
        const customMin = this._shiftDate(nextSelected, -365)
        patch.customRangePickerStartDate = customMin
        if (this.data.customRangeStartDate && this.data.customRangeStartDate > nextSelected) {
          patch.customRangeStartDate = nextSelected
        } else if (this.data.customRangeStartDate && this.data.customRangeStartDate < customMin) {
          patch.customRangeStartDate = customMin
        }
      }
      this._settingsLoaded = true
      this.setData(patch)
    } catch (e) {
      // settings 请求失败不阻塞、不永久锁定：下一次 loadData 会重试，
      // 同时 loadData 的后端统计校正（_reconcileFromServer）会兜底。
      console.error('加载统计日设置失败', e)
    } finally {
      this._settingsPromise = null
    }
  },

  /**
   * 以后端返回的统计日（/pomodoro/stats.today_date 或今日 daily-summary.date）为唯一权威，
   * 校正客户端基于设备时钟/本地缓存计算的"今日"与 day_start，覆盖 settings 请求失败、
   * 设备时钟偏差导致的"今日"不一致。
   */
  _reconcileFromServer(stats, summary) {
    const patch = {}
    if (stats) {
      const rawDsm = stats.day_start_minute
      if (rawDsm != null) {
        const dsm = Number.isFinite(Number(rawDsm)) ? Math.max(0, Math.min(1439, Number(rawDsm))) : this.data.dayStartMinute
        if (dsm !== this.data.dayStartMinute) {
          patch.dayStartMinute = dsm
          patch.dayStartTime = chinaTime.minuteToTimeText(dsm)
          patch.studyDayRangeText = this._studyDayRangeText(dsm)
        }
        this._settingsLoaded = true
      }
    }
    // stats.today_date 恒为权威"今日"；仅当查看"今日"时，summary.date 亦可代表今日
    const today = (stats && stats.today_date) || (summary && summary.date) || ''
    if (today) patch.cumulativePickerStartDate = this._shiftDate(today, -365)
    const prevToday = this.data._todayDate
    const prevSelected = this.data.selectedDate
    let changedToday = false
    if (today && today !== prevToday) {
      patch._todayDate = today
      changedToday = true
    }
    if (today && (!prevSelected || prevSelected === prevToday || prevSelected > today)) {
      patch.selectedDate = today
      patch.pieDateLabel = '今日'
      patch.selectedDurationLabel = '今日学习'
      changedToday = true
    }
    const finalToday = patch._todayDate || today || prevToday
    const finalSelected = patch.selectedDate || prevSelected
    if (finalToday && finalSelected) patch.canGoNextDate = finalSelected < finalToday
    if (finalSelected) {
      const customMin = this._shiftDate(finalSelected, -365)
      patch.customRangePickerStartDate = customMin
      if (this.data.customRangeStartDate && this.data.customRangeStartDate > finalSelected) {
        patch.customRangeStartDate = finalSelected
      } else if (this.data.customRangeStartDate && this.data.customRangeStartDate < customMin) {
        patch.customRangeStartDate = customMin
      }
    }
    if (Object.keys(patch).length) this.setData(patch)
    return {
      changedToday,
      today: today || this.data._todayDate,
      selectedDate: today && (!prevSelected || prevSelected === prevToday || prevSelected > today)
        ? today
        : prevSelected,
    }
  },

  _studyDayRangeText(dsm) {
    const minute = Math.max(0, Math.min(1439, Number(dsm) || 0))
    if (!minute) return '统计日从 00:00 开始'
    const t = chinaTime.minuteToTimeText(minute)
    return '统计周期 ' + t + ' - 次日 ' + t
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
    if (this._dynamicRefreshTimer) {
      clearTimeout(this._dynamicRefreshTimer)
      this._dynamicRefreshTimer = null
    }
  },

  _scheduleDynamicRefresh(delayMs) {
    this._clearDynamicRefresh()
    if (!this._alive || !this._isVisible || !this._viewReady) return
    const delay = Math.max(1000, Number(delayMs) || STATS_DYNAMIC_REFRESH_MS)
    this._dynamicRefreshTimer = setTimeout(async () => {
      this._dynamicRefreshTimer = null
      if (!this._alive || !this._isVisible || !this._viewReady) return
      // Do not race a date/settings/manual refresh. Try again shortly instead of
      // invalidating a user-triggered request with a background request id.
      if ((this._statsLoadInFlight || 0) > 0 || this.data.cumulativeLoading) {
        this._scheduleDynamicRefresh(3000)
        return
      }
      this._requestId++
      try {
        await this.loadData({ background: true })
      } finally {
        this._scheduleDynamicRefresh()
      }
    }, delay)
  },

  _syncThemeFromStorage() {
    const themeMode = pomodoroTheme.getTheme()
    pomodoroTheme.applyNativeTheme(themeMode)
    if (themeMode === this.data.themeMode) return false
    const subjects = (this.data.subjects || []).map(item => ({
      ...item,
      _color: getPieSubjectColor(item.subject_id != null ? String(item.subject_id) : (item.subject_code || item._label), themeMode),
    }))
    const history = (this.data.history || []).map(item => ({
      ...item,
      _color: getSubjectColor(item.subject_id != null ? String(item.subject_id) : (item.subject_code || item._subjectLabel), themeMode),
    }))
    this.setData({ themeMode, subjects, history }, () => {
      this._resetPieCache()
      if (!this._alive || !this._viewReady || !this._hasData) return
      const redraw = () => {
        if (!this._alive || !this._isVisible) return
        if (this.data.chartMode === 'pie') {
          this._renderPieChart(1, true)
        } else if (this.data.barCanvasMounted && this._trendCtx) {
          // 柱状图只有在用户主动挂载过后才允许参与主题重绘。
          this._renderTrendBars(1)
        }
      }
      if (wx.nextTick) wx.nextTick(redraw)
      else setTimeout(redraw, 0)
    })
    return true
  },

  _getCanvasPalette() {
    if (this.data.themeMode === 'light') {
      return {
        grid: 'rgba(21,51,35,0.065)',
        baseline: 'rgba(21,51,35,0.14)',
        emptyBar: 'rgba(21,51,35,0.10)',
        pendingBar: 'rgba(21,51,35,0.065)',
        dateText: 'rgba(21,35,26,0.44)',
        badgeFill: 'rgba(255,255,255,0.96)',
        badgeText: 'rgba(21,35,26,0.92)',
        pieLeader: 'rgba(57,76,64,0.52)',
        pieLabelText: 'rgba(37,54,43,0.90)',
        pieLabelSubtext: 'rgba(82,101,89,0.72)',
        pieInsideText: 'rgba(31,48,37,0.88)',
        emptyPieFill: 'rgba(21,51,35,0.045)',
        emptyPieStroke: 'rgba(21,51,35,0.13)',
        emptyPieText: 'rgba(21,35,26,0.42)',
        shadowStart: 'rgba(21,35,26,0.16)',
        shadowMid: 'rgba(21,35,26,0.06)',
        separator: 'rgba(21,35,26,0.14)',
        selectedMask: 'rgba(244,244,238,0.88)',
      }
    }
    return {
      grid: 'rgba(255,255,255,0.03)',
      baseline: 'rgba(255,255,255,0.08)',
      emptyBar: 'rgba(255,255,255,0.05)',
      pendingBar: 'rgba(255,255,255,0.03)',
      dateText: 'rgba(255,255,255,0.25)',
      badgeFill: 'rgba(11,17,33,0.9)',
      badgeText: 'rgba(255,255,255,0.92)',
      pieLeader: 'rgba(255,255,255,0.44)',
      pieLabelText: 'rgba(255,255,255,0.90)',
      pieLabelSubtext: 'rgba(255,255,255,0.58)',
      pieInsideText: 'rgba(255,255,255,0.88)',
      emptyPieFill: 'rgba(255,255,255,0.05)',
      emptyPieStroke: 'rgba(255,255,255,0.08)',
      emptyPieText: 'rgba(255,255,255,0.28)',
      shadowStart: 'rgba(0,0,0,0.25)',
      shadowMid: 'rgba(0,0,0,0.10)',
      separator: 'rgba(0,0,0,0.18)',
      selectedMask: 'rgba(0,0,0,0.7)',
    }
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
    const subjArr = this._normalizeDistributionSubjects(subjects)
    const totalDur = Math.max(1, subjArr.reduce((sum, item) => sum + (item.duration_sec || 0), 0))
    return subjArr.map(item => {
      const dur = item.duration_sec || 0
      const pct = dur / totalDur
      const code = item.subject_code || ''
      const subjectId = item.subject_id != null ? item.subject_id : null
      return {
        subject: subjectId != null ? subjectId : (code || 'uncategorized'),
        subject_id: subjectId,
        subject_code: code,
        duration_sec: dur,
        sessions: item.sessions || 0,
        participation_sessions: item.participation_sessions || 0,
        _label: item.subject_name || '未分类',
        _color: getPieSubjectColor(subjectId != null ? String(subjectId) : (code || '未分类'), this.data.themeMode),
        _durationText: this._fmtMin(dur),
        _durationBadgeText: this._fmtHourMinute(dur),
        _pct: pct,
        _pctText: (pct * 100).toFixed(1) + '%',
      }
    })
  },


  _cumulativeSummaryPatch(summary, requestedStart) {
    const data = summary || {}
    const startDate = requestedStart || data.start_date || this.data._todayDate || ''
    const sessions = Math.max(0, Number(data.sessions) || 0)
    const durationSec = Math.max(0, Number(data.duration_sec) || 0)
    const activeDays = Math.max(0, Number(data.active_days) || 0)
    const averageSec = activeDays > 0 ? Math.floor(durationSec / activeDays) : 0
    return {
      cumulativeStartDate: startDate,
      cumulativeSessions: sessions,
      cumulativeDurationText: this._fmtMin(durationSec),
      cumulativeAverageText: this._fmtMin(averageSec),
      cumulativeActiveDays: activeDays,
      cumulativeLoading: false,
    }
  },

  async _refreshCumulativeSummary(startDate, silent) {
    const start = String(startDate || '').trim()
    const end = this.data._todayDate
    if (!start || !end) return
    const seq = (this._cumulativeRequestSeq || 0) + 1
    this._cumulativeRequestSeq = seq
    if (!silent) this.setData({ cumulativeLoading: true })
    try {
      const summary = await api.get('/pomodoro/range-summary', { start_date: start, end_date: end })
      if (!this._alive || seq !== this._cumulativeRequestSeq || start !== this.data.cumulativeStartDate) return
      this.setData(this._cumulativeSummaryPatch(summary, start))
    } catch (e) {
      if (!this._alive || seq !== this._cumulativeRequestSeq) return
      console.error('加载累计专注失败', e)
      this.setData({ cumulativeLoading: false })
      if (!silent && wx.showToast) wx.showToast({ title: '累计统计加载失败', icon: 'none' })
    }
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
    this._distributionRawSubjects = Array.isArray(rawSubjects) ? rawSubjects.slice() : []
    this._resetPieCache()
    const subjectItems = this._buildSubjectItems(this._distributionRawSubjects)
    this.setData({
      subjects: subjectItems,
      distributionHasData: this._hasDistributionData(subjectItems),
      pieLoading: false,
      selectedSubjectDetail: null,
      _selectedSubject: null,
    }, () => {
      if (!this._alive || !this._isVisible || this.data.chartMode !== 'pie') return
      this._initCanvases(() => {
        if (!this._alive || !this._isVisible || this.data.chartMode !== 'pie') return
        if (animate) this._animatePieOnly()
        else this._renderPieChart(1, true)
      })
    })
  },

  async _loadDistributionForPeriod(period, animate = true) {
    const normalized = ['day', 'week', 'month', 'custom'].includes(period) ? period : 'day'
    const range = this._resolveDistributionRange(normalized, this.data.selectedDate)
    if (!range.start || !range.end) return

    if (normalized === 'day') {
      this.setData({
        distributionPeriod: 'day',
        distributionRangeStart: range.start,
        distributionRangeEnd: range.end,
      })
      this._commitDistributionSubjects(this._daySubjectsRaw || [], animate)
      return
    }

    const seq = (this._distributionRequestSeq || 0) + 1
    this._distributionRequestSeq = seq
    this.setData({
      distributionPeriod: normalized,
      distributionRangeStart: range.start,
      distributionRangeEnd: range.end,
      pieLoading: true,
      selectedSubjectDetail: null,
      _selectedSubject: null,
    })
    try {
      await this._ensureSubjectMeta().catch(() => null)
      const summary = await api.get('/pomodoro/range-summary', {
        start_date: range.start,
        end_date: range.end,
      })
      if (
        !this._alive ||
        seq !== this._distributionRequestSeq ||
        normalized !== this.data.distributionPeriod ||
        range.start !== this.data.distributionRangeStart ||
        range.end !== this.data.distributionRangeEnd
      ) return
      this._commitDistributionSubjects((summary && summary.subjects) || [], animate)
    } catch (e) {
      if (!this._alive || seq !== this._distributionRequestSeq) return
      console.error('加载区间专注分布失败', e)
      this.setData({ pieLoading: false })
      if (wx.showToast) wx.showToast({ title: '分布统计加载失败', icon: 'none' })
    }
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
    if (this.data.chartMode === 'bar') {
      this._barAnimationToken = (this._barAnimationToken || 0) + 1
      this.setData({ chartMode: 'pie', barRendering: false }, () => {
        const drawPie = () => {
          if (!this._alive || !this._isVisible || this.data.chartMode !== 'pie') return
          this._initCanvases(() => this._renderPieChart(1, true))
        }
        if (wx.nextTick) wx.nextTick(drawPie)
        else setTimeout(drawPie, 0)
      })
      return
    }

    // Lazy mount: WXML does not create #trend-bars-canvas before this explicit
    // user action, so entering the page never pays bar-canvas init/draw cost.
    const firstMount = !this.data.barCanvasMounted
    this.setData({
      chartMode: 'bar',
      barCanvasMounted: true,
      barRendering: firstMount || !this._barRenderedOnce,
      selectedSubjectDetail: null,
      _selectedSubject: null,
    }, () => {
      const drawBar = () => {
        if (!this._alive || !this._isVisible || this.data.chartMode !== 'bar') return
        this._initTrendCanvas(() => {
          if (!this._alive || !this._isVisible || this.data.chartMode !== 'bar') return
          if (firstMount || !this._barRenderedOnce) this._animateTrendOnly()
          else this._renderTrendBars(1)
        })
      }
      if (wx.nextTick) wx.nextTick(drawBar)
      else setTimeout(drawBar, 0)
    })
  },

  _animateTrendOnly() {
    if (!this._trendCtx || !this._trendBarsRect) {
      this.setData({ barRendering: false })
      return
    }
    const token = (this._barAnimationToken || 0) + 1
    this._barAnimationToken = token
    const duration = 620
    const startedAt = Date.now()
    const node = this._trendCanvasNode
    const raf = node && node.requestAnimationFrame
      ? cb => node.requestAnimationFrame(cb)
      : cb => setTimeout(cb, 16)
    let lastDrawAt = -Infinity
    this._renderTrendBars(0)

    const tick = () => {
      if (!this._alive || !this._isVisible || token !== this._barAnimationToken || this.data.chartMode !== 'bar') return
      const elapsed = Date.now() - startedAt
      const raw = Math.min(1, elapsed / duration)
      if (raw < 1 && elapsed - lastDrawAt >= 40) {
        lastDrawAt = elapsed
        this._renderTrendBars(this._easeOutCubic(raw))
      }
      if (raw < 1) {
        this._barRafId = raf(tick)
      } else {
        this._renderTrendBars(1)
        this._barRafId = null
        this._barRenderedOnce = true
        this.setData({ barRendering: false })
      }
    }
    this._barRafId = raf(tick)
  },


  _resetPieCache() {
    this._pieSectors = null
    this._pieWallSteps = null
    this._pieLabelLayout = null
    this._shadeCache = null
  },

  _cancelDeferredHistory(clearPending) {
    if (this._deferredHistoryTimer) {
      clearTimeout(this._deferredHistoryTimer)
      this._deferredHistoryTimer = null
    }
    if (clearPending) this._pendingHistoryCommit = null
  },

  _queueDeferredHistory(reqId, dateSeq, selectedDate, sessions, total) {
    this._cancelDeferredHistory(true)
    this._pendingHistoryCommit = {
      reqId,
      dateSeq,
      selectedDate,
      sessions: Array.isArray(sessions) ? sessions : [],
      total: Number(total) || 0,
    }
    // The history list is below the fold. Mount it after the chart/count-up
    // animations have finished so its view creation never competes with them.
    this._deferredHistoryTimer = setTimeout(() => {
      this._deferredHistoryTimer = null
      const pending = this._pendingHistoryCommit
      this._pendingHistoryCommit = null
      if (
        !pending ||
        !this._alive ||
        !this._isVisible ||
        pending.reqId !== this._requestId ||
        pending.dateSeq !== this._dateRequestSeq ||
        pending.selectedDate !== this.data.selectedDate
      ) return
      this.setData({
        history: pending.sessions.map(item => this._formatSession(item)),
        historyTotal: pending.total,
        historyReady: true,
      })
    }, 1300)
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
    const background = !!(options && options.background)
    await this._ensureSettings()
    const subjectMetaPromise = this._ensureSubjectMeta().catch(() => null)
    if (!this._alive) return
    const reqId = this._requestId
    const requestedDate = this.data.selectedDate
    this._dateRequestSeq = (this._dateRequestSeq || 0) + 1
    const dateSeq = this._dateRequestSeq
    if (this._hasData) this._cancelDeferredHistory(true)
    if (!background) this.setData({ loading: true, errorText: '' })
    this._statsLoadInFlight = (this._statsLoadInFlight || 0) + 1
    const viewingToday = !requestedDate || requestedDate === this.data._todayDate
    try {
      const initialResponses = await Promise.all([
        // 首屏只请求组合接口 + 当前日 history；柱状图 canvas 不在这里挂载。
        api.get('/pomodoro/statistics-overview', viewingToday ? {} : { date: requestedDate }),
        api.get('/pomodoro/history', { page: 1, page_size: 20, date: requestedDate }),
      ])
      await subjectMetaPromise
      const overview = initialResponses[0]
      const historyRes = initialResponses[1]
      const stats = (overview && overview.stats) || {}
      const trends = (overview && overview.trends) || []
      const summary = (overview && overview.daily_summary) || {}
      const lifetime = (overview && overview.lifetime_summary) || {}
      if (
        !this._alive ||
        reqId !== this._requestId ||
        dateSeq !== this._dateRequestSeq ||
        requestedDate !== this.data.selectedDate
      ) return

      // 以后端为准校正“今日”（settings 失败 / 设备时钟偏差兜底）。
      const reconciled = this._reconcileFromServer(stats, viewingToday ? summary : null)
      if (!this._alive || reqId !== this._requestId || dateSeq !== this._dateRequestSeq) return

      const effectiveDate = this.data.selectedDate
      const authoritativeToday = reconciled.today || this.data._todayDate || effectiveDate
      let effectiveHistory = historyRes
      if (reconciled.changedToday && viewingToday && effectiveDate !== requestedDate) {
        try {
          effectiveHistory = await api.get('/pomodoro/history', { page: 1, page_size: 20, date: effectiveDate })
        } catch (err) {
          console.error('重取今日 history 失败', err)
          effectiveHistory = { items: [], total: 0 }
        }
        if (!this._alive || reqId !== this._requestId || dateSeq !== this._dateRequestSeq) return
      }

      const daySessions = (effectiveHistory && effectiveHistory.items) || []
      const subjectBreakdown = (summary && summary.subjects) || []
      const selectedDurationSec = Number(summary && summary.duration_sec) || 0
      const selectedSessionCount = Number(summary && summary.sessions) || 0
      const hasBleedInSubjects = subjectBreakdown.some(
        item => Number(item.duration_sec) > 0 && Number(item.sessions) === 0
      )
      this._daySubjectsRaw = subjectBreakdown
      this._rawTodayDur = selectedDurationSec
      this._rawWeekDur = stats.week_duration_sec || 0

      const willAnimate = !this._hasData
      const recentSessions = daySessions
      this._hasData = true
      this._cancelDurationAnimation(false)
      this._displayTodayDurationSec = willAnimate ? 0 : selectedDurationSec

      const historyPatch = willAnimate
        ? { history: [], historyTotal: effectiveHistory.total || 0, historyReady: false }
        : {
            history: recentSessions.map(item => this._formatSession(item)),
            historyTotal: effectiveHistory.total || 0,
            historyReady: true,
          }

      const lifetimeStart = lifetime.start_date || this.data.lifetimeStartDate || effectiveDate || authoritativeToday
      const cumulativePatch = this._cumulativeCustomized
        ? { lifetimeStartDate: lifetimeStart }
        : {
            lifetimeStartDate: lifetimeStart,
            ...this._cumulativeSummaryPatch({
              ...lifetime,
              start_date: lifetimeStart,
            }, lifetimeStart),
          }
      const displayDaySubjects = this.data.distributionPeriod === 'day'
      if (displayDaySubjects) this._resetPieCache()

      this.setData({
        todaySessions: selectedSessionCount,
        todayDurationText: this._fmtMin(selectedDurationSec),
        selectedDurationLabel: this._formatSelectedDurationLabel(effectiveDate),
        weekSessions: stats.week_sessions || 0,
        weekDurationText: this._fmtMin(stats.week_duration_sec || 0),
        trends: trends.map(item => ({
          date: item.date,
          duration_sec: item.duration_sec,
          _shortDate: (item.date || '').slice(5),
        })),
        trendHasData: this._hasDistributionData(trends),
        subjects: displayDaySubjects ? this._buildSubjectItems(subjectBreakdown) : this.data.subjects,
        distributionHasData: displayDaySubjects ? this._hasDistributionData(subjectBreakdown) : this.data.distributionHasData,
        pieDateLabel: this._formatPieDateLabel(effectiveDate),
        distributionRangeStart: displayDaySubjects ? effectiveDate : this.data.distributionRangeStart,
        distributionRangeEnd: displayDaySubjects ? effectiveDate : this.data.distributionRangeEnd,
        canGoNextDate: !!(effectiveDate && authoritativeToday && effectiveDate < authoritativeToday),
        _crossDayBleedIn: hasBleedInSubjects,
        pieLoading: false,
        loading: false,
        contentReady: true,
        errorText: '',
        _dispTodaySessions: willAnimate ? 0 : selectedSessionCount,
        ...this._getTodayDurationDisplayPatch(willAnimate ? '0分钟' : this._fmtMin(selectedDurationSec)),
        durationValueAnimating: willAnimate,
        _dispWeekSessions: willAnimate ? 0 : (stats.week_sessions || 0),
        _dispWeekDurationText: willAnimate ? '0分钟' : this._fmtMin(stats.week_duration_sec || 0),
        ...cumulativePatch,
        ...historyPatch,
      }, () => {
        if (!this._alive || !this._isVisible || reqId !== this._requestId) return
        if (willAnimate) {
          this._queueDeferredHistory(
            reqId,
            dateSeq,
            effectiveDate,
            recentSessions,
            effectiveHistory.total || 0
          )
        }

        if (this._cumulativeCustomized && this.data.cumulativeStartDate) {
          this._refreshCumulativeSummary(this.data.cumulativeStartDate, true)
        }

        if (!displayDaySubjects) {
          // 周 / 月 / 自定义分布随当日锚点变化重新查询；不触碰柱状图挂载状态。
          this._loadDistributionForPeriod(this.data.distributionPeriod, !willAnimate)
        }

        if (this.data.chartMode === 'pie' && displayDaySubjects) {
          this._initCanvases(() => {
            if (!this._alive || !this._isVisible || this.data.chartMode !== 'pie') return
            if (willAnimate) {
              this._renderPieChart(0, false)
              const node = this._pieCanvasNode
              const raf = node && node.requestAnimationFrame
                ? cb => node.requestAnimationFrame(cb)
                : cb => setTimeout(cb, 16)
              const animReqId = this._requestId
              raf(() => raf(() => this._startAnimations(animReqId)))
            } else {
              this._renderPieChart(1, true)
            }
          })
        } else if (this.data.chartMode === 'bar' && this.data.barCanvasMounted) {
          // 这里仅可能发生在用户已经主动切换过柱状图之后。
          this._initTrendCanvas(() => this._renderTrendBars(1))
        }
      })
    } catch (e) {
      if (
        !this._alive ||
        reqId !== this._requestId ||
        dateSeq !== this._dateRequestSeq ||
        requestedDate !== this.data.selectedDate
      ) return
      console.error('加载统计失败', e)
      if (background && this.data.contentReady) {
        // Keep the last valid snapshot visible when a periodic refresh briefly
        // fails. A later tick/onShow will retry without turning the whole page into
        // an error state.
        this.setData({ loading: false, pieLoading: false, cumulativeLoading: false })
      } else {
        this.setData({ loading: false, pieLoading: false, cumulativeLoading: false, errorText: '加载失败，请检查网络后重试' })
      }
    } finally {
      this._statsLoadInFlight = Math.max(0, (this._statsLoadInFlight || 1) - 1)
    }
  },

  _formatSession(s) {
    return sessionViewModel.formatSession(s, {
      getTaskTypeLabel: session => storage.pomodoroTaskTypes.labelForSession(session),
      getSubjectColor: key => getSubjectColor(key, this.data.themeMode),
    })
  },

  _selectDate(date) {
    const nextDate = String(date || '').trim()
    const today = this.data._todayDate
    if (!nextDate || nextDate === this.data.selectedDate || (today && nextDate > today)) return
    this._cancelDeferredHistory(true)
    const patch = {
      selectedDate: nextDate,
      pieDateLabel: this._formatPieDateLabel(nextDate),
      selectedDurationLabel: this._formatSelectedDurationLabel(nextDate),
      canGoNextDate: !!(today && nextDate < today),
      customRangePickerStartDate: this._shiftDate(nextDate, -365),
      selectedSubjectDetail: null,
      _selectedSubject: null,
      durationValueAnimating: true,
    }
    const customMin = patch.customRangePickerStartDate
    if (this.data.customRangeStartDate && this.data.customRangeStartDate > nextDate) {
      patch.customRangeStartDate = nextDate
    } else if (this.data.customRangeStartDate && this.data.customRangeStartDate < customMin) {
      patch.customRangeStartDate = customMin
    }
    this.setData(patch, () => this.loadDateData(nextDate))
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
    if (wx.showLoading) wx.showLoading({ title: '保存中', mask: true })
    try {
      await api.put('/pomodoro/settings', { day_start_minute: minute })
      const today = chinaTime.getChinaStudyDate(minute)
      let selectedDate = this.data.selectedDate
      // 原 selectedDate 超过新的最大日期（今日）时自动收拢到今日
      if (!selectedDate || selectedDate > today) selectedDate = today
      this._settingsLoaded = true
      this.setData({
        dayStartMinute: minute,
        dayStartTime: chinaTime.minuteToTimeText(minute),
        studyDayRangeText: this._studyDayRangeText(minute),
        _todayDate: today,
        selectedDate,
        pieDateLabel: this._formatPieDateLabel(selectedDate),
        selectedDurationLabel: this._formatSelectedDurationLabel(selectedDate),
        canGoNextDate: !!(selectedDate && selectedDate < today),
        customRangeStartDate: this.data.customRangeStartDate && this.data.customRangeStartDate <= selectedDate
          ? this.data.customRangeStartDate
          : selectedDate,
        selectedSubjectDetail: null,
        _selectedSubject: null,
      }, () => {
        if (!this._alive || !this._viewReady) return
        // 重新加载全部统计（stats / trends / daily-summary / history）并重绘图表
        this.loadData()
      })
    } catch (e) {
      console.error('保存统计日设置失败', e)
      if (wx.showToast) wx.showToast({ title: '保存失败，请重试', icon: 'none' })
    } finally {
      if (wx.hideLoading) wx.hideLoading()
    }
  },

  goToToday() {
    const today = this.data._todayDate
    if (!today || today === this.data.selectedDate) return
    this._selectDate(today)
  },

  async loadDateData(date) {
    const requestDate = String(date || '').trim()
    if (!requestDate) return
    this._dateRequestSeq = (this._dateRequestSeq || 0) + 1
    const seq = this._dateRequestSeq
    const showDayDistribution = this.data.distributionPeriod === 'day'
    if (showDayDistribution) this.setData({ pieLoading: true })
    const viewingToday = requestDate === this.data._todayDate
    try {
      const dateResponses = await Promise.all([
        // 查看“今日”时不传 date，由后端返回权威当前学习日。
        api.get('/pomodoro/daily-summary', viewingToday ? {} : { date: requestDate }),
        api.get('/pomodoro/history', { page: 1, page_size: 20, date: requestDate }),
      ])
      const summary = dateResponses[0]
      const historyRes = dateResponses[1]
      if (
        !this._alive ||
        !this._isVisible ||
        seq !== this._dateRequestSeq ||
        requestDate !== this.data.selectedDate
      ) return

      const reconciled = this._reconcileFromServer(null, viewingToday ? summary : null)
      if (!this._alive || !this._isVisible || seq !== this._dateRequestSeq) return

      const effectiveDate = this.data.selectedDate
      let effectiveHistory = historyRes
      if (viewingToday && reconciled.changedToday && effectiveDate !== requestDate) {
        try {
          effectiveHistory = await api.get('/pomodoro/history', { page: 1, page_size: 20, date: effectiveDate })
        } catch (err) {
          console.error('重取今日 history 失败', err)
          effectiveHistory = { items: [], total: 0 }
        }
        if (!this._alive || !this._isVisible || seq !== this._dateRequestSeq) return
      }

      const daySessions = (effectiveHistory && effectiveHistory.items) || []
      const subjectBreakdown = (summary && summary.subjects) || []
      const selectedDurationSec = Number(summary && summary.duration_sec) || 0
      const selectedSessionCount = Number(summary && summary.sessions) || 0
      const hasBleedInSubjects = subjectBreakdown.some(
        item => Number(item.duration_sec) > 0 && Number(item.sessions) === 0
      )
      const previousDurationSec = Number.isFinite(this._displayTodayDurationSec)
        ? this._displayTodayDurationSec
        : (Number(this._rawTodayDur) || 0)
      const previousSessionCount = Math.max(0, Number(this.data._dispTodaySessions) || 0)
      this._rawTodayDur = selectedDurationSec
      this._daySubjectsRaw = subjectBreakdown
      if (showDayDistribution) this._resetPieCache()

      this.setData({
        todaySessions: selectedSessionCount,
        subjects: showDayDistribution ? this._buildSubjectItems(subjectBreakdown) : this.data.subjects,
        distributionHasData: showDayDistribution ? this._hasDistributionData(subjectBreakdown) : this.data.distributionHasData,
        todayDurationText: this._fmtMin(selectedDurationSec),
        selectedDurationLabel: this._formatSelectedDurationLabel(effectiveDate),
        history: daySessions.slice(0, 20).map(item => this._formatSession(item)),
        historyTotal: (effectiveHistory && effectiveHistory.total) || 0,
        historyReady: true,
        pieDateLabel: this._formatPieDateLabel(effectiveDate),
        distributionRangeStart: showDayDistribution ? effectiveDate : this.data.distributionRangeStart,
        distributionRangeEnd: showDayDistribution ? effectiveDate : this.data.distributionRangeEnd,
        canGoNextDate: !!(effectiveDate && this.data._todayDate && effectiveDate < this.data._todayDate),
        _crossDayBleedIn: hasBleedInSubjects,
        pieLoading: false,
        selectedSubjectDetail: null,
        _selectedSubject: null,
      }, () => {
        if (!this._alive || !this._isVisible || seq !== this._dateRequestSeq) return
        this._animateSelectedDuration(previousDurationSec, selectedDurationSec, previousSessionCount, selectedSessionCount)

        if (!showDayDistribution) {
          this._loadDistributionForPeriod(this.data.distributionPeriod, true)
          return
        }
        if (this.data.chartMode !== 'pie') return
        if (this._pieCtx && this._pieRect) this._animatePieOnly()
        else this._initCanvases(() => this._animatePieOnly())
      })
    } catch (e) {
      if (!this._alive || !this._isVisible || seq !== this._dateRequestSeq) return
      console.error('加载指定日期数据失败', e)
      this.setData({ pieLoading: false, durationValueAnimating: false })
      if (wx.showToast) wx.showToast({ title: '该日期数据加载失败', icon: 'none' })
    }
  },

  _animatePieOnly() {
    if (!this._pieCtx || !this._pieRect) return
    const token = (this._pieAnimationToken || 0) + 1
    this._pieAnimationToken = token
    this._pieLabelToken = (this._pieLabelToken || 0) + 1
    const duration = 980
    const start = Date.now()
    const node = this._pieCanvasNode
    const raf = node && node.requestAnimationFrame
      ? cb => node.requestAnimationFrame(cb)
      : cb => setTimeout(cb, 16)
    let lastDraw = 0

    this._renderPieChart(0, false)
    const tick = () => {
      if (!this._alive || !this._isVisible || token !== this._pieAnimationToken) return
      const elapsed = Date.now() - start
      const raw = Math.min(1, elapsed / duration)
      if (raw < 1 && elapsed - lastDraw >= 28) {
        lastDraw = elapsed
        this._renderPieChart(this._easeInOutCubic(raw), false)
      }
      if (raw < 1) {
        this._pieDateRafId = raf(tick)
      } else {
        // Keep the expensive percentage badges out of the final motion frame.
        this._renderPieChart(1, false)
        this._pieDateRafId = null
        this._revealPieLabelsIncrementally()
      }
    }
    this._pieDateRafId = raf(tick)
  },

  _revealPieLabelsIncrementally() {
    const ctx = this._pieCtx
    const rect = this._pieRect
    const layout = this._pieLabelLayout
    if (!ctx || !rect || !layout || !layout.length) return

    const token = (this._pieLabelToken || 0) + 1
    this._pieLabelToken = token
    const geometry = this._getPieGeometry(rect)
    const node = this._pieCanvasNode
    const raf = node && node.requestAnimationFrame
      ? cb => node.requestAnimationFrame(cb)
      : cb => setTimeout(cb, 16)
    let index = 0

    const drawNext = () => {
      if (!this._alive || !this._isVisible || token !== this._pieLabelToken) return
      const end = Math.min(layout.length, index + 2)
      this._drawPieLabels(ctx, geometry, layout, 1, index, end)
      index = end
      if (index < layout.length) {
        this._pieLabelRafId = raf(drawNext)
      } else {
        this._pieLabelRafId = null
      }
    }

    this._pieLabelRafId = raf(drawNext)
  },

  /* ==================== Animation Control ==================== */

  _cancelPendingWork() {
    this._clearDynamicRefresh()
    this._cancelDurationAnimation(false)
    this._cancelDeferredHistory(true)
    this._animActive = false
    this._finalDrawn = false
    this._requestId++
    if (this._rafId && this._pieCanvasNode && this._pieCanvasNode.cancelAnimationFrame) {
      this._pieCanvasNode.cancelAnimationFrame(this._rafId)
    }
    if (this._pieDateRafId && this._pieCanvasNode && this._pieCanvasNode.cancelAnimationFrame) {
      this._pieCanvasNode.cancelAnimationFrame(this._pieDateRafId)
    }
    if (this._pieLabelRafId && this._pieCanvasNode && this._pieCanvasNode.cancelAnimationFrame) {
      this._pieCanvasNode.cancelAnimationFrame(this._pieLabelRafId)
    }
    if (this._barRafId && this._trendCanvasNode && this._trendCanvasNode.cancelAnimationFrame) {
      this._trendCanvasNode.cancelAnimationFrame(this._barRafId)
    }
    this._rafId = null
    this._pieDateRafId = null
    this._pieLabelRafId = null
    this._barRafId = null
    this._pieAnimationToken = (this._pieAnimationToken || 0) + 1
    this._pieLabelToken = (this._pieLabelToken || 0) + 1
    this._barAnimationToken = (this._barAnimationToken || 0) + 1
    if (this._animTimer) {
      clearTimeout(this._animTimer)
      this._animTimer = null
    }
  },

  _initCanvases(callback) {
    // Compatibility name retained for existing callers/tests; this method now
    // initializes the pie canvas only.  The bar canvas has a separate lazy path.
    const doneCallback = typeof callback === 'function' ? callback : () => {}
    if (this._pieCanvasNode && this._pieCtx && this._pieRect) {
      doneCallback()
      return
    }
    if (this._canvasInitPending) {
      this._canvasInitCallbacks.push(doneCallback)
      return
    }
    this._canvasInitPending = true
    this._canvasInitCallbacks = [doneCallback]

    const finish = () => {
      this._canvasInitPending = false
      const callbacks = this._canvasInitCallbacks.slice()
      this._canvasInitCallbacks.length = 0
      callbacks.forEach(cb => cb())
    }
    const windowInfo = wx.getWindowInfo ? wx.getWindowInfo() : {}
    // Use the real device pixel ratio. Clamping to 2 left 3x devices rendering a
    // 2x backing store upscaled to the panel, which is exactly what blurred the
    // small percentage digits inside the leader-line badges.
    const dpr = windowInfo.pixelRatio || 2
    wx.createSelectorQuery().in(this)
      .select('#pie-canvas')
      .fields({ node: true, size: true })
      .exec(res => {
        if (!this._alive || !res || !res[0] || !res[0].node) { finish(); return }
        const node = res[0].node
        const ctx = node.getContext('2d')
        const w = res[0].width
        const h = res[0].height
        // hidden Canvas may report a zero-sized node. Do not cache that node;
        // the next data-bearing render will initialize it again at its real size.
        if (!w || !h) { finish(); return }
        node.width = Math.round(w * dpr)
        node.height = Math.round(h * dpr)
        ctx.scale(dpr, dpr)
        this._pieCanvasNode = node
        this._pieCtx = ctx
        this._pieRect = { width: w, height: h }
        this._pieDpr = dpr
        finish()
      })
  },

  _initTrendCanvas(callback) {
    const doneCallback = typeof callback === 'function' ? callback : () => {}
    if (!this.data.barCanvasMounted) {
      doneCallback()
      return
    }
    if (this._trendCanvasNode && this._trendCtx && this._trendBarsRect) {
      doneCallback()
      return
    }
    if (this._barInitPending) {
      this._barInitCallbacks.push(doneCallback)
      return
    }
    this._barInitPending = true
    this._barInitCallbacks = [doneCallback]

    const finish = () => {
      this._barInitPending = false
      const callbacks = this._barInitCallbacks.slice()
      this._barInitCallbacks.length = 0
      callbacks.forEach(cb => cb())
    }
    const windowInfo = wx.getWindowInfo ? wx.getWindowInfo() : {}
    // Match the pie canvas: no clamp, so the bar labels stay crisp on 3x screens.
    const dpr = windowInfo.pixelRatio || 2
    wx.createSelectorQuery().in(this)
      .select('#trend-bars-canvas')
      .fields({ node: true, size: true })
      .exec(res => {
        if (!this._alive || !res || !res[0] || !res[0].node) { finish(); return }
        const node = res[0].node
        const ctx = node.getContext('2d')
        const w = res[0].width
        const h = res[0].height
        // hidden Canvas may report a zero-sized node. Do not cache that node;
        // the next data-bearing render will initialize it again at its real size.
        if (!w || !h) { finish(); return }
        node.width = Math.round(w * dpr)
        node.height = Math.round(h * dpr)
        ctx.scale(dpr, dpr)
        this._trendCanvasNode = node
        this._trendCtx = ctx
        this._trendBarsRect = { width: w, height: h }
        finish()
      })
  },

  _shadeColorCached(hex, amount) {
    const key = hex + '|' + amount
    if (!this._shadeCache) this._shadeCache = {}
    if (this._shadeCache[key]) return this._shadeCache[key]
    const v = this._shadeColor(hex, amount)
    this._shadeCache[key] = v
    return v
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
    if (!layout || !layout.length || reveal <= 0) return
    const palette = this._getCanvasPalette()
    // Badge positions come from the collision solver, so they are fractional.
    // Drawing the box and a 10px label on a fractional device-pixel boundary is
    // the other half of the blur problem: snap them so both land on whole
    // device pixels.
    const dpr = this._pieDpr || 1
    const snap = (value) => Math.round(value * dpr) / dpr
    ctx.save()
    ctx.globalAlpha = Math.max(0, Math.min(1, reveal))
    ctx.lineCap = 'round'
    ctx.lineJoin = 'round'

    for (let i = startIndex; i < Math.min(endIndex, layout.length); i++) {
      const item = layout[i]
      const sec = item.sec

      // Short two-segment elbow: sector edge -> local outward elbow -> badge.
      ctx.strokeStyle = sec.color
      ctx.lineWidth = 1.15
      ctx.beginPath()
      ctx.moveTo(item.startX, item.startY)
      ctx.lineTo(item.elbowX, item.elbowY)
      ctx.lineTo(item.lineEndX, item.lineEndY)
      ctx.stroke()

      ctx.fillStyle = sec.color
      ctx.beginPath()
      ctx.arc(item.startX, item.startY, 2.1, 0, Math.PI * 2)
      ctx.fill()

      const badgeX = snap(item.badgeX)
      const badgeY = snap(item.badgeY)
      this._roundRectPath(ctx, badgeX, badgeY, item.badgeW, item.badgeH, 8)
      ctx.fillStyle = palette.badgeFill
      ctx.fill()
      ctx.strokeStyle = sec.color
      ctx.lineWidth = 0.8
      ctx.stroke()

      ctx.fillStyle = palette.badgeText
      ctx.font = '600 10px sans-serif'
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      // Snap only the glyph origin horizontally: horizontal subpixel offsets are
      // what smear the stroke edges. The vertical +0.5 is the existing optical
      // nudge for CJK under textBaseline:'middle' and is left untouched.
      ctx.fillText(
        sec.subject._durationBadgeText || '0时0分',
        snap(badgeX + item.badgeW / 2),
        badgeY + item.badgeH / 2 + 0.5
      )
    }
    ctx.restore()
  },

  _renderPieChart(progress, includeLabels = true) {
    const subjects = this.data.subjects
    const ctx = this._pieCtx
    const rect = this._pieRect
    if (!ctx || !rect || !rect.width) return

    const geometry = this._getPieGeometry(rect)
    const palette = this._getCanvasPalette()
    const { w, h, centerX, centerY, radius, tilt, depth } = geometry
    const reveal = Math.max(0, Math.min(1, (progress - 0.5) / 0.5))
    const labelReveal = Math.max(0, Math.min(1, (progress - 0.62) / 0.38))

    ctx.clearRect(0, 0, w, h)

    const hasData = subjects && subjects.length && subjects.some(item => (item.duration_sec || 0) > 0)
    // 空状态由 WXML 插画承载。Canvas 这里只保持透明，避免原来的
    // “空饼图 + 暂无数据”穿透插画层，尤其是在真机/开发者工具的 Canvas 合成层中。
    if (!hasData) return

    // Geometry, shades and label positions are cached for the entire data set.
    if (!this._pieSectors) {
      const totalDur = subjects.reduce((sum, item) => sum + (item.duration_sec || 0), 0) || 1
      const sectors = []
      let angle = -Math.PI / 2
      subjects.filter(item => (item.duration_sec || 0) > 0).forEach(item => {
        const pct = (item.duration_sec || 0) / totalDur
        const endA = angle + Math.PI * 2 * pct
        sectors.push({
          subject: item,
          color: item._color || '#3B82F6',
          pct,
          startA: angle,
          endA,
        })
        angle = endA
      })
      this._pieSectors = sectors
      // Keep layer count stable across the animation. The previous final-frame
      // jump from 3 layers to ~12 caused the visible tail-end hitch.
      const wallStepsFull = Math.max(5, Math.min(7, Math.round(depth)))
      this._pieWallSteps = wallStepsFull
      sectors.forEach(sec => {
        sec._wallShades = []
        for (let layer = 1; layer <= wallStepsFull; layer++) {
          const ratio = layer / wallStepsFull
          sec._wallShades.push(this._shadeColorCached(sec.color, Math.round(-52 + ratio * 38)))
        }
      })
      this._pieLabelLayout = this._buildPieLabelLayout(sectors, geometry)
    }

    const sectors = this._pieSectors
    const wallSteps = this._pieWallSteps
    const selectedSubject = this.data._selectedSubject

    // 1. Shadow fades in before completion instead of appearing on one heavy final frame.
    if (reveal > 0) {
      ctx.save()
      ctx.globalAlpha = reveal
      ctx.translate(centerX + 4, centerY + depth * 1.3)
      ctx.scale(1, tilt)
      const shadowGrad = ctx.createRadialGradient(0, 0, 0, 0, 0, radius * 1.05)
      shadowGrad.addColorStop(0, palette.shadowStart)
      shadowGrad.addColorStop(0.5, palette.shadowMid)
      shadowGrad.addColorStop(1, 'rgba(0,0,0,0)')
      ctx.fillStyle = shadowGrad
      ctx.beginPath()
      ctx.arc(0, 0, radius * 1.05, 0, Math.PI * 2)
      ctx.fill()
      ctx.restore()
    }

    const sortedSectors = selectedSubject
      ? sectors.slice().sort((a, b) => {
          const aSelected = a.subject.subject === selectedSubject ? 1 : 0
          const bSelected = b.subject.subject === selectedSubject ? 1 : 0
          return aSelected - bSelected
        })
      : sectors

    // 2. Side walls use a constant number of layers throughout the animation.
    for (let layer = wallSteps; layer >= 1; layer--) {
      const layerOffset = depth * layer / wallSteps * progress
      sortedSectors.forEach(sec => {
        const curEnd = sec.startA + (sec.endA - sec.startA) * progress
        if (curEnd - sec.startA < 0.002) return
        const mid = (sec.startA + curEnd) / 2
        const isSelected = selectedSubject && sec.subject.subject === selectedSubject
        const pull = isSelected ? 6 : 0
        const cx = centerX + Math.cos(mid) * pull
        const cy = centerY + Math.sin(mid) * pull * tilt + layerOffset
        this._drawEllipticSector(
          ctx, cx, cy, radius, tilt, sec.startA, curEnd,
          sec._wallShades[layer - 1]
        )
      })
    }

    // 3. Top sectors.
    sortedSectors.forEach(sec => {
      const curEnd = sec.startA + (sec.endA - sec.startA) * progress
      if (curEnd - sec.startA < 0.002) return
      const mid = (sec.startA + curEnd) / 2
      const isSelected = selectedSubject && sec.subject.subject === selectedSubject
      const pull = isSelected ? 6 : 0
      const cx = centerX + Math.cos(mid) * pull
      const cy = centerY + Math.sin(mid) * pull * tilt
      const fillColor = isSelected ? this._shadeColorCached(sec.color, 12) : sec.color
      this._drawEllipticSector(ctx, cx, cy, radius, tilt, sec.startA, curEnd, fillColor)
    })

    // 4. Separators fade in progressively.
    if (reveal > 0 && sectors.length > 1) {
      ctx.save()
      ctx.globalAlpha = reveal
      ctx.translate(centerX, centerY)
      ctx.scale(1, tilt)
      ctx.strokeStyle = palette.separator
      ctx.lineWidth = 1
      sectors.forEach(sec => {
        ctx.beginPath()
        ctx.moveTo(0, 0)
        ctx.lineTo(Math.cos(sec.startA) * radius, Math.sin(sec.startA) * radius)
        ctx.stroke()
      })
      ctx.restore()
    }

    // 5. Unified lighting, also progressive to avoid a final-frame spike.
    if (reveal > 0) {
      ctx.save()
      ctx.globalAlpha = reveal
      ctx.translate(centerX, centerY)
      ctx.scale(1, tilt)
      ctx.beginPath()
      ctx.arc(0, 0, radius, 0, Math.PI * 2)
      ctx.clip()
      const lightGrad = ctx.createRadialGradient(
        -radius * 0.2, -radius * 0.2, 0,
        -radius * 0.2, -radius * 0.2, radius
      )
      lightGrad.addColorStop(0, 'rgba(255,255,255,0.14)')
      lightGrad.addColorStop(0.35, 'rgba(255,255,255,0.04)')
      lightGrad.addColorStop(0.7, 'rgba(0,0,0,0.04)')
      lightGrad.addColorStop(1, 'rgba(0,0,0,0.10)')
      ctx.fillStyle = lightGrad
      ctx.beginPath()
      ctx.arc(0, 0, radius, 0, Math.PI * 2)
      ctx.fill()
      ctx.restore()
    }

    // 6. Selected state.
    if (selectedSubject && reveal > 0.9) {
      sectors.forEach(sec => {
        if (sec.subject.subject === selectedSubject) return
        ctx.save()
        ctx.globalAlpha = 0.12
        this._drawEllipticSector(
          ctx, centerX, centerY, radius, tilt,
          sec.startA, sec.endA, palette.selectedMask
        )
        ctx.restore()
      })
    }

    // 7. Every sector gets a compact one-line callout near its own slice.
    if (includeLabels) {
      this._drawPieLabels(ctx, geometry, this._pieLabelLayout, labelReveal)
    }
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
