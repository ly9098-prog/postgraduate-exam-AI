const api = require('../../utils/api')
const config = require('../../config')
const { safeDecodeURIComponent } = require('../../utils/route-params')
const pomodoroTheme = require('../../utils/pomodoro-theme')
const { parseServerUtc, getChinaWallParts, getChinaDayStartUtcMs } = require('../../utils/china-time')

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
const POMODORO_LOCAL_STATE_TTL_MS = 6 * 60 * 60 * 1000
const POMODORO_PENDING_SYNC_TTL_MS = 7 * 24 * 60 * 60 * 1000
const POMODORO_PENDING_SYNC_KEY = 'pomodoro_pending_sync' // v2 stores an ordered array; legacy object is migrated on read

function parseServerTime(value) {
  return parseServerUtc(value)
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
    endConfirmLine1: '',
    endConfirmLine2: '',
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
    ringCanvasPaintReady: false,
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
  _canvasInitSeq: 0,

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
    const activeSyncSeq = (this._activeSyncSeq || 0) + 1
    this._activeSyncSeq = activeSyncSeq
    this._syncThemeFromStorage()

    // Capture any action that timed out previously. It will be retried after the
    // local snapshot has restored the first frame, so network work never blocks UI.
    const pendingSync = this._getPendingPomodoroSync()

    // Make the page visible immediately. Active-session reconciliation must not
    // block the first frame behind a network request.
    if (!this.data.pageEntered) {
      this.setData({ pageEntered: true })
    }

    // Completion flag — check before active fetch since it may short-circuit
    const completionFlag = wx.getStorageSync('pomodoro_completion')
    if (completionFlag) {
      if (!completionFlag.sessionId) {
        wx.removeStorageSync('pomodoro_completion')
      } else if (!this.data.showCelebration) {
        wx.vibrateLong()
        this.setData({ showCelebration: true, celebrationMotto: completionFlag.motto, celebrationType: completionFlag.type || 'excellent' })
        // Celebration rendering must not suppress a pending completion retry.
        if (pendingSync) this._retryPendingPomodoroSync()
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
      const restoredConfirmSeq = (this._confirmActionSeq || 0) + 1
      this._confirmActionSeq = restoredConfirmSeq
      confirmSnapshot.confirmActionSeq = restoredConfirmSeq
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
          this._postPauseWithRetry(confirmSnapshot.sessionId, confirmSnapshot.openedAt)
            .then(() => {
              if (confirmSnapshot.confirmActionSeq !== this._confirmActionSeq || !this.data.showEndConfirm) return
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
        this._postPauseWithRetry(confirmSnapshot.sessionId, confirmSnapshot.openedAt)
          .then(() => {
            if (confirmSnapshot.confirmActionSeq !== this._confirmActionSeq || !this.data.showEndConfirm) return
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

    // Restore from the local running snapshot first so the dial starts moving
    // without waiting for /pomodoro/active. The server response below remains
    // authoritative and will reconcile stale/cross-device state afterwards.
    const cachedActive = this._getCachedActiveSession()
    let restoredFromCache = false
    if (cachedActive) {
      if (this._canLightSyncActive(cachedActive)) {
        this._syncActiveSessionLight(cachedActive)
      } else {
        this._restoreSession(cachedActive)
      }
      restoredFromCache = this.data.phase === PHASE.RUNNING && this._timerState.sessionId === cachedActive.id
    }

    // Breaks are purely local and must resume immediately, even while the network
    // is offline or an earlier completion is waiting to synchronize.
    let restoredBreak = false
    if (!cachedActive && this.data.phase !== PHASE.RUNNING) {
      restoredBreak = this._restoreBreak()
    }

    if (pendingSync) {
      const synced = await this._retryPendingPomodoroSync()
      if (!this._pageVisible || activeSyncSeq !== this._activeSyncSeq) return
      if (!synced) {
        // Keep the locally restored state stable while offline. Fetching /active
        // after a failed retry can only return the same stale server state and may
        // undo an optimistic pause/resume or resurrect a locally completed timer.
        setTimeout(() => this.loadTodayStats(), 200)
        return
      }
    }

    const active = await this._fetchActiveSession()
    if (!this._pageVisible || activeSyncSeq !== this._activeSyncSeq) return

    const activeHasPendingTerminal = active && this._hasPendingPomodoroAction(active.id, ['complete', 'interrupt'])
    if (activeHasPendingTerminal) {
      // A terminal local action is final from the user's perspective. Never
      // resurrect the same stale server row while its retry remains queued.
      wx.removeStorageSync('pomodoro_running_state')
    } else if (active) {
      if (restoredBreak) {
        this._clearTimer()
        wx.removeStorageSync('pomodoro_break')
        restoredBreak = false
      }
      if (this._canLightSyncActive(active)) {
        this._syncActiveSessionLight(active)
      } else {
        this._restoreSession(active)
      }
    } else if (restoredFromCache && this.data.phase === PHASE.RUNNING) {
      // Server confirmed there is no active session. Discard the optimistic
      // local recovery instead of leaving a stale timer running indefinitely.
      this._resetToIdle()
      this._restoreBreak()
    } else if (this.data.phase !== PHASE.RUNNING && !restoredBreak) {
      this._restoreBreak()
    }

    // Deferred: stats don't block active session recovery
    setTimeout(() => this.loadTodayStats(), 200)
  },

  onHide() {
    this._pageVisible = false
    this._activeSyncSeq = (this._activeSyncSeq || 0) + 1
    this._startRequestSeq = (this._startRequestSeq || 0) + 1

    // Native 2D canvas backing surfaces may be recreated while a Mini Program page
    // is hidden. Never reuse a context across onHide/onShow, even when selector
    // initialization had already completed successfully.
    this._canvasInitSeq = (this._canvasInitSeq || 0) + 1
    this._canvasInitPending = false
    this._canvasReady = false
    this._ctx = null
    this._ringCache = null
    this._pendingDraw = null
    this._lastDrawnProgress = undefined
    this._lastDrawnIsBreak = undefined
    if (this.data.ringCanvasPaintReady) this.setData({ ringCanvasPaintReady: false })

    // A start ceremony is UI-only. Leaving the page cancels it so its delayed
    // callback cannot create a hidden server session.
    if (this.data.phase === PHASE.CEREMONY) this.setData({ phase: PHASE.IDLE })

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
    this._pageVisible = false
    this._activeSyncSeq = (this._activeSyncSeq || 0) + 1
    this._startRequestSeq = (this._startRequestSeq || 0) + 1
    this._canvasInitSeq = (this._canvasInitSeq || 0) + 1
    this._canvasInitPending = false
    this._canvasReady = false
    this._ctx = null
    this._ringCache = null
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
    const startSeq = (this._startRequestSeq || 0) + 1
    this._startRequestSeq = startSeq

    // Flush any earlier local actions first. A terminal complete/interrupt that is
    // still pending would otherwise make /start collide with the old active row.
    if (this._getPendingPomodoroSyncQueue().length) {
      const synced = await this._retryPendingPomodoroSync()
      if (!this._pageVisible || startSeq !== this._startRequestSeq) return
      if (!synced) {
        wx.showToast({ title: '上次专注尚未同步，请联网后重试', icon: 'none' })
        return
      }
    }

    if (!this.data.selectedSubjectId || !this.data.selectedSubject) {
      wx.showToast({ title: '请选择学习科目', icon: 'none' })
      return
    }
    if (this.data.subjectsError) {
      wx.showToast({ title: '科目加载异常，请重试', icon: 'none' })
      return
    }

    if (this.data.selectedPreset === 'free') {
      await this._startFreeSession(startSeq)
      return
    }

    this.setData({ phase: PHASE.CEREMONY })
    await new Promise(r => setTimeout(r, this.data.selectedPreset === 'debug' ? 1000 : 2500))
    if (!this._pageVisible || startSeq !== this._startRequestSeq || this.data.phase !== PHASE.CEREMONY) return

    try {
      const session = await api.post('/pomodoro/start', {
        subject_id: this.data.selectedSubjectId,
        chapter_id: this.data.fromChapterId || null,
        preset: this.data.selectedPreset,
        work_duration: this.data.selectedPreset === 'debug' ? 1 : this.data.workDuration,
        break_duration: this.data.selectedPreset === 'debug' ? 1 : this.data.breakDuration,
      })
      if (!this._pageVisible || startSeq !== this._startRequestSeq) {
        // Request crossed a lifecycle boundary. Do not leave a hidden active row.
        this._setPendingPomodoroSync('interrupt', session.id)
        this._retryPendingPomodoroSync()
        return
      }
      this._beginCountdown(session)
    } catch (e) {
      if (!this._pageVisible || startSeq !== this._startRequestSeq) return
      const detail = (e && (e.detail || e.message || '')) || ''
      const isActiveConflict = (e && e.statusCode === 409) || /active|running|进行中/.test(detail)
      if (isActiveConflict) {
        wx.showToast({ title: '已有进行中的专注，请先结束', icon: 'none' })
        const active = await this._fetchActiveSession()
        if (this._pageVisible && startSeq === this._startRequestSeq && active) this._restoreSession(active)
      } else {
        wx.showToast({ title: '启动失败', icon: 'none' })
        this.setData({ phase: PHASE.IDLE })
      }
    }
  },

  /* ==================== Free Timer ==================== */

  async _startFreeSession(existingStartSeq) {
    const startSeq = existingStartSeq || ((this._startRequestSeq || 0) + 1)
    if (!existingStartSeq) this._startRequestSeq = startSeq

    if (this._getPendingPomodoroSyncQueue().length) {
      const synced = await this._retryPendingPomodoroSync()
      if (!this._pageVisible || startSeq !== this._startRequestSeq) return
      if (!synced) {
        wx.showToast({ title: '上次专注尚未同步，请联网后重试', icon: 'none' })
        return
      }
    }
    try {
      const session = await api.post('/pomodoro/start', {
        subject_id: this.data.selectedSubjectId,
        chapter_id: this.data.fromChapterId || null,
        preset: 'free',
        work_duration: 0,
        break_duration: 0,
      })
      if (!this._pageVisible || startSeq !== this._startRequestSeq) {
        this._setPendingPomodoroSync('interrupt', session.id)
        this._retryPendingPomodoroSync()
        return
      }
      this._beginFreeTimer(session)
    } catch (e) {
      if (!this._pageVisible || startSeq !== this._startRequestSeq) return
      const detail = (e && (e.detail || e.message || '')) || ''
      const isActiveConflict = (e && e.statusCode === 409) || /active|running|进行中/.test(detail)
      if (isActiveConflict) {
        wx.showToast({ title: '已有进行中的专注，请先结束', icon: 'none' })
        const active = await this._fetchActiveSession()
        if (this._pageVisible && startSeq === this._startRequestSeq && active) this._restoreSession(active)
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
      this._initCanvas(true)
      this.drawRing(0, false)
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
    const sessionId = this._timerState.sessionId
    const pauseStartedAt = Date.now()

    this._updateFreeElapsed()
    this._clearFreeTimerInterval()
    this._timerState.pauseStartTime = pauseStartedAt
    this._timerState.freeFriendlyText = formatElapsedSec(this._timerState.elapsedSec).friendly
    this.setData({ isPaused: true, actionLoading: true })
    wx.setStorageSync('pomodoro_free_pause', {
      totalPausedMs: this._timerState.totalPausedMs || 0,
      pauseStartTime: pauseStartedAt,
      sessionId,
      elapsedSec: this._timerState.elapsedSec,
      freeDisplayOffsetMs: this._timerState.freeDisplayOffsetMs || 0,
    })

    this._setPendingPomodoroSync('pause', sessionId, pauseStartedAt)
    this.setData({ actionLoading: false })
    this._retryPendingPomodoroSync().then(synced => {
      if (!synced) wx.showToast({ title: '已暂停，网络恢复后自动同步', icon: 'none' })
    })
  },

  async _resumeFreeTimer() {
    if (!this._timerState.sessionId || this.data.actionLoading) return
    const sessionId = this._timerState.sessionId
    const now = Date.now()
    const openPauseMs = this._timerState.pauseStartTime
      ? Math.max(0, now - this._timerState.pauseStartTime)
      : 0
    const localTotalPausedMs = Math.max(0, Number(this._timerState.totalPausedMs || 0) + openPauseMs)

    wx.setStorageSync('pomodoro_pause_adjustment', {
      sessionId,
      totalPausedMs: localTotalPausedMs,
      savedAt: now,
    })
    wx.removeStorageSync('pomodoro_free_pause')
    this._timerState.totalPausedMs = localTotalPausedMs
    this._timerState.pauseStartTime = null
    this.setData({ isPaused: false, ringCanvasVisible: true, actionLoading: true })
    this._startFreeTimerInterval()

    // Queue ordering is important: if a previous /pause timed out, it stays ahead
    // of this /resume and is synchronized first instead of being overwritten.
    this._setPendingPomodoroSync('resume', sessionId, now)
    this.setData({ actionLoading: false })
    this._retryPendingPomodoroSync().then(synced => {
      if (!synced) wx.showToast({ title: '已继续计时，网络恢复后自动同步', icon: 'none' })
    })
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
      const hasElapsed = elapsed >= 1
      return {
        showEndConfirm: true,
        endConfirmTheme: 'free',
        endConfirmTitle: '结束自由计时？',
        endConfirmText: hasElapsed
          ? `本次已专注 ${fmt.friendly}，确认后将计入学习统计。`
          : '当前计时时长较短，确认后仍会结束本次计时。',
        // cover-view 在部分基础库/真机上不会可靠自动换行，显式拆行为两行。
        endConfirmLine1: hasElapsed ? `本次已专注 ${fmt.friendly}` : '当前计时时长较短',
        endConfirmLine2: hasElapsed ? '确认后将计入学习统计。' : '确认后仍会结束本次计时。',
        endConfirmOkText: '确认结束',
        endConfirmCancelText: '继续计时',
      }
    }

    if (mode === 'countdown-interrupt') {
      const isBreak = snapshot.phase === 'break'
      const elapsedSec = Math.max(0, (snapshot.totalSec || 0) - (snapshot.remainingSec || 0))
      const fmt = formatElapsedSec(elapsedSec)
      const hasElapsed = elapsedSec > 0
      return {
        showEndConfirm: true,
        endConfirmTheme: isBreak ? 'break' : 'focus',
        endConfirmTitle: isBreak ? '结束休息？' : '结束本次专注？',
        endConfirmText: hasElapsed
          ? `本次已专注 ${fmt.friendly}。确认后将结束当前番茄钟。`
          : '确认后将结束当前番茄钟。',
        endConfirmLine1: hasElapsed ? `本次已专注 ${fmt.friendly}` : '确认后将结束当前番茄钟。',
        endConfirmLine2: hasElapsed ? '确认后将结束当前番茄钟。' : '',
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

    const confirmActionSeq = (this._confirmActionSeq || 0) + 1
    this._confirmActionSeq = confirmActionSeq
    const snapshot = {
      mode: 'free-complete',
      confirmActionSeq,
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
      this._postPauseWithRetry(this._timerState.sessionId, snapshot.openedAt)
        .then(() => {
          if (snapshot.confirmActionSeq !== this._confirmActionSeq || !this.data.showEndConfirm) return
          snapshot.backendPauseDone = true
          this._confirmTimerSnapshot = snapshot
          wx.setStorageSync('pomodoro_confirm_pause', snapshot)
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

  // Queue the confirm-window pause behind any earlier local mutations. This is
  // intentionally serialized with resume/complete/interrupt so a late /pause can
  // never arrive after the user has already chosen "continue".
  async _postPauseWithRetry(sessionId, clientActionAt) {
    this._setPendingPomodoroSync('pause', sessionId, clientActionAt)
    const synced = await this._retryPendingPomodoroSync()
    if (!synced) throw new Error('pomodoro pause sync pending')
    return true
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

    const confirmActionSeq = (this._confirmActionSeq || 0) + 1
    this._confirmActionSeq = confirmActionSeq
    const snapshot = {
      mode: 'countdown-interrupt',
      confirmActionSeq,
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

    // Sync backend pause asynchronously; the dialog appears immediately. The
    // confirmActionSeq guard prevents a late response from mutating a cancelled
    // confirmation snapshot.
    if (!wasPaused) {
      this._postPauseWithRetry(this._timerState.sessionId, snapshot.openedAt)
        .then(() => {
          if (snapshot.confirmActionSeq !== this._confirmActionSeq || !this.data.showEndConfirm) return
          snapshot.backendPauseDone = true
          this._confirmTimerSnapshot = snapshot
          wx.setStorageSync('pomodoro_confirm_pause', snapshot)
        })
        .catch(e => console.warn('confirm pause backend sync failed', e))
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
    this._confirmActionSeq = (this._confirmActionSeq || 0) + 1

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

      // 5. Queue backend resume after the confirm pause. The ordered queue keeps
      // pause -> resume sequencing stable even if the first request timed out.
      this._setPendingPomodoroSync('resume', snapshot.sessionId, now)
      this._retryPendingPomodoroSync().then(synced => {
        if (!synced) console.warn('resume after cancel confirm pending; keep local timer')
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
        // The 2D canvas is hidden while the cover-view confirm dialog is open.
        // On some real devices its backing surface is cleared while hidden, so
        // merely making it visible again leaves a blank dial. Rebuild and force
        // the first free-timer ring paint after the overlay is dismissed.
        this._redrawFreeRingAfterOverlay()
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
        this._redrawFreeRingAfterOverlay()
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
      this._redrawFreeRingAfterOverlay()

      // Backend resume is serialized behind the confirm pause.
      this._setPendingPomodoroSync('resume', snapshot.sessionId, now)
      this._retryPendingPomodoroSync().then(synced => {
        if (!synced) console.warn('resume free timer after cancel confirm pending; keep local timer')
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
    const sessionId = this._timerState.sessionId
    if (!sessionId) {
      this._confirmActionSeq = (this._confirmActionSeq || 0) + 1
      this._confirmTimerSnapshot = null
      wx.removeStorageSync('pomodoro_confirm_pause')
      this.setData({ showEndConfirm: false, actionLoading: false })
      return
    }
    this._confirmActionSeq = (this._confirmActionSeq || 0) + 1
    this.setData({ showEndConfirm: false, actionLoading: false })
    this._clearFreeTimerInterval()
    this._completeFreeTimerSession()
  },

  async _confirmInterruptCountdown() {
    if (!this._timerState.sessionId || this.data.actionLoading) return

    const sessionId = this._timerState.sessionId
    const snapshot = this._confirmTimerSnapshot
    let totalPausedMs = this._timerState.totalPausedMs || 0
    if (snapshot && snapshot.openedAt) {
      totalPausedMs = Math.max(0, Number(snapshot.totalPausedMs || 0) + (Date.now() - snapshot.openedAt))
    }
    this._timerState.totalPausedMs = totalPausedMs
    this._confirmActionSeq = (this._confirmActionSeq || 0) + 1

    // End locally first; the ordered queue persists the terminal mutation and
    // retries it without holding the UI behind a network timeout.
    this._setPendingPomodoroSync('interrupt', sessionId, Date.now())
    this._retryPendingPomodoroSync().then(synced => {
      if (!synced) wx.showToast({ title: '网络恢复后将自动同步', icon: 'none' })
      else this.loadTodayStats()
    })

    wx.showToast({ title: '已结束本次专注', icon: 'none' })
    wx.removeStorageSync('pomodoro_pause_adjustment')
    wx.removeStorageSync('pomodoro_confirm_pause')
    this._confirmTimerSnapshot = null
    this.setData({ showEndConfirm: false, actionLoading: false })
    this._resetToIdle()
  },

  async endSession() {
    if (!this._timerState.sessionId) return
    const sessionId = this._timerState.sessionId
    this._clearTimer()
    this._completePomodoroWithRetry(sessionId, Date.now()).then(synced => {
      if (synced) this.loadTodayStats()
    })
    this._resetToIdle()
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
    const sessionId = this._timerState.sessionId
    const pauseStartedAt = Date.now()

    this._clearTimer()
    this._timerState.pauseStartTime = pauseStartedAt
    this.setData({ isPaused: true, actionLoading: true })
    wx.setStorageSync('pomodoro_pause', {
      totalPausedMs: this._timerState.totalPausedMs || 0,
      pauseStartTime: pauseStartedAt,
      sessionId,
    })

    this._setPendingPomodoroSync('pause', sessionId, pauseStartedAt)
    this.setData({ actionLoading: false })
    this._retryPendingPomodoroSync().then(synced => {
      if (!synced) wx.showToast({ title: '已暂停，网络恢复后自动同步', icon: 'none' })
    })
  },

  async _resumeSession() {
    if (typeof this._timerState.sessionStartTime !== 'number' || this._timerState.sessionStartTime <= 0) {
      console.warn('resume aborted: invalid sessionStartTime', this._timerState.sessionStartTime)
      this._resetToIdle()
      return
    }
    if (!this._timerState.sessionId || this.data.actionLoading) return

    const sessionId = this._timerState.sessionId
    const now = Date.now()
    const openPauseMs = this._timerState.pauseStartTime
      ? Math.max(0, now - this._timerState.pauseStartTime)
      : 0
    const localTotalPausedMs = Math.max(0, Number(this._timerState.totalPausedMs || 0) + openPauseMs)
    const totalSec = this.data.selectedPreset === 'debug' ? 10 : (this.data.workDuration ?? 25) * 60

    wx.setStorageSync('pomodoro_pause_adjustment', {
      sessionId,
      totalPausedMs: localTotalPausedMs,
      savedAt: now,
    })
    wx.removeStorageSync('pomodoro_pause')
    this._timerState.totalPausedMs = localTotalPausedMs
    this._timerState.pauseStartTime = null
    this.setData({ isPaused: false, ringCanvasVisible: true, actionLoading: true })

    const elapsedMs = Math.max(0, now - this._timerState.sessionStartTime - localTotalPausedMs)
    const remainingMs = Math.max(0, totalSec * 1000 - elapsedMs)
    this._startTimer(totalSec, { remainingMs, forceRunning: true, reuseCanvas: true })

    this._setPendingPomodoroSync('resume', sessionId, now)
    this.setData({ actionLoading: false })
    this._retryPendingPomodoroSync().then(synced => {
      if (!synced) wx.showToast({ title: '已继续计时，网络恢复后自动同步', icon: 'none' })
    })
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

  /* ==================== Pending Network Sync ==================== */

  _getPendingPomodoroSyncQueue() {
    try {
      const raw = wx.getStorageSync(POMODORO_PENDING_SYNC_KEY)
      if (!raw) return []
      let list
      if (Array.isArray(raw)) {
        list = raw
      } else {
        // Migrate the previous single-slot format. The old implementation could
        // encode "pause/resume then complete" as completeAfter=true; preserve that
        // terminal action instead of silently dropping it during upgrade.
        list = [raw]
        if (raw.completeAfter && raw.sessionId && raw.action !== 'complete') {
          list.push({
            action: 'complete',
            sessionId: raw.sessionId,
            savedAt: Number(raw.savedAt || Date.now()),
            clientActionAt: Number(raw.savedAt || Date.now()),
            nonce: `${raw.nonce || 'legacy'}-complete`,
          })
        }
      }
      const now = Date.now()
      const validActions = ['pause', 'resume', 'complete', 'interrupt']
      const valid = list.filter(item => {
        const savedAt = Number(item && item.savedAt)
        return !!(
          item && item.sessionId && validActions.includes(item.action) &&
          Number.isFinite(savedAt) && savedAt > 0 &&
          savedAt <= now + 5 * 60 * 1000 &&
          now - savedAt <= POMODORO_PENDING_SYNC_TTL_MS
        )
      })
      if (valid.length !== list.length || !Array.isArray(raw)) {
        if (valid.length) wx.setStorageSync(POMODORO_PENDING_SYNC_KEY, valid)
        else wx.removeStorageSync(POMODORO_PENDING_SYNC_KEY)
      }
      return valid
    } catch (_) { return [] }
  },

  _getPendingPomodoroSync() {
    return this._getPendingPomodoroSyncQueue()[0] || null
  },

  _hasPendingPomodoroAction(sessionId, actions) {
    const allowed = Array.isArray(actions) ? actions : [actions]
    return this._getPendingPomodoroSyncQueue().some(item => (
      item.sessionId === sessionId && allowed.includes(item.action)
    ))
  },

  _setPendingPomodoroSync(action, sessionId, clientActionAt) {
    const queue = this._getPendingPomodoroSyncQueue()
    const last = queue[queue.length - 1]
    if (last && last.sessionId === sessionId && last.action === action) return last

    // complete/interrupt are terminal for a session. Reuse an already queued
    // terminal action instead of sending duplicate terminal mutations.
    if (action === 'complete' || action === 'interrupt') {
      const existing = queue.find(item => item.sessionId === sessionId && item.action === action)
      if (existing) return existing
    }

    const pending = {
      action,
      sessionId,
      savedAt: Date.now(),
      clientActionAt: Number.isFinite(clientActionAt) ? clientActionAt : Date.now(),
      nonce: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    }
    queue.push(pending)
    wx.setStorageSync(POMODORO_PENDING_SYNC_KEY, queue)
    return pending
  },

  _clearPendingPomodoroSync(expected) {
    try {
      if (!expected) {
        wx.removeStorageSync(POMODORO_PENDING_SYNC_KEY)
        return
      }
      const queue = this._getPendingPomodoroSyncQueue().filter(item => item.nonce !== expected.nonce)
      if (queue.length) wx.setStorageSync(POMODORO_PENDING_SYNC_KEY, queue)
      else wx.removeStorageSync(POMODORO_PENDING_SYNC_KEY)
    } catch (_) {}
  },

  async _retryPendingPomodoroSync() {
    if (this._pendingSyncDrainPromise) return this._pendingSyncDrainPromise

    this._pendingSyncDrainPromise = (async () => {
      while (true) {
        const queue = this._getPendingPomodoroSyncQueue()
        if (!queue.length) return true
        const pending = queue[0]
        try {
          let body = {}
          const actionAtMs = Number(pending.clientActionAt)
          if (Number.isFinite(actionAtMs) && actionAtMs > 0) {
            try {
              body = { client_action_at: new Date(actionAtMs).toISOString() }
            } catch (_) {}
          }
          await api.post(`/pomodoro/${pending.sessionId}/${pending.action}`, body)
          this._clearPendingPomodoroSync(pending)
        } catch (_) {
          return false
        }
      }
    })()

    try {
      return await this._pendingSyncDrainPromise
    } finally {
      this._pendingSyncDrainPromise = null
    }
  },

  async _completePomodoroWithRetry(sessionId, clientActionAt) {
    if (!sessionId) return false
    this._setPendingPomodoroSync('complete', sessionId, clientActionAt)
    const synced = await this._retryPendingPomodoroSync()
    return !!synced && !this._hasPendingPomodoroAction(sessionId, 'complete')
  },

  async _interruptPomodoroWithRetry(sessionId, clientActionAt) {
    if (!sessionId) return false
    this._setPendingPomodoroSync('interrupt', sessionId, clientActionAt)
    const synced = await this._retryPendingPomodoroSync()
    return !!synced && !this._hasPendingPomodoroAction(sessionId, 'interrupt')
  },

  /* ==================== Local Pause Adjustment ==================== */

  _getLocalPauseAdjustment(sessionId) {
    try {
      const adjust = wx.getStorageSync('pomodoro_pause_adjustment')
      if (!adjust || adjust.sessionId !== sessionId) return 0
      if (Date.now() - adjust.savedAt > POMODORO_LOCAL_STATE_TTL_MS) {
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

    await this._completeFreeTimerSession()

    this._freeTimerFinalizing = false
  },

  async _completeFreeTimerSession() {
    const sessionId = this._timerState.sessionId
    if (!sessionId) return
    this._clearFreeTimerInterval()
    const completedAt = Date.now()

    this._completePomodoroWithRetry(sessionId, completedAt).then(synced => {
      wx.showToast({
        title: synced ? '已记录本次专注' : '网络恢复后将自动同步',
        icon: 'none',
        duration: 2000,
      })
      if (synced) this.loadTodayStats()
    })

    // Do not keep the end-confirm UI blocked behind a 30s request timeout.
    this._resetToIdle()
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
    this._initCanvas(!options.reuseCanvas)

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
    const sessionId = this._timerState.sessionId
    if (!sessionId) {
      this._resetToIdle()
      return
    }

    const completedAt = Date.now()
    wx.vibrateLong()
    this._completePomodoroWithRetry(sessionId, completedAt).then(synced => {
      if (synced) {
        wx.removeStorageSync('pomodoro_pause_adjustment')
        this.loadTodayStats()
      } else {
        wx.showToast({ title: '已完成，网络恢复后自动同步', icon: 'none' })
      }
    })

    // Completion UI is local and immediate. The server-side /complete endpoint is
    // idempotent and duration-capped, so a delayed retry cannot inflate statistics.
    const motto = MOTTOES[Math.floor(Math.random() * MOTTOES.length)]
    const type = this._nextCelebrationType()
    wx.setStorageSync('pomodoro_completion', { motto, type, sessionId })
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

  _startBreak(totalSec, options = {}) {
    const originalTotalSec = Math.max(1, Number(totalSec) || 1)
    const breakStartTime = Number.isFinite(options.startTime) ? options.startTime : Date.now()
    const totalMs = originalTotalSec * 1000
    const naturalRemainingMs = Math.max(0, breakStartTime + totalMs - Date.now())
    const remainingMs = Number.isFinite(options.remainingMs)
      ? Math.max(0, Math.min(totalMs, options.remainingMs))
      : naturalRemainingMs

    if (remainingMs <= 0) {
      wx.removeStorageSync('pomodoro_break')
      this._resetToIdle()
      return
    }

    // Preserve the original break start/total across page restores. Re-basing the
    // timer to `remaining` made the dial jump back to a full ring on every onShow.
    wx.setStorageSync('pomodoro_break', { startTime: breakStartTime, totalSec: originalTotalSec })
    this._timerState.breakStartTime = breakStartTime
    this._timerState.remainingSec = Math.ceil(remainingMs / 1000)
    this._timerState.progress = remainingMs / totalMs
    const firstFmt = this._formatCountdownDisplay(this._timerState.remainingSec)
    this.setData({
      phase: PHASE.BREAK,
      ringCanvasVisible: true,
      displayMin: firstFmt.min,
      displaySec: firstFmt.sec,
    })
    this._clearTimer()
    this._initCanvas(true)
    this._countdownTotalSec = originalTotalSec
    this._countdownEndAt = breakStartTime + totalMs
    this.drawRing(originalTotalSec, true)

    const tick = () => {
      const currentRemainingMs = Math.max(0, this._countdownEndAt - Date.now())
      const displayRemainingSec = currentRemainingMs <= 0 ? 0 : Math.ceil(currentRemainingMs / 1000)
      const progress = currentRemainingMs / totalMs
      const fmt = this._formatCountdownDisplay(displayRemainingSec)

      if (
        displayRemainingSec !== this._timerState.remainingSec ||
        Math.abs(progress - this._timerState.progress) > 0.002
      ) {
        this._timerState.remainingSec = displayRemainingSec
        this._timerState.progress = progress
        this.setData({ displayMin: fmt.min, displaySec: fmt.sec })
      }
      this.drawRing(originalTotalSec, true)

      if (currentRemainingMs <= 0) {
        this._clearTimer()
        wx.removeStorageSync('pomodoro_break')
        this._resetToIdle()
        return
      }

      const nextDelay = Math.max(80, Math.min(250, currentRemainingMs % 1000 || 250))
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
    const serverStartTime = parseServerTime(active.start_time)
    if (Number.isFinite(serverStartTime) && serverStartTime > 0) {
      this._timerState.sessionStartTime = serverStartTime
    }

    const serverPausedMs = Math.max(0, Number(active.total_paused_sec || 0) * 1000)
    const localPausedMs = Math.max(0, Number(this._timerState.totalPausedMs || 0))
    const totalPausedMs = this._mergeLocalPauseAdjustment(
      this._timerState.sessionId,
      Math.max(serverPausedMs, localPausedMs)
    )
    this._timerState.totalPausedMs = totalPausedMs

    if (this.data.isFreeTimer) {
      if (!this._canvasReady || !this._ctx) {
        this._timerState.progress = 1
        wx.nextTick(() => {
          if (!this._pageVisible || this.data.phase !== PHASE.RUNNING || !this.data.isFreeTimer) return
          this._initCanvas(true)
          this.drawRing(0, false)
        })
      }
      if (!this.data.isPaused) {
        const elapsedMs = this._getEffectiveFreeElapsedMs(now)
        const cappedMs = Math.min(elapsedMs, FREE_TIMER_MAX_MS)
        const elapsed = Math.floor(cappedMs / 1000)
        if (elapsed !== this._timerState.elapsedSec) {
          const fmt = formatElapsedSec(elapsed)
          this._timerState.elapsedSec = elapsed
          this.setData({ freeDisplayTime: fmt.display })
        }
        if (elapsedMs >= FREE_TIMER_MAX_MS) {
          this._autoFinishFreeTimer()
          return
        }
        // onHide clears the interval, so onShow must always restart it.
        this._startFreeTimerInterval()
      }
      return
    }

    const totalSec = this.data.selectedPreset === 'debug' ? 10 : (this.data.workDuration ?? 25) * 60
    if (this.data.isPaused) {
      if (!this._canvasReady || !this._ctx) {
        wx.nextTick(() => {
          if (!this._pageVisible || this.data.phase !== PHASE.RUNNING || !this.data.isPaused) return
          this._initCanvas(true)
          this.drawRing(totalSec, false)
        })
      }
      return
    }

    const elapsedMs = Math.max(0, now - this._timerState.sessionStartTime - totalPausedMs)
    const remainingMs = Math.max(0, totalSec * 1000 - elapsedMs)
    if (remainingMs <= 0) {
      this._clearTimer()
      this._onWorkComplete()
      return
    }

    // onHide clears the timeout. Restart from wall-clock-derived remaining time
    // instead of repainting only one frame and leaving the countdown stopped.
    this._startTimer(totalSec, { remainingMs, forceRunning: true, reuseCanvas: true })
  },

  _buildCachedActiveSession(local) {
    if (!local || Date.now() - Number(local.savedAt || 0) >= POMODORO_LOCAL_STATE_TTL_MS) return null
    const cachedStartTime = Number(local.sessionStartTime)
    if (!Number.isFinite(cachedStartTime) || cachedStartTime <= 0 || !local.sessionId) return null
    const isPaused = !!local.isPaused
    return {
      id: local.sessionId,
      start_time: new Date(cachedStartTime).toISOString(),
      work_duration: Number(local.workDuration || 0),
      break_duration: Number(local.breakDuration || 0),
      preset: local.selectedPreset || 'standard',
      status: isPaused ? 'paused' : 'running',
      paused_at: isPaused && local.pauseStartTime
        ? new Date(local.pauseStartTime).toISOString()
        : null,
      total_paused_sec: Math.floor(Number(local.totalPausedMs || 0) / 1000),
      subject_id: local.selectedSubjectId,
      subject_code: local.selectedSubjectCode || '',
      subject_name: local.selectedSubjectName || '',
      _local_elapsed_sec: local.isFreeTimer ? Number(local.elapsedSec || 0) : undefined,
      _localFreeDisplayOffsetMs: local.isFreeTimer ? Number(local.freeDisplayOffsetMs || 0) : 0,
    }
  },

  _getCachedActiveSession() {
    try {
      const local = wx.getStorageSync('pomodoro_running_state')
      const cached = this._buildCachedActiveSession(local)
      if (!cached && local) wx.removeStorageSync('pomodoro_running_state')
      return cached
    } catch (_) {
      return null
    }
  },

  async _fetchActiveSession() {
    const local = wx.getStorageSync('pomodoro_running_state')
    const cached = this._buildCachedActiveSession(local)
    try {
      const server = await api.get('/pomodoro/active')
      if (server) {
        // Preserve local free display offset before clearing storage.
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
      // Weak/offline network: keep the timer usable from a fresh local snapshot.
      if (cached) return cached
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
      const completedAt = Math.min(
        Date.now(),
        startTime + Math.max(0, totalPausedMs) + totalSec * 1000
      )
      this._completePomodoroWithRetry(session.id, completedAt).catch(() => {})
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

    // Seed timing state before calling elapsed helpers. Cold/local restore used to
    // call _getFreeElapsedMs() while sessionStartTime still belonged to the previous
    // page instance, which could briefly render 00:00:00 until /active returned.
    this._timerState.sessionId = session.id
    this._timerState.sessionStartTime = startTime
    this._timerState.totalPausedMs = totalPausedMs
    this._timerState.freeDisplayOffsetMs = effectiveOffset
    this._timerState.pauseStartTime = isPaused ? Date.now() : null

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

    wx.nextTick(() => {
      this._initCanvas(true)
      this.drawRing(0, false)
    })

    if (!isPaused) {
      this._startFreeTimerInterval()
      // Check limit immediately after starting interval so elapsed never stays >5h
      this._checkFreeTimerLimitAndAutoEnd()
    }
  },

  _restoreBreak() {
    try {
      const saved = wx.getStorageSync('pomodoro_break')
      if (!saved || !saved.startTime || !saved.totalSec) return false
      const totalMs = Math.max(1, Number(saved.totalSec) * 1000)
      const remainingMs = Math.max(0, Number(saved.startTime) + totalMs - Date.now())
      if (remainingMs <= 0) {
        wx.removeStorageSync('pomodoro_break')
        this._resetToIdle()
        return false
      }
      this._startBreak(Number(saved.totalSec), {
        startTime: Number(saved.startTime),
        remainingMs,
      })
      return true
    } catch (_) {
      return false
    }
  },

  /* ==================== Progress Ring (Canvas 2D) ==================== */

  _redrawFreeRingAfterOverlay() {
    // Free timing uses a full ring (progress=1). cover-view dialogs temporarily
    // hide the native canvas; on real devices the canvas can come back blank.
    // Wait until setData has removed `hidden`, then rebuild the canvas so the
    // first frame is guaranteed to be painted instead of relying on stale ctx.
    this._timerState.progress = 1
    wx.nextTick(() => {
      if (this.data.showEndConfirm || !this.data.ringCanvasVisible) return
      this._initCanvas(true)
      this.drawRing(0, false)
    })
  },

  _initCanvas(force) {
    if (!force && ((this._canvasReady && this._ctx) || this._canvasInitPending)) return

    // Every forced rebuild invalidates older selector-query callbacks. On real
    // devices a callback from the previous page/layout can arrive late and bind
    // the 2D context to a stale native-canvas position, which makes the ring jump
    // to the top of the page after re-entering Pomodoro.
    const initSeq = (this._canvasInitSeq || 0) + 1
    this._canvasInitSeq = initSeq
    this._canvasInitPending = true
    this._canvasReady = false
    this._ctx = null
    this._ringCache = null // 清除缓存的渐变/几何
    if (this.data.ringCanvasPaintReady) {
      this.setData({ ringCanvasPaintReady: false })
    }

    // A rebuilt canvas is blank. Reset draw-throttle state as well, otherwise
    // the first paint can be skipped because progress barely changed.
    this._lastDrawnProgress = undefined
    this._lastDrawnIsBreak = undefined
    this._lastDrawnAt = 0
    this._scheduleCanvasInit(0, initSeq, null)
  },

  _scheduleCanvasInit(retryCount, initSeq, previousRect) {
    if (initSeq !== this._canvasInitSeq) return
    if (retryCount > 7) {
      this._canvasInitPending = false
      return
    }

    wx.nextTick(() => {
      if (initSeq !== this._canvasInitSeq) return
      if (!this._pageVisible) {
        this._canvasInitPending = false
        return
      }

      const query = wx.createSelectorQuery().in(this)
      query.select('.ring-stage').boundingClientRect()
      query.select('#progress-ring').fields({ node: true, size: true, rect: true })
      query.exec((res) => {
        if (initSeq !== this._canvasInitSeq) return

        const stageRect = res && res[0]
        const canvasInfo = res && res[1]
        if (!stageRect || !canvasInfo || !canvasInfo.node || !canvasInfo.width || !canvasInfo.height) {
          setTimeout(() => this._scheduleCanvasInit(retryCount + 1, initSeq, previousRect), 16)
          return
        }

        const rect = {
          left: Number.isFinite(canvasInfo.left) ? canvasInfo.left : stageRect.left,
          top: Number.isFinite(canvasInfo.top) ? canvasInfo.top : stageRect.top,
          width: canvasInfo.width,
          height: canvasInfo.height,
        }
        const stageAligned =
          Math.abs(rect.left - stageRect.left) <= 2 &&
          Math.abs(rect.top - stageRect.top) <= 2 &&
          Math.abs(rect.width - stageRect.width) <= 2 &&
          Math.abs(rect.height - stageRect.height) <= 2
        const stable = previousRect &&
          Math.abs(rect.left - previousRect.left) <= 1 &&
          Math.abs(rect.top - previousRect.top) <= 1 &&
          Math.abs(rect.width - previousRect.width) <= 1 &&
          Math.abs(rect.height - previousRect.height) <= 1

        // Require one stable layout frame before binding the native Canvas 2D
        // context. This avoids measuring while the running-state block is still
        // being inserted/reflowed during onShow restoration.
        if (!stageAligned || !stable) {
          setTimeout(() => this._scheduleCanvasInit(retryCount + 1, initSeq, rect), 16)
          return
        }

        const canvas = canvasInfo.node
        const windowInfo = wx.getWindowInfo ? wx.getWindowInfo() : {}
        const dpr = windowInfo.pixelRatio || 1
        this._dpr = dpr
        const width = canvasInfo.width
        const height = canvasInfo.height
        this._canvasSize = Math.min(width, height)
        canvas.width = Math.round(width * dpr)
        canvas.height = Math.round(height * dpr)
        const ctx = canvas.getContext('2d')
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
        this._ctx = ctx
        this._canvasReady = true
        this._canvasInitPending = false
        this._ringCache = null // 重建后缓存失效
        if (this._pendingDraw) {
          const pending = this._pendingDraw
          this._pendingDraw = null
          this.drawRing(pending.totalSec, pending.isBreak)
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
    var now = Date.now()
    // Keep throttling expensive canvas work, but guarantee a visible refresh at
    // least about once per second. The old fixed 1/360 threshold meant a 25-min
    // ring could wait ~4.2s and a 50-min ring ~8.3s before moving.
    if (this._lastDrawnProgress !== undefined && this._lastDrawnIsBreak === isBreak) {
      var diff = Math.abs(progress - this._lastDrawnProgress)
      var minProgressStep = totalSec > 0 ? Math.min(1 / 360, 0.8 / totalSec) : 0
      var sinceLastDraw = now - Number(this._lastDrawnAt || 0)
      if (diff < minProgressStep && sinceLastDraw < 1000) return
    }
    this._lastDrawnProgress = progress
    this._lastDrawnIsBreak = isBreak
    this._lastDrawnAt = now

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

    // Only reveal the canvas after a successful paint at a stable layout
    // position. Until then the glow/center text remain visible, preventing a
    // one-frame native-canvas flash at the top of the page.
    if (!this.data.ringCanvasPaintReady) {
      this.setData({ ringCanvasPaintReady: true })
    }
  },

  _resetToIdle() {
    this._clearFreeTimerInterval()
    this._confirmTimerSnapshot = null
    // Invalidate any selector callback that still points at the running-state
    // canvas before the wx:if block is removed.
    this._canvasInitSeq = (this._canvasInitSeq || 0) + 1
    this._canvasReady = false
    this._canvasInitPending = false
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
      ringCanvasPaintReady: false,
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
    const d = getChinaWallParts(Date.now())
    const week = ['日', '一', '二', '三', '四', '五', '六']
    return `${d.month}月${d.day}日 星期${week[d.weekday]}`
  },

  _getExamDays() {
    const nowParts = getChinaWallParts(Date.now())
    const todayStart = getChinaDayStartUtcMs(`${nowParts.year}-${String(nowParts.month).padStart(2, '0')}-${String(nowParts.day).padStart(2, '0')}`)
    const getExamDayUtc = (year) => {
      const dec31 = new Date(Date.UTC(year, 11, 31))
      const dayOfWeek = dec31.getUTCDay()
      const lastSaturday = 31 - ((dayOfWeek - 6 + 7) % 7)
      const targetDay = lastSaturday - 7
      return Date.UTC(year, 11, targetDay) - 8 * 60 * 60 * 1000
    }
    let examStart = getExamDayUtc(nowParts.year)
    if (examStart < todayStart) examStart = getExamDayUtc(nowParts.year + 1)
    return Math.max(0, Math.round((examStart - todayStart) / (24 * 60 * 60 * 1000)))
  },

})
