const api = require('../../../utils/api')
const examAttemptCache = require('../utils/exam-attempt-cache')
const view = require('../utils/exam-runner-view')
const { buildFinalSubmitAnswers, isRetryableSubmitError } = require('../utils/submit-helpers')
const { buildServerAnswersMap, mergeAnswerState, buildExamResultUrl, findPageInStack, buildPaperListUrl, buildPendingItem, computeAnsweredProgress } = require('../utils/hydrate-helpers')
const {
  createExamTimerController,
} = require('../utils/exam-timer-controller')

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

const EXAM_CACHE_SCHEMA_VERSION = 3
// 本地草稿保留时长：离开作答页后 60 分钟内可恢复，超时进入重新作答状态。
const EXAM_DRAFT_TTL_MS = 60 * 60 * 1000
// 到时后如果因为断网尚未完成交卷，pending 答案需要比普通草稿保留更久。
// 只有服务端确认终态后才主动清理；7 天上限用于防止异常缓存永久占用空间。
const EXAM_SUBMIT_PENDING_TTL_MS = 7 * 24 * 60 * 60 * 1000
const { cacheKey, v2CacheKey, legacyCacheKey } = examAttemptCache
function isPendingItemKey(value) { return /^\d+$/.test(String(value || '')) }
function sleep(ms) { return new Promise(resolve => setTimeout(resolve, Math.max(0, Number(ms) || 0))) }

function sanitizePendingItems(raw) {
  const source = raw && typeof raw === 'object' ? raw : {}
  const result = Object.create(null)
  Object.keys(source).forEach((key) => {
    if (!isPendingItemKey(key)) return
    const value = source[key]
    if (!value || typeof value !== 'object') return
    result[String(Number(key))] = {
      selected_answer: String(value.selected_answer || '').trim().toUpperCase() || null,
      marked_for_review: !!value.marked_for_review,
      used_time: Math.min(6 * 60 * 60, Math.max(0, Number(value.used_time || 0))),
    }
  })
  return result
}

Page({
  data: {
    statusBarHeight: 0,
    navBarHeight: 44,
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
    resultRecoveryPending: false,
  },

  onLoad(options) {
    const sys = wx.getWindowInfo ? (wx.getWindowInfo() || {}) : {}
    const attemptId = Number(options && options.attempt_id)
    const statusBarHeight = Number(sys.statusBarHeight || 0)
    let navBarHeight = 44
    try {
      const menu = wx.getMenuButtonBoundingClientRect && wx.getMenuButtonBoundingClientRect()
      if (menu && menu.height > 0 && menu.top >= statusBarHeight) {
        navBarHeight = Math.max(40, (menu.top - statusBarHeight) * 2 + menu.height)
      }
    } catch (e) {}
    this.setData({ statusBarHeight, navBarHeight, attemptId })
    if (!attemptId) {
      this.setData({ loading: false, errorText: '缺少考试记录 ID' })
      return
    }
    this._pageAlive = true
    this._navigationLocked = false
    this._terminalNavigation = false
    this._attemptTerminal = false
    this._attemptAbandoned = false
    this._renderCache = Object.create(null)
    this._answers = Object.create(null)
    this._retainPendingForSubmit = false
    this._pending = this._loadPending(attemptId)
    this._syncing = Object.create(null)
    this._attemptLoaded = false
    this._reconnectSyncing = false
    this._submitPromise = null
    this._confirmingSubmit = false
    this._networkStatusHandler = (res) => {
      if (res && res.isConnected) this._recoverPendingAfterReconnect().catch(() => {})
    }
    if (wx.onNetworkStatusChange) wx.onNetworkStatusChange(this._networkStatusHandler)
    this.loadAttempt()
  },

  onShow() {
    if (!this._pageAlive || !this._attemptLoaded) return
    // setInterval can be suspended while WeChat is backgrounded. Re-evaluate
    // against the server-synchronised wall clock immediately on resume so an
    // elapsed exam cannot keep accepting input until the next timer callback.
    this._tickTimer()
    if (!this.data.timeExpired) this._recoverPendingAfterReconnect().catch(() => {})
  },

  onUnload() {
    this._pageAlive = false
    this._attemptLoaded = false
    if (this._networkStatusHandler && wx.offNetworkStatusChange) {
      wx.offNetworkStatusChange(this._networkStatusHandler)
    }
    this._networkStatusHandler = null
    this._clearTimer()
    // 页面销毁阶段只落本地草稿，不再发起可能触发二次跳转的网络请求。
    // 已进入终态导航时也不再回写草稿，避免交卷成功后重新生成 pending 缓存。
    if (!this._attemptTerminal && !this._terminalNavigation) this._settleCurrentTime({ sync: false })
  },

  _loadPending(attemptId) {
    try {
      let raw = wx.getStorageSync(cacheKey(attemptId))
      let savedAt = 0
      let items = null
      let submitPending = false

      if (raw && typeof raw === 'object' && raw.items && typeof raw.items === 'object') {
        savedAt = Number(raw.saved_at || 0)
        items = sanitizePendingItems(raw.items)
        submitPending = raw.submit_pending === true
      } else {
        // v2 stored metadata (schema_version/saved_at) beside numeric item IDs.
        // That shape could accidentally make the sync loop PATCH pseudo item IDs
        // such as /answers/saved_at after a restart. Migrate only numeric keys.
        const v2 = wx.getStorageSync(v2CacheKey(attemptId))
        const v1 = wx.getStorageSync(legacyCacheKey(attemptId))
        const legacy = v2 && typeof v2 === 'object' ? v2 : (v1 && typeof v1 === 'object' ? v1 : null)
        if (legacy) {
          savedAt = Number(legacy.saved_at || 0)
          items = sanitizePendingItems(legacy.items && typeof legacy.items === 'object' ? legacy.items : legacy)
          submitPending = legacy.submit_pending === true
        }
      }

      if (!items) return Object.create(null)
      const ttl = submitPending ? EXAM_SUBMIT_PENDING_TTL_MS : EXAM_DRAFT_TTL_MS
      if (savedAt > 0 && api.now() - savedAt > ttl) {
        this._clearPendingStorage(attemptId)
        return Object.create(null)
      }
      this._retainPendingForSubmit = submitPending

      try {
        wx.setStorageSync(cacheKey(attemptId), {
          schema_version: EXAM_CACHE_SCHEMA_VERSION,
          saved_at: savedAt || api.now(),
          submit_pending: submitPending,
          items,
        })
        wx.removeStorageSync(v2CacheKey(attemptId))
        wx.removeStorageSync(legacyCacheKey(attemptId))
      } catch (_) {}
      return items
    } catch (_) {
      return Object.create(null)
    }
  },

  _clearPendingStorage(attemptId = this.data.attemptId) {
    examAttemptCache.clearPendingAttempt(attemptId)
  },

  _pendingItemIds() {
    return Object.keys(this._pending || {}).filter(isPendingItemKey)
  },

  _persistPending() {
    try {
      const keys = this._pendingItemIds()
      if (keys.length) {
        const items = Object.create(null)
        keys.forEach((key) => { items[key] = Object.assign({}, this._pending[key]) })
        wx.setStorageSync(cacheKey(this.data.attemptId), {
          schema_version: EXAM_CACHE_SCHEMA_VERSION,
          saved_at: api.now(),
          submit_pending: !!this._retainPendingForSubmit,
          items,
        })
      } else this._clearPendingStorage()
    } catch (_) {}
  },

  _navigateToResult() {
    if (!this._pageAlive || this._terminalNavigation) return
    this._terminalNavigation = true
    this._navigationLocked = true
    this._clearTimer()
    wx.redirectTo({
      url: buildExamResultUrl(this.data.attemptId),
      fail: () => {
        this._terminalNavigation = false
        if (this._pageAlive) {
          this._navigationLocked = true
          this.setData({ resultRecoveryPending: true })
          if (this.data.submitting) this.setData({ submitting: false })
          wx.showToast({ title: '答卷已归档，请重新打开结果页', icon: 'none' })
        }
      },
    })
  },

  retryResultNavigation() {
    if (!this._attemptTerminal || this._terminalNavigation) return
    this._terminalNavigation = false
    this._navigationLocked = false
    this.setData({ resultRecoveryPending: false })
    this._navigateToResult()
  },

  _navigateToPaperList() {
    if (!this._pageAlive || this._terminalNavigation) return
    this._terminalNavigation = true
    this._navigationLocked = true
    this._clearTimer()
    const targetRoute = 'subpackages/exam/paper-list/index'
    const pages = typeof getCurrentPages === 'function' ? getCurrentPages() : []
    const targetIndex = findPageInStack(pages, targetRoute)
    const fail = () => {
      this._terminalNavigation = false
      this._navigationLocked = false
      if (this._pageAlive) wx.showToast({ title: '套卷列表打开失败，请重试', icon: 'none' })
    }
    if (targetIndex >= 0) {
      wx.navigateBack({ delta: Math.max(1, pages.length - 1 - targetIndex), fail })
      return
    }
    wx.redirectTo({ url: buildPaperListUrl(), fail })
  },

  async loadAttempt() {
    this.setData({ loading: true, errorText: '' })
    try {
      const payload = await api.get(`/exams/attempts/${this.data.attemptId}`)
      if (!this._pageAlive) return
      if (payload.status === 'abandoned') {
        // 已放弃的草稿没有结果快照，回套卷列表重新开始而不是跳结果页。
        this._pending = Object.create(null)
        this._persistPending()
        this._navigateToPaperList()
        return
      }
      if (payload.status !== 'in_progress') {
        this._pending = Object.create(null)
        this._persistPending()
        this._attemptTerminal = true
        this._navigateToResult()
        return
      }
      this._hydrate(payload)
      this._attemptLoaded = true
      this.setData({ loading: false })
      this._startTimer(payload.remaining_sec)
      // Normal in-exam recovery still drains PATCHes eagerly.  At the deadline
      // pending rows are instead carried by the atomic submit request; trying to
      // PATCH them first recreates the exact expiry race we want to avoid.
      if (!this.data.timeExpired) this._flushAllPending({ quiet: true }).catch(() => {})
    } catch (error) {
      if (this._pageAlive) this.setData({ loading: false, errorText: api.getErrorMessage(error) })
    }
  },

  _hydrate(payload) {
    const serverAnswers = buildServerAnswersMap(payload.answers)
    const pending = this._pending || {}
    const questions = (payload.questions || []).map((raw) => {
      const itemId = String(raw.item_id)
      const answer = mergeAnswerState(serverAnswers[itemId], pending[itemId])
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
    this._examTimerController().start(initialRemaining)
  },

  _currentRemainingSec() {
    return this._examTimerController().currentRemainingSec()
  },

  _tickTimer() {
    this._examTimerController().tick()
  },

  _clearTimer() {
    this._examTimerController().clear()
  },
  _examTimerController() {
    return this._examTimer || (
      this._examTimer = createExamTimerController({
        now: () => api.now(),
        formatClock,
        isPageAlive: () => this._pageAlive,
        isAttemptTerminal: () => this._attemptTerminal,
        isTerminalNavigation: () => this._terminalNavigation,
        isTimeExpired: () => this.data.timeExpired,
        getRemainingText: () => this.data.remainingText,
        setData: patch => this.setData(patch),
        getBaseRemaining: () => this._timerBaseRemaining,
        setBaseRemaining: value => { this._timerBaseRemaining = value },
        getStartedAt: () => this._timerStartedAt,
        setStartedAt: value => { this._timerStartedAt = value },
        getTimer: () => this._timer,
        setTimer: timer => { this._timer = timer },
        setInterval,
        clearInterval,
        onExpired: () => {
          this._retainPendingForSubmit = true
          this._persistPending()
          this.submitExam({ auto: true }).catch(() => {})
        },
      })
    )
  },

  _currentItemId() {
    const q = this.data.currentQuestion
    return q && q._itemId ? String(q._itemId) : ''
  },

  _updateQuestionFlags(itemId) {
    const answer = this._answers[String(itemId)] || {}
    const questions = this.data.questions || []
    const index = questions.findIndex(q => String(q._itemId) === String(itemId))
    if (index < 0) return
    const answered = !!answer.selected_answer
    const marked = !!answer.marked_for_review
    if (questions[index]._answered === answered && questions[index]._marked === marked) return
    const update = {}
    update[`questions[${index}]._answered`] = answered
    update[`questions[${index}]._marked`] = marked
    this.setData(update)
  },

  selectOption(e) {
    if (this.data.timeExpired || this.data.submitting || this._navigationLocked) return
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
    if (this.data.timeExpired || this.data.submitting || this._navigationLocked) return
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
    this.setData(computeAnsweredProgress(this.data.questions))
  },

  _queueItem(itemId) {
    this._pending[String(itemId)] = buildPendingItem(this._answers[String(itemId)])
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
            this._attemptTerminal = true
            if (this._pageAlive && !this.data.submitting) this._navigateToResult()
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
        const ids = this._pendingItemIds()
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
    return this._reconcileAttemptState()
  },

  async _reconcileAttemptState() {
    if (!this._pageAlive) return false
    try {
      const payload = await api.get(
        `/exams/attempts/${this.data.attemptId}`,
        {},
        { timeout: 10000, suppressNetworkToast: true }
      )
      if (!payload || payload.status === 'in_progress') return false
      if (payload.status === 'abandoned') {
        this._pending = Object.create(null)
        this._retainPendingForSubmit = false
        this._clearPendingStorage()
        this._attemptTerminal = true
        this._attemptAbandoned = true
        if (this._pageAlive && !this.data.submitting) this._navigateToPaperList()
        return true
      }
      if (payload.status !== 'submitted' && payload.status !== 'expired') return false
      this._pending = Object.create(null)
      this._retainPendingForSubmit = false
      this._clearPendingStorage()
      this._attemptTerminal = true
      this._attemptAbandoned = false
      if (this._pageAlive && !this.data.submitting) this._navigateToResult()
      return true
    } catch (_) {
      return false
    }
  },

  _buildFinalSubmitAnswers() {
    return buildFinalSubmitAnswers(this._pendingItemIds(), this._pending)
  },

  _isRetryableSubmitError(error) {
    return isRetryableSubmitError(error)
  },

  async _postSubmitWithRetry(finalAnswers) {
    // POST /submit is server-idempotent: once the attempt is terminal it returns
    // the immutable result snapshot. That lets us safely retry ambiguous network
    // failures (request committed but response lost) without duplicate records.
    const delays = [0, 450, 1200]
    let lastError = null
    for (let i = 0; i < delays.length; i += 1) {
      if (!this._pageAlive || this._terminalNavigation) throw lastError || new Error('页面已关闭')
      if (delays[i] > 0) await sleep(delays[i])
      try {
        return await api.post(
          `/exams/attempts/${this.data.attemptId}/submit`,
          { answers: finalAnswers },
          { timeout: 12000, suppressNetworkToast: true }
        )
      } catch (error) {
        lastError = error
        if (!this._pageAlive) throw error
        // First determine whether the previous POST actually committed.  The
        // attempt GET is now side-effect free, so this reconciliation cannot
        // accidentally grade an expired draft before its pending answers arrive.
        if (await this._reconcileAttemptState()) return { _reconciled: true }
        if (!this._isRetryableSubmitError(error) || i === delays.length - 1) throw error
      }
    }
    throw lastError || new Error('交卷失败')
  },

  async _recoverPendingAfterReconnect() {
    if (!this._pageAlive || !this._attemptLoaded || this._reconnectSyncing || this._attemptTerminal || this._terminalNavigation) return
    this._reconnectSyncing = true
    try {
      this._tickTimer()
      if (this.data.timeExpired) {
        if (!this.data.submitting) await this.submitExam({ auto: true })
      } else {
        await this._flushAllPending({ quiet: true })
      }
    } catch (_) {
      // 保留 pending，等待下一次网络恢复或用户操作再次同步。
    } finally {
      this._reconnectSyncing = false
    }
  },

  _moveTo(index) {
    if (this.data.timeExpired || this.data.submitting || this._navigationLocked) return
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
    if (this.data.submitting || this._navigationLocked) return
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
    if (this._attemptTerminal || this._navigationLocked) return false
    if (this._submitPromise) return this._submitPromise
    if (this.data.submitting) return
    const auto = !!options.auto || this.data.timeExpired
    if (!auto) {
      if (this._confirmingSubmit) return
      this._confirmingSubmit = true
      const unanswered = Math.max(0, this.data.totalCount - this.data.answeredCount)
      const marked = (this.data.questions || []).filter((q) => q._marked).length
      let confirmed = false
      try {
        confirmed = await this._showAppDialog({
          scenario: unanswered ? 'unanswered' : 'all-done',
          title: '确认交卷',
          message: `${unanswered ? `还有 ${unanswered} 题未作答。` : '所有题目均已作答。'}${marked ? `\n另有 ${marked} 题待检查。` : ''}\n交卷后不可修改。`,
          confirmText: '确认交卷',
          cancelText: '继续检查',
          hideEyebrow: true,
        })
      } finally {
        this._confirmingSubmit = false
      }
      if (!confirmed) return
    }

    // The countdown can expire while the manual confirmation modal is open.
    // In that case the auto-submit path may already have started; do not launch
    // a second client-side flush/submit sequence after the modal resolves.
    if (this._submitPromise) return this._submitPromise
    if (this.data.submitting || this._attemptTerminal || this._navigationLocked) {
      return false
    }

    const task = this._performSubmit(auto)
    this._submitPromise = task
    try {
      return await task
    } finally {
      if (this._submitPromise === task) this._submitPromise = null
    }
  },

  async _performSubmit(auto) {
    const remainingBeforeSubmit = this._currentRemainingSec()
    auto = !!auto || this.data.timeExpired || (remainingBeforeSubmit != null && remainingBeforeSubmit <= 0)
    if (auto) {
      this._retainPendingForSubmit = true
      this._persistPending()
    }
    this.setData({ submitting: true })
    this._clearTimer()
    try {
      // Only settle the local final time slice.  Do not issue N PATCH requests
      // here: all still-pending rows are embedded in the single submit request
      // and persisted atomically with grading on the server.
      await this._settleCurrentTime({ sync: false })
      const finalAnswers = this._buildFinalSubmitAnswers()
      const result = await this._postSubmitWithRetry(finalAnswers)
      if (result && result._reconciled) {
        this._attemptTerminal = true
        if (this._pageAlive && !this._terminalNavigation) {
          if (this._attemptAbandoned) this._navigateToPaperList()
          else this._navigateToResult()
        }
        return
      }

      this._pending = Object.create(null)
      this._retainPendingForSubmit = false
      this._clearPendingStorage()
      this._attemptTerminal = true
      this._navigateToResult()
    } catch (error) {
      // Keep the local pending snapshot intact on every uncertain failure.  A
      // later reconnect can retry the same idempotent submit payload safely.
      if (!this._pageAlive) return false
      if (await this._reconcileAttemptState()) {
        this._attemptTerminal = true
        if (this._pageAlive && !this._terminalNavigation) {
          if (this._attemptAbandoned) this._navigateToPaperList()
          else this._navigateToResult()
        }
        return
      }
      if (this._pageAlive) this.setData({ submitting: false })
      if (auto) {
        if (this._pageAlive) {
          this.setData({ timeExpired: true, remainingText: '已到时 · 待联网交卷' })
          wx.showToast({ title: '时间已到，答案已保留，联网后将自动交卷', icon: 'none' })
        }
      } else {
        if (this._pageAlive) {
          wx.showToast({ title: api.getErrorMessage(error), icon: 'none' })
          const remaining = this._currentRemainingSec()
          if (remaining == null || remaining > 0) this._startTimer(remaining)
          else {
            this.setData({ timeExpired: true, remainingText: '已到时 · 待联网交卷' })
            // Run after the current single-flight promise releases; otherwise
            // submitExam() would simply return the promise that is finishing now.
            setTimeout(() => {
              if (this._pageAlive && !this._attemptTerminal && !this._terminalNavigation) {
                this.submitExam({ auto: true }).catch(() => {})
              }
            }, 0)
          }
        }
      }
      return false
    }
  },

  retry() { this.loadAttempt() },
})
