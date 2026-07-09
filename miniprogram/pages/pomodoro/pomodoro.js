const api = require('../../utils/api')
const config = require('../../config')

const SUBJECT_EMOJI = {
  data_structure: '📃',
  computer_organization: '💻',
  operating_system: '⚙️',
  computer_network: '🌐',
  english: '📖',
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
    endConfirmText: '',
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
    this.loadTodayStats()

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

    const active = await this._fetchActiveSession()
    if (active) {
      this._restoreSession(active)
    } else if (this.data.phase !== PHASE.RUNNING) {
      this._restoreBreak()
    }
    setTimeout(() => {
      this.setData({ pageEntered: true })
    }, 50)
  },

  onHide() {
    this._pageVisible = false
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
    this._clearFreeTimerInterval()
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
    setTimeout(() => { this._initCanvas(); this.drawRing(0, false) }, 200)
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
      // Paused: freeze at pause-start value, don't increment
      elapsed = this.data.elapsedSec
    } else {
      elapsed = Math.max(0, Math.floor((now - startTime) / 1000) - Math.floor(totalPausedMs / 1000))
    }
    const fmt = formatElapsedSec(elapsed)
    this.setData({
      elapsedSec: elapsed,
      freeDisplayTime: fmt.display,
    })
  },

  _clearFreeTimerInterval() {
    if (this._freeTimerId) {
      clearInterval(this._freeTimerId)
      this._freeTimerId = null
    }
  },

  _startFreeTimerInterval() {
    this._clearFreeTimerInterval()
    this._freeTimerId = setInterval(() => this._updateFreeElapsed(), 500)
  },

  async _pauseFreeTimer() {
    if (!this.data.sessionId || this.data.actionLoading) return
    this.setData({ actionLoading: true })
    this._clearFreeTimerInterval()
    try {
      const server = await api.post(`/pomodoro/${this.data.sessionId}/pause`, {})
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
      // Restart interval on failure — don't lose counting time
      if (!this.data.isPaused) this._startFreeTimerInterval()
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
      wx.showToast({ title: '继续失败，请重试', icon: 'none' })
      // Keep paused state — do NOT restart interval on failure
    }
  },

  _showEndFreeConfirm() {
    const elapsed = Math.max(0, this.data.elapsedSec || 0)
    const fmt = formatElapsedSec(elapsed)
    this.setData({
      showEndConfirm: true,
      endConfirmText: elapsed >= 1 ? `本次已专注 ${fmt.friendly}，确认后将计入学习统计。` : '计时时长过短，确认后将计入学习统计。',
    })
  },

  _cancelEndFreeTimer() {
    this.setData({ showEndConfirm: false })
    if (!this.data.isPaused) {
      this._startFreeTimerInterval()
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
      // Don't clear state on failure
      if (!this.data.isPaused) {
        this._startFreeTimerInterval()
      }
      return
    }
    this._resetToIdle()
    this.loadTodayStats()
  },

  async endSession() {
    if (!this.data.sessionId) return
    this._clearTimer()
    try {
      await api.post(`/pomodoro/${this.data.sessionId}/complete`, {
        total_paused_ms: this.data.totalPausedMs || 0,
      })
    } catch (e) {
      try { await api.post(`/pomodoro/${this.data.sessionId}/interrupt`) } catch (_) {}
    }
    this._resetToIdle()
    this.loadTodayStats()
  },

  async interruptSession() {
    if (!this.data.sessionId) return
    // Free timer: show confirmation instead of immediate interrupt
    if (this.data.isFreeTimer) {
      this._showEndFreeConfirm()
      return
    }
    this._clearTimer()
    try {
      await api.post(`/pomodoro/${this.data.sessionId}/interrupt`, {
        total_paused_ms: this.data.totalPausedMs || 0,
      })
    } catch (_) {}
    this._resetToIdle()
  },

  /* ==================== Countdown Timer ==================== */

  _beginCountdown(session) {
    const startTime = parseServerTime(session.start_time)
    const totalSec = this.data.selectedPreset === 'debug' ? 10 : this.data.workDuration * 60
    this.setData({
      phase: PHASE.RUNNING,
      sessionId: session.id,
      sessionStartTime: startTime,
      remainingSec: totalSec,
      progress: 1,
      isPaused: false,
      totalPausedMs: 0,
      pauseStartTime: null,
    })
    this._startTimer(totalSec)
    this._updateComputedFields()
    setTimeout(() => this.drawRing(totalSec, false), 200)
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

  _pauseSession() {
    this._clearTimer()
    this.setData({
      isPaused: true,
      pauseStartTime: Date.now(),
    })
    wx.setStorageSync('pomodoro_pause', {
      totalPausedMs: this.data.totalPausedMs,
      pauseStartTime: Date.now(),
      sessionId: this.data.sessionId,
    })
    if (this.data.sessionId) {
      api.post(`/pomodoro/${this.data.sessionId}/pause`, {}).catch(() => {})
    }
  },

  _resumeSession() {
    if (typeof this.data.sessionStartTime !== 'number' || this.data.sessionStartTime <= 0) {
      console.warn('resume aborted: invalid sessionStartTime', this.data.sessionStartTime)
      this._resetToIdle()
      return
    }
    const pausedDuration = Date.now() - (this.data.pauseStartTime || Date.now())
    const totalPausedMs = (this.data.totalPausedMs || 0) + Math.max(0, pausedDuration)
    this.setData({
      isPaused: false,
      totalPausedMs: totalPausedMs,
      pauseStartTime: null,
    })
    const totalSec = this.data.selectedPreset === 'debug' ? 10 : (this.data.workDuration ?? 25) * 60
    const elapsed = Math.floor((Date.now() - this.data.sessionStartTime - totalPausedMs) / 1000)
    const remainingSec = Math.max(0, totalSec - elapsed)
    this.setData({
      remainingSec: remainingSec,
      displayMin: String(Math.floor(remainingSec / 60)).padStart(2, '0'),
      displaySec: String(remainingSec % 60).padStart(2, '0'),
      progress: totalSec > 0 ? remainingSec / totalSec : 0,
    })
    wx.removeStorageSync('pomodoro_pause')
    if (this.data.sessionId) {
      api.post(`/pomodoro/${this.data.sessionId}/resume`, {}).catch(() => {})
    }
    this._startTimer(totalSec)
  },

  _startTimer(totalSec) {
    this._clearTimer()
    this._initCanvas()
    const tick = () => {
      const now = Date.now()
      const elapsed = Math.floor((now - this.data.sessionStartTime - (this.data.totalPausedMs || 0)) / 1000)
      const remaining = Math.max(0, totalSec - elapsed)
      const m = Math.floor(remaining / 60)
      const s = remaining % 60
      this.setData({
        remainingSec: remaining,
        displayMin: String(m).padStart(2, '0'),
        displaySec: String(s).padStart(2, '0'),
        progress: totalSec > 0 ? remaining / totalSec : 0,
      })
      this.drawRing(totalSec, this.data.phase === PHASE.BREAK)
      if (remaining <= 0) {
        this._clearTimer()
        this._onWorkComplete()
      }
    }
    tick()
    this._timer = setInterval(tick, 500)
  },

  _clearTimer() {
    if (this._timer) {
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
    wx.setStorageSync('pomodoro_break', { startTime: breakStartTime, totalSec })
    this.setData({
      phase: PHASE.BREAK,
      remainingSec: totalSec,
      breakStartTime,
      progress: 1,
      displayMin: String(Math.floor(totalSec / 60)).padStart(2, '0'),
      displaySec: String(totalSec % 60).padStart(2, '0'),
    })
    this._clearTimer()
    const tick = () => {
      const elapsed = Math.floor((Date.now() - breakStartTime) / 1000)
      const remaining = Math.max(0, totalSec - elapsed)
      const m = Math.floor(remaining / 60)
      const s = remaining % 60
      this.setData({
        remainingSec: remaining,
        displayMin: String(m).padStart(2, '0'),
        displaySec: String(s).padStart(2, '0'),
        progress: totalSec > 0 ? remaining / totalSec : 0,
      })
      this.drawRing(totalSec, true)
      if (remaining <= 0) {
        this._clearTimer()
        wx.removeStorageSync('pomodoro_break')
        this._resetToIdle()
      }
    }
    tick()
    this._initCanvas()
    setTimeout(() => this.drawRing(totalSec, true), 100)
    this._timer = setInterval(tick, 1000)
  },

  skipBreak() {
    this._clearTimer()
    wx.removeStorageSync('pomodoro_break')
    this._resetToIdle()
  },

  /* ==================== Session Restore ==================== */

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
      return {
        id: local.sessionId,
        start_time: new Date(cachedStartTime).toISOString(),
        work_duration: local.workDuration,
        break_duration: local.breakDuration,
        preset: local.selectedPreset || 'standard',
        subject_id: local.selectedSubjectId,
        subject_code: local.selectedSubjectCode || '',
        subject_name: local.selectedSubjectName || '',
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

  _initCanvas() {
    this._canvasReady = false
    this._ctx = null
    const query = wx.createSelectorQuery().in(this)
    query.select('#progress-ring')
      .fields({ node: true, size: true })
      .exec((res) => {
        if (!res[0] || !res[0].node) return
        const canvas = res[0].node
        const ctx = canvas.getContext('2d')
        const dpr = wx.getSystemInfoSync().pixelRatio
        const width = res[0].width
        const height = res[0].height
        const scale = dpr * 2
        canvas.width = Math.round(width * scale)
        canvas.height = Math.round(height * scale)
        ctx.scale(scale, scale)
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
    this._canvasReady = false
    this._ctx = null
    this._pendingDraw = null
    wx.removeStorageSync('pomodoro_break')
    wx.removeStorageSync('pomodoro_completion')
    wx.removeStorageSync('pomodoro_pause')
    wx.removeStorageSync('pomodoro_free_pause')
    wx.removeStorageSync('pomodoro_running_state')
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
    const map = {
      'math2': 'math2',
      'math2-calculus': 'advanced_math',
      'math2-linalg': 'linear_algebra',
      'exam408': 'exam408',
      'exam408-ds': 'data_structure',
      'exam408-os': 'operating_system',
      'exam408-co': 'computer_organization',
      'exam408-cn': 'computer_network',
      'english': 'english',
    }
    return map[raw] || raw
  },

})
