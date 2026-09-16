const api = require('../../../utils/api')
const pomodoroTheme = require('../utils/pomodoro-theme')
const chinaTime = require('../utils/china-time')
const storage = require('../../../utils/storage')

const DARK_SUBJECT_COLORS = ['#3B82F6', '#F59E0B', '#10B981', '#06B6D4', '#F97316', '#2DD4BF', '#EA580C', '#8B5CF6', '#6366F1', '#EC4899']
const LIGHT_SUBJECT_COLORS = ['#2F6B4F', '#7A9B76', '#2B8C83', '#B59A38', '#C4773B', '#D96B5F', '#6685A3', '#718C45', '#B45E46', '#876F8F']
// A clearer jewel-toned palette used only by the light-mode pie chart.
// History accents and the trend chart keep their existing colors.
const LIGHT_PIE_COLORS = ['#E76F51', '#2A9D8F', '#457B9D', '#E9C46A', '#8E6BBE', '#F28482', '#6A994E', '#43AA8B', '#B56576', '#577590']
const DARK_TREND_COLORS = ['#22C55E', '#06B6D4', '#3B82F6', '#818CF8', '#A78BFA', '#D946EF']
const LIGHT_TREND_COLORS = ['#2F6B4F', '#7A9B76', '#2B8C83', '#B59A38', '#C4773B', '#D96B5F', '#6685A3']
const STATS_DYNAMIC_REFRESH_MS = 60 * 1000

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

/**
 * Format duration seconds into a human-readable hours/minutes string.
 *
 * Rules:
 *  - Floor to complete minutes (no rounding up).
 *  - < 1 hour: "X分钟" (e.g. "41分钟")
 *  - >= 1 hour: "X时Y分" (e.g. "4时19分", "1时0分")
 *  - Never show seconds.
 */
function formatDuration(sec) {
  var s = Math.max(0, sec || 0)
  var totalMin = Math.floor(s / 60)
  var hours = Math.floor(totalMin / 60)
  var mins = totalMin % 60
  if (hours > 0) return hours + '时' + mins + '分'
  return mins + '分钟'
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
    return 1 - Math.pow(1 - t, 3)
  },

  _easeInOutCubic(t) {
    return t < 0.5
      ? 4 * t * t * t
      : 1 - Math.pow(-2 * t + 2, 3) / 2
  },

  _parseDateStr(s) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(s || ''))
    if (!m) return null
    return [Number(m[1]), Number(m[2]), Number(m[3])]
  },

  _formatDateParts(parts) {
    if (!parts) return ''
    const pad = n => String(n).padStart(2, '0')
    return `${parts[0]}-${pad(parts[1])}-${pad(parts[2])}`
  },

  _shiftDate(value, deltaDays) {
    const parts = this._parseDateStr(value)
    if (!parts) return value || ''
    const utc = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2] + Number(deltaDays || 0)))
    return this._formatDateParts([utc.getUTCFullYear(), utc.getUTCMonth() + 1, utc.getUTCDate()])
  },

  _startOfWeek(value) {
    const parts = this._parseDateStr(value)
    if (!parts) return value || ''
    const utc = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]))
    const weekday = utc.getUTCDay()
    const offset = weekday === 0 ? -6 : 1 - weekday
    return this._shiftDate(value, offset)
  },

  _monthStart(value) {
    const parts = this._parseDateStr(value)
    return parts ? this._formatDateParts([parts[0], parts[1], 1]) : (value || '')
  },

  _monthEnd(value) {
    const parts = this._parseDateStr(value)
    if (!parts) return value || ''
    const utc = new Date(Date.UTC(parts[0], parts[1], 0))
    return this._formatDateParts([utc.getUTCFullYear(), utc.getUTCMonth() + 1, utc.getUTCDate()])
  },

  _minDate(a, b) {
    if (!a) return b || ''
    if (!b) return a || ''
    return a <= b ? a : b
  },

  _resolveDistributionRange(period, anchorDate) {
    const anchor = anchorDate || this.data.selectedDate || this.data._todayDate
    const today = this.data._todayDate || anchor
    if (period === 'week') {
      const start = this._startOfWeek(anchor)
      return { start, end: this._minDate(this._shiftDate(start, 6), today) }
    }
    if (period === 'month') {
      return { start: this._monthStart(anchor), end: this._minDate(this._monthEnd(anchor), today) }
    }
    if (period === 'custom') {
      let start = this.data.customRangeStartDate || anchor
      if (start > anchor) start = anchor
      return { start, end: anchor }
    }
    return { start: anchor, end: anchor }
  },

  _formatPieDateLabel(value) {
    if (!value) return '今日'
    if (value === this.data._todayDate) return '今日'
    const today = this._parseDateStr(this.data._todayDate)
    const target = this._parseDateStr(value)
    if (today && target) {
      // 用 Date.UTC 计算日历日差，避免设备时区偏差
      const diffDays = Math.round(
        (Date.UTC(today[0], today[1] - 1, today[2]) - Date.UTC(target[0], target[1] - 1, target[2])) / 86400000
      )
      if (diffDays === 1) return '昨日'
      return `${target[1]}月${target[2]}日`
    }
    return value
  },

  _formatSelectedDurationLabel(value) {
    const dateLabel = this._formatPieDateLabel(value)
    return dateLabel === '今日' ? '今日学习' : `${dateLabel}学习`
  },

  _hasDistributionData(subjects) {
    return Array.isArray(subjects) && subjects.some(item => Number(item && item.duration_sec) > 0)
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
    const roots = Array.isArray(tree) ? tree : []
    const byId = {}
    const leafIds = []
    const normalizeId = value => {
      const n = Number(value)
      return Number.isFinite(n) && n > 0 ? n : null
    }
    const visit = (node, parentId) => {
      if (!node || node.is_active === false) return []
      const id = normalizeId(node.subject_id || node.id)
      const children = Array.isArray(node.children) ? node.children : []
      const childLeafIds = []
      children.forEach(child => {
        const descendants = visit(child, id)
        descendants.forEach(leafId => childLeafIds.push(leafId))
      })
      const label = String(node.subject_name || node.display_name || node.name || '').trim() || '未分类'
      const code = String(node.subject_code || node.product_code || node.code || '').trim()
      const isLeaf = childLeafIds.length === 0
      const descendantLeafIds = isLeaf && id != null ? [id] : childLeafIds.slice()
      if (id != null) {
        byId[id] = {
          id,
          parentId: normalizeId(parentId),
          name: label,
          code,
          isLeaf,
          descendantLeafIds,
        }
        if (isLeaf) leafIds.push(id)
      }
      return descendantLeafIds
    }
    roots.forEach(node => visit(node, null))
    return { byId, leafIds }
  },

  _distributeAggregateValue(total, leafIds, currentTotals) {
    const count = Array.isArray(leafIds) ? leafIds.length : 0
    const safeTotal = Math.max(0, Math.round(Number(total) || 0))
    if (!count || !safeTotal) return []
    const weights = leafIds.map(id => Math.max(0, Number(currentTotals[id]) || 0))
    const weightSum = weights.reduce((sum, value) => sum + value, 0)
    const base = []
    const remainders = []
    let assigned = 0
    leafIds.forEach((id, index) => {
      const share = weightSum > 0
        ? (safeTotal * weights[index]) / weightSum
        : safeTotal / count
      const value = Math.floor(share)
      base[index] = value
      remainders[index] = share - value
      assigned += value
    })
    let rest = safeTotal - assigned
    const order = leafIds.map((id, index) => ({ index, remainder: remainders[index], weight: weights[index] }))
      .sort((a, b) => {
        if (b.remainder !== a.remainder) return b.remainder - a.remainder
        if (b.weight !== a.weight) return b.weight - a.weight
        return a.index - b.index
      })
    let cursor = 0
    while (rest > 0 && order.length) {
      const target = order[cursor % order.length]
      base[target.index] += 1
      rest -= 1
      cursor += 1
    }
    return leafIds.map((id, index) => ({ id, value: base[index] }))
  },

  _normalizeDistributionSubjects(subjects) {
    const subjArr = Array.isArray(subjects) ? subjects : []
    const meta = this._subjectMeta
    if (!meta || !meta.byId) return subjArr.slice()

    const bucketById = {}
    const passthrough = []
    const parentBuckets = []
    const upsertLeaf = (subjectId, fallbackItem) => {
      const metaNode = meta.byId[subjectId] || {}
      if (!bucketById[subjectId]) {
        bucketById[subjectId] = {
          subject_id: subjectId,
          subject_code: metaNode.code || String((fallbackItem && fallbackItem.subject_code) || ''),
          subject_name: metaNode.name || String((fallbackItem && fallbackItem.subject_name) || '未分类'),
          sessions: 0,
          duration_sec: 0,
        }
      }
      return bucketById[subjectId]
    }

    subjArr.forEach(item => {
      const subjectId = item && item.subject_id != null ? Number(item.subject_id) : null
      const durationSec = Math.max(0, Number(item && item.duration_sec) || 0)
      const sessions = Math.max(0, Number(item && item.sessions) || 0)
      if (subjectId == null || !meta.byId[subjectId]) {
        passthrough.push({
          subject_id: item && item.subject_id != null ? item.subject_id : null,
          subject_code: String((item && item.subject_code) || ''),
          subject_name: String((item && item.subject_name) || '未分类'),
          sessions,
          duration_sec: durationSec,
        })
        return
      }
      const node = meta.byId[subjectId]
      if (node.isLeaf) {
        const bucket = upsertLeaf(subjectId, item)
        bucket.sessions += sessions
        bucket.duration_sec += durationSec
        return
      }
      const leafIds = Array.isArray(node.descendantLeafIds) ? node.descendantLeafIds.filter(id => meta.byId[id] && meta.byId[id].isLeaf) : []
      if (!leafIds.length) {
        passthrough.push({
          subject_id: subjectId,
          subject_code: node.code || String((item && item.subject_code) || ''),
          subject_name: node.name || String((item && item.subject_name) || '未分类'),
          sessions,
          duration_sec: durationSec,
        })
        return
      }
      parentBuckets.push({ item, leafIds, durationSec, sessions })
    })

    parentBuckets.forEach(entry => {
      const currentDurations = {}
      const currentSessions = {}
      entry.leafIds.forEach(id => {
        currentDurations[id] = bucketById[id] ? bucketById[id].duration_sec : 0
        currentSessions[id] = bucketById[id] ? bucketById[id].sessions : 0
      })
      const durationShares = this._distributeAggregateValue(entry.durationSec, entry.leafIds, currentDurations)
      const sessionShares = this._distributeAggregateValue(entry.sessions, entry.leafIds, currentSessions)
      durationShares.forEach(share => {
        const bucket = upsertLeaf(share.id, entry.item)
        bucket.duration_sec += share.value
      })
      sessionShares.forEach(share => {
        const bucket = upsertLeaf(share.id, entry.item)
        bucket.sessions += share.value
      })
    })

    const normalized = Object.values(bucketById)
      .concat(passthrough)
      .filter(item => Number(item.duration_sec) > 0 || Number(item.sessions) > 0)
      .sort((a, b) => {
        const diff = Number(b.duration_sec || 0) - Number(a.duration_sec || 0)
        if (diff !== 0) return diff
        return String(a.subject_name || '').localeCompare(String(b.subject_name || ''), 'zh-Hans-CN')
      })
    return normalized
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
    this._durationAnimationToken = (this._durationAnimationToken || 0) + 1
    if (this._durationAnimationTimer) {
      clearTimeout(this._durationAnimationTimer)
      this._durationAnimationTimer = null
    }
    if (resetState && this._alive) {
      this.setData({ durationValueAnimating: false })
    }
  },

  _animateSelectedDuration(fromSec, toSec, fromSessions, toSessions) {
    const startValue = Math.max(0, Number(fromSec) || 0)
    const targetValue = Math.max(0, Number(toSec) || 0)
    const startSessions = Math.max(0, Number(fromSessions) || 0)
    const targetSessions = Math.max(0, Number(toSessions) || 0)

    this._cancelDurationAnimation(false)
    const token = this._durationAnimationToken
    const startText = this._fmtMin(startValue)
    const targetText = this._fmtMin(targetValue)

    this._displayTodayDurationSec = startValue
    if (startText === targetText && startSessions === targetSessions) {
      this._displayTodayDurationSec = targetValue
      this.setData({
        _dispTodaySessions: targetSessions,
        ...this._getTodayDurationDisplayPatch(targetText),
        durationValueAnimating: false,
      })
      return
    }

    // Keep the selected-day count and duration on one transition clock. Sparse
    // setData ticks leave the canvas animation enough main-thread time.
    const duration = 620
    const steps = 12
    const interval = Math.round(duration / steps)
    const delta = targetValue - startValue
    const sessionDelta = targetSessions - startSessions
    let step = 0
    let lastText = startText
    let lastValue = startValue
    let lastSessions = startSessions

    this.setData({ durationValueAnimating: true })

    const tick = () => {
      if (
        !this._alive ||
        !this._isVisible ||
        token !== this._durationAnimationToken
      ) return

      step += 1
      const progress = Math.min(1, step / steps)
      const eased = this._easeInOutCubic(progress)
      let nextValue = Math.round(startValue + delta * eased)
      let nextSessions = Math.round(startSessions + sessionDelta * eased)

      // Guard against rounding producing a one-frame reversal.
      nextValue = delta >= 0
        ? Math.max(lastValue, Math.min(targetValue, nextValue))
        : Math.min(lastValue, Math.max(targetValue, nextValue))
      nextSessions = sessionDelta >= 0
        ? Math.max(lastSessions, Math.min(targetSessions, nextSessions))
        : Math.min(lastSessions, Math.max(targetSessions, nextSessions))

      if (progress >= 1) {
        nextValue = targetValue
        nextSessions = targetSessions
      }
      lastValue = nextValue
      lastSessions = nextSessions
      this._displayTodayDurationSec = nextValue

      const nextText = this._fmtMin(nextValue)
      const isFinal = progress >= 1
      if (nextText !== lastText || nextSessions !== this.data._dispTodaySessions || isFinal) {
        lastText = nextText
        this.setData({
          _dispTodaySessions: nextSessions,
          ...this._getTodayDurationDisplayPatch(nextText),
          durationValueAnimating: !isFinal,
        })
      }

      if (!isFinal) {
        this._durationAnimationTimer = setTimeout(tick, interval)
      } else {
        this._durationAnimationTimer = null
      }
    }

    this._durationAnimationTimer = setTimeout(tick, interval)
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
    // 统一按中国时间（UTC+8）格式化，不依赖设备时区
    const timeStr = chinaTime.formatChinaTimeHM(s.start_time)
    const dateStr = chinaTime.formatChinaMonthDay(s.start_time)
    const durSec = s.actual_duration ?? s.actual_duration_sec ?? s.duration_sec ?? 0
    const subjectName = s.subject_name || '未分类'
    const subjectKey = s.subject_code || ''
    const isPractice = s.record_type === 'practice'
    const isFree = s.preset === 'free'
    const sessionTaskType = storage.pomodoroTaskTypes.labelForSession(s)
    const durationText = formatDuration(durSec)
    // 刷题会话：左侧明确标出「刷题」，状态为「刷题」而非「完成」，与番茄钟区分。
    let _subjectLabel, _statusLabel, _statusClass
    if (isPractice) {
      _subjectLabel = '刷题 · ' + subjectName
      _statusLabel = '刷题'
      _statusClass = 'status-done'
    } else {
      _subjectLabel = isFree ? '自由计时 · ' + subjectName : subjectName
      _statusLabel = s.status === 'completed' ? '完成' : '中断'
      _statusClass = s.status === 'completed' ? 'status-done' : 'status-interrupt'
    }
    return {
      ...s,
      _time: timeStr,
      _date: dateStr,
      _duration: durationText,
      _taskTypeLabel: sessionTaskType,
      _subjectLabel,
      _color: getSubjectColor(s.subject_id != null ? String(s.subject_id) : (subjectKey || subjectName), this.data.themeMode),
      _statusLabel,
      _statusClass,
      _iconType: isPractice ? 'practice' : (isFree ? 'free' : 'focus'),
    }
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
    const dpr = Math.min(2, windowInfo.pixelRatio || 2)
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
    const dpr = Math.min(2, windowInfo.pixelRatio || 2)
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
    if (!this._alive || !this._isVisible || reqId !== this._requestId || this.data.chartMode !== 'pie') return
    this._animActive = true
    this._finalDrawn = false
    this._pieLabelToken = (this._pieLabelToken || 0) + 1
    const pieAnimDuration = 980
    const startTime = Date.now()

    // 首屏只做“当日专注”数字 + 扇形图动画。柱状图完全留到用户点击切换后。
    const targetSessions = this.data.todaySessions
    const numberDuration = 420
    const totalSteps = 7
    let step = 0
    const numTick = () => {
      if (!this._animActive || !this._alive || !this._isVisible || reqId !== this._requestId) return
      step += 1
      const p = Math.min(1, step / totalSteps)
      const eased = this._easeOutCubic(p)
      const displayDurationSec = Math.round(this._rawTodayDur * eased)
      this._displayTodayDurationSec = displayDurationSec
      this.setData({
        _dispTodaySessions: Math.round(targetSessions * eased),
        ...this._getTodayDurationDisplayPatch(this._fmtMin(displayDurationSec)),
        durationValueAnimating: p < 1,
      })
      if (step < totalSteps) {
        this._animTimer = setTimeout(numTick, Math.round(numberDuration / totalSteps))
      } else {
        this._animTimer = null
      }
    }
    numTick()

    const node = this._pieCanvasNode
    const raf = node && node.requestAnimationFrame
      ? cb => node.requestAnimationFrame(cb)
      : cb => setTimeout(cb, 16)
    let lastPieDraw = -Infinity
    const tick = () => {
      if (
        !this._animActive ||
        !this._alive ||
        !this._isVisible ||
        reqId !== this._requestId ||
        this.data.chartMode !== 'pie'
      ) return
      const elapsed = Date.now() - startTime
      const raw = Math.min(1, elapsed / pieAnimDuration)
      if (raw < 1 && elapsed - lastPieDraw >= 28) {
        lastPieDraw = elapsed
        this._renderPieChart(this._easeInOutCubic(raw), false)
      }
      if (raw < 1) {
        this._rafId = raf(tick)
      } else if (!this._finalDrawn) {
        this._finalDrawn = true
        this._animActive = false
        this._renderPieChart(1, false)
        this._rafId = raf(() => {
          this._rafId = null
          if (!this._alive || !this._isVisible || reqId !== this._requestId || this.data.chartMode !== 'pie') return
          this._revealPieLabelsIncrementally()
        })
      }
    }
    this._rafId = raf(tick)
  },

  /* ==================== Trend Bars ==================== */

  _renderTrendBars(progress) {
    const trendColors = this.data.themeMode === 'light' ? LIGHT_TREND_COLORS : DARK_TREND_COLORS
    const palette = this._getCanvasPalette()
    const trends = this.data.trends
    if (!trends || !trends.length) return
    const ctx = this._trendCtx
    const rect = this._trendBarsRect
    if (!ctx || !rect || !rect.width) return

    const w = rect.width
    const h = rect.height
    const padL = 44
    const padR = 16
    const padT = 24
    const padB = 32
    const chartW = w - padL - padR
    const chartH = h - padT - padB
    const barW = Math.min(32, chartW / trends.length * 0.5)
    const gap = chartW / trends.length
    const maxDur = Math.max.apply(Math, [1].concat(trends.map(t => t.duration_sec || 0)))
    const depth = Math.min(7, barW * 0.28)
    const topTilt = 0.45

    const isFinal = progress >= 1
    const fadeIn = (start) => Math.max(0, Math.min(1, (progress - start) / (1 - start)))
    const finalFade = fadeIn(0.82)

    ctx.clearRect(0, 0, w, h)

    // Grid lines — subtle horizontal guides
    for (let i = 0; i <= 3; i++) {
      const y = padT + chartH * (1 - i / 3)
      ctx.beginPath()
      ctx.strokeStyle = palette.grid
      ctx.lineWidth = 0.5
      ctx.moveTo(padL, y)
      ctx.lineTo(w - padR, y)
      ctx.stroke()
    }

    // Baseline
    ctx.beginPath()
    ctx.strokeStyle = palette.baseline
    ctx.lineWidth = 1
    ctx.moveTo(padL, padT + chartH)
    ctx.lineTo(w - padR, padT + chartH)
    ctx.stroke()

    trends.forEach((t, i) => {
      const x = padL + gap * i + (gap - barW) / 2
      const finalBarH = (t.duration_sec || 0) / maxDur * chartH
      const barH = Math.max(0, finalBarH * progress)
      const baseY = padT + chartH
      const topY = baseY - barH
      const show3D = finalFade > 0.01 && barH > depth * topTilt * 2

      if (t.duration_sec > 0 && barH > 0) {
        // Ground shadow — soft ellipse at base, fades in with finalFade
        if (finalFade > 0) {
          ctx.save()
          ctx.globalAlpha = finalFade * 0.45
          ctx.translate(x + barW / 2, baseY + 2)
          ctx.scale(1, 0.28)
          const shGrad = ctx.createRadialGradient(0, 0, 0, 0, 0, barW * 0.75)
          shGrad.addColorStop(0, 'rgba(0,0,0,0.32)')
          shGrad.addColorStop(0.5, 'rgba(0,0,0,0.14)')
          shGrad.addColorStop(1, 'rgba(0,0,0,0)')
          ctx.fillStyle = shGrad
          ctx.beginPath()
          ctx.arc(0, 0, barW * 0.75, 0, Math.PI * 2)
          ctx.fill()
          ctx.restore()
        }

        // Per-bar color
        const barColor = trendColors[i % trendColors.length]
        const rc = parseInt(barColor.slice(1, 3), 16)
        const gc = parseInt(barColor.slice(3, 5), 16)
        const bc = parseInt(barColor.slice(5, 7), 16)

        // Right side face — darker crystal depth
        if (show3D) {
          ctx.save()
          ctx.globalAlpha = finalFade
          ctx.fillStyle = `rgba(${Math.round(rc*0.5)},${Math.round(gc*0.5)},${Math.round(bc*0.5)},0.85)`
          ctx.beginPath()
          ctx.moveTo(x + barW, topY)
          ctx.lineTo(x + barW + depth, topY - depth * topTilt)
          ctx.lineTo(x + barW + depth, baseY - depth * topTilt)
          ctx.lineTo(x + barW, baseY)
          ctx.closePath()
          ctx.fill()
          ctx.restore()
        }

        // Left edge glow — light escaping crystal facet
        ctx.fillStyle = `rgba(${Math.min(255,rc+110)},${Math.min(255,gc+110)},${Math.min(255,bc+110)},0.3)`
        ctx.fillRect(x, topY + 2, 1.5, barH - 4)

        // Front face — translucent crystal gradient
        const barGrad = ctx.createLinearGradient(0, topY, 0, baseY)
        barGrad.addColorStop(0, 'rgba(255,255,255,0.12)')
        barGrad.addColorStop(0.1, `rgba(${rc},${gc},${bc},0.6)`)
        barGrad.addColorStop(0.42, `rgba(${rc},${gc},${bc},0.92)`)
        barGrad.addColorStop(0.82, `rgba(${Math.round(rc*0.7)},${Math.round(gc*0.7)},${Math.round(bc*0.7)},0.72)`)
        barGrad.addColorStop(1, `rgba(${Math.round(rc*0.4)},${Math.round(gc*0.4)},${Math.round(bc*0.4)},0.5)`)
        ctx.fillStyle = barGrad
        ctx.fillRect(x, topY, barW, barH)

        // Center light channel — light pipe through crystal
        if (barH > 8) {
          const lcW = Math.max(2, barW * 0.28)
          const lcX = x + (barW - lcW) / 2
          const lcGrad = ctx.createLinearGradient(0, topY, 0, topY + barH * 0.7)
          lcGrad.addColorStop(0, 'rgba(255,255,255,0.52)')
          lcGrad.addColorStop(0.35, 'rgba(255,255,255,0.12)')
          lcGrad.addColorStop(1, 'rgba(255,255,255,0)')
          ctx.fillStyle = lcGrad
          ctx.fillRect(lcX, topY, lcW, barH)
        }

        // Front top-edge highlight — sharp crystal rim
        if (barH > 4) {
          ctx.fillStyle = 'rgba(255,255,255,0.35)'
          ctx.fillRect(x, topY, barW, Math.min(2.5, barH / 5))
          ctx.fillStyle = 'rgba(255,255,255,0.15)'
          ctx.fillRect(x, topY + Math.min(2.5, barH / 5), barW, Math.min(1.5, barH / 8))
        }

        // Front gloss sweep — refined light wash on upper portion
        if (show3D && barH > 20) {
          ctx.save()
          ctx.globalAlpha = fadeIn(0.84) * 0.28
          const fg = ctx.createLinearGradient(x, topY, x + barW, topY)
          fg.addColorStop(0, 'rgba(255,255,255,0)')
          fg.addColorStop(0.2, 'rgba(255,255,255,0.5)')
          fg.addColorStop(0.45, 'rgba(255,255,255,0.04)')
          fg.addColorStop(1, 'rgba(255,255,255,0)')
          ctx.fillStyle = fg
          ctx.fillRect(x, topY, barW, barH * 0.55)
          ctx.restore()
        }

        // Top face — bright crystal facet
        if (show3D) {
          ctx.save()
          ctx.globalAlpha = fadeIn(0.83)
          ctx.fillStyle = `rgba(${Math.min(255,rc+100)},${Math.min(255,gc+100)},${Math.min(255,bc+100)},0.6)`
          ctx.beginPath()
          ctx.moveTo(x, topY)
          ctx.lineTo(x + depth, topY - depth * topTilt)
          ctx.lineTo(x + barW + depth, topY - depth * topTilt)
          ctx.lineTo(x + barW, topY)
          ctx.closePath()
          ctx.fill()

          // Crystal ridge — bright seam along front-top edge
          ctx.fillStyle = 'rgba(255,255,255,0.4)'
          ctx.fillRect(x + depth * 0.15, topY - depth * topTilt * 0.3, barW * 0.7, depth * topTilt * 0.3)

          // Top facet highlight spot
          ctx.fillStyle = 'rgba(255,255,255,0.18)'
          const spotW = barW * 0.3
          const spotX = x + barW * 0.5
          ctx.fillRect(spotX, topY - depth * topTilt * 0.65, spotW, depth * topTilt * 0.35)
          ctx.restore()
        }
      } else if (t.duration_sec > 0) {
        ctx.fillStyle = palette.emptyBar
        ctx.fillRect(x, baseY - 1, barW, 1)
      } else {
        ctx.fillStyle = palette.pendingBar
        ctx.fillRect(x, baseY - 2, barW, 2)
      }

      // Date label
      ctx.fillStyle = palette.dateText
      ctx.font = '9px sans-serif'
      ctx.textAlign = 'center'
      ctx.fillText(t._shortDate || '', x + barW / 2, baseY + 18)
    })
  },

  /* ==================== Pie Chart ==================== */

  _shadeColor(hex, amount) {
    const safeHex = /^#[0-9a-fA-F]{6}$/.test(hex) ? hex : '#3B82F6'
    const num = parseInt(safeHex.slice(1), 16)
    const clamp = value => Math.max(0, Math.min(255, value))
    const r = clamp((num >> 16) + amount)
    const g = clamp(((num >> 8) & 0xff) + amount)
    const b = clamp((num & 0xff) + amount)
    return `rgb(${r}, ${g}, ${b})`
  },

  _drawEllipticSector(ctx, cx, cy, radius, scaleY, startA, endA, fillStyle, strokeStyle, lineW) {
    ctx.save()
    ctx.translate(cx, cy)
    ctx.scale(1, scaleY)
    ctx.beginPath()
    ctx.moveTo(0, 0)
    ctx.arc(0, 0, radius, startA, endA)
    ctx.closePath()
    if (fillStyle) {
      ctx.fillStyle = fillStyle
      ctx.fill()
    }
    if (strokeStyle) {
      ctx.strokeStyle = strokeStyle
      ctx.lineWidth = lineW || 1
      ctx.stroke()
    }
    ctx.restore()
  },

  _getPieGeometry(rect) {
    const w = rect.width
    const h = rect.height
    // Reserve explicit side gutters for reference-style labels.  The old 25.5%
    // radius left too little horizontal room, forcing leader lines into a
    // vertical stack on one side of the pie.
    const radius = Math.min(w * 0.215, h * 0.275)
    return {
      w,
      h,
      centerX: w / 2,
      centerY: h * 0.49,
      radius,
      tilt: 0.74,
      depth: radius * 0.08,
    }
  },

  _roundRectPath(ctx, x, y, width, height, radius) {
    const r = Math.min(radius, width / 2, height / 2)
    ctx.beginPath()
    ctx.moveTo(x + r, y)
    ctx.lineTo(x + width - r, y)
    ctx.quadraticCurveTo(x + width, y, x + width, y + r)
    ctx.lineTo(x + width, y + height - r)
    ctx.quadraticCurveTo(x + width, y + height, x + width - r, y + height)
    ctx.lineTo(x + r, y + height)
    ctx.quadraticCurveTo(x, y + height, x, y + height - r)
    ctx.lineTo(x, y + r)
    ctx.quadraticCurveTo(x, y, x + r, y)
    ctx.closePath()
  },

  _buildPieLabelLayout(sectors, geometry) {
    const { w, h, centerX, centerY, radius, tilt } = geometry
    const badgeW = 54
    const badgeH = 23
    const marginX = 6
    const marginY = 8
    const gapX = 5
    const gapY = 4
    const outerRadiusX = radius + 36
    const outerRadiusY = radius * tilt + 31
    const clamp = (value, min, max) => Math.max(min, Math.min(max, value))

    const items = sectors.map((sec, index) => {
      const mid = (sec.startA + sec.endA) / 2
      const cos = Math.cos(mid)
      const sin = Math.sin(mid)
      const startX = centerX + cos * radius * 1.02
      const startY = centerY + sin * radius * tilt * 1.02
      const elbowX = centerX + cos * (radius + 9)
      const elbowY = centerY + sin * (radius * tilt + 8)

      // The badge follows the sector around an expanded ellipse.  Dense small
      // sectors are resolved along the local tangent below, rather than being
      // snapped into a left/right gutter column.
      const baseX = centerX + cos * outerRadiusX
      const baseY = centerY + sin * outerRadiusY
      const tangentLen = Math.hypot(-sin, cos * tilt) || 1
      const tangentX = -sin / tangentLen
      const tangentY = (cos * tilt) / tangentLen
      const radialLen = Math.hypot(cos, sin * tilt) || 1
      const radialX = cos / radialLen
      const radialY = (sin * tilt) / radialLen

      return {
        sec,
        index,
        mid,
        startX,
        startY,
        elbowX,
        elbowY,
        baseX,
        baseY,
        badgeCenterX: clamp(baseX, marginX + badgeW / 2, w - marginX - badgeW / 2),
        badgeCenterY: clamp(baseY, marginY + badgeH / 2, h - marginY - badgeH / 2),
        badgeW,
        badgeH,
        tangentX,
        tangentY,
        radialX,
        radialY,
      }
    })

    const overlaps = (a, b) => (
      Math.abs(a.badgeCenterX - b.badgeCenterX) < (badgeW + gapX) &&
      Math.abs(a.badgeCenterY - b.badgeCenterY) < (badgeH + gapY)
    )

    // Local 2-D collision resolution.  Push along the ellipse tangent first:
    // top clusters fan horizontally, side clusters fan vertically.  A small
    // outward component gives especially dense groups a second ring without
    // turning them into a vertical list.
    for (let pass = 0; pass < 56; pass++) {
      let changed = false
      for (let i = 0; i < items.length; i++) {
        for (let j = i + 1; j < items.length; j++) {
          const a = items[i]
          const b = items[j]
          if (!overlaps(a, b)) continue
          changed = true

          const avgMid = (a.mid + b.mid) / 2
          const tangentLen = Math.hypot(-Math.sin(avgMid), Math.cos(avgMid) * tilt) || 1
          const tx = -Math.sin(avgMid) / tangentLen
          const ty = (Math.cos(avgMid) * tilt) / tangentLen
          const order = a.mid <= b.mid ? 1 : -1

          const overlapX = (badgeW + gapX) - Math.abs(a.badgeCenterX - b.badgeCenterX)
          const overlapY = (badgeH + gapY) - Math.abs(a.badgeCenterY - b.badgeCenterY)
          const needed = Math.max(2.2, Math.min(7.5, Math.min(overlapX, overlapY) * 0.35 + 1.8))

          a.badgeCenterX -= tx * needed * order
          a.badgeCenterY -= ty * needed * order
          b.badgeCenterX += tx * needed * order
          b.badgeCenterY += ty * needed * order

          // Every third pass adds a gentle radial fan.  This is what lets a
          // run of tiny top sectors spread above the pie instead of stacking.
          if (pass % 3 === 2) {
            const outward = 1.35 + Math.min(2.4, pass * 0.035)
            a.badgeCenterX += a.radialX * outward
            a.badgeCenterY += a.radialY * outward
            b.badgeCenterX += b.radialX * outward
            b.badgeCenterY += b.radialY * outward
          }
        }
      }

      items.forEach(item => {
        // A weak tether keeps labels near their own sector after repulsion.
        item.badgeCenterX += (item.baseX - item.badgeCenterX) * 0.035
        item.badgeCenterY += (item.baseY - item.badgeCenterY) * 0.035
        item.badgeCenterX = clamp(item.badgeCenterX, marginX + badgeW / 2, w - marginX - badgeW / 2)
        item.badgeCenterY = clamp(item.badgeCenterY, marginY + badgeH / 2, h - marginY - badgeH / 2)
      })
      if (!changed) break
    }

    // Final hard-separation pass: no spring-back here.  It guarantees that
    // neighboring percentage badges remain distinct even in a very dense fan.
    for (let pass = 0; pass < 32; pass++) {
      let changed = false
      for (let i = 0; i < items.length; i++) {
        for (let j = i + 1; j < items.length; j++) {
          const a = items[i]
          const b = items[j]
          if (!overlaps(a, b)) continue
          changed = true
          const avgMid = (a.mid + b.mid) / 2
          const tangentLen = Math.hypot(-Math.sin(avgMid), Math.cos(avgMid) * tilt) || 1
          const tx = -Math.sin(avgMid) / tangentLen
          const ty = (Math.cos(avgMid) * tilt) / tangentLen
          const order = a.mid <= b.mid ? 1 : -1
          const push = 2.8
          a.badgeCenterX -= tx * push * order
          a.badgeCenterY -= ty * push * order
          b.badgeCenterX += tx * push * order
          b.badgeCenterY += ty * push * order
          if (pass % 4 === 3) {
            a.badgeCenterX += a.radialX * 1.2
            a.badgeCenterY += a.radialY * 1.2
            b.badgeCenterX += b.radialX * 1.2
            b.badgeCenterY += b.radialY * 1.2
          }
          a.badgeCenterX = clamp(a.badgeCenterX, marginX + badgeW / 2, w - marginX - badgeW / 2)
          a.badgeCenterY = clamp(a.badgeCenterY, marginY + badgeH / 2, h - marginY - badgeH / 2)
          b.badgeCenterX = clamp(b.badgeCenterX, marginX + badgeW / 2, w - marginX - badgeW / 2)
          b.badgeCenterY = clamp(b.badgeCenterY, marginY + badgeH / 2, h - marginY - badgeH / 2)
        }
      }
      if (!changed) break
    }

    return items.map(item => {
      const badgeX = item.badgeCenterX - badgeW / 2
      const badgeY = item.badgeCenterY - badgeH / 2

      // Keep a visible but compact elbow even when a badge sits almost exactly
      // on the sector's radial line.  The bend follows the label's local
      // tangent displacement, so it still reads as belonging to that sector.
      const tangentDisplacement = (item.badgeCenterX - item.baseX) * item.tangentX + (item.badgeCenterY - item.baseY) * item.tangentY
      const bendSign = Math.abs(tangentDisplacement) > 0.5
        ? (tangentDisplacement > 0 ? 1 : -1)
        : (item.index % 2 === 0 ? 1 : -1)
      const elbowX = item.elbowX + item.tangentX * 7 * bendSign
      const elbowY = item.elbowY + item.tangentY * 7 * bendSign

      // Intersect the line from the badge centre toward the elbow with the
      // badge rectangle.  The callout therefore needs only one short elbow.
      const dx = elbowX - item.badgeCenterX
      const dy = elbowY - item.badgeCenterY
      const sx = Math.abs(dx) > 1e-6 ? (badgeW / 2) / Math.abs(dx) : Infinity
      const sy = Math.abs(dy) > 1e-6 ? (badgeH / 2) / Math.abs(dy) : Infinity
      const scale = Math.min(sx, sy)
      const lineEndX = item.badgeCenterX + dx * scale
      const lineEndY = item.badgeCenterY + dy * scale

      return {
        ...item,
        badgeX,
        badgeY,
        elbowX,
        elbowY,
        lineEndX,
        lineEndY,
      }
    })
  },

  _drawPieLabels(ctx, geometry, layout, reveal, startIndex = 0, endIndex = layout ? layout.length : 0) {
    if (!layout || !layout.length || reveal <= 0) return
    const palette = this._getCanvasPalette()
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

      this._roundRectPath(ctx, item.badgeX, item.badgeY, item.badgeW, item.badgeH, 8)
      ctx.fillStyle = palette.badgeFill
      ctx.fill()
      ctx.strokeStyle = sec.color
      ctx.lineWidth = 0.8
      ctx.stroke()

      ctx.fillStyle = palette.badgeText
      ctx.font = '600 10px sans-serif'
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillText(sec.subject._durationBadgeText || '0时0分', item.badgeCenterX, item.badgeCenterY + 0.5)
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
    if (!this.data.distributionHasData) return
    const touch = (e.changedTouches && e.changedTouches[0]) || (e.touches && e.touches[0])
    const tapX = touch ? touch.clientX : e.detail && e.detail.x
    const tapY = touch ? touch.clientY : e.detail && e.detail.y
    if (typeof tapX !== 'number' || typeof tapY !== 'number') return

    const query = wx.createSelectorQuery().in(this)
    query.select('#pie-canvas').boundingClientRect(rect => {
      if (!rect || !rect.width) return
      const x = tapX - rect.left
      const y = tapY - rect.top
      const geometry = this._getPieGeometry(rect)
      const { centerX, centerY, radius, tilt } = geometry

      const dx = x - centerX
      const dy = (y - centerY) / tilt
      const dist = Math.sqrt(dx * dx + dy * dy)

      // Outside the 3D pie footprint — dismiss
      if (dist > radius) {
        if (this.data.selectedSubjectDetail) {
          this.setData({
            selectedSubjectDetail: null,
            _selectedSubject: null,
          }, () => { if (this._alive) this._renderPieChart(1) })
        }
        return
      }

      let angle = Math.atan2(dy, dx)
      if (angle < -Math.PI / 2) angle += Math.PI * 2

      const subjects = this.data.subjects
      const totalDur = subjects.reduce((sum, s) => sum + (s.duration_sec || 0), 0) || 1
      let cumulativeStart = -Math.PI / 2
      for (let subjectIndex = 0; subjectIndex < subjects.length; subjectIndex++) {
        const s = subjects[subjectIndex]
        const pct = (s.duration_sec || 0) / totalDur
        const cumulativeEnd = cumulativeStart + Math.PI * 2 * pct
        if (pct > 0 && angle >= cumulativeStart && angle < cumulativeEnd) {
          this.setData({
            selectedSubjectDetail: s,
            _selectedSubject: s.subject,
            pieTapped: true,
          }, () => {
            if (!this._alive) return
            this._renderPieChart(1)
            setTimeout(() => { if (this._alive) this.setData({ pieTapped: false }) }, 350)
          })
          return
        }
        cumulativeStart = cumulativeEnd
      }
    }).exec()
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
    const normalized = String(text || '').trim() || '0分钟'
    const parts = []
    const regex = /(\d+)|(小时|分钟|时|分)/g
    let match = null
    while ((match = regex.exec(normalized))) {
      if (match[1]) parts.push({ type: 'num', text: match[1] })
      else if (match[2]) parts.push({ type: 'unit', text: match[2] })
    }
    if (!parts.length) return [{ type: 'num', text: normalized }]
    return parts
  },

  _fmtHourMinute(sec) {
    const s = Math.max(0, sec || 0)
    const m = Math.floor(s / 60)
    const h = Math.floor(m / 60)
    const mins = m % 60
    return `${h}时${mins}分`
  },

  _fmtMin(sec) {
    const s = Math.max(0, sec || 0)
    const m = Math.floor(s / 60)
    if (m < 60) return `${m}分钟`
    return `${Math.floor(m / 60)}时${m % 60}分`
  },
}

if (typeof Page === 'function') Page(pageConfig)
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { formatDuration }
}
