const api = require('../../../utils/api')
const pomodoroTheme = require('../../../utils/pomodoro-theme')
const chinaTime = require('../utils/china-time')

const DARK_SUBJECT_COLORS = ['#3B82F6', '#F59E0B', '#10B981', '#06B6D4', '#F97316', '#2DD4BF', '#EA580C', '#8B5CF6', '#6366F1', '#EC4899']
const LIGHT_SUBJECT_COLORS = ['#2F6B4F', '#7A9B76', '#2B8C83', '#B59A38', '#C4773B', '#D96B5F', '#6685A3', '#718C45', '#B45E46', '#876F8F']
// A clearer jewel-toned palette used only by the light-mode pie chart.
// History accents and the trend chart keep their existing colors.
const LIGHT_PIE_COLORS = ['#E76F51', '#2A9D8F', '#457B9D', '#E9C46A', '#8E6BBE', '#F28482', '#6A994E', '#43AA8B', '#B56576', '#577590']
const DARK_TREND_COLORS = ['#22C55E', '#06B6D4', '#3B82F6', '#818CF8', '#A78BFA', '#D946EF']
const LIGHT_TREND_COLORS = ['#2F6B4F', '#7A9B76', '#2B8C83', '#B59A38', '#C4773B', '#D96B5F', '#6685A3']

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
    selectedDurationLabel: '今日专注',
    weekSessions: 0,
    weekDurationText: '0分钟',
    trends: [],
    subjects: [],
    history: [],
    historyTotal: 0,

    // 统计日设置（后端为权威，此处为本地展示/计算缓存）
    dayStartMinute: 0,
    dayStartTime: '00:00',
    studyDayRangeText: '统计日从 00:00 开始',
    dayStartNoteText: '专注时长按统计日边界拆分，专注次数按开始时间归属',
    // 当日无"开始"记录但有时长（跨统计日 session 归属到本日）时用于空态文案
    _crossDayBleedIn: false,

    // The only date picker lives in the pie card; the selected date also filters history.
    selectedDate: '',
    _todayDate: '',
    pieDateLabel: '今日',
    pieLoading: false,

    // pie chart detail popup
    selectedSubjectDetail: null,
    _selectedSubject: null,
    pieTapped: false,

    // Animated display values
    _dispTodaySessions: 0,
    _dispTodayDurationText: '0分钟',
    durationValueAnimating: false,
    _dispWeekSessions: 0,
    _dispWeekDurationText: '0分钟',
  },

  onLoad() {
    this._alive = true
    this._isVisible = false
    this._requestId = 0
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
    const themeMode = pomodoroTheme.getTheme()
    pomodoroTheme.applyNativeTheme(themeMode)
    // 先用默认 day_start=0 计算当前中国统计日，settings 加载后若 day_start 不同会校正。
    const today = chinaTime.getChinaStudyDate(0)
    this.setData({
      selectedDate: today,
      _todayDate: today,
      pieDateLabel: '今日',
      themeMode,
    })
    this._init()
  },

  async _init() {
    await this._ensureSettings()
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
      }
      if (today !== prevToday) patch._todayDate = today
      // 用户停留在旧"今天"或原选中日期超过新最大日期时，跟随新的 today
      if (!this.data.selectedDate || this.data.selectedDate === prevToday || this.data.selectedDate > today) {
        patch.selectedDate = today
        patch.pieDateLabel = '今日'
        patch.selectedDurationLabel = '今日专注'
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
      patch.selectedDurationLabel = '今日专注'
      changedToday = true
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
  },

  onReady() {
    this._viewReady = true
    this._isVisible = true
    this._requestId++
    this.loadData()
    const warmCanvases = () => {
      if (!this._alive || !this._isVisible) return
      this._initCanvases(() => {})
    }
    if (wx.nextTick) wx.nextTick(warmCanvases)
    else setTimeout(warmCanvases, 0)
  },

  onHide() {
    this._isVisible = false
    this._cancelDurationAnimation(false)
    this._cancelDeferredHistory(true)
  },

  onUnload() {
    this._alive = false
    this._isVisible = false
    this._cancelPendingWork()
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
      wx.nextTick(() => {
        if (!this._alive || !this._isVisible) return
        this._renderTrendBars(1)
        this._renderPieChart(1, true)
      })
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
    return dateLabel === '今日' ? '今日专注' : `${dateLabel}专注`
  },

  _buildSubjectItems(subjects) {
    const subjArr = Array.isArray(subjects) ? subjects : []
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
        _pct: pct,
        _pctText: (pct * 100).toFixed(1) + '%',
      }
    })
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
        _dispTodayDurationText: targetText,
        durationValueAnimating: false,
      })
      return
    }

    // Keep the selected-day count and duration on one transition clock. Sparse
    // setData ticks leave the canvas animation enough main-thread time.
    const duration = 960
    const steps = 15
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
          _dispTodayDurationText: nextText,
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

  async loadData() {
    await this._ensureSettings()
    if (!this._alive) return
    const reqId = this._requestId
    const requestedDate = this.data.selectedDate
    this._dateRequestSeq = (this._dateRequestSeq || 0) + 1
    const dateSeq = this._dateRequestSeq
    if (this._hasData) this._cancelDeferredHistory(true)
    this.setData({ loading: true, errorText: '' })
    const viewingToday = !requestedDate || requestedDate === this.data._todayDate
    try {
      const [stats, trends, summary, historyRes] = await Promise.all([
        api.get('/pomodoro/stats'),
        api.get('/pomodoro/trends', { days: 7 }),
        // 查看"今日"时不传 date，由后端返回权威当前学习日；查看历史日期才显式传
        api.get('/pomodoro/daily-summary', viewingToday ? {} : { date: requestedDate }),
        api.get('/pomodoro/history', { page: 1, page_size: 20, date: requestedDate }),
      ])
      if (
        !this._alive ||
        reqId !== this._requestId ||
        dateSeq !== this._dateRequestSeq ||
        requestedDate !== this.data.selectedDate
      ) return

      // 以后端为准校正"今日"（settings 失败 / 设备时钟偏差兜底）
      const reconciled = this._reconcileFromServer(stats, viewingToday ? summary : null)
      if (!this._alive || reqId !== this._requestId || dateSeq !== this._dateRequestSeq) return

      const effectiveDate = this.data.selectedDate
      let effectiveHistory = historyRes
      // 校正后"今日"变化且原先请求的是旧"今日" → 用权威日期重取 history
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
      // 统计口径由后端 daily-summary 提供，前端不再拉全量 history 自算。
      const subjectBreakdown = (summary && summary.subjects) || []
      const selectedDurationSec = Number(summary && summary.duration_sec) || 0
      const selectedSessionCount = Number(summary && summary.sessions) || 0
      // 跨统计日渗透：daily-summary 中 duration>0 但 sessions==0 的科目切片即来自
      // 前一日开始、本日结束的 session —— 时长计入本日但 history（按开始日）无对应行。
      // 用它作为提示信号，比"本日无 session"更准（本日有其他 session 时同样成立）。
      const hasBleedInSubjects = (subjectBreakdown || []).some(
        s => Number(s.duration_sec) > 0 && Number(s.sessions) === 0
      )
      // Both values in the main overview card follow the same selected-date
      // records used by the pie chart and recent-history list.
      this._rawTodayDur = selectedDurationSec
      this._rawWeekDur = stats.week_duration_sec || 0
      this._resetPieCache()

      const willAnimate = !this._hasData
      const recentSessions = daySessions
      this._hasData = true
      this._cancelDurationAnimation(false)
      this._displayTodayDurationSec = willAnimate ? 0 : selectedDurationSec

      const historyPatch = willAnimate
        ? {
            history: [],
            historyTotal: effectiveHistory.total || 0,
            historyReady: false,
          }
        : {
            history: recentSessions.map(item => this._formatSession(item)),
            historyTotal: effectiveHistory.total || 0,
            historyReady: true,
          }

      this.setData({
        todaySessions: selectedSessionCount,
        todayDurationText: this._fmtMin(selectedDurationSec),
        selectedDurationLabel: this._formatSelectedDurationLabel(effectiveDate),
        weekSessions: stats.week_sessions || 0,
        weekDurationText: this._fmtMin(stats.week_duration_sec || 0),
        trends: (trends || []).map(t => ({
          date: t.date,
          duration_sec: t.duration_sec,
          _shortDate: (t.date || '').slice(5),
        })),
        subjects: this._buildSubjectItems(subjectBreakdown),
        pieDateLabel: this._formatPieDateLabel(effectiveDate),
        _crossDayBleedIn: hasBleedInSubjects,
        pieLoading: false,
        loading: false,
        contentReady: true,
        errorText: '',
        _dispTodaySessions: willAnimate ? 0 : selectedSessionCount,
        _dispTodayDurationText: willAnimate ? '0分钟' : this._fmtMin(selectedDurationSec),
        durationValueAnimating: willAnimate,
        _dispWeekSessions: willAnimate ? 0 : (stats.week_sessions || 0),
        _dispWeekDurationText: willAnimate ? '0分钟' : this._fmtMin(stats.week_duration_sec || 0),
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
        this._initCanvases(() => {
          if (!this._alive || !this._isVisible) return
          if (willAnimate) {
            this._renderPieChart(0, false)
            this._renderTrendBars(0)
            const node = this._pieCanvasNode
            const raf = node && node.requestAnimationFrame
              ? cb => node.requestAnimationFrame(cb)
              : cb => setTimeout(cb, 16)
            const animReqId = this._requestId
            raf(() => raf(() => this._startAnimations(animReqId)))
          } else {
            this._renderPieChart(1)
            this._renderTrendBars(1)
          }
        })
      })
    } catch (e) {
      if (
        !this._alive ||
        reqId !== this._requestId ||
        dateSeq !== this._dateRequestSeq ||
        requestedDate !== this.data.selectedDate
      ) return
      console.error('加载统计失败', e)
      this.setData({ loading: false, pieLoading: false, errorText: '加载失败，请检查网络后重试' })
    }
  },

  _formatSession(s) {
    // 统一按中国时间（UTC+8）格式化，不依赖设备时区
    const timeStr = chinaTime.formatChinaTimeHM(s.start_time)
    const dateStr = chinaTime.formatChinaMonthDay(s.start_time)
    const durSec = s.actual_duration ?? s.actual_duration_sec ?? s.duration_sec ?? 0
    const subjectName = s.subject_name || '未分类'
    const subjectKey = s.subject_code || ''
    const isFree = s.preset === 'free'
    const durationText = formatDuration(durSec)
    return {
      ...s,
      _time: timeStr,
      _date: dateStr,
      _duration: durationText,
      _subjectLabel: isFree ? '自由计时 · ' + subjectName : subjectName,
      _color: getSubjectColor(s.subject_id != null ? String(s.subject_id) : (subjectKey || subjectName), this.data.themeMode),
      _statusLabel: s.status === 'completed' ? '完成' : '中断',
      _statusClass: s.status === 'completed' ? 'status-done' : 'status-interrupt',
    }
  },

  onDateChange(e) {
    const date = e && e.detail ? e.detail.value : ''
    if (!date || date === this.data.selectedDate) return
    this._cancelDeferredHistory(true)
    this.setData({
      selectedDate: date,
      pieDateLabel: this._formatPieDateLabel(date),
      selectedDurationLabel: this._formatSelectedDurationLabel(date),
      selectedSubjectDetail: null,
      _selectedSubject: null,
    }, () => this.loadDateData(date))
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
    this._cancelDeferredHistory(true)
    this.setData({
      selectedDate: today,
      pieDateLabel: '今日',
      selectedDurationLabel: '今日专注',
      selectedSubjectDetail: null,
      _selectedSubject: null,
    }, () => this.loadDateData(today))
  },

  async loadDateData(date) {
    const requestDate = String(date || '').trim()
    if (!requestDate) return
    this._dateRequestSeq = (this._dateRequestSeq || 0) + 1
    const seq = this._dateRequestSeq
    this.setData({ pieLoading: true })
    const viewingToday = requestDate === this.data._todayDate
    try {
      const [summary, historyRes] = await Promise.all([
        // 查看"今日"时不传 date，由后端返回权威当前学习日
        api.get('/pomodoro/daily-summary', viewingToday ? {} : { date: requestDate }),
        api.get('/pomodoro/history', { page: 1, page_size: 20, date: requestDate }),
      ])
      if (
        !this._alive ||
        !this._isVisible ||
        seq !== this._dateRequestSeq ||
        requestDate !== this.data.selectedDate
      ) return

      // 查看"今日"时以后端返回的 date 校正"今日"（settings 失败 / 时钟偏差兜底）
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
      const hasBleedInSubjects = (subjectBreakdown || []).some(
        s => Number(s.duration_sec) > 0 && Number(s.sessions) === 0
      )
      const previousDurationSec = Number.isFinite(this._displayTodayDurationSec)
        ? this._displayTodayDurationSec
        : (Number(this._rawTodayDur) || 0)
      const previousSessionCount = Math.max(0, Number(this.data._dispTodaySessions) || 0)
      this._rawTodayDur = selectedDurationSec
      this._resetPieCache()
      this.setData({
        todaySessions: selectedSessionCount,
        subjects: this._buildSubjectItems(subjectBreakdown),
        todayDurationText: this._fmtMin(selectedDurationSec),
        selectedDurationLabel: this._formatSelectedDurationLabel(effectiveDate),
        history: daySessions.slice(0, 20).map(item => this._formatSession(item)),
        historyTotal: (effectiveHistory && effectiveHistory.total) || 0,
        historyReady: true,
        pieDateLabel: this._formatPieDateLabel(effectiveDate),
        _crossDayBleedIn: hasBleedInSubjects,
        pieLoading: false,
        selectedSubjectDetail: null,
        _selectedSubject: null,
      }, () => {
        if (!this._alive || !this._isVisible || seq !== this._dateRequestSeq) return
        this._animateSelectedDuration(previousDurationSec, selectedDurationSec, previousSessionCount, selectedSessionCount)
        if (this._pieCtx && this._pieRect) {
          this._animatePieOnly()
        } else {
          this._initCanvases(() => this._animatePieOnly())
        }
      })
    } catch (e) {
      if (!this._alive || !this._isVisible || seq !== this._dateRequestSeq) return
      console.error('加载指定日期数据失败', e)
      this.setData({ pieLoading: false })
      wx.showToast({ title: '该日期数据加载失败', icon: 'none' })
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
    this._rafId = null
    this._pieDateRafId = null
    this._pieLabelRafId = null
    this._pieAnimationToken = (this._pieAnimationToken || 0) + 1
    this._pieLabelToken = (this._pieLabelToken || 0) + 1
    if (this._animTimer) {
      clearTimeout(this._animTimer)
      this._animTimer = null
    }
  },

  _initCanvases(callback) {
    const doneCallback = typeof callback === 'function' ? callback : () => {}
    if (
      this._pieCanvasNode && this._pieCtx && this._pieRect &&
      this._trendCanvasNode && this._trendCtx && this._trendBarsRect
    ) {
      doneCallback()
      return
    }
    if (this._canvasInitPending) {
      this._canvasInitCallbacks.push(doneCallback)
      return
    }
    this._canvasInitPending = true
    this._canvasInitCallbacks = [doneCallback]
    let pending = 2
    const done = () => {
      if (--pending !== 0) return
      this._canvasInitPending = false
      const callbacks = this._canvasInitCallbacks.slice()
      this._canvasInitCallbacks.length = 0
      callbacks.forEach(cb => cb())
    }
    // Cap DPR at 2 — backbuffer cost grows quadratically and DPR=3 on iPhones
    // produces ~56% more pixel-fill work for negligible visual gain on a 250px pie.
    const windowInfo = wx.getWindowInfo ? wx.getWindowInfo() : {}
    const rawDpr = windowInfo.pixelRatio || 2
    const dpr = Math.min(2, rawDpr)

    const setup = (selector, nodeKey, ctxKey, rectKey) => {
      wx.createSelectorQuery().in(this)
        .select(selector)
        .fields({ node: true, size: true })
        .exec(res => {
          if (!this._alive) { done(); return }
          if (!res || !res[0] || !res[0].node) { done(); return }
          const node = res[0].node
          const ctx = node.getContext('2d')
          const w = res[0].width
          const h = res[0].height
          node.width = Math.round(w * dpr)
          node.height = Math.round(h * dpr)
          ctx.scale(dpr, dpr)
          this[nodeKey] = node
          this[ctxKey] = ctx
          this[rectKey] = { width: w, height: h }
          done()
        })
    }

    setup('#pie-canvas', '_pieCanvasNode', '_pieCtx', '_pieRect')
    setup('#trend-bars-canvas', '_trendCanvasNode', '_trendCtx', '_trendBarsRect')
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
    if (!this._alive || !this._isVisible || reqId !== this._requestId) return
    this._animActive = true
    this._finalDrawn = false
    this._pieLabelToken = (this._pieLabelToken || 0) + 1
    const pieAnimDuration = 1100
    const trendAnimDuration = 700
    const animDuration = Math.max(pieAnimDuration, trendAnimDuration)
    const startTime = Date.now()

    // Finish number updates before the two canvas charts reach their final
    // frames, so setData/layout work never competes with the heaviest draws.
    const tSessions = this.data.todaySessions
    const wSessions = this.data.weekSessions
    const numberDuration = 520
    const totalSteps = 9
    let step = 0
    const numTick = () => {
      if (!this._animActive || !this._alive || !this._isVisible || reqId !== this._requestId) return
      step++
      const p = Math.min(1, step / totalSteps)
      const e = this._easeOutCubic(p)
      const displayDurationSec = Math.round(this._rawTodayDur * e)
      this._displayTodayDurationSec = displayDurationSec
      this.setData({
        _dispTodaySessions: Math.round(tSessions * e),
        _dispTodayDurationText: this._fmtMin(displayDurationSec),
        durationValueAnimating: p < 1,
        _dispWeekSessions: Math.round(wSessions * e),
        _dispWeekDurationText: this._fmtMin(Math.round(this._rawWeekDur * e)),
      })
      if (step < totalSteps) {
        this._animTimer = setTimeout(numTick, Math.round(numberDuration / totalSteps))
      } else {
        this._animTimer = null
      }
    }
    numTick()

    // Canvas animation — RAF only, no setData
    const node = this._pieCanvasNode
    const raf = node && node.requestAnimationFrame
      ? cb => node.requestAnimationFrame(cb)
      : cb => setTimeout(cb, 16)

    let lastPieDraw = -Infinity
    let lastTrendDraw = -Infinity
    const tick = () => {
      if (!this._animActive || !this._alive || !this._isVisible || reqId !== this._requestId) return
      const elapsed = Date.now() - startTime
      const rawP = Math.min(1, elapsed / animDuration)
      const pieProgress = this._easeInOutCubic(Math.min(1, elapsed / pieAnimDuration))
      const trendProgress = this._easeOutCubic(Math.min(1, elapsed / trendAnimDuration))

      if (rawP < 1) {
        // Draw at most one canvas per RAF.  Previously both charts often
        // repainted in the same final frames, producing a visible hitch.
        const pieLag = elapsed - lastPieDraw
        const trendLag = elapsed - lastTrendDraw
        const pieDue = pieLag >= 28
        const trendDue = trendLag >= 42
        if (pieDue && (!trendDue || pieLag >= trendLag)) {
          lastPieDraw = elapsed
          this._renderPieChart(pieProgress, false)
        } else if (trendDue) {
          lastTrendDraw = elapsed
          this._renderTrendBars(trendProgress)
        }
        this._rafId = raf(tick)
      } else if (!this._finalDrawn) {
        this._finalDrawn = true
        this._animActive = false
        // Stagger final chart frames and then paint percentage labels in small
        // batches.  Data remains dynamic, but no single frame carries all work.
        this._renderPieChart(1, false)
        this._rafId = raf(() => {
          if (!this._alive || !this._isVisible || reqId !== this._requestId) return
          this._renderTrendBars(1)
          this._rafId = raf(() => {
            if (!this._alive || !this._isVisible || reqId !== this._requestId) return
            this._rafId = null
            this._revealPieLabelsIncrementally()
          })
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
    const maxDur = Math.max(1, ...trends.map(t => t.duration_sec || 0))
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
    const radius = Math.min(w * 0.255, h * 0.3)
    return {
      w,
      h,
      centerX: w / 2,
      centerY: h * 0.44,
      radius,
      tilt: 0.72,
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
    const { w, h, centerY, radius, tilt } = geometry
    const minY = 24
    const maxY = h - 28
    const left = []
    const right = []

    sectors.forEach(sec => {
      const mid = (sec.startA + sec.endA) / 2
      const item = {
        sec,
        mid,
        side: Math.cos(mid) >= 0 ? 'right' : 'left',
        rawY: centerY + Math.sin(mid) * radius * tilt * 1.14,
      }
      ;(item.side === 'right' ? right : left).push(item)
    })

    const distribute = items => {
      if (!items.length) return
      items.sort((a, b) => a.rawY - b.rawY)
      const gap = items.length > 1
        ? Math.max(19, Math.min(25, (maxY - minY) / (items.length - 1)))
        : 0
      items[0].labelY = Math.max(minY, items[0].rawY)
      for (let i = 1; i < items.length; i++) {
        items[i].labelY = Math.max(items[i].rawY, items[i - 1].labelY + gap)
      }
      if (items[items.length - 1].labelY > maxY) {
        items[items.length - 1].labelY = maxY
        for (let i = items.length - 2; i >= 0; i--) {
          items[i].labelY = Math.min(items[i].labelY, items[i + 1].labelY - gap)
        }
      }
      if (items[0].labelY < minY) {
        const shift = minY - items[0].labelY
        items.forEach(item => { item.labelY += shift })
      }
    }

    distribute(left)
    distribute(right)

    return left.concat(right).map(item => ({
      ...item,
      badgeX: item.side === 'right' ? w - 57 : 7,
      badgeW: 50,
      badgeH: 23,
    }))
  },

  _drawPieLabels(ctx, geometry, layout, reveal, startIndex = 0, endIndex = layout ? layout.length : 0) {
    if (!layout || !layout.length || reveal <= 0) return
    const { centerX, centerY, radius, tilt } = geometry
    const palette = this._getCanvasPalette()
    ctx.save()
    ctx.globalAlpha = Math.max(0, Math.min(1, reveal))
    ctx.lineCap = 'round'
    ctx.lineJoin = 'round'

    for (let i = startIndex; i < Math.min(endIndex, layout.length); i++) {
      const item = layout[i]
      const sec = item.sec
      const startX = centerX + Math.cos(item.mid) * radius * 1.02
      const startY = centerY + Math.sin(item.mid) * radius * tilt * 1.02
      const elbowX = item.side === 'right'
        ? centerX + radius + 13
        : centerX - radius - 13
      const lineEndX = item.side === 'right' ? item.badgeX : item.badgeX + item.badgeW
      const lineY = item.labelY

      ctx.strokeStyle = sec.color
      ctx.lineWidth = 1.15
      ctx.beginPath()
      ctx.moveTo(startX, startY)
      ctx.lineTo(elbowX, lineY)
      ctx.lineTo(lineEndX, lineY)
      ctx.stroke()

      ctx.fillStyle = sec.color
      ctx.beginPath()
      ctx.arc(startX, startY, 2.1, 0, Math.PI * 2)
      ctx.fill()

      const badgeY = lineY - item.badgeH / 2
      this._roundRectPath(ctx, item.badgeX, badgeY, item.badgeW, item.badgeH, 8)
      ctx.fillStyle = palette.badgeFill
      ctx.fill()
      ctx.strokeStyle = sec.color
      ctx.lineWidth = 0.8
      ctx.stroke()

      ctx.fillStyle = palette.badgeText
      ctx.font = '600 10px sans-serif'
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillText(sec.subject._pctText || '0%', item.badgeX + item.badgeW / 2, lineY + 0.5)
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
    if (!hasData) {
      this._drawEllipticSector(
        ctx, centerX, centerY, radius, tilt, 0, Math.PI * 2,
        palette.emptyPieFill, palette.emptyPieStroke, 1
      )
      ctx.fillStyle = palette.emptyPieText
      ctx.font = '12px sans-serif'
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillText(`${this.data.pieDateLabel || '该日'}暂无数据`, centerX, centerY + 5)
      return
    }

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

    // 7. Every sector gets a leader line and percentage badge.
    if (includeLabels) {
      this._drawPieLabels(ctx, geometry, this._pieLabelLayout, labelReveal)
    }
  },

  /* ==================== Touch Interactions ==================== */

  onPieTap(e) {
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
      for (const s of subjects) {
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
