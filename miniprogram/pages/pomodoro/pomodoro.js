const api = require('../../utils/api')
const config = require('../../config')

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

    // 番茄钟完成提醒（默认关闭；开启后启动专注会请求微信订阅消息授权）
    notifyOn: false,

    // new features
    examDays: 0,
    showCelebration: false,
    celebrationMotto: '',
    celebrationType: 'excellent',
    pageEntered: false,
    debugMode: false,
  },

  _timer: null,
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
      notifyOn: !!wx.getStorageSync('pomodoro_notify_on'),
    })

    if (opts.subject) {
      const mapped = this._mapPracticeSubject(opts.subject)
      this.setData({ fromSubject: mapped, selectedSubject: mapped })
    }
    if (opts.chapterId) this.setData({ fromChapterId: opts.chapterId })
    if (opts.chapterName) this.setData({ fromChapterName: decodeURIComponent(opts.chapterName) })
  },

  async onShow() {
    this._pageVisible = true
    this.loadTodayStats()

    const completionFlag = wx.getStorageSync('pomodoro_completion')
    if (completionFlag) {
      // Drop stale/corrupt flags (missing sessionId from earlier buggy paths)
      // so we never replay vibration for a session that was never synced.
      if (!completionFlag.sessionId) {
        wx.removeStorageSync('pomodoro_completion')
      } else if (!this.data.showCelebration) {
        // Deferred celebration — timer completed while page was in background / locked
        wx.vibrateLong()
        this.setData({ showCelebration: true, celebrationMotto: completionFlag.motto, celebrationType: completionFlag.type || 'excellent' })
        return
      } else {
        // Already showing celebration — clean up stale flag but don't replay
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
    // Save running state for offline restore when app returns from background
    if (this.data.phase === PHASE.RUNNING && this.data.sessionId) {
      wx.setStorageSync('pomodoro_running_state', {
        sessionStartTime: this.data.sessionStartTime,
        workDuration: this.data.workDuration,
        breakDuration: this.data.breakDuration,
        selectedPreset: this.data.selectedPreset,
        selectedSubject: this.data.selectedSubject,
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
      backgroundColor: '#4F7FFF',
    })
  },

  /* ==================== UI Handlers ==================== */

  selectSubject(e) {
    this.setData({ selectedSubject: e.currentTarget.dataset.key })
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
      return
    }
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

    // 申请番茄钟完成订阅消息授权（开关关闭则跳过；用户拒绝不影响启动）
    const notificationEnabled = this.data.notifyOn
      ? await this._requestPomodoroSubscribe()
      : false

    this.setData({ phase: PHASE.CEREMONY })

    // ceremony duration: shorter for debug
    await new Promise(r => setTimeout(r, this.data.selectedPreset === 'debug' ? 1000 : 2500))

    try {
      const session = await api.post('/pomodoro/start', {
        subject: this.data.selectedSubject,
        chapter_id: this.data.fromChapterId || null,
        preset: this.data.selectedPreset,
        work_duration: this.data.selectedPreset === 'debug' ? 1 : this.data.workDuration,
        break_duration: this.data.selectedPreset === 'debug' ? 1 : this.data.breakDuration,
        notification_enabled: notificationEnabled,
      })
      this._beginCountdown(session)
    } catch (e) {
      wx.showToast({ title: '启动失败', icon: 'none' })
      this.setData({ phase: PHASE.IDLE })
    }
  },

  /**
   * 申请番茄钟完成订阅消息授权。
   * 通知核心由后端推送（即使小程序退出/锁屏也能收到），前端只负责申请权限。
   * 用户拒绝时返回 false，不阻断番茄钟启动。
   */
  _requestPomodoroSubscribe() {
    return new Promise((resolve) => {
      const tmplId = (config && config.POMODORO_SUBSCRIBE_TMPL_ID) || ''
      if (!tmplId) {
        // 模板未配置，跳过申请，正常启动番茄钟
        resolve(false)
        return
      }
      try {
        wx.requestSubscribeMessage({
          tmplIds: [tmplId],
          success: (res) => {
            const status = res && res[tmplId]
            resolve(status === 'accept')
          },
          fail: () => resolve(false),
        })
      } catch (_) {
        resolve(false)
      }
    })
  },

  /**
   * 切换"番茄钟完成提醒"开关。
   * 开 → 立即弹一次订阅授权，引导用户勾选"总是保持以上选择"以避免每次启动都弹窗。
   * 关 → 静默关闭，启动番茄钟时不会再请求授权。
   */
  async toggleNotify() {
    const next = !this.data.notifyOn
    if (next) {
      const tmplId = (config && config.POMODORO_SUBSCRIBE_TMPL_ID) || ''
      if (!tmplId) {
        wx.showToast({ title: '订阅模板未配置', icon: 'none' })
        return
      }
      const accepted = await this._requestPomodoroSubscribe()
      if (!accepted) {
        wx.showToast({ title: '未授权，提醒未开启', icon: 'none' })
        return
      }
      this.setData({ notifyOn: true })
      wx.setStorageSync('pomodoro_notify_on', true)
      wx.showToast({
        title: '建议勾选"总是保持以上选择"',
        icon: 'none',
        duration: 2400,
      })
    } else {
      this.setData({ notifyOn: false })
      wx.setStorageSync('pomodoro_notify_on', false)
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
    // 通知后端暂停（推迟通知推送时刻）；失败不阻断本地暂停
    if (this.data.sessionId) {
      api.post(`/pomodoro/${this.data.sessionId}/pause`, {}).catch(() => {})
    }
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
    // 通知后端恢复（按暂停时长延后通知推送时刻）；失败不阻断本地继续
    if (this.data.sessionId) {
      api.post(`/pomodoro/${this.data.sessionId}/resume`, {}).catch(() => {})
    }
    const totalSec = this.data.workDuration * 60
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

    // Celebration — only show if page is in foreground; otherwise defer to onShow
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
        this._resetToIdle()
      }
    }
    tick()
    this._initCanvas()
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
        break_duration: local.breakDuration,
        preset: local.selectedPreset || 'standard',
        subject: local.selectedSubject || this.data.selectedSubject,
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
    } else if (session.paused_at) {
      // 后端有暂停标记但本地没存（清缓存/换设备）；按后端 paused_at 重建本地状态
      const pausedAtMs = new Date(session.paused_at + '+00:00').getTime()
      totalPausedMs = Math.max(0, Date.now() - pausedAtMs)
      isPaused = true
    }

    const elapsed = Math.floor((Date.now() - startTime - totalPausedMs) / 1000)
    const remaining = Math.max(0, totalSec - elapsed)
    if (remaining <= 0) {
      wx.removeStorageSync('pomodoro_pause')
      wx.removeStorageSync('pomodoro_running_state')
      // Session expired while page was hidden — complete it now and show
      // deferred celebration so the user gets their earned break.
      // Send the actual duration directly since the timer ran to completion.
      // This prevents the server from computing inflated duration
      // (now - start_time - paused) when the user returns hours later.
      api.post(`/pomodoro/${session.id}/complete`, {
        total_paused_ms: totalPausedMs || 0,
        actual_duration_sec: session.work_duration * 60,
      }).catch(() => {
        api.post(`/pomodoro/${session.id}/interrupt`, {
          total_paused_ms: totalPausedMs || 0,
          actual_duration_sec: session.work_duration * 60,
        }).catch(() => {})
      })
      // Restore session config so dismissCelebration reads correct durations
      this.setData({
        selectedSubject: session.subject,
        selectedPreset: session.preset || 'standard',
        workDuration: session.work_duration,
        breakDuration: session.break_duration,
        isPaused: false,
        totalPausedMs: 0,
        pauseStartTime: null,
      })
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
      selectedSubject: session.subject,
      selectedPreset: session.preset || 'standard',
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
        // Super-sample at 2x device resolution for smooth anti-aliasing
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
      : { start: '#06B6D4', end: '#3B82F6', dot: '#3B82F6' }

    // Glow layer
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

    // Background track
    ctx.beginPath()
    ctx.strokeStyle = 'rgba(255,255,255,0.06)'
    ctx.lineWidth = lineWidth
    ctx.arc(center, center, radius, 0, Math.PI * 2)
    ctx.stroke()

    // Progress arc
    ctx.beginPath()
    const grad = ctx.createLinearGradient(0, 0, size, size)
    grad.addColorStop(0, colors.start)
    grad.addColorStop(1, colors.end)
    ctx.strokeStyle = grad
    ctx.lineWidth = lineWidth
    ctx.lineCap = 'round'
    ctx.arc(center, center, radius, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * progress)
    ctx.stroke()

    // End dot
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
    this._canvasReady = false
    this._ctx = null
    this._pendingDraw = null
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
