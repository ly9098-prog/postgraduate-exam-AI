const api = require('../../utils/api')

const SUBJECTS = [
  { key: 'data_structure', label: '数据结构', emoji: '📃', color: '#5B7B9A' },
  { key: 'computer_organization', label: '组成原理', emoji: '💻', color: '#C49A6B' },
  { key: 'operating_system', label: '操作系统', emoji: '⚙️', color: '#6B9B6B' },
  { key: 'computer_network', label: '计算机网络', emoji: '🌐', color: '#7B8DB3' },
  { key: 'english', label: '英语', emoji: '📖', color: '#B38B6B' },
  { key: 'math', label: '数学', emoji: '📐', color: '#8B9B7B' },
  { key: 'politics', label: '政治', emoji: '📜', color: '#A08B8B' },
]

const SUBJECT_COLOR_MAP = {}
const SUBJECT_EMOJI_MAP = {}
SUBJECTS.forEach(s => {
  SUBJECT_COLOR_MAP[s.key] = s.color
  SUBJECT_EMOJI_MAP[s.key] = s.emoji
})

const PRESETS = [
  { key: 'standard', label: '标准', work: 25, break: 5 },
  { key: 'long', label: '长时间', work: 50, break: 10 },
  { key: 'custom', label: '自定义', work: 25, break: 5 },
]

const PHASE = { IDLE: 'idle', RUNNING: 'running', BREAK: 'break', CEREMONY: 'ceremony' }

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

Page({
  data: {
    phase: PHASE.IDLE,
    subjects: SUBJECTS,
    selectedSubject: '',
    presets: PRESETS,
    selectedPreset: 'standard',
    workDuration: 25,
    breakDuration: 5,
    showCustom: false,
    isPaused: false,
    totalPausedMs: 0,
    pauseStartTime: null,

    // session
    sessionId: null,
    sessionStartTime: null,

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
    fromChapterId: '',
    fromChapterName: '',

    // font size accessibility
    fontSizeLevel: 'medium',

    // new features
    examDays: 0,
    showCelebration: false,
    celebrationMotto: '',
    pageEntered: false,
  },

  _timer: null,
  _touchStartX: 0,

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

    if (opts.subject) {
      const mapped = this._mapPracticeSubject(opts.subject)
      this.setData({ fromSubject: mapped, selectedSubject: mapped })
    }
    if (opts.chapterId) this.setData({ fromChapterId: opts.chapterId })
    if (opts.chapterName) this.setData({ fromChapterName: decodeURIComponent(opts.chapterName) })
  },

  async onShow() {
    this.loadTodayStats()

    const completionFlag = wx.getStorageSync('pomodoro_completion')
    if (completionFlag) {
      // Vibration can now fire since we're back in foreground
      wx.vibrateLong()
      if (!this.data.showCelebration) {
        this.setData({ showCelebration: true, celebrationMotto: completionFlag.motto })
        return
      }
      // Already showing celebration — clean up stale flag but don't replay
      wx.removeStorageSync('pomodoro_completion')
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
    // Save running state for offline restore when app returns from background
    if (this.data.phase === PHASE.RUNNING && this.data.sessionId) {
      wx.setStorageSync('pomodoro_running_state', {
        sessionStartTime: this.data.sessionStartTime,
        workDuration: this.data.workDuration,
        isPaused: this.data.isPaused,
        totalPausedMs: this.data.totalPausedMs,
        pauseStartTime: this.data.isPaused ? (this.data.pauseStartTime || Date.now()) : null,
        sessionId: this.data.sessionId,
        savedAt: Date.now(),
      })
    }
    this._clearTimer()
  },

  onUnload() {
    this._clearTimer()
    wx.setNavigationBarColor({
      frontColor: '#ffffff',
      backgroundColor: '#5B7B9A',
    })
  },

  /* ==================== UI Handlers ==================== */

  selectSubject(e) {
    this.setData({ selectedSubject: e.currentTarget.dataset.key })
  },

  selectPreset(e) {
    const key = e.currentTarget.dataset.key
    const preset = PRESETS.find(p => p.key === key)
    this.setData({
      selectedPreset: key,
      showCustom: key === 'custom',
      workDuration: preset ? preset.work : 25,
      breakDuration: preset ? preset.break : 5,
    })
  },

  onWorkChange(e) {
    const v = Math.max(5, Math.min(120, parseInt(e.detail.value) || 25))
    this.setData({ workDuration: v })
  },

  onBreakChange(e) {
    const v = Math.max(5, Math.min(120, parseInt(e.detail.value) || 5))
    this.setData({ breakDuration: v })
  },

  /* ==================== Touch / Swipe ==================== */

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
      // swipe left → next
      const next = (idx + 1) % keys.length
      this.selectPreset({ currentTarget: { dataset: { key: keys[next] } } })
    } else {
      // swipe right → previous
      const prev = (idx - 1 + keys.length) % keys.length
      this.selectPreset({ currentTarget: { dataset: { key: keys[prev] } } })
    }
  },

  /* ==================== Start Ceremony ==================== */

  async startSession() {
    if (!this.data.selectedSubject) {
      wx.showToast({ title: '请选择学习科目', icon: 'none' })
      return
    }
    this.setData({ phase: PHASE.CEREMONY })

    // ceremony duration: 2.5s
    await new Promise(r => setTimeout(r, 2500))

    try {
      const session = await api.post('/pomodoro/start', {
        subject: this.data.selectedSubject,
        chapter_id: this.data.fromChapterId || null,
        preset: this.data.selectedPreset,
        work_duration: this.data.workDuration,
        break_duration: this.data.breakDuration,
      })
      this._beginCountdown(session)
    } catch (e) {
      wx.showToast({ title: '启动失败', icon: 'none' })
      this.setData({ phase: PHASE.IDLE })
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
      try { await api.post(`/pomodoro/${this.data.sessionId}/interrupt`) } catch (_) {}
    }
    this._resetToIdle()
    this.loadTodayStats()
  },

  async interruptSession() {
    if (!this.data.sessionId) return
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
    const startTime = new Date(session.start_time + '+00:00').getTime()
    const totalSec = this.data.workDuration * 60
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
    setTimeout(() => this.drawRing(totalSec, false), 200)
  },

  togglePause() {
    if (this.data.isPaused) {
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
    // Persist pause state to survive page unload
    wx.setStorageSync('pomodoro_pause', {
      totalPausedMs: this.data.totalPausedMs,
      pauseStartTime: Date.now(),
      sessionId: this.data.sessionId,
    })
  },

  _resumeSession() {
    const pausedDuration = Date.now() - (this.data.pauseStartTime || Date.now())
    const totalPausedMs = (this.data.totalPausedMs || 0) + pausedDuration
    this.setData({
      isPaused: false,
      totalPausedMs: totalPausedMs,
      pauseStartTime: null,
    })
    wx.removeStorageSync('pomodoro_pause')
    const totalSec = this.data.workDuration * 60
    this._startTimer(totalSec)
  },

  _startTimer(totalSec) {
    this._clearTimer()
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
  },

  /* ==================== Work Complete ==================== */

  async _onWorkComplete() {
    wx.vibrateLong()
    try {
      await api.post(`/pomodoro/${this.data.sessionId}/complete`, {
        total_paused_ms: this.data.totalPausedMs || 0,
      })
    } catch (e) {
      console.error('同步失败', e)
    }
    this.loadTodayStats()

    // Celebration overlay — wait for user confirmation, DO NOT auto-start break
    const motto = MOTTOES[Math.floor(Math.random() * MOTTOES.length)]
    wx.setStorageSync('pomodoro_completion', { motto, sessionId: this.data.sessionId })
    this.setData({ showCelebration: true, celebrationMotto: motto })
    // Break starts only when user taps confirmCelebration()
  },

  confirmCelebration() {
    wx.removeStorageSync('pomodoro_completion')
    this.setData({ showCelebration: false })
    const breakSec = this.data.breakDuration * 60
    if (breakSec > 0) {
      this._startBreak(breakSec)
    } else {
      this._resetToIdle()
    }
  },

  /* ==================== Break Timer ==================== */

  _startBreak(totalSec) {
    wx.setStorageSync('pomodoro_break', { startTime: Date.now(), totalSec })
    this.setData({
      phase: PHASE.BREAK,
      remainingSec: totalSec,
      progress: 1,
      displayMin: String(Math.floor(totalSec / 60)).padStart(2, '0'),
      displaySec: String(totalSec % 60).padStart(2, '0'),
    })
    this._clearTimer()
    const tick = () => {
      const remaining = Math.max(0, this.data.remainingSec - 1)
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
        wx.vibrateShort()
        this._resetToIdle()
      }
    }
    tick()
    setTimeout(() => this.drawRing(totalSec, true), 100)
    this._timer = setInterval(tick, 500)
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
      // Server reachable but no active session — clear stale local state, don't fabricate
      wx.removeStorageSync('pomodoro_running_state')
      return null
    } catch (_) {
      // Network unreachable — fall through to local fallback
    }
    if (local && (Date.now() - local.savedAt < 7200000)) {
      return {
        id: local.sessionId,
        start_time: new Date(local.sessionStartTime).toISOString(),
        work_duration: local.workDuration,
        break_duration: this.data.breakDuration,
        subject: this.data.selectedSubject,
      }
    }
    wx.removeStorageSync('pomodoro_running_state')
    return null
  },

  _restoreSession(session) {
    const startTime = new Date(session.start_time + '+00:00').getTime()
    const totalSec = session.work_duration * 60

    // Recover paused state from storage (survives page unload)
    const savedPause = wx.getStorageSync('pomodoro_pause')
    let totalPausedMs = 0
    let isPaused = false
    if (savedPause && savedPause.sessionId === session.id) {
      totalPausedMs = (savedPause.totalPausedMs || 0) + (Date.now() - (savedPause.pauseStartTime || Date.now()))
      isPaused = true
    }

    const elapsed = Math.floor((Date.now() - startTime - totalPausedMs) / 1000)
    const remaining = Math.max(0, totalSec - elapsed)
    if (remaining <= 0) {
      wx.removeStorageSync('pomodoro_pause')
      this._onWorkComplete()
      return
    }

    this.setData({
      phase: PHASE.RUNNING,
      sessionId: session.id,
      sessionStartTime: startTime,
      selectedSubject: session.subject,
      workDuration: session.work_duration,
      breakDuration: session.break_duration,
      remainingSec: remaining,
      displayMin: String(Math.floor(remaining / 60)).padStart(2, '0'),
      displaySec: String(remaining % 60).padStart(2, '0'),
      isPaused: isPaused,
      totalPausedMs: totalPausedMs,
      pauseStartTime: isPaused ? Date.now() : null,
    })

    if (isPaused) {
      // Update stored pause start to now, with accumulated totalPausedMs
      wx.setStorageSync('pomodoro_pause', {
        totalPausedMs: totalPausedMs,
        pauseStartTime: Date.now(),
        sessionId: session.id,
      })
    } else {
      this._startTimer(totalSec)
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

  /* ==================== Progress Ring (Canvas) ==================== */

  drawRing(totalSec, isBreak) {
    const query = wx.createSelectorQuery().in(this)
    query.select('#progress-ring').boundingClientRect(rect => {
      if (!rect || !rect.width) return
      const size = Math.min(rect.width, rect.height)
      const center = size / 2
      const radius = center - 18
      const lineWidth = 12
      const progress = this.data.progress

      const ctx = wx.createCanvasContext('progress-ring', this)
      ctx.clearRect(0, 0, size, size)

      // Background track — very dim on dark bg
      ctx.beginPath()
      ctx.setStrokeStyle('rgba(255,255,255,0.06)')
      ctx.setLineWidth(lineWidth)
      ctx.arc(center, center, radius, 0, Math.PI * 2)
      ctx.stroke()

      // Gradient colors
      const colors = isBreak
        ? { start: '#F43F5E', end: '#F97316', dot: '#F97316' }
        : { start: '#06B6D4', end: '#3B82F6', dot: '#3B82F6' }

      // Progress arc
      ctx.beginPath()
      const grad = ctx.createLinearGradient(0, 0, size, size)
      grad.addColorStop(0, colors.start)
      grad.addColorStop(1, colors.end)
      ctx.setStrokeStyle(grad)
      ctx.setLineWidth(lineWidth)
      ctx.setLineCap('round')
      ctx.arc(center, center, radius, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * progress)
      ctx.stroke()

      // End dot (only if there's progress)
      if (progress > 0 && progress < 1) {
        const endAngle = -Math.PI / 2 + Math.PI * 2 * progress
        const endX = center + radius * Math.cos(endAngle)
        const endY = center + radius * Math.sin(endAngle)
        ctx.beginPath()
        ctx.setFillStyle(colors.dot)
        ctx.arc(endX, endY, lineWidth / 2 + 1, 0, Math.PI * 2)
        ctx.fill()
      }

      ctx.draw()
    }).exec()
  },

  _resetToIdle() {
    wx.removeStorageSync('pomodoro_break')
    wx.removeStorageSync('pomodoro_completion')
    wx.removeStorageSync('pomodoro_pause')
    wx.removeStorageSync('pomodoro_running_state')
    this.setData({
      phase: PHASE.IDLE,
      sessionId: null,
      sessionStartTime: null,
      remainingSec: 0,
      displayMin: '00',
      displaySec: '00',
      progress: 1,
      isPaused: false,
      totalPausedMs: 0,
      pauseStartTime: null,
    })
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

  /* ==================== Utility ==================== */

  subjectLabel(key) {
    const s = SUBJECTS.find(s => s.key === key)
    return s ? s.label : key
  },

  subjectColor(key) {
    return SUBJECT_COLOR_MAP[key] || '#5B7B9A'
  },

  subjectEmoji(key) {
    return SUBJECT_EMOJI_MAP[key] || '📚'
  },

  presetLabel(key) {
    const p = PRESETS.find(p => p.key === key)
    return p ? p.label : key
  },

  getDateStr() {
    const d = new Date()
    const week = ['日', '一', '二', '三', '四', '五', '六']
    return `${d.getMonth() + 1}月${d.getDate()}日 星期${week[d.getDay()]}`
  },

  /**
   * 获取距离最近一次考研初试（第一天）的剩余天数
   * 考研时间规则：每年12月倒数第二个星期六（通常为初试第一天）
   * 若当年考试已结束，则自动顺延至下一年
   * @returns {number} 剩余天数（非负整数）
   */
  _getExamDays() {
    // 当前日期（当天0点，消除时间影响）
    const now = new Date()
    now.setHours(0, 0, 0, 0)

    // 计算指定年份的考研日期（12月倒数第二个星期六）
    const getExamDate = (year) => {
      const dec31 = new Date(year, 11, 31)
      const dayOfWeek = dec31.getDay()            // 周日0 ~ 周六6
      const lastSaturday = dec31.getDate() - ((dayOfWeek - 6 + 7) % 7)
      const targetDay = lastSaturday - 7           // 倒数第二个周六
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
      'math2': 'math', 'math2-calculus': 'math', 'math2-linalg': 'math',
      'exam408': 'data_structure',
      'exam408-ds': 'data_structure', 'exam408-os': 'operating_system',
      'exam408-co': 'computer_organization', 'exam408-cn': 'computer_network',
      'english': 'english',
    }
    return map[raw] || raw
  },
})
