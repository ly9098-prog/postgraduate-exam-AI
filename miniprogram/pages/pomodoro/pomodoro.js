const api = require('../../utils/api')
const config = require('../../config')
const { safeDecodeURIComponent } = require('../../utils/route-params')
const pomodoroTheme = require('../../utils/pomodoro-theme')

const PHASE = { IDLE: 'idle', RUNNING: 'running', BREAK: 'break', CEREMONY: 'ceremony' }

const SUBJECT_EMOJI = {
  // New codes
  'exam408-ds': '📃',
  'exam408-co': '💻',
  'exam408-os': '⚙️',
  'exam408-cn': '🌐',
  'math2-calculus': '📐',
  'math2-linalg': '📏',
  english: '📖',
  pol: '📜',
  math2: '📐',
  exam408: '📚',
  // Legacy codes (backward compat)
  data_structure: '📃',
  computer_organization: '💻',
  operating_system: '⚙️',
  computer_network: '🌐',
  math: '📐',
  advanced_math: '📐',
  linear_algebra: '📏',
  politics: '📜',
}

const PRESETS = [
  { key: 'standard', label: '标准', work: 25, break: 5 },
  { key: 'long', label: '长时间', work: 50, break: 10 },
  { key: 'custom', label: '自定义', work: 25, break: 5 },
  { key: 'free', label: '自由计时', work: 0, break: 0 },
]

const FREE_TIMER_MAX_MS = 5 * 60 * 60 * 1000 // 5 hours max for free timer

function parseServerTime(value) {
  if (!value) return NaN
  if (typeof value === 'number') return value
  const s = String(value).trim()
  if (!s) return NaN
  const hasTimezone = /Z$|[+-]\d{2}:?\d{2}$/.test(s)
  return new Date(hasTimezone ? s : s + '+00:00').getTime()
}

const MOTTOES = [
  '击败了昨天的自己',
  '每一步都算数',
  '坚持就是胜利',
  '离上岸又近一步',
  '今天的你比昨天更强',
  '积少成多，聚沙成塔',
  '专注是最好的努力',
  '为梦想全力以赴',
]

function flattenSubjectTree(tree) {
  const result = []
  function walk(nodes) {
    for (const node of nodes) {
      if (!node) continue
      const activeChildren = (node.children || []).filter(c => c.is_active !== false)
      if (activeChildren.length === 0) {
        result.push({
          id: node.subject_id,
          code: node.subject_code || '',
          name: node.subject_name || node.display_name || '',
        })
      } else {
        walk(activeChildren)
      }
    }
  }
  walk(tree || [])
  return result
}

function subjectEmojiByCode(code) {
  return SUBJECT_EMOJI[code] || '📚'
}

function formatElapsedSec(sec) {
  const s = Math.max(0, sec || 0)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const secs = s % 60
  return {
    display: `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(secs).padStart(2, '0')}`,
    friendly: h > 0
      ? `${h}小时${String(m).padStart(2, '0')}分${String(secs).padStart(2, '0')}秒`
      : m > 0
        ? `${m}分${String(secs).padStart(2, '0')}秒`
        : `${secs}秒`,
  }
}

Page({
  data: {
    phase: PHASE.IDLE,
    subjects: [],
    subjectsLoading: true,
    subjectsError: '',
    selectedSubjectId: null,
    selectedSubject: null,
    presets: PRESETS,
    selectedPreset: 'standard',
    workDuration: 25,
    breakDuration: 5,
    showCustom: false,
    isPaused: false,

    // free timer fields
    isFreeTimer: false,
    freeDisplayTime: '00:00:00',
    showEndConfirm: false,
    endConfirmTheme: '',
    endConfirmTitle: '',
    endConfirmText: '',
    endConfirmOkText: '确认结束',
    endConfirmCancelText: '继续计时',
    actionLoading: false,

    // timer display
    displayMin: '00',
    displaySec: '00',

    // today stats
    todaySessions: 0,
    todayDurationText: '0分钟',

    // practice page context
    fromSubjectId: null,
    fromChapterId: '',
    fromChapterName: '',

    // font size accessibility
    fontSizeLevel: 'medium',

    // shared light/dark theme (default light, stored per local user)
    themeMode: 'light',
    themeSwitching: false,
    sliderBlockColor: '#153323',
    sliderTrackColor: 'rgba(21,51,35,0.12)',
    celebrationTheme: 'light',

    // new features
    examDays: 0,
    showCelebration: false,
    celebrationMotto: '',
    celebrationType: 'excellent',
    pageEntered: false,
    debugMode: false,
    ringCanvasVisible: true,
    selectedSubjectLabel: '',
    selectedSubjectEmoji: '📚',
    selectedPresetLabel: '',
  },

  _timer: null,
  _freeTimerId: null,
  _freeTimerFinalizing: false,
  _touchStartX: 0,
  _pageVisible: false,
  _debugTapCount: 0,
  _debugTapTimer: null,
  _countdownEndAt: 0,
  _countdownTotalSec: 0,
  _countdownRemainingSnapshot: null,
  _confirmTimerSnapshot: null,
  _lastDrawnProgress: undefined,
  _lastDrawnIsBreak: undefined,
  _ringCache: null,

  /* ==================== Lifecycle ==================== */

  _createTimerState() {
    return {
      sessionId: null,
      sessionStartTime: null,
      breakStartTime: null,
      totalPausedMs: 0,
      pauseStartTime: null,
      elapsedSec: 0,
      remainingSec: 0,
      endConfirmMode: '',
      freeFriendlyText: '',
      freeDisplayOffsetMs: 0,
      progress: 1,
      todayDurationSec: 0,
    }
  },

  onLoad(opts) {
    this._timerState = this._createTimerState()
    const themeMode = pomodoroTheme.getTheme()
    pomodoroTheme.applyNativeTheme(themeMode)
    this.setData({
      examDays: this._getExamDays(),
      fontSizeLevel: wx.getStorageSync('pomodoro_font_size') || 'medium',
      ...this._getThemeViewModel(themeMode),
    })
    this._loadSubjects()

    if (opts.subject_id) {
      this.setData({ fromSubjectId: Number(opts.subject_id) })
    }
    if (opts.chapterId) this.setData({ fromChapterId: opts.chapterId })
    if (opts.chapterName) this.setData({ fromChapterName: safeDecodeURIComponent(opts.chapterName, '') })
  },

  async onShow() {
    this._pageVisible = true
    this._syncThemeFromStorage()

    // Completion flag — check before active fetch since it may short-circuit
    const completionFlag = wx.getStorageSync('pomodoro_completion')
    if (completionFlag) {
      if (!completionFlag.sessionId) {
        wx.removeStorageSync('pomodoro_completion')
      } else if (!this.data.showCelebration) {
        wx.vibrateLong()
        this.setData({ showCelebration: true, celebrationMotto: completionFlag.motto, celebrationType: completionFlag.type || 'excellent' })
        return
      } else {
        wx.removeStorageSync('pomodoro_completion')
      }
    }

    // Navigation guard: returning from pomodoro-stats — don't restore stale snapshot
    if (this._navigatingToStats) {
      this._navigatingToStats = false
      wx.removeStorageSync('pomodoro_confirm_pause')
      this._confirmTimerSnapshot = null
      this._timerState.endConfirmMode = ''
      this.setData({ showEndConfirm: false })
    } else {
      // Validate and optionally restore confirm snapshot
      const confirmSnapshot = this._confirmTimerSnapshot || wx.getStorageSync('pomodoro_confirm_pause')
      if (confirmSnapshot && confirmSnapshot.sessionId) {
        if (this._isValidConfirmSnapshot(confirmSnapshot)) {
      this._confirmTimerSnapshot = confirmSnapshot

      if (confirmSnapshot.mode === 'free-complete') {
        const fmt = formatElapsedSec(confirmSnapshot.elapsedSec || 0)
        this._timerState.sessionId = confirmSnapshot.sessionId
        this._timerState.sessionStartTime = confirmSnapshot.sessionStartTime || this._timerState.sessionStartTime
        this._timerState.endConfirmMode = 'free-complete'
        this._timerState.elapsedSec = confirmSnapshot.elapsedSec || 0
        this._timerState.freeFriendlyText = fmt.friendly
        this._timerState.totalPausedMs = confirmSnapshot.totalPausedMs || 0
        this._timerState.freeDisplayOffsetMs = Number(confirmSnapshot.freeDisplayOffsetMs || 0)
        this.setData({
          ...this._buildEndConfirmViewModel('free-complete', confirmSnapshot),
          phase: PHASE.RUNNING,
          isFreeTimer: true,
          isPaused: true,
          ringCanvasVisible: true,
          freeDisplayTime: fmt.display,
        })
        if (confirmSnapshot.pausedByConfirm && !confirmSnapshot.backendPauseDone) {
          api.post('/pomodoro/' + confirmSnapshot.sessionId + '/pause', {})
            .then(server => {
              confirmSnapshot.totalPausedMs = (server.total_paused_sec || 0) * 1000
              confirmSnapshot.backendPauseDone = true
              wx.setStorageSync('pomodoro_confirm_pause', confirmSnapshot)
            })
            .catch(() => {})
        }
        setTimeout(() => this.loadTodayStats(), 200)
        return
      }

      const fmt = this._formatCountdownDisplay(confirmSnapshot.remainingSec)
      this._timerState.sessionId = confirmSnapshot.sessionId
      this._timerState.sessionStartTime = confirmSnapshot.sessionStartTime || this._timerState.sessionStartTime
      this._timerState.endConfirmMode = 'countdown-interrupt'
      this._timerState.remainingSec = confirmSnapshot.remainingSec
      this._timerState.progress = confirmSnapshot.progress
      this._timerState.totalPausedMs = confirmSnapshot.totalPausedMs || 0
      this.setData({
        ...this._buildEndConfirmViewModel('countdown-interrupt', confirmSnapshot),
        phase: confirmSnapshot.phase || PHASE.RUNNING,
        isPaused: true,
        ringCanvasVisible: true,
        displayMin: fmt.min,
        displaySec: fmt.sec,
      })
      wx.nextTick(() => {
        this._initCanvas(true)
        this.drawRing(confirmSnapshot.totalSec, confirmSnapshot.phase === 'break')
      })
      // If backend pause wasn't done, try now (fire-and-forget)
      if (confirmSnapshot.pausedByConfirm && !confirmSnapshot.backendPauseDone) {
        api.post('/pomodoro/' + confirmSnapshot.sessionId + '/pause', {})
          .then(server => {
            confirmSnapshot.totalPausedMs = (server.total_paused_sec || 0) * 1000
            confirmSnapshot.backendPauseDone = true
            wx.setStorageSync('pomodoro_confirm_pause', confirmSnapshot)
          })
          .catch(() => {})
      }
      setTimeout(() => this.loadTodayStats(), 200)
      return
    }
      // Snapshot exists but is invalid — clean up stale data
      wx.removeStorageSync('pomodoro_confirm_pause')
      this._confirmTimerSnapshot = null
      this._timerState.endConfirmMode = ''
      this.setData({ showEndConfirm: false })
    }
    }

    const active = await this._fetchActiveSession()
    if (active) {
      if (this._canLightSyncActive(active)) {
        this._syncActiveSessionLight(active)
      } else {
        this._restoreSession(active)
      }
    } else if (this.data.phase !== PHASE.RUNNING) {
      this._restoreBreak()
    }

    // Deferred: stats don't block active session recovery
    setTimeout(() => this.loadTodayStats(), 200)

    // Don't re-trigger entrance animation if already entered
    if (!this.data.pageEntered) {
      setTimeout(() => this.setData({ pageEntered: true }), 50)
    }
  },

  onHide() {
    this._pageVisible = false

    // Persist confirm snapshot before it's lost
    if (this.data.showEndConfirm && this._confirmTimerSnapshot) {
      wx.setStorageSync('pomodoro_confirm_pause', this._confirmTimerSnapshot)
    }

    if (this.data.phase === PHASE.RUNNING && this._timerState.sessionId) {
      wx.setStorageSync('pomodoro_running_state', {
        sessionStartTime: this._timerState.sessionStartTime,
        workDuration: this.data.workDuration,
        breakDuration: this.data.breakDuration,
        selectedPreset: this.data.selectedPreset,
        selectedSubjectId: this.data.selectedSubjectId,
        selectedSubjectCode: this.data.selectedSubject ? this.data.selectedSubject.code : '',
        selectedSubjectName: this.data.selectedSubject ? this.data.selectedSubject.name : '',
        isPaused: this.data.isPaused,
        totalPausedMs: this._timerState.totalPausedMs,
        pauseStartTime: this.data.isPaused ? (this._timerState.pauseStartTime || Date.now()) : null,
        sessionId: this._timerState.sessionId,
        isFreeTimer: this.data.isFreeTimer,
        elapsedSec: this._timerState.elapsedSec,
        freeDisplayOffsetMs: this._timerState.freeDisplayOffsetMs || 0,
        savedAt: Date.now(),
      })
    }
    // Single cleanup call — _clearTimer already clears free interval too
    this._clearTimer()
  },

  onUnload() {
    this._clearTimer()
    if (this._themeSwitchTimer) {
      clearTimeout(this._themeSwitchTimer)
      this._themeSwitchTimer = null
    }
    wx.setNavigationBarColor({
      frontColor: '#ffffff',
      backgroundColor: '#4F7FFF',
    })
    try {
      if (wx.setBackgroundColor) {
        wx.setBackgroundColor({
          backgroundColor: '#F4F4EE',
          backgroundColorTop: '#F4F4EE',
          backgroundColorBottom: '#F4F4EE',
        })
      }
      if (wx.setBackgroundTextStyle) wx.setBackgroundTextStyle({ textStyle: 'dark' })
    } catch (_) {}
  },

  /* ==================== Subject Loading ==================== */

  async _loadSubjects() {
    this.setData({ subjectsLoading: true, subjectsError: '' })
    try {
      const tree = await api.get('/practice/subjects')
      if (!tree || !Array.isArray(tree)) {
        throw new Error('科目数据格式错误')
      }
      const flat = flattenSubjectTree(tree).map(s => ({
        ...s,
        _emoji: subjectEmojiByCode(s.code),
      }))
      this.setData({ subjects: flat, subjectsLoading: false, subjectsError: '' })
      // 旧版 pomodoro_running_state 缓存可能只带 subject_code，用已加载列表迁移到 subject_id
      this._migrateRunningStateCache(flat)

      // If coming from practice page with a subject_id, auto-select
      if (this.data.fromSubjectId) {
        const match = flat.find(s => s.id === this.data.fromSubjectId)
        if (match) {
          this.setData({ selectedSubjectId: match.id, selectedSubject: match })
          this._updateComputedFields()
        }
      }
      // 恢复的旧会话可能只有 subject_code（无 subject_id），用已加载列表回填
      const restored = this.data.selectedSubject
      if (restored && !restored.id && restored.code) {
        const match = flat.find(s => s.code === restored.code)
        if (match) {
          this.setData({ selectedSubjectId: match.id, selectedSubject: match })
          this._updateComputedFields()
        }
      }
    } catch (e) {
      console.error('加载科目失败', e)
      this.setData({ subjectsLoading: false, subjectsError: '科目加载失败，请稍后重试' })
    }
  },

  _lookupSubjectIdByCode(code) {
    if (!code) return null
    const match = (this.data.subjects || []).find(s => s.code === code)
    return match ? match.id : null
  },

  _migrateRunningStateCache(subjects) {
    try {
      const local = wx.getStorageSync('pomodoro_running_state')
      if (!local || local.selectedSubjectId || !local.selectedSubjectCode) return
      const match = (subjects || []).find(s => s.code === local.selectedSubjectCode)
      if (match) {
        local.selectedSubjectId = match.id
        if (!local.selectedSubjectName) local.selectedSubjectName = match.name || ''
        wx.setStorageSync('pomodoro_running_state', local)
      } else {
        // 无法映射的旧 code 缓存 → 安全清除，避免恢复出无科目会话
        wx.removeStorageSync('pomodoro_running_state')
      }
    } catch (_) {}
  },

  /* ==================== UI Handlers ==================== */

  selectSubject(e) {
    const id = parseInt(e.currentTarget.dataset.id, 10) || null
    const subject = id ? this.data.subjects.find(s => s.id === id) : null
    if (subject) {
      this.setData({ selectedSubjectId: id, selectedSubject: subject })
      this._updateComputedFields()
    }
  },

  onExamTap() {
    if (!config.DEBUG_MODE) return
    this._debugTapCount++
    if (this._debugTapTimer) clearTimeout(this._debugTapTimer)
    if (this._debugTapCount >= 5) {
      this._debugTapCount = 0
      const next = !this.data.debugMode
      this.setData({ debugMode: next })
      wx.showToast({ title: next ? '开发模式已开启' : '开发模式已关闭', icon: 'none', duration: 1500 })
      if (!next && this.data.selectedPreset === 'debug') {
        this.setData({ selectedPreset: 'standard', workDuration: 25, breakDuration: 5 })
      }
    } else {
      this._debugTapTimer = setTimeout(() => { this._debugTapCount = 0 }, 1500)
    }
  },

  selectPreset(e) {
    const key = e.currentTarget.dataset.key
    if (key === 'debug') {
      this.setData({ selectedPreset: 'debug', showCustom: false, workDuration: 0, breakDuration: 0 })
      this._updateComputedFields()
      return
    }
    if (key === 'free') {
      this.setData({ selectedPreset: 'free', showCustom: false, workDuration: 0, breakDuration: 0 })
      this._updateComputedFields()
      return
    }
    const preset = PRESETS.find(p => p.key === key)
    this.setData({
      selectedPreset: key,
      showCustom: key === 'custom',
      workDuration: preset ? preset.work : 25,
      breakDuration: preset ? preset.break : 5,
    })
    this._updateComputedFields()
  },

  onWorkChange(e) {
    const v = Math.max(5, Math.min(120, parseInt(e.detail.value, 10) || 25))
    this.setData({ workDuration: v })
  },

  onBreakChange(e) {
    const v = Math.max(5, Math.min(120, parseInt(e.detail.value, 10) || 5))
    this.setData({ breakDuration: v })
  },

  /* ==================== Touch / Swipe ==================== */

  noop() {},
  onCustomAreaTouch() {},

  onTouchStart(e) {
    this._touchStartX = e.touches[0].clientX
  },

  onTouchEnd(e) {
    if (this.data.phase !== PHASE.IDLE) return
    const diff = e.changedTouches[0].clientX - this._touchStartX
    if (Math.abs(diff) < 50) return

    const keys = PRESETS.map(p => p.key)
    const idx = keys.indexOf(this.data.selectedPreset)
    if (diff < 0) {
      const next = (idx + 1) % keys.length
      this.selectPreset({ currentTarget: { dataset: { key: keys[next] } } })
    } else {
      const prev = (idx - 1 + keys.length) % keys.length
      this.selectPreset({ currentTarget: { dataset: { key: keys[prev] } } })
    }
  },

  /* ==================== Start Ceremony ==================== */

  async startSession() {
    if (!this.data.selectedSubjectId || !this.data.selectedSubject) {
      wx.showToast({ title: '请选择学习科目', icon: 'none' })
      return
    }
    if (this.data.subjectsError) {
      wx.showToast({ title: '科目加载异常，请重试', icon: 'none' })
      return
    }

    // Free timer: skip ceremony, start directly
    if (this.data.selectedPreset === 'free') {
      await this._startFreeSession()
      return
    }

    this.setData({ phase: PHASE.CEREMONY })
    await new Promise(r => setTimeout(r, this.data.selectedPreset === 'debug' ? 1000 : 2500))

    try {
      const session = await api.post('/pomodoro/start', {
        subject_id: this.data.selectedSubjectId,
        chapter_id: this.data.fromChapterId || null,
        preset: this.data.selectedPreset,
        work_duration: this.data.selectedPreset === 'debug' ? 1 : this.data.workDuration,
        break_duration: this.data.selectedPreset === 'debug' ? 1 : this.data.breakDuration,
      })
      this._beginCountdown(session)
    } catch (e) {
      wx.showToast({ title: '启动失败', icon: 'none' })
      this.setData({ phase: PHASE.IDLE })
    }
  },

  /* ==================== Free Timer ==================== */

  async _startFreeSession() {
    try {
      const session = await api.post('/pomodoro/start', {
        subject_id: this.data.selectedSubjectId,
        chapter_id: this.data.fromChapterId || null,
        preset: 'free',
        work_duration: 0,
        break_duration: 0,
      })
      this._beginFreeTimer(session)
    } catch (e) {
      const detail = (e && (e.detail || e.message || '')) || ''
      if (detail.includes('active') || detail.includes('running')) {
        wx.showToast({ title: '已有进行中的专注，请先结束', icon: 'none' })
        // Try to restore
        const active = await this._fetchActiveSession()
        if (active) this._restoreSession(active)
      } else {
        wx.showToast({ title: '启动失败，请重试', icon: 'none' })
      }
    }
  },

  _beginFreeTimer(session) {
    const startTime = parseServerTime(session.start_time)
    const totalPausedSec = session.total_paused_sec || 0
    const now = Date.now()
    const startupElapsedMs = Math.max(0, now - startTime - totalPausedSec * 1000)

    this._clearTimer()
    this._timerState.sessionId = session.id
    this._timerState.sessionStartTime = startTime
    this._timerState.totalPausedMs = totalPausedSec * 1000
    this._timerState.freeDisplayOffsetMs = startupElapsedMs
    this._timerState.pauseStartTime = null
    this._timerState.elapsedSec = 0
    this._timerState.freeFriendlyText = ''
    this._timerState.progress = 1
    this.setData({
      phase: PHASE.RUNNING,
      ringCanvasVisible: true,
      isFreeTimer: true,
      isPaused: false,
      freeDisplayTime: '00:00:00',
      showEndConfirm: false,
    })
    this._updateComputedFields()
    this._startFreeTimerInterval()
    wx.nextTick(() => {
      setTimeout(() => { this._initCanvas(); this.drawRing(0, false) }, 50)
    })
  },

  _updateFreeElapsed() {
    if (!this.data.isFreeTimer) return
    if (this.data.showEndConfirm) return

    if (this.data.isPaused) {
      const fmt = formatElapsedSec(this._timerState.elapsedSec || 0)
      this.setData({
        freeDisplayTime: fmt.display,
      })
      this._timerState.freeFriendlyText = fmt.friendly
      return
    }

    const elapsedMs = this._getEffectiveFreeElapsedMs()
    // Cap display at 5-hour max so UI never shows >05:00:00
    const cappedMs = Math.min(elapsedMs, FREE_TIMER_MAX_MS)
    const elapsedSec = Math.floor(cappedMs / 1000)

    if (elapsedSec === this._timerState.elapsedSec) return
    const fmt = formatElapsedSec(elapsedSec)
    this._timerState.elapsedSec = elapsedSec
    this._timerState.freeFriendlyText = fmt.friendly
    this.setData({
      freeDisplayTime: fmt.display,
    })
  },

  _clearFreeTimerInterval() {
    if (this._freeTimerId) {
      clearTimeout(this._freeTimerId)
      this._freeTimerId = null
    }
  },

  _startFreeTimerInterval() {
    if (this._freeTimerId) return

    const scheduleNext = () => {
      const elapsedMs = this._getEffectiveFreeElapsedMs()
      const remainder = elapsedMs % 1000
      const delay = remainder === 0 ? 1000 : 1000 - remainder
      this._freeTimerId = setTimeout(tick, Math.max(100, Math.min(delay, 1000)))
    }

    const tick = async () => {
      this._freeTimerId = null
      if (this.data.isPaused || this.data.showEndConfirm) return
      this._updateFreeElapsed()

      // Check 5-hour limit after display update; if auto-ended, stop scheduling
      if (this._checkFreeTimerLimitAndAutoEnd()) return

      scheduleNext()
    }

    scheduleNext()
  },

  _restartFreeTimerInterval() {
    this._clearFreeTimerInterval()
    this._startFreeTimerInterval()
  },

  async _pauseFreeTimer() {
    if (!this._timerState.sessionId || this.data.actionLoading) return
    this.setData({ actionLoading: true })
    try {
      const server = await api.post(`/pomodoro/${this._timerState.sessionId}/pause`, {})
      this._clearFreeTimerInterval()
      this._timerState.pauseStartTime = Date.now()
      this._timerState.totalPausedMs = (server.total_paused_sec || 0) * 1000
      this._timerState.freeFriendlyText = formatElapsedSec(this._timerState.elapsedSec).friendly
      this.setData({
        isPaused: true,
        actionLoading: false,
      })
      wx.setStorageSync('pomodoro_free_pause', {
        totalPausedMs: (server.total_paused_sec || 0) * 1000,
        pauseStartTime: Date.now(),
        sessionId: this._timerState.sessionId,
        elapsedSec: this._timerState.elapsedSec,
        freeDisplayOffsetMs: this._timerState.freeDisplayOffsetMs || 0,
      })
    } catch (e) {
      this.setData({ actionLoading: false })
      wx.showToast({ title: '暂停失败，请重试', icon: 'none' })
    }
  },

  async _resumeFreeTimer() {
    if (!this._timerState.sessionId || this.data.actionLoading) return
    this.setData({ actionLoading: true })
    this._clearFreeTimerInterval()
    try {
      const server = await api.post(`/pomodoro/${this._timerState.sessionId}/resume`, {})
      const startTime = parseServerTime(server.start_time)
      let serverTotalPausedSec = server.total_paused_sec || 0

      // Merge with local pause adjustment
      const effectiveTotalPausedMs = this._mergeLocalPauseAdjustment(server.id, serverTotalPausedSec * 1000)
      serverTotalPausedSec = Math.floor(effectiveTotalPausedMs / 1000)

      this._timerState.sessionStartTime = startTime
      this._timerState.totalPausedMs = effectiveTotalPausedMs
      this._timerState.pauseStartTime = null
      // Preserve freeDisplayOffsetMs — already set in _timerState

      const elapsedMs = this._getEffectiveFreeElapsedMs()
      const elapsed = Math.floor(elapsedMs / 1000)
      const fmt = formatElapsedSec(elapsed)
      this._timerState.elapsedSec = elapsed
      this.setData({
        isPaused: false,
        ringCanvasVisible: true,
        freeDisplayTime: fmt.display,
        actionLoading: false,
      })
      wx.removeStorageSync('pomodoro_free_pause')
      this._startFreeTimerInterval()
    } catch (e) {
      this.setData({ actionLoading: false })
      await this._reconcileAfterResumeError(e, this._timerState.sessionId)
    }
  },

  async _reconcileAfterResumeError(e, sessionId) {
    if (!e || e.code !== 404) {
      wx.showToast({ title: '继续失败，请重试', icon: 'none' })
      return
    }
    try {
      const active = await api.get('/pomodoro/active')
      if (!active || active.id !== sessionId) {
        this._resetToIdle()
        wx.showToast({ title: '当前专注已结束或失效', icon: 'none' })
        return
      }
      if (active.status !== 'running') {
        wx.showToast({ title: '继续失败，请稍后重试', icon: 'none' })
        return
      }
      // Server says running — fix local state and continue
      const startTime = parseServerTime(active.start_time)
      const totalPausedSec = active.total_paused_sec || 0
      const totalPausedMs = totalPausedSec * 1000
      if (this.data.isFreeTimer) {
        this._timerState.sessionStartTime = startTime
        this._timerState.totalPausedMs = this._mergeLocalPauseAdjustment(active.id, totalPausedMs)
        this._timerState.pauseStartTime = null

        const elapsedMs = this._getEffectiveFreeElapsedMs()
        const elapsed = Math.floor(elapsedMs / 1000)
        const fmt = formatElapsedSec(elapsed)
        this._timerState.elapsedSec = elapsed
        this.setData({
          isPaused: false,
          freeDisplayTime: fmt.display,
          ringCanvasVisible: true,
        })
        this._startFreeTimerInterval()
        wx.removeStorageSync('pomodoro_free_pause')
      } else {
        const now = Date.now()
        const totalSec = this._getCurrentTotalSec()

        // Merge with local pause adjustment
        const effectiveTotalPausedMs = this._mergeLocalPauseAdjustment(active.id, totalPausedMs)

        const elapsed = Math.floor((now - startTime - effectiveTotalPausedMs) / 1000)
        const remainingSec = Math.max(0, totalSec - elapsed)
        this._timerState.sessionStartTime = startTime
        this._timerState.totalPausedMs = effectiveTotalPausedMs
        this._timerState.pauseStartTime = null
        this._timerState.remainingSec = remainingSec
        this._timerState.progress = totalSec > 0 ? remainingSec / totalSec : 0
        this.setData({
          isPaused: false,
          remainingSec,
          displayMin: String(Math.floor(remainingSec / 60)).padStart(2, '0'),
          displaySec: String(remainingSec % 60).padStart(2, '0'),
          ringCanvasVisible: true,
        })
        this._startTimer(totalSec)
        wx.removeStorageSync('pomodoro_pause')
      }
      wx.showToast({ title: '已恢复计时', icon: 'none' })
    } catch (_) {
      wx.showToast({ title: '继续失败，请重试', icon: 'none' })
    }
  },

  _isValidConfirmSnapshot(snapshot) {
    if (!snapshot || !snapshot.sessionId) return false
    if (!snapshot.mode) return false
    if (snapshot.confirmVisible === false) return false
    if (!snapshot.openedAt) return false
    // Snapshots older than 1 hour are stale
    if (Date.now() - snapshot.openedAt > 3600000) return false
    return true
  },

  _buildEndConfirmViewModel(mode, snapshot) {
    if (mode === 'free-complete') {
      const elapsed = Math.max(0, snapshot.elapsedSec || 0)
      const fmt = formatElapsedSec(elapsed)
      return {
        showEndConfirm: true,
        endConfirmTheme: 'free',
        endConfirmTitle: '结束自由计时？',
        endConfirmText: elapsed >= 1
          ? `本次已专注 ${fmt.friendly}，确认后将计入学习统计。`
          : '当前计时时长较短，确认后仍会结束本次计时。',
        endConfirmOkText: '确认结束',
        endConfirmCancelText: '继续计时',
      }
    }

    if (mode === 'countdown-interrupt') {
      const isBreak = snapshot.phase === 'break'
      const elapsedSec = Math.max(0, (snapshot.totalSec || 0) - (snapshot.remainingSec || 0))
      const fmt = formatElapsedSec(elapsedSec)
      return {
        showEndConfirm: true,
        endConfirmTheme: isBreak ? 'break' : 'focus',
        endConfirmTitle: isBreak ? '结束休息？' : '结束本次专注？',
        endConfirmText: elapsedSec > 0
          ? `本次已专注 ${fmt.friendly}。确认后将结束当前番茄钟。`
          : '确认后将结束当前番茄钟。',
        endConfirmOkText: '结束',
        endConfirmCancelText: isBreak ? '继续休息' : '继续专注',
      }
    }

    throw new Error('Unknown confirm mode: ' + mode)
  },

  async _showEndFreeConfirm() {
    if (!this._timerState.sessionId || this.data.actionLoading) return

    const now = Date.now()
    const wasPaused = !!this.data.isPaused
    const elapsed = Math.max(0, this._timerState.elapsedSec || 0)
    const fmt = formatElapsedSec(elapsed)

    this._clearFreeTimerInterval()

    const snapshot = {
      mode: 'free-complete',
      sessionId: this._timerState.sessionId,
      openedAt: now,
      wasPaused,
      pausedByConfirm: !wasPaused,
      elapsedSec: elapsed,
      totalPausedMs: this._timerState.totalPausedMs || 0,
      pauseStartTime: this._timerState.pauseStartTime || null,
      sessionStartTime: this._timerState.sessionStartTime,
      backendPauseDone: false,
      confirmVisible: true,
      freeDisplayOffsetMs: this._timerState.freeDisplayOffsetMs || 0,
    }

    this._confirmTimerSnapshot = snapshot
    wx.setStorageSync('pomodoro_confirm_pause', snapshot)

    this._timerState.elapsedSec = elapsed
    this._timerState.pauseStartTime = now
    this._timerState.freeFriendlyText = fmt.friendly
    this._timerState.endConfirmMode = 'free-complete'
    this.setData({
      ...this._buildEndConfirmViewModel('free-complete', snapshot),
      ringCanvasVisible: true,
      freeDisplayTime: fmt.display,
      isPaused: true,
    })

    // Backend pause async — don't block UI
    if (!wasPaused) {
      api.post('/pomodoro/' + this._timerState.sessionId + '/pause', {})
        .then(server => {
          const serverPausedMs = (server.total_paused_sec || 0) * 1000
          snapshot.totalPausedMs = Math.max(snapshot.totalPausedMs || 0, serverPausedMs)
          snapshot.backendPauseDone = true
          this._confirmTimerSnapshot = snapshot
          wx.setStorageSync('pomodoro_confirm_pause', snapshot)
          this._timerState.totalPausedMs = snapshot.totalPausedMs
          this._timerState.pauseStartTime = Date.now()
})
        .catch(e => console.warn('free confirm pause backend sync failed', e))
    }
  },

  _getCurrentTotalSec() {
    if (this.data.phase === 'break') {
      return this.data.selectedPreset === 'debug'
        ? 5
        : Math.max(1, this.data.breakDuration * 60)
    }
    return this.data.selectedPreset === 'debug'
      ? 10
      : Math.max(1, this.data.workDuration * 60)
  },

  async _pauseCountdownForEndConfirm() {
    if (!this._timerState.sessionId || this.data.actionLoading) return false

    const now = Date.now()
    const totalSec = this._getCurrentTotalSec()
    const totalMs = Math.max(1, totalSec * 1000)

    const remainingMs = this._countdownEndAt
      ? Math.max(0, this._countdownEndAt - now)
      : Math.max(0, (this._timerState.remainingSec || 0) * 1000)

    const remainingSec = remainingMs <= 0 ? 0 : Math.ceil(remainingMs / 1000)
    const progress = totalMs > 0 ? remainingMs / totalMs : 0
    const wasPaused = !!this.data.isPaused

    this._clearTimer()

    const snapshot = {
      mode: 'countdown-interrupt',
      sessionId: this._timerState.sessionId,
      openedAt: now,
      wasPaused: wasPaused,
      pausedByConfirm: !wasPaused,
      phase: this.data.phase,
      totalSec: totalSec,
      totalMs: totalMs,
      remainingMs: remainingMs,
      remainingSec: remainingSec,
      progress: progress,
      sessionStartTime: this._timerState.sessionStartTime,
      countdownEndAt: this._countdownEndAt,
      totalPausedMs: this._timerState.totalPausedMs || 0,
      pauseStartTime: this._timerState.pauseStartTime || null,
      backendPauseDone: false,
      confirmVisible: true,
    }

    this._confirmTimerSnapshot = snapshot
    wx.setStorageSync('pomodoro_confirm_pause', snapshot)

    this._countdownEndAt = 0

    const fmt = this._formatCountdownDisplay(remainingSec)

    this._timerState.pauseStartTime = now
    this._timerState.remainingSec = remainingSec
    this._timerState.progress = progress
    this.setData({
      isPaused: true,
      displayMin: fmt.min,
      displaySec: fmt.sec,
    })

    this.drawRing(totalSec, this.data.phase === 'break')

    this._timerState.endConfirmMode = 'countdown-interrupt'

    // Sync backend pause (async, don't block UI)
    if (!wasPaused) {
      try {
        const server = await api.post('/pomodoro/' + this._timerState.sessionId + '/pause', {})
        const serverPausedMs = (server.total_paused_sec || 0) * 1000
        snapshot.totalPausedMs = serverPausedMs
        snapshot.backendPauseDone = true
        this._confirmTimerSnapshot = snapshot
        wx.setStorageSync('pomodoro_confirm_pause', snapshot)
        this._timerState.totalPausedMs = serverPausedMs
        this._timerState.pauseStartTime = Date.now()
      } catch (e) {
        console.warn('confirm pause backend sync failed', e)
        // Keep frontend frozen; cancelEndConfirm handles recovery
      }
    }

    return true
  },

  async _showCountdownInterruptConfirm() {
    if (this.data.actionLoading) return

    const ok = await this._pauseCountdownForEndConfirm()
    if (!ok || !this._confirmTimerSnapshot) return

    const snapshot = this._confirmTimerSnapshot

    this.setData({
      ...this._buildEndConfirmViewModel('countdown-interrupt', snapshot),
      ringCanvasVisible: true,
    })

    wx.nextTick(() => {
      this._initCanvas(true)
      this.drawRing(snapshot.totalSec, snapshot.phase === 'break')
    })
  },

  async cancelEndConfirm() {
    if (this.data.actionLoading) return

    const mode = this._timerState.endConfirmMode
    const snapshot = this._confirmTimerSnapshot || wx.getStorageSync('pomodoro_confirm_pause')
    const now = Date.now()

    if (mode === 'countdown-interrupt' && snapshot && snapshot.sessionId) {
      this._confirmTimerSnapshot = snapshot
      const fmt = this._formatCountdownDisplay(snapshot.remainingSec)

      if (snapshot.wasPaused) {
        // Was paused before confirm — keep paused after cancel
        this._timerState.remainingSec = snapshot.remainingSec
        this._timerState.progress = snapshot.progress
        this._timerState.pauseStartTime = snapshot.pauseStartTime || Date.now()
        this._timerState.totalPausedMs = snapshot.totalPausedMs || 0
        this._timerState.endConfirmMode = ''
        this.setData({
          showEndConfirm: false,
          ringCanvasVisible: true,
          endConfirmTheme: '',
          endConfirmTitle: '',
          endConfirmText: '',
          displayMin: fmt.min,
          displaySec: fmt.sec,
          isPaused: true,
        })

        wx.removeStorageSync('pomodoro_confirm_pause')
        this._confirmTimerSnapshot = null

        wx.nextTick(() => {
          this._initCanvas(true)
          this.drawRing(snapshot.totalSec, snapshot.phase === 'break')
        })
        return
      }

      // ===== Was running before confirm — resume after cancel =====
      // 1. Calculate local adjustment immediately
      const pauseDelta = Math.max(0, now - snapshot.openedAt)
      const localTotalPausedMs = (snapshot.totalPausedMs || 0) + pauseDelta

      // 2. Save local pause adjustment to storage (survives onShow/active-sync)
      wx.setStorageSync('pomodoro_pause_adjustment', {
        sessionId: snapshot.sessionId,
        totalPausedMs: localTotalPausedMs,
        savedAt: Date.now(),
        source: 'cancel_end_confirm',
      })

      // 3. Restore UI immediately from snapshot — no await
      this._timerState.remainingSec = snapshot.remainingSec
      this._timerState.progress = snapshot.progress
      this._timerState.totalPausedMs = localTotalPausedMs
      this._timerState.pauseStartTime = null
      this._timerState.endConfirmMode = ''
      this.setData({
        showEndConfirm: false,
        ringCanvasVisible: true,
        endConfirmTheme: '',
        endConfirmTitle: '',
        endConfirmText: '',
        displayMin: fmt.min,
        displaySec: fmt.sec,
        isPaused: false,
        actionLoading: false,
      })

      wx.removeStorageSync('pomodoro_confirm_pause')

      // 4. Start timer immediately from snapshot remainingMs
      this._countdownTotalSec = snapshot.totalSec
      this._startTimer(snapshot.totalSec, { remainingMs: snapshot.remainingMs, forceRunning: true })

      wx.nextTick(() => {
        this._initCanvas(true)
        this.drawRing(snapshot.totalSec, snapshot.phase === 'break')
      })

      this._confirmTimerSnapshot = null

      // 5. Fire-and-forget backend resume — must not block UI
      api.post('/pomodoro/' + snapshot.sessionId + '/resume', {
        total_paused_ms: localTotalPausedMs,
      }).then(server => {
        const serverPausedMs = (server.total_paused_sec || 0) * 1000
        const finalPausedMs = Math.max(serverPausedMs, localTotalPausedMs)
        this._timerState.totalPausedMs = finalPausedMs

        wx.setStorageSync('pomodoro_pause_adjustment', {
          sessionId: snapshot.sessionId,
          totalPausedMs: finalPausedMs,
          savedAt: Date.now(),
          source: 'cancel_end_confirm',
        })
      }).catch(e => {
        console.warn('resume after cancel confirm failed, keep local timer', e)
      })

      return
    }

    if (mode === 'free-complete') {
      const snapshot = this._confirmTimerSnapshot || wx.getStorageSync('pomodoro_confirm_pause')

      if (!snapshot || snapshot.mode !== 'free-complete') {
        this._timerState.endConfirmMode = ''
        this.setData({
          showEndConfirm: false,
          ringCanvasVisible: true,
          endConfirmTheme: '',
          endConfirmTitle: '',
          endConfirmText: '',
        })
        if (!this.data.isPaused) this._startFreeTimerInterval()
        return
      }

      const fmt = formatElapsedSec(snapshot.elapsedSec || 0)

      // Was paused before confirm — keep paused after cancel
      if (snapshot.wasPaused) {
        this._timerState.pauseStartTime = snapshot.pauseStartTime || Date.now()
        this._timerState.totalPausedMs = snapshot.totalPausedMs || 0
        this._timerState.elapsedSec = snapshot.elapsedSec || 0
        this._timerState.freeFriendlyText = fmt.friendly
        this._timerState.endConfirmMode = ''
        this._timerState.freeDisplayOffsetMs = Number(snapshot.freeDisplayOffsetMs || 0)
        this.setData({
          showEndConfirm: false,
          ringCanvasVisible: true,
          endConfirmTheme: '',
          endConfirmTitle: '',
          endConfirmText: '',
          isPaused: true,
          freeDisplayTime: fmt.display,
        })

        wx.removeStorageSync('pomodoro_confirm_pause')
        this._confirmTimerSnapshot = null
        return
      }

      // Was running before confirm — resume from snapshot.elapsedSec
      const pauseDelta = Math.max(0, Date.now() - snapshot.openedAt)
      const localTotalPausedMs = (snapshot.totalPausedMs || 0) + pauseDelta

      wx.setStorageSync('pomodoro_pause_adjustment', {
        sessionId: snapshot.sessionId,
        totalPausedMs: localTotalPausedMs,
        savedAt: Date.now(),
        source: 'cancel_free_end_confirm',
      })

      this._timerState.pauseStartTime = null
      this._timerState.totalPausedMs = localTotalPausedMs
      this._timerState.elapsedSec = snapshot.elapsedSec || 0
      this._timerState.freeFriendlyText = ''
      this._timerState.endConfirmMode = ''
      this._timerState.freeDisplayOffsetMs = Number(snapshot.freeDisplayOffsetMs || 0)
      this.setData({
        showEndConfirm: false,
        ringCanvasVisible: true,
        endConfirmTheme: '',
        endConfirmTitle: '',
        endConfirmText: '',
        isPaused: false,
        freeDisplayTime: fmt.display,
      })

      wx.removeStorageSync('pomodoro_confirm_pause')
      this._confirmTimerSnapshot = null

      this._restartFreeTimerInterval()

      // Backend resume async — must not block local recovery
      api.post('/pomodoro/' + snapshot.sessionId + '/resume', {
        total_paused_ms: localTotalPausedMs,
      }).then(server => {
        const serverPausedMs = (server.total_paused_sec || 0) * 1000
        const finalPausedMs = Math.max(serverPausedMs, localTotalPausedMs)

        this._timerState.totalPausedMs = finalPausedMs

        wx.setStorageSync('pomodoro_pause_adjustment', {
          sessionId: snapshot.sessionId,
          totalPausedMs: finalPausedMs,
          savedAt: Date.now(),
          source: 'cancel_free_end_confirm',
        })
      }).catch(e => {
        console.warn('resume free timer after cancel confirm failed, keep local timer', e)
      })

      return
    }

    this._timerState.endConfirmMode = ''
    this.setData({
      showEndConfirm: false,
      endConfirmTheme: '',
      endConfirmTitle: '',
      endConfirmText: '',
    })
    this._confirmTimerSnapshot = null
  },

  async confirmEndTimer() {
    if (this.data.actionLoading) return

    const mode = this._timerState.endConfirmMode
    const snapshot = this._confirmTimerSnapshot

    if (mode === 'free-complete') {
      return this._confirmEndFreeTimer()
    }

    if (mode === 'countdown-interrupt') {
      return this._confirmInterruptCountdown()
    }

    console.warn('[pomodoro] invalid end confirm mode', {
      mode,
      sessionId: this._timerState.sessionId,
      snapshotMode: snapshot && snapshot.mode,
    })
    wx.showToast({
      title: '结束状态异常，请重新操作',
      icon: 'none',
    })
  },

  async _confirmEndFreeTimer() {
    if (this.data.actionLoading) return
    this.setData({ showEndConfirm: false, actionLoading: true })
    if (!this._timerState.sessionId) return
    this._clearFreeTimerInterval()
    const elapsedSec = Math.max(1, this._timerState.elapsedSec || 0)
    await this._completeFreeTimerSession(elapsedSec)
    this.setData({ actionLoading: false })
  },

  async _confirmInterruptCountdown() {
    if (!this._timerState.sessionId || this.data.actionLoading) return

    const snapshot = this._confirmTimerSnapshot
    let totalPausedMs = this._timerState.totalPausedMs || 0

    if (snapshot && snapshot.openedAt) {
      totalPausedMs = Math.max(0, snapshot.totalPausedMs + (Date.now() - snapshot.openedAt))
    }

    this._timerState.totalPausedMs = totalPausedMs
    this.setData({ actionLoading: true })

    try {
      await api.post(`/pomodoro/${this._timerState.sessionId}/interrupt`, {
        total_paused_ms: totalPausedMs,
      })
      wx.showToast({ title: '已结束本次专注', icon: 'none' })
      wx.removeStorageSync('pomodoro_pause_adjustment')
      this._confirmTimerSnapshot = null
      this.setData({ showEndConfirm: false, actionLoading: false })
      this._resetToIdle()
      this.loadTodayStats()
    } catch (e) {
      this.setData({ actionLoading: false, ringCanvasVisible: true }, () => {
        wx.nextTick(() => {
          this._initCanvas(true)
          this.drawRing(this._getCurrentTotalSec(), this.data.phase === 'break')
        })
      })
      wx.showToast({ title: '结束失败，请重试', icon: 'none' })
    }
  },

  async endSession() {
    if (!this._timerState.sessionId) return
    this._clearTimer()
    try {
      await api.post(`/pomodoro/${this._timerState.sessionId}/complete`, {
        total_paused_ms: this._timerState.totalPausedMs || 0,
      })
    } catch (e) {
      try { await api.post(`/pomodoro/${this._timerState.sessionId}/interrupt`, {
        total_paused_ms: this._timerState.totalPausedMs || 0,
      }) } catch (_) {}
    }
    this._resetToIdle()
    this.loadTodayStats()
  },

  async interruptSession() {
    if (!this._timerState.sessionId) return

    if (this.data.isFreeTimer) {
      this._showEndFreeConfirm()
      return
    }

    this._showCountdownInterruptConfirm()
  },

  /* ==================== Countdown Timer ==================== */

  _beginCountdown(session) {
    const startTime = parseServerTime(session.start_time)
    const totalSec = this.data.selectedPreset === 'debug' ? 10 : this.data.workDuration * 60
    this._timerState.sessionId = session.id
    this._timerState.sessionStartTime = startTime
    this._timerState.remainingSec = totalSec
    this._timerState.progress = 1
    this._timerState.totalPausedMs = 0
    this._timerState.pauseStartTime = null
    this.setData({
      phase: PHASE.RUNNING,
      ringCanvasVisible: true,
      isPaused: false,
    })
    this._countdownTotalSec = totalSec
    this._countdownEndAt = Date.now() + totalSec * 1000
    this._startTimer(totalSec)
    this._updateComputedFields()
    wx.nextTick(() => {
      setTimeout(() => this.drawRing(totalSec, false), 50)
    })
  },

  togglePause() {
    if (this.data.isFreeTimer) {
      if (this.data.isPaused) {
        this._resumeFreeTimer()
      } else {
        this._pauseFreeTimer()
      }
    } else if (this.data.isPaused) {
      this._resumeSession()
    } else {
      this._pauseSession()
    }
  },

  async _pauseSession() {
    if (!this._timerState.sessionId || this.data.actionLoading) return
    this.setData({ actionLoading: true })
    try {
      const server = await api.post(`/pomodoro/${this._timerState.sessionId}/pause`, {})
      this._clearTimer()
      this._timerState.pauseStartTime = Date.now()
      this._timerState.totalPausedMs = (server.total_paused_sec || 0) * 1000
      this.setData({
        isPaused: true,
        actionLoading: false,
      })
      wx.setStorageSync('pomodoro_pause', {
        totalPausedMs: (server.total_paused_sec || 0) * 1000,
        pauseStartTime: Date.now(),
        sessionId: this._timerState.sessionId,
      })
    } catch (e) {
      this.setData({ actionLoading: false })
      wx.showToast({ title: '暂停失败，请重试', icon: 'none' })
    }
  },

  async _resumeSession() {
    if (typeof this._timerState.sessionStartTime !== 'number' || this._timerState.sessionStartTime <= 0) {
      console.warn('resume aborted: invalid sessionStartTime', this._timerState.sessionStartTime)
      this._resetToIdle()
      return
    }
    if (!this._timerState.sessionId || this.data.actionLoading) return
    this.setData({ actionLoading: true })
    try {
      const server = await api.post(`/pomodoro/${this._timerState.sessionId}/resume`, {})
      const startTime = parseServerTime(server.start_time)
      let serverTotalPausedSec = server.total_paused_sec || 0
      const totalSec = this.data.selectedPreset === 'debug' ? 10 : (this.data.workDuration ?? 25) * 60

      // Merge with local pause adjustment
      const serverTotalPausedMs = serverTotalPausedSec * 1000
      const effectiveTotalPausedMs = this._mergeLocalPauseAdjustment(server.id, serverTotalPausedMs)
      serverTotalPausedSec = Math.floor(effectiveTotalPausedMs / 1000)

      const elapsed = Math.floor((Date.now() - startTime) / 1000) - serverTotalPausedSec
      const remainingSec = Math.max(0, totalSec - elapsed)
      this._timerState.totalPausedMs = effectiveTotalPausedMs
      this._timerState.pauseStartTime = null
      this._timerState.remainingSec = remainingSec
      this._timerState.progress = totalSec > 0 ? remainingSec / totalSec : 0
      this.setData({
        isPaused: false,
        ringCanvasVisible: true,
        displayMin: String(Math.floor(remainingSec / 60)).padStart(2, '0'),
        displaySec: String(remainingSec % 60).padStart(2, '0'),
        actionLoading: false,
      })
      wx.removeStorageSync('pomodoro_pause')
      this._startTimer(totalSec)
    } catch (e) {
      this.setData({ actionLoading: false })
      await this._reconcileAfterResumeError(e, this._timerState.sessionId)
    }
  },

  _formatCountdownDisplay(sec) {
    const safe = Math.max(0, Number(sec) || 0)
    const m = Math.floor(safe / 60)
    const s = safe % 60
    return {
      min: String(m).padStart(2, '0'),
      sec: String(s).padStart(2, '0'),
    }
  },

  /* ==================== Local Pause Adjustment ==================== */

  _getLocalPauseAdjustment(sessionId) {
    try {
      const adjust = wx.getStorageSync('pomodoro_pause_adjustment')
      if (!adjust || adjust.sessionId !== sessionId) return 0
      if (Date.now() - adjust.savedAt > 2 * 60 * 60 * 1000) {
        wx.removeStorageSync('pomodoro_pause_adjustment')
        return 0
      }
      return Number(adjust.totalPausedMs || 0)
    } catch (_) { return 0 }
  },

  _mergeLocalPauseAdjustment(sessionId, serverPausedMs) {
    const localPausedMs = this._getLocalPauseAdjustment(sessionId)
    return Math.max(Number(serverPausedMs || 0), Number(localPausedMs || 0))
  },

  /* ==================== Free Timer Display Offset ==================== */

  _getFreeElapsedMs(now) {
    if (typeof now !== 'number') now = Date.now()
    const startTime = Number(this._timerState.sessionStartTime)
    if (!Number.isFinite(startTime) || startTime <= 0) return 0
    const totalPausedMs = Number(this._timerState.totalPausedMs || 0)
    const displayOffsetMs = Number(this._timerState.freeDisplayOffsetMs || 0)
    return Math.max(0, now - startTime - totalPausedMs - displayOffsetMs)
  },

  _getEffectiveFreeElapsedMs(now) {
    if (typeof now !== 'number') now = Date.now()
    const startTime = Number(this._timerState.sessionStartTime)
    if (!Number.isFinite(startTime) || startTime <= 0) return 0
    let totalPausedMs = Number(this._timerState.totalPausedMs || 0)
    totalPausedMs = this._mergeLocalPauseAdjustment(this._timerState.sessionId, totalPausedMs)
    const displayOffsetMs = Number(this._timerState.freeDisplayOffsetMs || 0)
    return Math.max(0, now - startTime - totalPausedMs - displayOffsetMs)
  },

  _checkFreeTimerLimitAndAutoEnd() {
    if (!this.data.isFreeTimer || this.data.isPaused || this._freeTimerFinalizing) return false
    const elapsedMs = this._getEffectiveFreeElapsedMs()
    if (elapsedMs >= FREE_TIMER_MAX_MS) {
      this._autoFinishFreeTimer()
      return true
    }
    return false
  },

  async _autoFinishFreeTimer() {
    if (this._freeTimerFinalizing) return
    this._freeTimerFinalizing = true

    this._clearFreeTimerInterval()

    // Fix elapsed to exactly 5 hours for the record
    const elapsedSec = Math.floor(FREE_TIMER_MAX_MS / 1000)

    this._timerState.elapsedSec = elapsedSec
    const fmt = formatElapsedSec(elapsedSec)
    this.setData({ freeDisplayTime: fmt.display })

    wx.showToast({ title: '自由计时已达5小时上限，已自动结束', icon: 'none', duration: 2000 })

    await this._completeFreeTimerSession(elapsedSec)

    this._freeTimerFinalizing = false
  },

  async _completeFreeTimerSession(elapsedSec) {
    if (!this._timerState.sessionId) return
    this._clearFreeTimerInterval()
    const totalPausedMs = this._timerState.totalPausedMs || 0
    const totalPausedSec = Math.floor(totalPausedMs / 1000)
    try {
      await api.post(`/pomodoro/${this._timerState.sessionId}/complete`, {
        actual_duration_sec: Math.max(1, elapsedSec),
        total_paused_sec: totalPausedSec,
      })
      wx.showToast({ title: '已记录本次专注', icon: 'none', duration: 2000 })
    } catch (e) {
      wx.showToast({ title: '结束计时失败，请重试', icon: 'none' })
      this.setData({ ringCanvasVisible: true, actionLoading: false })
      // On failure, don't continue counting (stay at 5h max)
      return
    }
    this._resetToIdle()
    this.loadTodayStats()
  },

  _getEffectivePausedMsFromSession(session) {
    const serverBaseMs = (session.total_paused_sec || 0) * 1000
    let serverEffectiveMs = serverBaseMs

    if (session.paused_at) {
      const pausedAtMs = parseServerTime(session.paused_at)
      if (Number.isFinite(pausedAtMs)) {
        serverEffectiveMs += Math.max(0, Date.now() - pausedAtMs)
      }
    }

    return this._mergeLocalPauseAdjustment(session.id, serverEffectiveMs)
  },

  _startTimer(totalSec, options = {}) {
    this._clearTimer()
    this._initCanvas(true)

    // remainingMs has highest priority, then remainingSec, then this._timerState.remainingSec, then totalSec
    let remainMs
    if (Number.isFinite(options.remainingMs)) {
      remainMs = Math.max(0, options.remainingMs)
    } else {
      const remainSec = Number.isFinite(options.remainingSec)
        ? Math.max(0, options.remainingSec)
        : Math.max(0, this._timerState.remainingSec || totalSec)
      remainMs = remainSec * 1000
    }

    const totalMs = Math.max(1, totalSec * 1000)

    const displayRemainingSec = remainMs <= 0 ? 0 : Math.ceil(remainMs / 1000)
    const progress = totalMs > 0 ? remainMs / totalMs : 0
    const fmt = this._formatCountdownDisplay(displayRemainingSec)

    this._countdownTotalSec = totalSec
    this._countdownEndAt = Date.now() + remainMs

    this._timerState.remainingSec = displayRemainingSec
    this._timerState.progress = progress
    const update = { displayMin: fmt.min, displaySec: fmt.sec, ringCanvasVisible: true }
    if (options.forceRunning) {
      update.isPaused = false
    }
    this.setData(update)

    const tick = () => {
      if (this.data.isPaused || this.data.showEndConfirm) {
        this._timer = null
        return
      }

      const remainingMs = Math.max(0, this._countdownEndAt - Date.now())
      const displayRemainingSec = remainingMs <= 0 ? 0 : Math.ceil(remainingMs / 1000)
      const progress = totalMs > 0 ? remainingMs / totalMs : 0
      const fmt = this._formatCountdownDisplay(displayRemainingSec)

      if (
        displayRemainingSec !== this._timerState.remainingSec ||
        Math.abs(progress - this._timerState.progress) > 0.002
      ) {
        this._timerState.remainingSec = displayRemainingSec
        this._timerState.progress = progress
        this.setData({
          displayMin: fmt.min,
          displaySec: fmt.sec,
        })
      }

      this.drawRing(totalSec, this.data.phase === 'break')

      if (remainingMs <= 0) {
        this._clearTimer()
        this._onWorkComplete()
        return
      }

      const nextDelay = Math.max(80, Math.min(250, remainingMs % 1000 || 250))
      this._timer = setTimeout(tick, nextDelay)
    }

    tick()
  },

  _clearTimer() {
    if (this._timer) {
      clearTimeout(this._timer)
      clearInterval(this._timer)
      this._timer = null
    }
    this._clearFreeTimerInterval()
  },

  /* ==================== Work Complete ==================== */

  async _onWorkComplete() {
    if (!this._timerState.sessionId) {
      this._resetToIdle()
      return
    }
    wx.vibrateLong()
    try {
      await api.post(`/pomodoro/${this._timerState.sessionId}/complete`, {
        total_paused_ms: this._timerState.totalPausedMs || 0,
      })
      wx.removeStorageSync('pomodoro_pause_adjustment')
    } catch (e) {
      console.error('同步失败', e)
    }
    this.loadTodayStats()

    const motto = MOTTOES[Math.floor(Math.random() * MOTTOES.length)]
    const type = this._nextCelebrationType()
    wx.setStorageSync('pomodoro_completion', { motto, type: type, sessionId: this._timerState.sessionId })
    if (this._pageVisible) {
      this.setData({ showCelebration: true, celebrationMotto: motto, celebrationType: type })
    }
  },

  dismissCelebration() {
    wx.removeStorageSync('pomodoro_completion')
    this.setData({ showCelebration: false })
    const breakSec = this.data.selectedPreset === 'debug' ? 5 : this.data.breakDuration * 60
    if (breakSec > 0) {
      this._startBreak(breakSec)
    } else {
      this._resetToIdle()
    }
  },

  /* ==================== Break Timer ==================== */

  _startBreak(totalSec) {
    const breakStartTime = Date.now()
    const totalMs = Math.max(1, totalSec * 1000)
    wx.setStorageSync('pomodoro_break', { startTime: breakStartTime, totalSec })
    this._timerState.breakStartTime = breakStartTime
    this._timerState.remainingSec = totalSec
    this._timerState.progress = 1
    this.setData({
      phase: PHASE.BREAK,
      ringCanvasVisible: true,
      displayMin: String(Math.floor(totalSec / 60)).padStart(2, '0'),
      displaySec: String(totalSec % 60).padStart(2, '0'),
    })
    this._clearTimer()
    this._initCanvas(true)
    this._countdownTotalSec = totalSec
    this._countdownEndAt = Date.now() + totalSec * 1000
    setTimeout(() => this.drawRing(totalSec, true), 100)

    const tick = () => {
      const remainingMs = Math.max(0, this._countdownEndAt - Date.now())
      const displayRemainingSec = remainingMs <= 0 ? 0 : Math.ceil(remainingMs / 1000)
      const progress = totalMs > 0 ? remainingMs / totalMs : 0
      const fmt = this._formatCountdownDisplay(displayRemainingSec)

      if (
        displayRemainingSec !== this._timerState.remainingSec ||
        Math.abs(progress - this._timerState.progress) > 0.002
      ) {
        this._timerState.remainingSec = displayRemainingSec
        this._timerState.progress = progress
        this.setData({
          displayMin: fmt.min,
          displaySec: fmt.sec,
        })
      }
      this.drawRing(totalSec, true)

      if (remainingMs <= 0) {
        this._clearTimer()
        wx.removeStorageSync('pomodoro_break')
        this._resetToIdle()
        return
      }

      const nextDelay = Math.max(80, Math.min(250, remainingMs % 1000 || 250))
      this._timer = setTimeout(tick, nextDelay)
    }
    tick()
  },

  skipBreak() {
    this._clearTimer()
    wx.removeStorageSync('pomodoro_break')
    this._resetToIdle()
  },

  /* ==================== Session Restore ==================== */

  _canLightSyncActive(active) {
    if (!this._timerState.sessionId) return false
    if (active.id !== this._timerState.sessionId) return false
    if (this.data.phase !== PHASE.RUNNING) return false
    if ((active.status === 'paused') !== this.data.isPaused) return false
    if ((active.preset === 'free') !== this.data.isFreeTimer) return false
    if (typeof this._timerState.sessionStartTime !== 'number' || this._timerState.sessionStartTime <= 0) return false
    return true
  },

  _syncActiveSessionLight(active) {
    const now = Date.now()
    let totalPausedMs = this._timerState.totalPausedMs || 0
    totalPausedMs = this._mergeLocalPauseAdjustment(this._timerState.sessionId, totalPausedMs)

    if (this.data.isFreeTimer) {
      if (!this.data.isPaused) {
        const elapsedMs = this._getEffectiveFreeElapsedMs(now)
        const cappedMs = Math.min(elapsedMs, FREE_TIMER_MAX_MS)
        const elapsed = Math.floor(cappedMs / 1000)
        if (elapsed !== this._timerState.elapsedSec) {
          const fmt = formatElapsedSec(elapsed)
          this._timerState.elapsedSec = elapsed
          this.setData({ freeDisplayTime: fmt.display })
        }
        // Check limit after display update
        if (elapsedMs >= FREE_TIMER_MAX_MS) {
          this._autoFinishFreeTimer()
          return
        }
      }
      // Idempotent interval start — won't create duplicate
      this._startFreeTimerInterval()
    } else {
      const totalSec = this.data.selectedPreset === 'debug' ? 10 : (this.data.workDuration ?? 25) * 60
      if (this.data.isPaused) return
      const elapsed = Math.floor((now - this._timerState.sessionStartTime - totalPausedMs) / 1000)
      const remaining = Math.max(0, totalSec - elapsed)
      if (remaining <= 0) {
        // Timer expired while away — trigger completion
        this._clearTimer()
        this._onWorkComplete()
        return
      }
      this._timerState.remainingSec = remaining
      this._timerState.progress = totalSec > 0 ? remaining / totalSec : 0
      this.setData({
        ringCanvasVisible: true,
        displayMin: String(Math.floor(remaining / 60)).padStart(2, '0'),
        displaySec: String(remaining % 60).padStart(2, '0'),
      })
      this.drawRing(totalSec, false)
    }
  },

  async _fetchActiveSession() {
    const local = wx.getStorageSync('pomodoro_running_state')
    try {
      const server = await api.get('/pomodoro/active')
      if (server) {
        // Preserve local free display offset before clearing storage
        if (local && local.sessionId === server.id && server.preset === 'free') {
          server._localFreeDisplayOffsetMs = Number(local.freeDisplayOffsetMs || 0)
          server._localElapsedSec = Number(local.elapsedSec || 0)
        }
        wx.removeStorageSync('pomodoro_running_state')
        return server
      }
      wx.removeStorageSync('pomodoro_running_state')
      return null
    } catch (_) {
    }
    if (local && (Date.now() - local.savedAt < 7200000)) {
      const cachedStartTime = Number(local.sessionStartTime)
      if (!Number.isFinite(cachedStartTime) || cachedStartTime <= 0) {
        wx.removeStorageSync('pomodoro_running_state')
        return null
      }
      const isPaused = !!local.isPaused
      return {
        id: local.sessionId,
        start_time: new Date(cachedStartTime).toISOString(),
        work_duration: local.workDuration || 0,
        break_duration: local.breakDuration || 0,
        preset: local.selectedPreset || 'standard',
        status: isPaused ? 'paused' : 'running',
        paused_at: isPaused && local.pauseStartTime
          ? new Date(local.pauseStartTime).toISOString()
          : null,
        total_paused_sec: Math.floor((local.totalPausedMs || 0) / 1000),
        subject_id: local.selectedSubjectId,
        subject_code: local.selectedSubjectCode || '',
        subject_name: local.selectedSubjectName || '',
        _local_elapsed_sec: local.isFreeTimer ? local.elapsedSec : undefined,
        _localFreeDisplayOffsetMs: local.isFreeTimer ? Number(local.freeDisplayOffsetMs || 0) : 0,
      }
    }
    wx.removeStorageSync('pomodoro_running_state')
    return null
  },

  _restoreSession(session) {
    // Free timer recovery
    if (session.preset === 'free') {
      this._restoreFreeSession(session)
      return
    }

    // Guard: if confirm snapshot is active, don't overwrite with server state
    const confirmSnapshot = this._confirmTimerSnapshot || wx.getStorageSync('pomodoro_confirm_pause')
    if (confirmSnapshot && confirmSnapshot.sessionId === session.id && this.data.showEndConfirm) {
      return
    }

    const startTime = parseServerTime(session.start_time)
    const totalSec = session.work_duration * 60

    if (!Number.isFinite(startTime) || !Number.isFinite(totalSec) || totalSec <= 0) {
      wx.removeStorageSync('pomodoro_pause')
      wx.removeStorageSync('pomodoro_running_state')
      this._resetToIdle()
      wx.showToast({ title: '番茄钟状态异常，已重置', icon: 'none' })
      return
    }

    // Compute effective paused ms: server base + current segment + local adjustment
    const serverBaseMs = (session.total_paused_sec || 0) * 1000
    let totalPausedMs = serverBaseMs
    let isPaused = false

    const savedPause = wx.getStorageSync('pomodoro_pause')
    if (savedPause && savedPause.sessionId === session.id) {
      const savedTotal = Number(savedPause.totalPausedMs || 0)
      const pauseStart = Number(savedPause.pauseStartTime || Date.now())
      totalPausedMs = Number.isFinite(savedTotal) && Number.isFinite(pauseStart)
        ? savedTotal + (Date.now() - pauseStart)
        : serverBaseMs
      isPaused = totalPausedMs > 0
    } else if (session.paused_at) {
      const pausedAtMs = parseServerTime(session.paused_at)
      if (Number.isFinite(pausedAtMs)) {
        totalPausedMs = serverBaseMs + Math.max(0, Date.now() - pausedAtMs)
        isPaused = true
      }
    }

    if (!Number.isFinite(totalPausedMs) || totalPausedMs < 0) totalPausedMs = 0

    // Apply local pause adjustment (e.g. from cancelEndConfirm)
    totalPausedMs = this._mergeLocalPauseAdjustment(session.id, totalPausedMs)

    const elapsed = Math.floor((Date.now() - startTime - totalPausedMs) / 1000)
    const remaining = Number.isFinite(totalSec) && Number.isFinite(elapsed)
      ? Math.max(0, totalSec - elapsed) : 0

    // Resolve subject from session (legacy cache may only carry subject_code)
    const subjectId = session.subject_id || this._lookupSubjectIdByCode(session.subject_code) || null
    const subjectCode = session.subject_code || ''
    const subjectName = session.subject_name || '未分类'

    if (remaining <= 0) {
      wx.removeStorageSync('pomodoro_pause')
      wx.removeStorageSync('pomodoro_running_state')
      api.post(`/pomodoro/${session.id}/complete`, {
        total_paused_ms: totalPausedMs || 0,
        actual_duration_sec: session.work_duration * 60,
      }).catch(() => {
        api.post(`/pomodoro/${session.id}/interrupt`, {
          total_paused_ms: totalPausedMs || 0,
          actual_duration_sec: session.work_duration * 60,
        }).catch(() => {})
      })
      this._timerState.totalPausedMs = 0
      this._timerState.pauseStartTime = null
      this.setData({
        selectedSubjectId: subjectId,
        selectedSubject: subjectId ? { id: subjectId, code: subjectCode, name: subjectName } : null,
        selectedPreset: session.preset || 'standard',
        workDuration: session.work_duration,
        breakDuration: session.break_duration,
        isPaused: false,
      })
      this._updateComputedFields()
      this.loadTodayStats()
      wx.vibrateLong()
      const motto = MOTTOES[Math.floor(Math.random() * MOTTOES.length)]
      const type = this._nextCelebrationType()
      wx.setStorageSync('pomodoro_completion', { motto, type: type, sessionId: session.id })
      this.setData({ showCelebration: true, celebrationMotto: motto, celebrationType: type })
      return
    }

    this._timerState.sessionId = session.id
    this._timerState.sessionStartTime = startTime
    this._timerState.remainingSec = remaining
    this._timerState.totalPausedMs = totalPausedMs
    this._timerState.pauseStartTime = isPaused ? Date.now() : null
    this._timerState.progress = totalSec > 0 ? remaining / totalSec : 0
    this.setData({
      phase: PHASE.RUNNING,
      ringCanvasVisible: true,
      selectedSubjectId: subjectId,
      selectedSubject: subjectId ? { id: subjectId, code: subjectCode, name: subjectName } : null,
      selectedPreset: session.preset || 'standard',
      workDuration: session.work_duration,
      breakDuration: session.break_duration,
      displayMin: String(Math.floor(remaining / 60)).padStart(2, '0'),
      displaySec: String(remaining % 60).padStart(2, '0'),
      isPaused: isPaused,
    })

    if (isPaused) {
      wx.setStorageSync('pomodoro_pause', {
        totalPausedMs: totalPausedMs,
        pauseStartTime: Date.now(),
        sessionId: session.id,
      })
      // Draw ring at the paused progress — canvas never destroyed with hidden
      wx.nextTick(() => {
        this._initCanvas(true)
        this.drawRing(totalSec, false)
      })
    } else {
      this._startTimer(totalSec)
    }
    this._updateComputedFields()
  },

  _restoreFreeSession(session) {
    const startTime = parseServerTime(session.start_time)
    if (!Number.isFinite(startTime) || startTime <= 0) {
      wx.removeStorageSync('pomodoro_free_pause')
      wx.removeStorageSync('pomodoro_running_state')
      this._resetToIdle()
      return
    }

    // Restore local display offset (from running_state or free_pause)
    const localOffsetMs = Number(session._localFreeDisplayOffsetMs || 0)
    const hasLocalOffset = Number.isFinite(localOffsetMs) && localOffsetMs >= 0 && session._localFreeDisplayOffsetMs !== undefined

    const serverTotalPausedSec = session.total_paused_sec || 0
    const savedPause = wx.getStorageSync('pomodoro_free_pause')
    let totalPausedMs = serverTotalPausedSec * 1000
    let isPaused = false
    let savedElapsed = 0
    let savedOffsetMs = 0

    if (savedPause && savedPause.sessionId === session.id) {
      const savedTotal = Number(savedPause.totalPausedMs || 0)
      const pauseStart = Number(savedPause.pauseStartTime || Date.now())
      totalPausedMs = Number.isFinite(savedTotal) && Number.isFinite(pauseStart)
        ? savedTotal + (Date.now() - pauseStart)
        : totalPausedMs
      isPaused = true
      savedElapsed = Number(savedPause.elapsedSec || 0)
      savedOffsetMs = Number(savedPause.freeDisplayOffsetMs || 0)
    } else if (session.paused_at) {
      const pausedAtMs = parseServerTime(session.paused_at)
      if (Number.isFinite(pausedAtMs)) {
        isPaused = true
        totalPausedMs += Date.now() - pausedAtMs
      }
    }

    if (!Number.isFinite(totalPausedMs) || totalPausedMs < 0) totalPausedMs = 0

    // Apply local pause adjustment (e.g. from cancelEndConfirm)
    totalPausedMs = this._mergeLocalPauseAdjustment(session.id, totalPausedMs)

    // Determine effective offset: from running_state, or from free_pause fallback
    const effectiveOffset = hasLocalOffset ? localOffsetMs : savedOffsetMs
    const hasEffectiveOffset = hasLocalOffset || (savedOffsetMs > 0)

    // Use unified elapsed calculation with offset, or fallback to server elapsed
    let elapsed
    if (hasEffectiveOffset && !isPaused) {
      this._timerState.freeDisplayOffsetMs = effectiveOffset
      elapsed = Math.floor(this._getFreeElapsedMs() / 1000)
    } else if (hasEffectiveOffset && isPaused) {
      this._timerState.freeDisplayOffsetMs = effectiveOffset
      elapsed = savedElapsed || Math.floor(this._getFreeElapsedMs() / 1000)
    } else {
      // No local offset — fallback to server elapsed (other device or cold restore)
      this._timerState.freeDisplayOffsetMs = 0
      elapsed = isPaused
        ? savedElapsed || Math.max(0, Math.floor((Date.now() - startTime - totalPausedMs) / 1000))
        : Math.max(0, Math.floor((Date.now() - startTime - totalPausedMs) / 1000))
    }

    // Cap elapsed at 5-hour max to prevent display showing >05:00:00 during restore
    elapsed = Math.min(elapsed, Math.floor(FREE_TIMER_MAX_MS / 1000))

    const fmt = formatElapsedSec(elapsed)

    // Resolve subject (legacy cache may only carry subject_code)
    const subjectId = session.subject_id || this._lookupSubjectIdByCode(session.subject_code) || null
    const subjectCode = session.subject_code || ''
    const subjectName = session.subject_name || '未分类'

    this._clearTimer()
    this._timerState.sessionId = session.id
    this._timerState.sessionStartTime = startTime
    this._timerState.totalPausedMs = totalPausedMs
    this._timerState.pauseStartTime = isPaused ? Date.now() : null
    this._timerState.elapsedSec = elapsed
    this._timerState.freeFriendlyText = ''
    this._timerState.progress = 1
    this.setData({
      phase: PHASE.RUNNING,
      ringCanvasVisible: true,
      isFreeTimer: true,
      selectedSubjectId: subjectId,
      selectedSubject: subjectId ? { id: subjectId, code: subjectCode, name: subjectName } : null,
      selectedPreset: 'free',
      workDuration: 0,
      breakDuration: 0,
      isPaused: isPaused,
      freeDisplayTime: fmt.display,
      showEndConfirm: false,
    })
    this._updateComputedFields()

    setTimeout(() => { this._initCanvas(); this.drawRing(0, false) }, 200)

    if (!isPaused) {
      this._startFreeTimerInterval()
      // Check limit immediately after starting interval so elapsed never stays >5h
      this._checkFreeTimerLimitAndAutoEnd()
    }
  },

  _restoreBreak() {
    try {
      const saved = wx.getStorageSync('pomodoro_break')
      if (!saved) return
      wx.removeStorageSync('pomodoro_break')
      const elapsed = Math.floor((Date.now() - saved.startTime) / 1000)
      const remaining = Math.max(0, saved.totalSec - elapsed)
      if (remaining <= 0) {
        this._resetToIdle()
        return
      }
      this._timerState.remainingSec = remaining
      this._timerState.progress = remaining / saved.totalSec
      this.setData({
        phase: PHASE.BREAK,
        displayMin: String(Math.floor(remaining / 60)).padStart(2, '0'),
        displaySec: String(remaining % 60).padStart(2, '0'),
      })
      this._startBreak(remaining > 0 ? remaining : saved.totalSec)
    } catch (_) {}
  },

  /* ==================== Progress Ring (Canvas 2D) ==================== */

  _initCanvas(force) {
    if (!force && this._canvasReady && this._ctx) return
    this._canvasReady = false
    this._ctx = null
    this._ringCache = null // 清除缓存的渐变/几何
    this._scheduleCanvasInit(0)
  },

  _scheduleCanvasInit(retryCount) {
    if (retryCount > 5) return
    wx.nextTick(() => {
      const query = wx.createSelectorQuery().in(this)
      query.select('#progress-ring')
        .fields({ node: true, size: true })
        .exec((res) => {
          if (!res || !res[0] || !res[0].node || !res[0].width || !res[0].height) {
            this._scheduleCanvasInit(retryCount + 1)
            return
          }
          const canvas = res[0].node
          const windowInfo = wx.getWindowInfo ? wx.getWindowInfo() : {}
          const dpr = windowInfo.pixelRatio || 1
          this._dpr = dpr
          const width = res[0].width
          const height = res[0].height
          this._canvasSize = Math.min(width, height)
          canvas.width = Math.round(width * dpr)
          canvas.height = Math.round(height * dpr)
          const ctx = canvas.getContext('2d')
          ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
          this._ctx = ctx
          this._canvasReady = true
          this._ringCache = null // 重建后缓存失效
          if (this._pendingDraw) {
            this.drawRing(this._pendingDraw.totalSec, this._pendingDraw.isBreak)
            this._pendingDraw = null
          }
        })
    })
  },

  _buildRingCache(isBreak) {
    var ctx = this._ctx
    if (!ctx) return null
    var size = this._canvasSize
    var center = size / 2
    var radius = center - 18
    var lineWidth = 12
    var colors = isBreak
      ? { start: '#F43F5E', end: '#F97316', dot: '#F97316' }
      : this.data.isFreeTimer
        ? { start: '#34D399', end: '#059669', dot: '#10B981' }
        : { start: '#06B6D4', end: '#3B82F6', dot: '#3B82F6' }
    // 构建渐变（颜色在 session 内不变，只需构建一次）
    var glowGrad = ctx.createLinearGradient(0, 0, size, size)
    glowGrad.addColorStop(0, colors.start)
    glowGrad.addColorStop(1, colors.end)
    var grad = ctx.createLinearGradient(0, 0, size, size)
    grad.addColorStop(0, colors.start)
    grad.addColorStop(1, colors.end)
    return {
      size: size,
      center: center,
      radius: radius,
      lineWidth: lineWidth,
      colors: colors,
      glowGrad: glowGrad,
      grad: grad,
    }
  },

  drawRing(totalSec, isBreak) {
    if (!this._ctx) {
      this._pendingDraw = { totalSec, isBreak }
      return
    }
    var ctx = this._ctx
    var progress = this._timerState.progress
    // progress 未变化时不重绘（避免每帧重建 canvas）
    // 允许极小变化（< 1/360）跳过重绘
    if (this._lastDrawnProgress !== undefined && this._lastDrawnIsBreak === isBreak) {
      var diff = Math.abs(progress - this._lastDrawnProgress)
      if (diff < 1 / 360) return
    }
    this._lastDrawnProgress = progress
    this._lastDrawnIsBreak = isBreak

    // 缓存渐变和几何，仅在 isBreak/freeTimer 切换时重建
    var cacheKey = (isBreak ? 'break' : (this.data.isFreeTimer ? 'free' : 'focus')) + '|' + this.data.themeMode
    if (!this._ringCache || this._ringCache._key !== cacheKey) {
      this._ringCache = this._buildRingCache(isBreak)
      if (this._ringCache) this._ringCache._key = cacheKey
    }
    var cache = this._ringCache
    if (!cache) return

    var center = cache.center
    var radius = cache.radius
    var lineWidth = cache.lineWidth
    var colors = cache.colors

    ctx.clearRect(0, 0, cache.size, cache.size)

    if (progress > 0) {
      ctx.beginPath()
      ctx.strokeStyle = cache.glowGrad
      ctx.lineWidth = lineWidth + 14
      ctx.lineCap = 'round'
      ctx.globalAlpha = 0.18
      ctx.arc(center, center, radius, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * progress)
      ctx.stroke()
      ctx.globalAlpha = 1
    }

    ctx.beginPath()
    ctx.strokeStyle = this.data.themeMode === 'light' ? 'rgba(21,51,35,0.12)' : 'rgba(255,255,255,0.06)'
    ctx.lineWidth = lineWidth
    ctx.arc(center, center, radius, 0, Math.PI * 2)
    ctx.stroke()

    ctx.beginPath()
    ctx.strokeStyle = cache.grad
    ctx.lineWidth = lineWidth
    ctx.lineCap = 'round'
    ctx.arc(center, center, radius, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * progress)
    ctx.stroke()

    if (progress > 0 && progress < 1) {
      var endAngle = -Math.PI / 2 + Math.PI * 2 * progress
      var endX = center + radius * Math.cos(endAngle)
      var endY = center + radius * Math.sin(endAngle)
      ctx.beginPath()
      ctx.fillStyle = colors.dot
      ctx.arc(endX, endY, lineWidth / 2 + 1, 0, Math.PI * 2)
      ctx.fill()
    }
  },

  _resetToIdle() {
    this._clearFreeTimerInterval()
    this._confirmTimerSnapshot = null
    this._canvasReady = false
    this._ctx = null
    this._pendingDraw = null
    this._lastDrawnProgress = undefined
    this._lastDrawnIsBreak = undefined
    this._ringCache = null
    this._timerState = this._createTimerState()
    wx.removeStorageSync('pomodoro_break')
    wx.removeStorageSync('pomodoro_completion')
    wx.removeStorageSync('pomodoro_pause')
    wx.removeStorageSync('pomodoro_free_pause')
    wx.removeStorageSync('pomodoro_running_state')
    wx.removeStorageSync('pomodoro_confirm_pause')
    wx.removeStorageSync('pomodoro_pause_adjustment')
    this.setData({
      phase: PHASE.IDLE,
      displayMin: '00',
      displaySec: '00',
      isPaused: false,
      isFreeTimer: false,
      freeDisplayTime: '00:00:00',
      showEndConfirm: false,
      endConfirmTheme: '',
      endConfirmTitle: '',
      endConfirmText: '',
    })
    this._updateComputedFields()
  },

  /* ==================== Stats ==================== */

  async loadTodayStats() {
    try {
      const stats = await api.get('/pomodoro/stats')
      const m = Math.floor((stats.today_duration_sec || 0) / 60)
      this._timerState.todayDurationSec = stats.today_duration_sec || 0
      this.setData({
        todaySessions: stats.today_sessions || 0,
        todayDurationText: m >= 60 ? `${Math.floor(m / 60)}时${m % 60}分` : `${m}分钟`,
      })
    } catch (_) {}
  },

  goStats() {
    this._navigatingToStats = true
    wx.navigateTo({ url: '/subpackages/productivity/pomodoro-stats/index' })
  },


  /* ==================== Theme ==================== */

  _getThemeViewModel(mode) {
    const themeMode = pomodoroTheme.normalizeTheme(mode)
    const isLight = themeMode === 'light'
    return {
      themeMode,
      sliderBlockColor: isLight ? '#153323' : '#ffffff',
      sliderTrackColor: isLight ? 'rgba(21,51,35,0.12)' : 'rgba(255,255,255,0.06)',
      celebrationTheme: isLight ? 'light' : 'dark',
    }
  },

  _syncThemeFromStorage() {
    const themeMode = pomodoroTheme.getTheme()
    pomodoroTheme.applyNativeTheme(themeMode)
    if (themeMode === this.data.themeMode) return
    this._applyTheme(themeMode, false, false)
  },

  _applyTheme(mode, persist, animate) {
    const themeMode = pomodoroTheme.normalizeTheme(mode)
    if (persist) pomodoroTheme.setTheme(themeMode)
    pomodoroTheme.applyNativeTheme(themeMode)

    if (this._themeSwitchTimer) {
      clearTimeout(this._themeSwitchTimer)
      this._themeSwitchTimer = null
    }

    const patch = this._getThemeViewModel(themeMode)
    if (animate) patch.themeSwitching = true
    this.setData(patch, () => {
      this._ringCache = null
      this._lastDrawnProgress = undefined
      this._lastDrawnIsBreak = undefined
      if ((this.data.phase === PHASE.RUNNING || this.data.phase === PHASE.BREAK) &&
          this.data.ringCanvasVisible && !this.data.showEndConfirm) {
        wx.nextTick(() => this.drawRing(this._getCurrentTotalSec(), this.data.phase === PHASE.BREAK))
      }
    })

    if (animate) {
      this._themeSwitchTimer = setTimeout(() => {
        this._themeSwitchTimer = null
        this.setData({ themeSwitching: false })
      }, 520)
    }
  },

  toggleTheme() {
    const next = this.data.themeMode === 'dark' ? 'light' : 'dark'
    this._applyTheme(next, true, true)
  },

  /* ==================== Font Size Toggle ==================== */

  cycleFontSize() {
    const levels = ['medium', 'large']
    const current = this.data.fontSizeLevel
    const idx = levels.indexOf(current)
    const next = levels[(idx + 1) % levels.length]
    this.setData({ fontSizeLevel: next })
    wx.setStorageSync('pomodoro_font_size', next)
  },

  _updateComputedFields() {
    const subj = this.data.selectedSubject
    this.setData({
      selectedSubjectLabel: subj ? subj.name : '',
      selectedSubjectEmoji: subj ? subjectEmojiByCode(subj.code) : '📚',
      selectedPresetLabel: this.presetLabel(this.data.selectedPreset),
    })
  },

  /* ==================== Utility ==================== */

  subjectLabel(key) {
    const { getSubjectName } = require('../../utils/subject-meta')
    const s = this.data.subjects.find(s => s.code === key)
    return s ? s.name : getSubjectName(key)
  },

  subjectColor(key) {
    return '#3B82F6'
  },

  subjectEmoji(key) {
    return subjectEmojiByCode(key)
  },

  presetLabel(key) {
    const p = PRESETS.find(p => p.key === key)
    return p ? p.label : key
  },

  _nextCelebrationType() {
    var types = ['excellent', 'award', 'thumbsUp']
    var idx = wx.getStorageSync('pomodoro_anim_idx') || 0
    var next = (idx + 1) % types.length
    wx.setStorageSync('pomodoro_anim_idx', next)
    return types[idx]
  },

  getDateStr() {
    const d = new Date()
    const week = ['日', '一', '二', '三', '四', '五', '六']
    return `${d.getMonth() + 1}月${d.getDate()}日 星期${week[d.getDay()]}`
  },

  _getExamDays() {
    const now = new Date()
    now.setHours(0, 0, 0, 0)
    const getExamDate = (year) => {
      const dec31 = new Date(year, 11, 31)
      const dayOfWeek = dec31.getDay()
      const lastSaturday = dec31.getDate() - ((dayOfWeek - 6 + 7) % 7)
      const targetDay = lastSaturday - 7
      return new Date(year, 11, targetDay)
    }
    let examDate = getExamDate(now.getFullYear())
    if (examDate < now) {
      examDate = getExamDate(now.getFullYear() + 1)
    }
    const diff = Math.ceil((examDate - now) / (1000 * 60 * 60 * 24))
    return Math.max(0, diff)
  },

})
