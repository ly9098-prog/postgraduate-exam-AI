const api = require('../../utils/api')

const SUBJECTS = [
  { key: 'data_structure', label: '数据结构', color: '#5B7B9A' },
  { key: 'computer_organization', label: '计算机组成原理', color: '#C49A6B' },
  { key: 'operating_system', label: '操作系统', color: '#6B9B6B' },
  { key: 'computer_network', label: '计算机网络', color: '#7B8DB3' },
  { key: 'english', label: '英语', color: '#B38B6B' },
  { key: 'math', label: '数学', color: '#8B9B7B' },
  { key: 'politics', label: '政治', color: '#A08B8B' },
]

const SUBJECT_COLOR_MAP = {}
SUBJECTS.forEach(s => { SUBJECT_COLOR_MAP[s.key] = s.color })

const PRESETS = [
  { key: 'standard', label: '标准番茄钟', work: 25, break: 5 },
  { key: 'long', label: '长时间学习', work: 50, break: 10 },
  { key: 'custom', label: '自定义', work: 25, break: 5 },
]

const PHASE = { IDLE: 'idle', RUNNING: 'running', BREAK: 'break' }

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

    // 当前 session
    sessionId: null,
    sessionStartTime: null,

    // 计时器显示
    remainingSec: 0,
    displayMin: '00',
    displaySec: '00',
    progress: 1,

    // 今日统计
    todaySessions: 0,
    todayDurationSec: 0,
    todayDurationText: '0分钟',

    // 从刷题页面传入
    fromSubject: '',
    fromChapterId: '',
    fromChapterName: '',
  },

  _timer: null,

  onLoad(opts) {
    if (opts.subject) {
      const mapped = this._mapPracticeSubject(opts.subject)
      this.setData({ fromSubject: mapped, selectedSubject: mapped })
    }
    if (opts.chapterId) this.setData({ fromChapterId: opts.chapterId })
    if (opts.chapterName) this.setData({ fromChapterName: decodeURIComponent(opts.chapterName) })
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

  async onShow() {
    this.loadTodayStats()
    const active = await this._fetchActiveSession()
    if (active) {
      this._restoreSession(active)
    } else if (this.data.phase !== PHASE.RUNNING) {
      this._restoreBreak()
    }
  },

  onHide() {
    this._clearTimer()
  },

  onUnload() {
    this._clearTimer()
  },

  /* ==================== 设置阶段 ==================== */

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

  /* ==================== 开始 / 结束 ==================== */

  async startSession() {
    if (!this.data.selectedSubject) {
      wx.showToast({ title: '请选择学习科目', icon: 'none' })
      return
    }
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
    }
  },

  async endSession() {
    if (!this.data.sessionId) return
    this._clearTimer()
    try {
      await api.post(`/pomodoro/${this.data.sessionId}/complete`)
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
      await api.post(`/pomodoro/${this.data.sessionId}/interrupt`)
    } catch (_) {}
    this._resetToIdle()
  },

  /* ==================== 计时器 ==================== */

  _beginCountdown(session) {
    const startTime = new Date(session.start_time).getTime()
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
    setTimeout(() => this.drawRing(totalSec, false), 100)
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
  },

  _resumeSession() {
    const pausedDuration = Date.now() - (this.data.pauseStartTime || Date.now())
    const totalPausedMs = (this.data.totalPausedMs || 0) + pausedDuration
    this.setData({
      isPaused: false,
      totalPausedMs: totalPausedMs,
      pauseStartTime: null,
    })
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

  async _onWorkComplete() {
    wx.vibrateLong()
    try {
      await api.post(`/pomodoro/${this.data.sessionId}/complete`)
    } catch (e) {
      console.error('番茄钟完成同步失败', e)
    }
    this.loadTodayStats()

    // 进入休息阶段
    const breakSec = this.data.breakDuration * 60
    wx.showModal({
      title: '学习完成！',
      content: `太棒了！休息 ${this.data.breakDuration} 分钟吧`,
      confirmText: '开始休息',
      cancelText: '跳过休息',
      success: (res) => {
        if (res.confirm) {
          this._startBreak(breakSec)
        } else {
          this._resetToIdle()
        }
      },
    })
  },

  _startBreak(totalSec) {
    wx.setStorageSync('pomodoro_break', { startTime: Date.now(), totalSec: totalSec })
    this.setData({
      phase: PHASE.BREAK,
      remainingSec: totalSec,
      progress: 1,
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
        wx.showToast({ title: '休息结束', icon: 'none' })
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

  /* ==================== 恢复与统计 ==================== */

  async _fetchActiveSession() {
    try {
      return await api.get('/pomodoro/active')
    } catch (_) {
      return null
    }
  },

  _restoreSession(session) {
    const startTime = new Date(session.start_time).getTime()
    const totalSec = session.work_duration * 60
    const elapsed = Math.floor((Date.now() - startTime) / 1000)
    const remaining = Math.max(0, totalSec - elapsed)
    if (remaining <= 0) {
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
      isPaused: false,
      totalPausedMs: 0,
      pauseStartTime: null,
    })
    this._startTimer(totalSec)
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
      this._startBreak(saved.totalSec)
    } catch (_) {}
  },

  drawRing(totalSec, isBreak) {
    const canvasId = isBreak ? 'progress-ring-break' : 'progress-ring'
    const query = wx.createSelectorQuery().in(this)
    query.select(`#${canvasId}`).boundingClientRect(rect => {
      if (!rect || !rect.width) return
      const size = Math.min(rect.width, rect.height)
      const center = size / 2
      const radius = center - 14
      const lineWidth = 12
      const progress = this.data.progress
      const ctx = wx.createCanvasContext(canvasId, this)
      ctx.clearRect(0, 0, size, size)

      const baseColor = isBreak ? '#6B9B6B' : '#5B7B9A'

      // 底色圆环（带微弱内阴影效果）
      ctx.beginPath()
      ctx.setStrokeStyle('#E8E5E0')
      ctx.setLineWidth(lineWidth)
      ctx.arc(center, center, radius, 0, Math.PI * 2)
      ctx.stroke()

      // 外层光晕
      if (progress < 1) {
        ctx.beginPath()
        ctx.setStrokeStyle(isBreak ? 'rgba(107,155,107,0.08)' : 'rgba(91,123,154,0.08)')
        ctx.setLineWidth(lineWidth + 8)
        ctx.setLineCap('round')
        ctx.arc(center, center, radius, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * (1 - progress))
        ctx.stroke()
      }

      // 进度弧
      ctx.beginPath()
      ctx.setStrokeStyle(baseColor)
      ctx.setLineWidth(lineWidth)
      ctx.setLineCap('round')
      ctx.arc(center, center, radius, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * (1 - progress))
      ctx.stroke()

      // 进度起点圆点
      if (progress < 1) {
        const startAngle = -Math.PI / 2
        const dotX = center + radius * Math.cos(startAngle)
        const dotY = center + radius * Math.sin(startAngle)
        ctx.beginPath()
        ctx.setFillStyle(baseColor)
        ctx.arc(dotX, dotY, lineWidth / 2, 0, Math.PI * 2)
        ctx.fill()
      }

      // 进度终点圆点
      const endAngle = -Math.PI / 2 + Math.PI * 2 * (1 - progress)
      const endX = center + radius * Math.cos(endAngle)
      const endY = center + radius * Math.sin(endAngle)
      ctx.beginPath()
      ctx.setFillStyle(baseColor)
      ctx.arc(endX, endY, lineWidth / 2, 0, Math.PI * 2)
      ctx.fill()

      ctx.draw()
    }).exec()
  },

  _resetToIdle() {
    wx.removeStorageSync('pomodoro_break')
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

  /* ==================== 工具 ==================== */

  subjectLabel(key) {
    const s = SUBJECTS.find(s => s.key === key)
    return s ? s.label : key
  },

  subjectColor(key) {
    return SUBJECT_COLOR_MAP[key] || '#5B7B9A'
  },

  getDateStr() {
    const d = new Date()
    const week = ['日', '一', '二', '三', '四', '五', '六']
    return `${d.getMonth() + 1}月${d.getDate()}日 星期${week[d.getDay()]}`
  },
})
