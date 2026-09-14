const api = require('../../../utils/api')
const view = require('../utils/exam-runner-view')

function cleanUiLabel(value, fallback = '') {
  return String(value || fallback).replace(/408/g, '').replace(/\s{2,}/g, ' ').trim()
}

const EXAM_SUBJECT_LABELS = {
  data_structure: '数据结构',
  ds: '数据结构',
  'exam408-ds': '数据结构',
  computer_organization: '计算机组成原理',
  co: '计算机组成原理',
  'exam408-co': '计算机组成原理',
  operating_system: '操作系统',
  os: '操作系统',
  'exam408-os': '操作系统',
  computer_network: '计算机网络',
  cn: '计算机网络',
  'exam408-cn': '计算机网络',
}

function examSubjectLabel(name, code) {
  const normalizedCode = String(code || '').trim().toLowerCase()
  if (EXAM_SUBJECT_LABELS[normalizedCode]) return EXAM_SUBJECT_LABELS[normalizedCode]

  const cleaned = cleanUiLabel(name)
    .replace(/^[-—–·：:\s]+|[-—–·：:\s]+$/g, '')
    .trim()
  if (!cleaned) return '未分类'
  if (/数据结构/.test(cleaned)) return '数据结构'
  if (/计算机组成原理|组成原理|计组/.test(cleaned)) return '计算机组成原理'
  if (/操作系统/.test(cleaned)) return '操作系统'
  if (/计算机网络|计网/.test(cleaned)) return '计算机网络'
  return cleaned
}

function pad2(n) { return String(Math.max(0, Number(n) || 0)).padStart(2, '0') }
function formatClock(sec) {
  sec = Math.max(0, Math.floor(Number(sec) || 0))
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  const s = sec % 60
  return h > 0 ? `${pad2(h)}:${pad2(m)}:${pad2(s)}` : `${pad2(m)}:${pad2(s)}`
}

const EXAM_CACHE_SCHEMA_VERSION = 2
const EXAM_CACHE_MIGRATION_MARK = 'exam_cache_migration_mark_v2'
// 本地草稿保留时长：离开作答页后 60 分钟内可恢复，超时进入重新作答状态。
const EXAM_DRAFT_TTL_MS = 60 * 60 * 1000
function cacheKey(attemptId) { return `exam_attempt_pending_v2:${attemptId}` }
function legacyCacheKey(attemptId) { return `exam_attempt_pending_v1:${attemptId}` }

Page({
  data: {
    statusBarHeight: 0,
    loading: true,
    errorText: '',
    submitting: false,
    attemptId: 0,
    paperTitle: '',
    questions: [],
    currentQuestion: null,
    currentAnswerState: null,
    currentIndex: 0,
    totalCount: 0,
    answeredCount: 0,
    progressPercent: 0,
    remainingText: '--:--',
    markedForReview: false,
    timeExpired: false,
  },

  onLoad(options) {
    const sys = wx.getSystemInfoSync ? wx.getSystemInfoSync() : {}
    const attemptId = Number(options && options.attempt_id)
    this.setData({ statusBarHeight: Number(sys.statusBarHeight || 0), attemptId })
    if (!attemptId) {
      this.setData({ loading: false, errorText: '缺少考试记录 ID' })
      return
    }
    this._pageAlive = true
    this._renderCache = Object.create(null)
    this._answers = Object.create(null)
    this._pending = this._loadPending(attemptId)
    this._syncing = Object.create(null)
    this._attemptLoaded = false
    this._reconnectSyncing = false
    this._networkStatusHandler = (res) => {
      if (res && res.isConnected) this._recoverPendingAfterReconnect().catch(() => {})
    }
    if (wx.onNetworkStatusChange) wx.onNetworkStatusChange(this._networkStatusHandler)
    this.loadAttempt()
  },

  onShow() {
    if (this._pageAlive && this._attemptLoaded) this._recoverPendingAfterReconnect().catch(() => {})
  },

  onUnload() {
    this._pageAlive = false
    this._attemptLoaded = false
    if (this._networkStatusHandler && wx.offNetworkStatusChange) {
      wx.offNetworkStatusChange(this._networkStatusHandler)
    }
    this._networkStatusHandler = null
    this._clearTimer()
    this._settleCurrentTime({ sync: true })
  },

  _loadPending(attemptId) {
    try {
      let raw = wx.getStorageSync(cacheKey(attemptId))
      if ((!raw || typeof raw !== 'object') && wx.getStorageSync) {
        const legacy = wx.getStorageSync(legacyCacheKey(attemptId))
        if (legacy && typeof legacy === 'object') {
          raw = Object.assign({ schema_version: 1 }, legacy)
          wx.setStorageSync(cacheKey(attemptId), Object.assign({}, raw, { schema_version: EXAM_CACHE_SCHEMA_VERSION }))
          wx.removeStorageSync(legacyCacheKey(attemptId))
        }
      }
      if (raw && typeof raw === 'object') {
        const savedAt = Number(raw.saved_at || 0)
        if (savedAt > 0 && api.now() - savedAt > EXAM_DRAFT_TTL_MS) {
          // 草稿超过 60 分钟：清除本地缓存内容，进入页面后按“重新作答”处理
          // （服务端答案仍以 loadAttempt 拉到的为准，但不再恢复本地草稿）。
          wx.removeStorageSync(cacheKey(attemptId))
          wx.removeStorageSync(legacyCacheKey(attemptId))
          return Object.create(null)
        }
      }
      return raw && typeof raw === 'object' ? raw : Object.create(null)
    } catch (_) {
      return Object.create(null)
    }
  },

  _persistPending() {
    try {
      const keys = Object.keys(this._pending || {})
      if (keys.length) {
        wx.setStorageSync(cacheKey(this.data.attemptId), Object.assign({}, this._pending, {
          schema_version: EXAM_CACHE_SCHEMA_VERSION,
          saved_at: api.now(),
        }))
      } else wx.removeStorageSync(cacheKey(this.data.attemptId))
    } catch (_) {}
  },

  async loadAttempt() {
    this.setData({ loading: true, errorText: '' })
    try {
      const payload = await api.get(`/exams/attempts/${this.data.attemptId}`)
      if (payload.status === 'abandoned') {
        // 已放弃的草稿没有结果快照，回套卷列表重新开始而不是跳结果页。
        this._pending = Object.create(null)
        this._persistPending()
        wx.redirectTo({ url: '/subpackages/exam/paper-list/index' })
        return
      }
      if (payload.status !== 'in_progress') {
        this._pending = Object.create(null)
        this._persistPending()
        wx.redirectTo({ url: `/subpackages/exam/result/index?attempt_id=${payload.id}` })
        return
      }
      this._hydrate(payload)
      this._attemptLoaded = true
      this.setData({ loading: false })
      this._startTimer(payload.remaining_sec)
      this._flushAllPending({ quiet: true }).catch(() => {})
    } catch (error) {
      this.setData({ loading: false, errorText: api.getErrorMessage(error) })
    }
  },

  _hydrate(payload) {
    const serverAnswers = Object.create(null)
    ;(payload.answers || []).forEach((a) => {
      serverAnswers[String(a.item_id)] = {
        selected_answer: a.selected_answer || null,
        marked_for_review: !!a.marked_for_review,
        used_time: Math.max(0, Number(a.used_time || 0)),
      }
    })
    const pending = this._pending || {}
    const questions = (payload.questions || []).map((raw) => {
      const itemId = String(raw.item_id)
      const answer = Object.assign({}, serverAnswers[itemId] || {}, pending[itemId] || {})
      this._answers[itemId] = answer
      const rv = view.buildRenderView(raw)
      this._renderCache[itemId] = rv
      return Object.assign({}, rv.question, {
        _itemId: Number(raw.item_id),
        _position: Number(raw.position),
        _score: Number(raw.score || 0),
        _subjectCode: String(raw.subject_code || ''),
        _subjectName: examSubjectLabel(raw.subject_name, raw.subject_code),
        _answered: !!answer.selected_answer,
        _marked: !!answer.marked_for_review,
      })
    })
    const index = this._findResumeIndex(questions)
    this.setData({
      paperTitle: cleanUiLabel(payload.paper_title, '选择题考试'),
      questions,
      totalCount: questions.length,
      currentIndex: index,
    })
    this._setCurrent(index)
  },

  _findResumeIndex(questions) {
    for (let i = 0; i < questions.length; i++) {
      const a = this._answers[String(questions[i]._itemId)] || {}
      if (!a.selected_answer) return i
    }
    return 0
  },

  _setCurrent(index) {
    const questions = this.data.questions || []
    if (!questions.length) return
    index = Math.max(0, Math.min(Number(index) || 0, questions.length - 1))
    const q = questions[index]
    const itemId = String(q._itemId)
    const answer = this._answers[itemId] || {}
    const renderView = this._renderCache[itemId]
    this._questionEnterAt = api.now()
    const answeredCount = questions.reduce((n, item) => n + (item._answered ? 1 : 0), 0)
    this.setData({
      currentIndex: index,
      currentQuestion: q,
      currentAnswerState: view.buildAnswerState(renderView, answer.selected_answer),
      markedForReview: !!answer.marked_for_review,
      answeredCount,
      progressPercent: questions.length ? Math.round((answeredCount / questions.length) * 100) : 0,
    })
  },

  _startTimer(initialRemaining) {
    this._clearTimer()
    const remaining = initialRemaining == null ? null : Math.max(0, Number(initialRemaining || 0))
    this._timerBaseRemaining = remaining
    this._timerStartedAt = api.now()
    const tick = () => {
      if (!this._pageAlive) return
      if (this._timerBaseRemaining == null) {
        this.setData({ remainingText: '不限时' })
        return
      }
      const elapsed = Math.max(0, Math.floor((api.now() - this._timerStartedAt) / 1000))
      const left = Math.max(0, this._timerBaseRemaining - elapsed)
      this.setData({ remainingText: `剩余 ${formatClock(left)}` })
      if (left <= 0) {
        this._clearTimer()
        this.setData({ timeExpired: true, remainingText: '已到时 · 正在交卷' })
        this.submitExam({ auto: true })
      }
    }
    tick()
    this._timer = setInterval(tick, 1000)
  },

  _clearTimer() {
    if (this._timer) clearInterval(this._timer)
    this._timer = null
  },

  _currentItemId() {
    const q = this.data.currentQuestion
    return q && q._itemId ? String(q._itemId) : ''
  },

  _updateQuestionFlags(itemId) {
    const answer = this._answers[String(itemId)] || {}
    const questions = (this.data.questions || []).map((q) => {
      if (String(q._itemId) !== String(itemId)) return q
      return Object.assign({}, q, {
        _answered: !!answer.selected_answer,
        _marked: !!answer.marked_for_review,
      })
    })
    this.setData({ questions })
  },

  selectOption(e) {
    if (this.data.timeExpired || this.data.submitting) return
    const itemId = this._currentItemId()
    if (!itemId) return
    const answer = this._answers[itemId] || { used_time: 0 }
    answer.selected_answer = String(e.detail.option || '').trim().toUpperCase() || null
    this._answers[itemId] = answer
    this._queueItem(itemId)
    this._updateQuestionFlags(itemId)
    const rv = this._renderCache[itemId]
    this.setData({ currentAnswerState: view.buildAnswerState(rv, answer.selected_answer) })
    this._setCountsOnly()
    this._syncItem(itemId).catch(() => {})
  },

  toggleMark() {
    if (this.data.timeExpired || this.data.submitting) return
    const itemId = this._currentItemId()
    if (!itemId) return
    const answer = this._answers[itemId] || { used_time: 0 }
    answer.marked_for_review = !answer.marked_for_review
    this._answers[itemId] = answer
    this._queueItem(itemId)
    this._updateQuestionFlags(itemId)
    this.setData({ markedForReview: !!answer.marked_for_review })
    this._syncItem(itemId).catch(() => {})
  },

  _setCountsOnly() {
    const questions = this.data.questions || []
    const answeredCount = questions.reduce((n, q) => n + (q._answered ? 1 : 0), 0)
    this.setData({
      answeredCount,
      progressPercent: questions.length ? Math.round((answeredCount / questions.length) * 100) : 0,
    })
  },

  _queueItem(itemId) {
    const a = this._answers[String(itemId)] || {}
    this._pending[String(itemId)] = {
      selected_answer: a.selected_answer || null,
      marked_for_review: !!a.marked_for_review,
      used_time: Math.max(0, Number(a.used_time || 0)),
    }
    this._persistPending()
  },

  _settleCurrentTime(options = {}) {
    const itemId = this._currentItemId()
    if (!itemId || !this._questionEnterAt) return Promise.resolve()
    const now = api.now()
    const delta = Math.max(0, Math.floor((now - this._questionEnterAt) / 1000))
    this._questionEnterAt = now
    if (delta <= 0) return Promise.resolve()
    const a = this._answers[itemId] || { used_time: 0 }
    a.used_time = Math.min(6 * 60 * 60, Math.max(0, Number(a.used_time || 0)) + delta)
    this._answers[itemId] = a
    this._queueItem(itemId)
    if (options.sync === false) return Promise.resolve()
    return this._syncItem(itemId).catch(() => {})
  },

  async _syncItem(itemId) {
    itemId = String(itemId)
    if (this._syncing[itemId]) return this._syncing[itemId]
    const run = async () => {
      while (this._pending[itemId]) {
        const snapshot = Object.assign({}, this._pending[itemId])
        try {
          const res = await api.request('PATCH', `/exams/attempts/${this.data.attemptId}/answers/${itemId}`, snapshot)
          if (res && res.status && res.status !== 'in_progress') {
            delete this._pending[itemId]
            this._persistPending()
            wx.redirectTo({ url: `/subpackages/exam/result/index?attempt_id=${this.data.attemptId}` })
            return
          }
          const current = this._pending[itemId]
          if (current && JSON.stringify(current) === JSON.stringify(snapshot)) {
            delete this._pending[itemId]
            this._persistPending()
          }
        } catch (error) {
          if (await this._resolveTerminalSyncConflict(error)) return
          throw error
        }
      }
    }
    this._syncing[itemId] = run().finally(() => { delete this._syncing[itemId] })
    return this._syncing[itemId]
  },

  async _flushAllPending(options = {}) {
    try {
      // Re-scan after each pass. This matters during lifecycle/network callbacks:
      // an item can be queued while an earlier item is awaiting its PATCH.
      // Submission freezes editing, so the loop deterministically converges.
      while (true) {
        const ids = Object.keys(this._pending || {})
        if (!ids.length) return true
        for (let idIndex = 0; idIndex < ids.length; idIndex++) await this._syncItem(ids[idIndex])
      }
    } catch (error) {
      if (!options.quiet) wx.showToast({ title: '还有答案未同步，请检查网络', icon: 'none' })
      throw error
    }
  },

  async _resolveTerminalSyncConflict(error) {
    if (!error || Number(error.statusCode) !== 409) return false
    try {
      const payload = await api.get(`/exams/attempts/${this.data.attemptId}`)
      if (!payload || payload.status === 'in_progress') return false
      this._pending = Object.create(null)
      this._persistPending()
      if (this._pageAlive && !this.data.submitting) {
        wx.redirectTo({ url: `/subpackages/exam/result/index?attempt_id=${this.data.attemptId}` })
      }
      return true
    } catch (_) {
      return false
    }
  },

  async _recoverPendingAfterReconnect() {
    if (!this._pageAlive || !this._attemptLoaded || this._reconnectSyncing) return
    this._reconnectSyncing = true
    try {
      await this._flushAllPending({ quiet: true })
      if (this.data.timeExpired && !this.data.submitting) await this.submitExam({ auto: true })
    } catch (_) {
      // 保留 pending，等待下一次网络恢复或用户操作再次同步。
    } finally {
      this._reconnectSyncing = false
    }
  },

  _moveTo(index) {
    if (this.data.timeExpired || this.data.submitting) return
    const previousItemId = this._currentItemId()
    this._settleCurrentTime({ sync: false })
    if (previousItemId) this._syncItem(previousItemId).catch(() => {})
    this._setCurrent(index)
  },
  goPrev(e) { this._moveTo(e.detail.index) },
  goNext(e) { this._moveTo(e.detail.index) },
  goQuestion(e) { this._moveTo(e.detail.index) },

  _showAppDialog(opts) {
    const dialog = this.selectComponent('#appDialog')
    if (!dialog || typeof dialog.show !== 'function') return Promise.resolve(false)
    return dialog.show(opts || {})
  },

  async requestExit() {
    if (this.data.submitting) return
    this._settleCurrentTime().catch(() => {})
    const confirmed = await this._showAppDialog({
      scenario: 'all-done',
      title: '暂时退出考试？',
      message: '60 分钟内回来可继续作答；超过 60 分钟草稿将被清除，需要重新作答。',
      confirmText: '退出',
      cancelText: '继续作答',
      hideEyebrow: true,
    })
    if (confirmed) wx.navigateBack({ delta: 1 })
  },

  async submitExam(options = {}) {
    if (this.data.submitting) return
    const auto = !!options.auto || this.data.timeExpired
    if (!auto) {
      const unanswered = Math.max(0, this.data.totalCount - this.data.answeredCount)
      const marked = (this.data.questions || []).filter((q) => q._marked).length
      const confirmed = await this._showAppDialog({
        scenario: unanswered ? 'unanswered' : 'all-done',
        title: '确认交卷',
        message: `${unanswered ? `还有 ${unanswered} 题未作答。` : '所有题目均已作答。'}${marked ? `\n另有 ${marked} 题待检查。` : ''}\n交卷后不可修改。`,
        confirmText: '确认交卷',
        cancelText: '继续检查',
        hideEyebrow: true,
      })
      if (!confirmed) return
    }

    // The countdown can expire while the manual confirmation modal is open.
    // In that case the auto-submit path may already have started; do not launch
    // a second client-side flush/submit sequence after the modal resolves.
    if (this.data.submitting) return
    this.setData({ submitting: true })
    this._clearTimer()
    try {
      await this._settleCurrentTime()
      await this._flushAllPending()
      await api.post(`/exams/attempts/${this.data.attemptId}/submit`, {})
      try { wx.removeStorageSync(cacheKey(this.data.attemptId)) } catch (_) {}
      try { wx.removeStorageSync(legacyCacheKey(this.data.attemptId)) } catch (_) {}
      wx.redirectTo({ url: `/subpackages/exam/result/index?attempt_id=${this.data.attemptId}` })
    } catch (error) {
      this.setData({ submitting: false })
      if (auto) {
        this.setData({ timeExpired: true, remainingText: '已到时 · 待联网交卷' })
        wx.showToast({ title: '时间已到，请联网后再次交卷', icon: 'none' })
      } else {
        wx.showToast({ title: api.getErrorMessage(error), icon: 'none' })
        this._startTimer(this._timerBaseRemaining == null ? null : Math.max(0, this._timerBaseRemaining - Math.floor((api.now() - this._timerStartedAt) / 1000)))
      }
    }
  },

  retry() { this.loadAttempt() },
})
