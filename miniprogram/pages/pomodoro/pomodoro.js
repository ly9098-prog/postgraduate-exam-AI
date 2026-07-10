const api = require('../../utils/api')
const config = require('../../config')

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

const PHASE = { IDLE: 'idle', RUNNING: 'running', BREAK: 'break', CEREMONY: 'ceremony' }

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
    breakStartTime: null,
    showCustom: false,
    isPaused: false,
    totalPausedMs: 0,
    pauseStartTime: null,

    // session
    sessionId: null,
    sessionStartTime: null,

    // free timer fields
    isFreeTimer: false,
    elapsedSec: 0,
    freeDisplayTime: '00:00:00',
    freeFriendlyText: '',
    showEndConfirm: false,
    endConfirmMode: '',
    endConfirmTheme: '',
    endConfirmTitle: '',
    endConfirmText: '',
    endConfirmOkText: '确认结束',
    endConfirmCancelText: '继续计时',
    actionLoading: false,

    // timer display
    remainingSec: 0,
    displayMin: '00',
    displaySec: '00',
    progress: 1,

    // today stats
    todaySessions: 0,
    todayDurationSec: 0,
    todayDurationText: '0分钟',

    // practice page context
    fromSubject: '',
    fromSubjectId: null,
    fromChapterId: '',
    fromChapterName: '',

    // font size accessibility
    fontSizeLevel: 'medium',

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
  _touchStartX: 0,
  _pageVisible: false,
  _debugTapCount: 0,
  _debugTapTimer: null,
  _countdownEndAt: 0,
  _countdownTotalSec: 0,
  _countdownRemainingSnapshot: null,
  _confirmTimerSnapshot: null,

  /* ==================== Lifecycle ==================== */

  onLoad(opts) {
    wx.setNavigationBarColor({
      frontColor: '#ffffff',
      backgroundColor: '#0B1121',
    })
    this.setData({
      examDays: this._getExamDays(),
      fontSizeLevel: wx.getStorageSync('pomodoro_font_size') || 'medium',
    })
    this._loadSubjects()

    if (opts.subject) {
      const mapped = this._mapPracticeSubject(opts.subject)
      this.setData({ fromSubject: mapped })
    } else if (opts.subject_id) {
      this.setData({ fromSubjectId: Number(opts.subject_id) })
    }
    if (opts.chapterId) this.setData({ fromChapterId: opts.chapterId })
    if (opts.chapterName) this.setData({ fromChapterName: decodeURIComponent(opts.chapterName) })
  },

  async onShow() {
    this._pageVisible = true

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

    // Check for persisted confirm snapshot — must restore before active session
    const confirmSnapshot = this._confirmTimerSnapshot || wx.getStorageSync('pomodoro_confirm_pause')
    if (confirmSnapshot && confirmSnapshot.sessionId) {
      this._confirmTimerSnapshot = confirmSnapshot
      const fmt = this._formatCountdownDisplay(confirmSnapshot.remainingSec)
      this.setData({
        phase: confirmSnapshot.phase || PHASE.RUNNING,
        sessionId: confirmSnapshot.sessionId,
        sessionStartTime: confirmSnapshot.sessionStartTime || this.data.sessionStartTime,
        isPaused: true,
        showEndConfirm: true,
        endConfirmMode: 'countdown-interrupt',
        ringCanvasVisible: true,
        remainingSec: confirmSnapshot.remainingSec,
        displayMin: fmt.min,
        displaySec: fmt.sec,
        progress: confirmSnapshot.progress,
        totalPausedMs: confirmSnapshot.totalPausedMs || 0,
      })
      wx.nextTick(() => {
        this._initCanvas(true)
        this.drawRing(confirmSnapshot.totalSec, confirmSnapshot.phase === 'break')
      })
      // If backend pause wasn't done, try now (fire-and-forget)
      if (confirmSnapshot.pausedByConfirm && !confirmSnapshot.backendPauseDone) {
        api.post('/pomodoro/' + confirmSnapshot.sessionId + '/pause', {})
          .then(function(server) {
            confirmSnapshot.totalPausedMs = (server.total_paused_sec || 0) * 1000
            confirmSnapshot.backendPauseDone = true
            wx.setStorageSync('pomodoro_confirm_pause', confirmSnapshot)
          })
          .catch(function() {})
      }
      setTimeout(() => this.loadTodayStats(), 200)
      return
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

    if (this.data.phase === PHASE.RUNNING && this.data.sessionId) {
      wx.setStorageSync('pomodoro_running_state', {
        sessionStartTime: this.data.sessionStartTime,
        workDuration: this.data.workDuration,
        breakDuration: this.data.breakDuration,
        selectedPreset: this.data.selectedPreset,
        selectedSubjectId: this.data.selectedSubjectId,
        selectedSubjectCode: this.data.selectedSubject ? this.data.selectedSubject.code : '',
        selectedSubjectName: this.data.selectedSubject ? this.data.selectedSubject.name : '',
        isPaused: this.data.isPaused,
        totalPausedMs: this.data.totalPausedMs,
        pauseStartTime: this.data.isPaused ? (this.data.pauseStartTime || Date.now()) : null,
        sessionId: this.data.sessionId,
        isFreeTimer: this.data.isFreeTimer,
        elapsedSec: this.data.elapsedSec,
        savedAt: Date.now(),
      })
    }
    // Single cleanup call — _clearTimer already clears free interval too
    this._clearTimer()
  },

  onUnload() {
    this._clearTimer()
    wx.setNavigationBarColor({
      frontColor: '#ffffff',
      backgroundColor: '#4F7FFF',
    })
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

      // If coming from practice page with a subject_id, auto-select
      if (this.data.fromSubjectId) {
        const match = flat.find(s => s.id === this.data.fromSubjectId)
        if (match) {
          this.setData({ selectedSubjectId: match.id, selectedSubject: match })
          this._updateComputedFields()
        }
      } else if (this.data.fromSubject) {
        const match = flat.find(s => s.code === this.data.fromSubject)
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

    this._clearTimer()
    this.setData({
      phase: PHASE.RUNNING,
      ringCanvasVisible: true,
      isFreeTimer: true,
      sessionId: session.id,
      sessionStartTime: startTime,
      isPaused: false,
      totalPausedMs: totalPausedSec * 1000,
      pauseStartTime: null,
      elapsedSec: 0,
      freeDisplayTime: '00:00:00',
      freeFriendlyText: '',
      showEndConfirm: false,
      progress: 1,
    })
    this._updateComputedFields()
    this._updateFreeElapsed()
    this._startFreeTimerInterval()
    wx.nextTick(() => {
      setTimeout(() => { this._initCanvas(); this.drawRing(0, false) }, 50)
    })
  },

  _updateFreeElapsed() {
    if (!this.data.isFreeTimer) return
    const startTime = this.data.sessionStartTime
    if (typeof startTime !== 'number' || !Number.isFinite(startTime)) {
      this.setData({ freeDisplayTime: '00:00:00' })
      return
    }
    const now = Date.now()
    const totalPausedMs = this.data.totalPausedMs || 0
    let elapsed
    if (this.data.isPaused) {
      elapsed = this.data.elapsedSec
    } else {
      elapsed = Math.max(0, Math.floor((now - startTime) / 1000) - Math.floor(totalPausedMs / 1000))
    }
    // Only setData when elapsed actually changes — reduces render
    if (elapsed === this.data.elapsedSec) return
    const fmt = formatElapsedSec(elapsed)
    this.setData({
      elapsedSec: elapsed,
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
    const tick = () => {
      if (this.data.isPaused || this.data.showEndConfirm) return
      this._updateFreeElapsed()
      // Align each tick to the next exact second boundary, self-correcting for drift
      const delay = 1000 - (Date.now() % 1000)
      this._freeTimerId = setTimeout(tick, Math.max(100, delay))
    }
    // First tick aligns to next second boundary
    const firstDelay = 1000 - (Date.now() % 1000)
    this._freeTimerId = setTimeout(tick, Math.max(100, firstDelay))
  },

  _restartFreeTimerInterval() {
    this._clearFreeTimerInterval()
    this._startFreeTimerInterval()
  },

  async _pauseFreeTimer() {
    if (!this.data.sessionId || this.data.actionLoading) return
    this.setData({ actionLoading: true })
    try {
      const server = await api.post(`/pomodoro/${this.data.sessionId}/pause`, {})
      this._clearFreeTimerInterval()
      this.setData({
        isPaused: true,
        pauseStartTime: Date.now(),
        totalPausedMs: (server.total_paused_sec || 0) * 1000,
        freeFriendlyText: formatElapsedSec(this.data.elapsedSec).friendly,
        actionLoading: false,
      })
      wx.setStorageSync('pomodoro_free_pause', {
        totalPausedMs: (server.total_paused_sec || 0) * 1000,
        pauseStartTime: Date.now(),
        sessionId: this.data.sessionId,
        elapsedSec: this.data.elapsedSec,
      })
    } catch (e) {
      this.setData({ actionLoading: false })
      wx.showToast({ title: '暂停失败，请重试', icon: 'none' })
    }
  },

  async _resumeFreeTimer() {
    if (!this.data.sessionId || this.data.actionLoading) return
    this.setData({ actionLoading: true })
    this._clearFreeTimerInterval()
    try {
      const server = await api.post(`/pomodoro/${this.data.sessionId}/resume`, {})
      const startTime = parseServerTime(server.start_time)
      const serverTotalPausedSec = server.total_paused_sec || 0
      const now = Date.now()
      const elapsed = Math.max(0, Math.floor((now - startTime) / 1000) - serverTotalPausedSec)
      const fmt = formatElapsedSec(elapsed)
      this.setData({
        isPaused: false,
        ringCanvasVisible: true,
        sessionStartTime: startTime,
        totalPausedMs: serverTotalPausedSec * 1000,
        pauseStartTime: null,
        elapsedSec: elapsed,
        freeDisplayTime: fmt.display,
        actionLoading: false,
      })
      wx.removeStorageSync('pomodoro_free_pause')
      this._startFreeTimerInterval()
    } catch (e) {
      this.setData({ actionLoading: false })
      await this._reconcileAfterResumeError(e, this.data.sessionId)
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
        const now = Date.now()
        const elapsed = Math.max(0, Math.floor((now - startTime) / 1000) - totalPausedSec)
        const fmt = formatElapsedSec(elapsed)
        this.setData({
          isPaused: false,
          sessionStartTime: startTime,
          totalPausedMs,
          pauseStartTime: null,
          elapsedSec: elapsed,
          freeDisplayTime: fmt.display,
          ringCanvasVisible: true,
        })
        this._startFreeTimerInterval()
        wx.removeStorageSync('pomodoro_free_pause')
      } else {
        const now = Date.now()
        const totalSec = this._getCurrentTotalSec()
        const elapsed = Math.floor((now - startTime - totalPausedMs) / 1000)
        const remainingSec = Math.max(0, totalSec - elapsed)
        this.setData({
          isPaused: false,
          sessionStartTime: startTime,
          totalPausedMs,
          pauseStartTime: null,
          remainingSec,
          displayMin: String(Math.floor(remainingSec / 60)).padStart(2, '0'),
          displaySec: String(remainingSec % 60).padStart(2, '0'),
          progress: totalSec > 0 ? remainingSec / totalSec : 0,
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

  _showEndFreeConfirm() {
    this._clearFreeTimerInterval()
    this._confirmOpenedAt = Date.now()
    const elapsed = Math.max(0, this.data.elapsedSec || 0)
    const fmt = formatElapsedSec(elapsed)
    this.setData({
      showEndConfirm: true,
      ringCanvasVisible: false,
      endConfirmMode: 'free-complete',
      endConfirmTheme: 'free',
      endConfirmTitle: '结束自由计时？',
      endConfirmText: elapsed >= 1 ? `本次已专注 ${fmt.friendly}，确认后将计入学习统计。` : '当前计时时长较短，确认后仍会结束本次计时。',
      endConfirmOkText: '确认结束',
      endConfirmCancelText: '继续计时',
    })
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
    if (!this.data.sessionId || this.data.actionLoading) return false

    const now = Date.now()
    const totalSec = this._getCurrentTotalSec()
    const totalMs = Math.max(1, totalSec * 1000)

    const remainingMs = this._countdownEndAt
      ? Math.max(0, this._countdownEndAt - now)
      : Math.max(0, (this.data.remainingSec || 0) * 1000)

    const remainingSec = remainingMs <= 0 ? 0 : Math.ceil(remainingMs / 1000)
    const progress = totalMs > 0 ? remainingMs / totalMs : 0
    const wasPaused = !!this.data.isPaused

    this._clearTimer()

    const snapshot = {
      mode: 'countdown-interrupt',
      sessionId: this.data.sessionId,
      openedAt: now,
      wasPaused: wasPaused,
      pausedByConfirm: !wasPaused,
      phase: this.data.phase,
      totalSec: totalSec,
      totalMs: totalMs,
      remainingMs: remainingMs,
      remainingSec: remainingSec,
      progress: progress,
      sessionStartTime: this.data.sessionStartTime,
      countdownEndAt: this._countdownEndAt,
      totalPausedMs: this.data.totalPausedMs || 0,
      pauseStartTime: this.data.pauseStartTime || null,
      backendPauseDone: false,
    }

    this._confirmTimerSnapshot = snapshot
    wx.setStorageSync('pomodoro_confirm_pause', snapshot)

    this._countdownEndAt = 0

    const fmt = this._formatCountdownDisplay(remainingSec)

    this.setData({
      isPaused: true,
      pauseStartTime: now,
      remainingSec: remainingSec,
      displayMin: fmt.min,
      displaySec: fmt.sec,
      progress: progress,
    })

    this.drawRing(totalSec, this.data.phase === 'break')

    // Sync backend pause (async, don't block UI)
    if (!wasPaused) {
      try {
        const server = await api.post('/pomodoro/' + this.data.sessionId + '/pause', {})
        const serverPausedMs = (server.total_paused_sec || 0) * 1000
        snapshot.totalPausedMs = serverPausedMs
        snapshot.backendPauseDone = true
        this._confirmTimerSnapshot = snapshot
        wx.setStorageSync('pomodoro_confirm_pause', snapshot)
        this.setData({ totalPausedMs: serverPausedMs, pauseStartTime: Date.now() })
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
    const elapsedSec = Math.max(0, snapshot.totalSec - snapshot.remainingSec)
    const fmt = formatElapsedSec(elapsedSec)

    this.setData({
      showEndConfirm: true,
      ringCanvasVisible: true,
      endConfirmMode: 'countdown-interrupt',
      endConfirmTheme: this.data.phase === 'break' ? 'break' : 'focus',
      endConfirmTitle: '结束本次专注？',
      endConfirmText: elapsedSec > 0
        ? `本次已专注 ${fmt.friendly}。确认后将结束当前番茄钟。`
        : '确认后将结束当前番茄钟。',
      endConfirmOkText: '结束',
      endConfirmCancelText: '继续专注',
    })

    wx.nextTick(() => {
      this._initCanvas(true)
      this.drawRing(snapshot.totalSec, snapshot.phase === 'break')
    })
  },

  async cancelEndConfirm() {
    if (this.data.actionLoading) return

    const mode = this.data.endConfirmMode
    const snapshot = this._confirmTimerSnapshot || wx.getStorageSync('pomodoro_confirm_pause')
    const now = Date.now()

    if (mode === 'countdown-interrupt' && snapshot && snapshot.sessionId) {
      this._confirmTimerSnapshot = snapshot
      const fmt = this._formatCountdownDisplay(snapshot.remainingSec)

      if (snapshot.wasPaused) {
        // Was paused before confirm — keep paused after cancel
        this.setData({
          showEndConfirm: false,
          ringCanvasVisible: true,
          endConfirmMode: '',
          endConfirmTheme: '',
          endConfirmTitle: '',
          endConfirmText: '',
          remainingSec: snapshot.remainingSec,
          displayMin: fmt.min,
          displaySec: fmt.sec,
          progress: snapshot.progress,
          isPaused: true,
          pauseStartTime: snapshot.pauseStartTime || Date.now(),
          totalPausedMs: snapshot.totalPausedMs || 0,
        })

        wx.removeStorageSync('pomodoro_confirm_pause')
        this._confirmTimerSnapshot = null

        wx.nextTick(() => {
          this._initCanvas(true)
          this.drawRing(snapshot.totalSec, snapshot.phase === 'break')
        })
        return
      }

      // Was running before confirm — resume after cancel
      this.setData({ actionLoading: true })

      let nextTotalPausedMs = snapshot.totalPausedMs || 0
      try {
        const server = await api.post('/pomodoro/' + snapshot.sessionId + '/resume', {})
        nextTotalPausedMs = (server.total_paused_sec || 0) * 1000
      } catch (e) {
        console.warn('resume after cancel confirm failed', e)
        // If backend pause succeeded, add pauseDelta locally
        if (snapshot.backendPauseDone) {
          const pauseDelta = Math.max(0, now - snapshot.openedAt)
          nextTotalPausedMs = (snapshot.totalPausedMs || 0) + pauseDelta
        }
      }

      this.setData({
        showEndConfirm: false,
        ringCanvasVisible: true,
        endConfirmMode: '',
        endConfirmTheme: '',
        endConfirmTitle: '',
        endConfirmText: '',
        remainingSec: snapshot.remainingSec,
        displayMin: fmt.min,
        displaySec: fmt.sec,
        progress: snapshot.progress,
        totalPausedMs: nextTotalPausedMs,
        isPaused: false,
        pauseStartTime: null,
        actionLoading: false,
      })

      wx.removeStorageSync('pomodoro_confirm_pause')

      this._countdownTotalSec = snapshot.totalSec
      this._startTimer(snapshot.totalSec, { remainingMs: snapshot.remainingMs, forceRunning: true })

      wx.nextTick(() => {
        this._initCanvas(true)
        this.drawRing(snapshot.totalSec, snapshot.phase === 'break')
      })

      this._confirmTimerSnapshot = null
      return
    }

    if (mode === 'free-complete') {
      this.setData({
        showEndConfirm: false,
        ringCanvasVisible: true,
        endConfirmMode: '',
        endConfirmTheme: '',
        endConfirmTitle: '',
        endConfirmText: '',
      })
      if (!this.data.isPaused) this._startFreeTimerInterval()
      this._confirmTimerSnapshot = null
      return
    }

    this.setData({
      showEndConfirm: false,
      endConfirmMode: '',
      endConfirmTheme: '',
      endConfirmTitle: '',
      endConfirmText: '',
    })
    this._confirmTimerSnapshot = null
  },

  async confirmEndTimer() {
    const mode = this.data.endConfirmMode

    if (mode === 'free-complete') {
      return this._confirmEndFreeTimer()
    }

    if (mode === 'countdown-interrupt') {
      return this._confirmInterruptCountdown()
    }
  },

  async _confirmEndFreeTimer() {
    this.setData({ showEndConfirm: false })
    if (!this.data.sessionId) return
    this._clearFreeTimerInterval()
    const elapsedSec = Math.max(1, this.data.elapsedSec || 0)
    const totalPausedMs = this.data.totalPausedMs || 0
    const totalPausedSec = Math.floor(totalPausedMs / 1000)
    try {
      await api.post(`/pomodoro/${this.data.sessionId}/complete`, {
        actual_duration_sec: elapsedSec,
        total_paused_sec: totalPausedSec,
      })
      wx.showToast({ title: '已记录本次专注', icon: 'none', duration: 2000 })
    } catch (e) {
      wx.showToast({ title: '结束计时失败，请重试', icon: 'none' })
      this.setData({ ringCanvasVisible: true })
      // Don't clear state on failure
      if (!this.data.isPaused) {
        this._startFreeTimerInterval()
      }
      return
    }
    this._resetToIdle()
    this.loadTodayStats()
  },

  async _confirmInterruptCountdown() {
    if (!this.data.sessionId || this.data.actionLoading) return

    const snapshot = this._confirmTimerSnapshot
    let totalPausedMs = this.data.totalPausedMs || 0

    if (snapshot && snapshot.openedAt) {
      totalPausedMs = Math.max(0, snapshot.totalPausedMs + (Date.now() - snapshot.openedAt))
    }

    this.setData({ actionLoading: true, totalPausedMs })

    try {
      await api.post(`/pomodoro/${this.data.sessionId}/interrupt`, {
        total_paused_ms: totalPausedMs,
      })
      wx.showToast({ title: '已结束本次专注', icon: 'none' })
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
    if (!this.data.sessionId) return
    this._clearTimer()
    try {
      await api.post(`/pomodoro/${this.data.sessionId}/complete`, {
        total_paused_ms: this.data.totalPausedMs || 0,
      })
    } catch (e) {
      try { await api.post(`/pomodoro/${this.data.sessionId}/interrupt`, {
        total_paused_ms: this.data.totalPausedMs || 0,
      }) } catch (_) {}
    }
    this._resetToIdle()
    this.loadTodayStats()
  },

  async interruptSession() {
    if (!this.data.sessionId) return

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
    this.setData({
      phase: PHASE.RUNNING,
      ringCanvasVisible: true,
      sessionId: session.id,
      sessionStartTime: startTime,
      remainingSec: totalSec,
      progress: 1,
      isPaused: false,
      totalPausedMs: 0,
      pauseStartTime: null,
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
    if (!this.data.sessionId || this.data.actionLoading) return
    this.setData({ actionLoading: true })
    try {
      const server = await api.post(`/pomodoro/${this.data.sessionId}/pause`, {})
      this._clearTimer()
      this.setData({
        isPaused: true,
        pauseStartTime: Date.now(),
        totalPausedMs: (server.total_paused_sec || 0) * 1000,
        actionLoading: false,
      })
      wx.setStorageSync('pomodoro_pause', {
        totalPausedMs: (server.total_paused_sec || 0) * 1000,
        pauseStartTime: Date.now(),
        sessionId: this.data.sessionId,
      })
    } catch (e) {
      this.setData({ actionLoading: false })
      wx.showToast({ title: '暂停失败，请重试', icon: 'none' })
    }
  },

  async _resumeSession() {
    if (typeof this.data.sessionStartTime !== 'number' || this.data.sessionStartTime <= 0) {
      console.warn('resume aborted: invalid sessionStartTime', this.data.sessionStartTime)
      this._resetToIdle()
      return
    }
    if (!this.data.sessionId || this.data.actionLoading) return
    this.setData({ actionLoading: true })
    try {
      const server = await api.post(`/pomodoro/${this.data.sessionId}/resume`, {})
      const startTime = parseServerTime(server.start_time)
      const serverTotalPausedSec = server.total_paused_sec || 0
      const totalSec = this.data.selectedPreset === 'debug' ? 10 : (this.data.workDuration ?? 25) * 60
      const elapsed = Math.floor((Date.now() - startTime) / 1000) - serverTotalPausedSec
      const remainingSec = Math.max(0, totalSec - elapsed)
      this.setData({
        isPaused: false,
        ringCanvasVisible: true,
        totalPausedMs: serverTotalPausedSec * 1000,
        pauseStartTime: null,
        remainingSec: remainingSec,
        displayMin: String(Math.floor(remainingSec / 60)).padStart(2, '0'),
        displaySec: String(remainingSec % 60).padStart(2, '0'),
        progress: totalSec > 0 ? remainingSec / totalSec : 0,
        actionLoading: false,
      })
      wx.removeStorageSync('pomodoro_pause')
      this._startTimer(totalSec)
    } catch (e) {
      this.setData({ actionLoading: false })
      await this._reconcileAfterResumeError(e, this.data.sessionId)
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

  _startTimer(totalSec, options = {}) {
    this._clearTimer()
    this._initCanvas(true)

    // remainingMs has highest priority, then remainingSec, then this.data.remainingSec, then totalSec
    let remainMs
    if (Number.isFinite(options.remainingMs)) {
      remainMs = Math.max(0, options.remainingMs)
    } else {
      const remainSec = Number.isFinite(options.remainingSec)
        ? Math.max(0, options.remainingSec)
        : Math.max(0, this.data.remainingSec || totalSec)
      remainMs = remainSec * 1000
    }

    const displayRemainingSec = remainMs <= 0 ? 0 : Math.ceil(remainMs / 1000)
    const progress = totalMs > 0 ? remainMs / totalMs : 0
    const fmt = this._formatCountdownDisplay(displayRemainingSec)

    this._countdownTotalSec = totalSec
    this._countdownEndAt = Date.now() + remainMs

    const update = { remainingSec: displayRemainingSec, displayMin: fmt.min, displaySec: fmt.sec, progress, ringCanvasVisible: true }
    if (options.forceRunning) {
      update.isPaused = false
      update.pauseStartTime = null
    }
    this.setData(update)

    const totalMs = Math.max(1, totalSec * 1000)

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
        displayRemainingSec !== this.data.remainingSec ||
        Math.abs(progress - this.data.progress) > 0.002
      ) {
        this.setData({
          remainingSec: displayRemainingSec,
          displayMin: fmt.min,
          displaySec: fmt.sec,
          progress,
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
    if (!this.data.sessionId) {
      this._resetToIdle()
      return
    }
    wx.vibrateLong()
    try {
      await api.post(`/pomodoro/${this.data.sessionId}/complete`, {
        total_paused_ms: this.data.totalPausedMs || 0,
      })
    } catch (e) {
      console.error('同步失败', e)
    }
    this.loadTodayStats()

    const motto = MOTTOES[Math.floor(Math.random() * MOTTOES.length)]
    const type = this._nextCelebrationType()
    wx.setStorageSync('pomodoro_completion', { motto, type: type, sessionId: this.data.sessionId })
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
    this.setData({
      phase: PHASE.BREAK,
      ringCanvasVisible: true,
      remainingSec: totalSec,
      breakStartTime,
      progress: 1,
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
        displayRemainingSec !== this.data.remainingSec ||
        Math.abs(progress - this.data.progress) > 0.002
      ) {
        this.setData({
          remainingSec: displayRemainingSec,
          displayMin: fmt.min,
          displaySec: fmt.sec,
          progress,
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
    if (!this.data.sessionId) return false
    if (active.id !== this.data.sessionId) return false
    if (this.data.phase !== PHASE.RUNNING) return false
    if ((active.status === 'paused') !== this.data.isPaused) return false
    if ((active.preset === 'free') !== this.data.isFreeTimer) return false
    if (typeof this.data.sessionStartTime !== 'number' || this.data.sessionStartTime <= 0) return false
    return true
  },

  _syncActiveSessionLight(active) {
    const now = Date.now()
    const totalPausedMs = this.data.totalPausedMs || 0

    if (this.data.isFreeTimer) {
      if (!this.data.isPaused) {
        const elapsed = Math.max(0, Math.floor((now - this.data.sessionStartTime) / 1000) - Math.floor(totalPausedMs / 1000))
        if (elapsed !== this.data.elapsedSec) {
          const fmt = formatElapsedSec(elapsed)
          this.setData({ elapsedSec: elapsed, freeDisplayTime: fmt.display })
        }
      }
      // Idempotent interval start — won't create duplicate
      this._startFreeTimerInterval()
    } else {
      const totalSec = this.data.selectedPreset === 'debug' ? 10 : (this.data.workDuration ?? 25) * 60
      if (this.data.isPaused) return
      const elapsed = Math.floor((now - this.data.sessionStartTime - totalPausedMs) / 1000)
      const remaining = Math.max(0, totalSec - elapsed)
      if (remaining <= 0) {
        // Timer expired while away — trigger completion
        this._clearTimer()
        this._onWorkComplete()
        return
      }
      this.setData({
        remainingSec: remaining,
        ringCanvasVisible: true,
        displayMin: String(Math.floor(remaining / 60)).padStart(2, '0'),
        displaySec: String(remaining % 60).padStart(2, '0'),
        progress: totalSec > 0 ? remaining / totalSec : 0,
      })
      this.drawRing(totalSec, false)
    }
  },

  async _fetchActiveSession() {
    const local = wx.getStorageSync('pomodoro_running_state')
    try {
      const server = await api.get('/pomodoro/active')
      if (server) {
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

    const savedPause = wx.getStorageSync('pomodoro_pause')
    let totalPausedMs = 0
    let isPaused = false
    if (savedPause && savedPause.sessionId === session.id) {
      const savedTotal = Number(savedPause.totalPausedMs || 0)
      const pauseStart = Number(savedPause.pauseStartTime || Date.now())
      totalPausedMs = Number.isFinite(savedTotal) && Number.isFinite(pauseStart)
        ? savedTotal + (Date.now() - pauseStart)
        : 0
      isPaused = totalPausedMs > 0
    } else if (session.paused_at) {
      const pausedAtMs = parseServerTime(session.paused_at)
      totalPausedMs = Number.isFinite(pausedAtMs) ? Math.max(0, Date.now() - pausedAtMs) : 0
      isPaused = Number.isFinite(pausedAtMs)
    }

    if (!Number.isFinite(totalPausedMs) || totalPausedMs < 0) totalPausedMs = 0

    const elapsed = Math.floor((Date.now() - startTime - totalPausedMs) / 1000)
    const remaining = Number.isFinite(totalSec) && Number.isFinite(elapsed)
      ? Math.max(0, totalSec - elapsed) : 0

    // Resolve subject from session
    const subjectId = session.subject_id || null
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
      this.setData({
        selectedSubjectId: subjectId,
        selectedSubject: subjectId ? { id: subjectId, code: subjectCode, name: subjectName } : null,
        selectedPreset: session.preset || 'standard',
        workDuration: session.work_duration,
        breakDuration: session.break_duration,
        isPaused: false,
        totalPausedMs: 0,
        pauseStartTime: null,
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

    this.setData({
      phase: PHASE.RUNNING,
      ringCanvasVisible: true,
      sessionId: session.id,
      sessionStartTime: startTime,
      selectedSubjectId: subjectId,
      selectedSubject: subjectId ? { id: subjectId, code: subjectCode, name: subjectName } : null,
      selectedPreset: session.preset || 'standard',
      workDuration: session.work_duration,
      breakDuration: session.break_duration,
      remainingSec: remaining,
      displayMin: String(Math.floor(remaining / 60)).padStart(2, '0'),
      displaySec: String(remaining % 60).padStart(2, '0'),
      isPaused: isPaused,
      totalPausedMs: totalPausedMs,
      pauseStartTime: isPaused ? Date.now() : null,
      progress: totalSec > 0 ? remaining / totalSec : 0,
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

    const serverTotalPausedSec = session.total_paused_sec || 0
    const savedPause = wx.getStorageSync('pomodoro_free_pause')
    let totalPausedMs = serverTotalPausedSec * 1000
    let isPaused = false
    let savedElapsed = 0

    if (savedPause && savedPause.sessionId === session.id) {
      const savedTotal = Number(savedPause.totalPausedMs || 0)
      const pauseStart = Number(savedPause.pauseStartTime || Date.now())
      totalPausedMs = Number.isFinite(savedTotal) && Number.isFinite(pauseStart)
        ? savedTotal + (Date.now() - pauseStart)
        : totalPausedMs
      isPaused = true
      savedElapsed = Number(savedPause.elapsedSec || 0)
    } else if (session.paused_at) {
      const pausedAtMs = parseServerTime(session.paused_at)
      if (Number.isFinite(pausedAtMs)) {
        isPaused = true
        totalPausedMs += Date.now() - pausedAtMs
      }
    }

    if (!Number.isFinite(totalPausedMs) || totalPausedMs < 0) totalPausedMs = 0

    const elapsed = isPaused
      ? savedElapsed || Math.max(0, Math.floor((Date.now() - startTime - totalPausedMs) / 1000))
      : Math.max(0, Math.floor((Date.now() - startTime - totalPausedMs) / 1000))

    const fmt = formatElapsedSec(elapsed)

    // Resolve subject
    const subjectId = session.subject_id || null
    const subjectCode = session.subject_code || ''
    const subjectName = session.subject_name || '未分类'

    this._clearTimer()
    this.setData({
      phase: PHASE.RUNNING,
      ringCanvasVisible: true,
      isFreeTimer: true,
      sessionId: session.id,
      sessionStartTime: startTime,
      selectedSubjectId: subjectId,
      selectedSubject: subjectId ? { id: subjectId, code: subjectCode, name: subjectName } : null,
      selectedPreset: 'free',
      workDuration: 0,
      breakDuration: 0,
      isPaused: isPaused,
      totalPausedMs: totalPausedMs,
      pauseStartTime: isPaused ? Date.now() : null,
      elapsedSec: elapsed,
      freeDisplayTime: fmt.display,
      freeFriendlyText: '',
      showEndConfirm: false,
      progress: 1,
    })
    this._updateComputedFields()

    setTimeout(() => { this._initCanvas(); this.drawRing(0, false) }, 200)

    if (!isPaused) {
      this._startFreeTimerInterval()
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
      this.setData({
        phase: PHASE.BREAK,
        remainingSec: remaining,
        displayMin: String(Math.floor(remaining / 60)).padStart(2, '0'),
        displaySec: String(remaining % 60).padStart(2, '0'),
        progress: remaining / saved.totalSec,
      })
      this._startBreak(remaining > 0 ? remaining : saved.totalSec)
    } catch (_) {}
  },

  /* ==================== Progress Ring (Canvas 2D) ==================== */

  _initCanvas(force) {
    if (!force && this._canvasReady && this._ctx) return
    this._canvasReady = false
    this._ctx = null
    const query = wx.createSelectorQuery().in(this)
    query.select('#progress-ring')
      .fields({ node: true, size: true })
      .exec((res) => {
        if (!res[0] || !res[0].node) return
        const canvas = res[0].node
        const dpr = this._dpr || wx.getSystemInfoSync().pixelRatio || 1
        this._dpr = dpr
        const width = res[0].width
        const height = res[0].height
        canvas.width = Math.round(width * dpr)
        canvas.height = Math.round(height * dpr)
        const ctx = canvas.getContext('2d')
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
        this._ctx = ctx
        this._canvasSize = Math.min(width, height)
        this._canvasReady = true
        if (this._pendingDraw) {
          this.drawRing(this._pendingDraw.totalSec, this._pendingDraw.isBreak)
          this._pendingDraw = null
        }
      })
  },

  drawRing(totalSec, isBreak) {
    if (!this._ctx) {
      this._pendingDraw = { totalSec, isBreak }
      return
    }
    const ctx = this._ctx
    const size = this._canvasSize
    const center = size / 2
    const radius = center - 18
    const lineWidth = 12
    const progress = this.data.progress

    ctx.clearRect(0, 0, size, size)

    const colors = isBreak
      ? { start: '#F43F5E', end: '#F97316', dot: '#F97316' }
      : this.data.isFreeTimer
        ? { start: '#34D399', end: '#059669', dot: '#10B981' }
        : { start: '#06B6D4', end: '#3B82F6', dot: '#3B82F6' }

    if (progress > 0) {
      const glowGrad = ctx.createLinearGradient(0, 0, size, size)
      glowGrad.addColorStop(0, colors.start)
      glowGrad.addColorStop(1, colors.end)
      ctx.beginPath()
      ctx.strokeStyle = glowGrad
      ctx.lineWidth = lineWidth + 14
      ctx.lineCap = 'round'
      ctx.globalAlpha = 0.18
      ctx.arc(center, center, radius, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * progress)
      ctx.stroke()
      ctx.globalAlpha = 1
    }

    ctx.beginPath()
    ctx.strokeStyle = 'rgba(255,255,255,0.06)'
    ctx.lineWidth = lineWidth
    ctx.arc(center, center, radius, 0, Math.PI * 2)
    ctx.stroke()

    ctx.beginPath()
    const grad = ctx.createLinearGradient(0, 0, size, size)
    grad.addColorStop(0, colors.start)
    grad.addColorStop(1, colors.end)
    ctx.strokeStyle = grad
    ctx.lineWidth = lineWidth
    ctx.lineCap = 'round'
    ctx.arc(center, center, radius, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * progress)
    ctx.stroke()

    if (progress > 0 && progress < 1) {
      const endAngle = -Math.PI / 2 + Math.PI * 2 * progress
      const endX = center + radius * Math.cos(endAngle)
      const endY = center + radius * Math.sin(endAngle)
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
    wx.removeStorageSync('pomodoro_break')
    wx.removeStorageSync('pomodoro_completion')
    wx.removeStorageSync('pomodoro_pause')
    wx.removeStorageSync('pomodoro_free_pause')
    wx.removeStorageSync('pomodoro_running_state')
    wx.removeStorageSync('pomodoro_confirm_pause')
    this.setData({
      phase: PHASE.IDLE,
      sessionId: null,
      sessionStartTime: null,
      breakStartTime: null,
      remainingSec: 0,
      displayMin: '00',
      displaySec: '00',
      progress: 1,
      isPaused: false,
      totalPausedMs: 0,
      pauseStartTime: null,
      isFreeTimer: false,
      elapsedSec: 0,
      freeDisplayTime: '00:00:00',
      freeFriendlyText: '',
      showEndConfirm: false,
      endConfirmMode: '',
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
      this.setData({
        todaySessions: stats.today_sessions || 0,
        todayDurationSec: stats.today_duration_sec || 0,
        todayDurationText: m >= 60 ? `${Math.floor(m / 60)}时${m % 60}分` : `${m}分钟`,
      })
    } catch (_) {}
  },

  goStats() {
    wx.navigateTo({ url: '/pages/pomodoro-stats/pomodoro-stats' })
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
    const s = this.data.subjects.find(s => s.code === key)
    return s ? s.name : key
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

  _mapPracticeSubject(raw) {
    // Only map legacy codes → new codes; keep new codes as-is
    const map = {
      'data_structure': 'exam408-ds',
      'operating_system': 'exam408-os',
      'computer_organization': 'exam408-co',
      'computer_network': 'exam408-cn',
      'advanced_math': 'math2-calculus',
      'linear_algebra': 'math2-linalg',
      'politics': 'pol',
      'math': 'math2',
    }
    return map[raw] || raw
  },

})
