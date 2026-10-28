const api = require('../../../utils/api')
const view = require('../utils/exam-runner-view')
const { buildFinalSubmitAnswers, isRetryableSubmitError } = require('../utils/submit-helpers')
const { buildServerAnswersMap, mergeAnswerState, buildExamResultUrl, findPageInStack, buildPaperListUrl, buildPendingItem, computeAnsweredProgress } = require('../utils/hydrate-helpers')
const {
  createExamTimerController,
} = require('../utils/exam-timer-controller')
const {
  createExamPendingCacheController,
} = require('../utils/exam-pending-cache-controller')
const {
  createExamAnswerSyncController,
} = require('../utils/exam-answer-sync-controller')
const {
  createExamSubmitRetryController,
} = require('../utils/exam-submit-retry-controller')
const {
  createExamAttemptReconcileController,
} = require('../utils/exam-attempt-reconcile-controller')
const {
  createExamSubmitOutcomeController,
} = require('../utils/exam-submit-outcome-controller')
const {
  createExamSubmitPreparationController,
} = require('../utils/exam-submit-preparation-controller')
const {
  createExamInteractionController,
} = require('../utils/exam-interaction-controller')
const {
  createExamQuestionTimeController,
} = require('../utils/exam-question-time-controller')
const {
  createExamQuestionNavigationController,
} = require('../utils/exam-question-navigation-controller')
const {
  createExamReconnectController,
} = require('../utils/exam-reconnect-controller')
const {
  createExamSubmitEntryController,
} = require('../utils/exam-submit-entry-controller')
const {
  createExamExitRequestController,
} = require('../utils/exam-exit-request-controller')
const {
  buildExamPendingCachePageCapabilities,
  isPendingItemKey,
} = require('../utils/exam-runner-pending-cache-page-adapter')
const {
  buildExamTimerPageCapabilities,
} = require('../utils/exam-runner-timer-page-adapter')
const {
  buildExamInteractionPageCapabilities,
  buildExamQuestionTimePageCapabilities,
  buildExamAnswerSyncPageCapabilities,
  buildExamAttemptReconcilePageCapabilities,
} = require('../utils/exam-runner-answer-page-adapter')
const {
  buildExamQuestionNavigationPageCapabilities,
  buildExamExitRequestPageCapabilities,
} = require('../utils/exam-runner-navigation-page-adapter')
const {
  buildExamSubmitRetryPageCapabilities,
  buildExamSubmitEntryPageCapabilities,
  buildExamSubmitPreparationPageCapabilities,
  buildExamSubmitOutcomePageCapabilities,
} = require('../utils/exam-runner-submit-page-adapter')
const {
  buildExamReconnectPageCapabilities,
} = require('../utils/exam-runner-reconnect-page-adapter')

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
    return this._examPendingCacheController().load(attemptId)
  },

  _clearPendingStorage(attemptId = this.data.attemptId) {
    this._examPendingCacheController().clear(attemptId)
  },

  _pendingItemIds() {
    return Object.keys(this._pending || {}).filter(isPendingItemKey)
  },

  _persistPending() {
    this._examPendingCacheController().persist(
      this._pending,
      this.data.attemptId,
      this._retainPendingForSubmit
    )
  },
  _examPendingCacheController() {
    return this._examPendingCache || (
      this._examPendingCache = createExamPendingCacheController(
        buildExamPendingCachePageCapabilities(this)
      )
    )
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
    this._examQuestionNavigationController().setCurrent(index)
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
      this._examTimer = createExamTimerController(
        buildExamTimerPageCapabilities(this)
      )
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
    this._examInteractionController().selectOption(e)
  },

  toggleMark() {
    this._examInteractionController().toggleMark()
  },

  _setCountsOnly() {
    this.setData(computeAnsweredProgress(this.data.questions))
  },

  _examInteractionController() {
    return this._examInteraction || (
      this._examInteraction = createExamInteractionController(
        buildExamInteractionPageCapabilities(this)
      )
    )
  },

  _queueItem(itemId) {
    this._pending[String(itemId)] = buildPendingItem(this._answers[String(itemId)])
    this._persistPending()
  },

  _settleCurrentTime(options = {}) {
    return this._examQuestionTimeController().settle(options)
  },

  _examQuestionTimeController() {
    return this._examQuestionTime || (
      this._examQuestionTime = createExamQuestionTimeController(
        buildExamQuestionTimePageCapabilities(this)
      )
    )
  },

  async _syncItem(itemId) {
    return this._examAnswerSyncController().syncItem(itemId)
  },

  async _flushAllPending(options = {}) {
    return this._examAnswerSyncController().flushAllPending(options)
  },

  _examAnswerSyncController() {
    return this._examAnswerSync || (
      this._examAnswerSync = createExamAnswerSyncController(
        buildExamAnswerSyncPageCapabilities(this)
      )
    )
  },

  async _resolveTerminalSyncConflict(error) {
    if (!error || Number(error.statusCode) !== 409) return false
    return this._reconcileAttemptState()
  },

  async _reconcileAttemptState() {
    return this._examAttemptReconcileController().reconcile()
  },

  _examAttemptReconcileController() {
    return this._examAttemptReconcile || (
      this._examAttemptReconcile = createExamAttemptReconcileController(
        buildExamAttemptReconcilePageCapabilities(this)
      )
    )
  },

  _buildFinalSubmitAnswers() {
    return buildFinalSubmitAnswers(this._pendingItemIds(), this._pending)
  },

  _isRetryableSubmitError(error) {
    return isRetryableSubmitError(error)
  },

  async _postSubmitWithRetry(finalAnswers) {
    return this._examSubmitRetryController().postWithRetry(finalAnswers)
  },

  _examSubmitRetryController() {
    return this._examSubmitRetry || (
      this._examSubmitRetry = createExamSubmitRetryController(
        buildExamSubmitRetryPageCapabilities(this)
      )
    )
  },

  async _recoverPendingAfterReconnect() {
    return this._examReconnectController().recoverPending()
  },

  _examReconnectController() {
    return this._examReconnect || (
      this._examReconnect = createExamReconnectController(
        buildExamReconnectPageCapabilities(this)
      )
    )
  },

  _moveTo(index) {
    this._examQuestionNavigationController().moveTo(index)
  },

  _examQuestionNavigationController() {
    return this._examQuestionNavigation || (
      this._examQuestionNavigation = createExamQuestionNavigationController(
        buildExamQuestionNavigationPageCapabilities(this)
      )
    )
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
    return this._examExitRequestController().request()
  },

  _examExitRequestController() {
    return this._examExitRequest || (
      this._examExitRequest = createExamExitRequestController(
        buildExamExitRequestPageCapabilities(this)
      )
    )
  },

  async submitExam(options = {}) {
    return this._examSubmitEntryController().request(options)
  },

  _examSubmitEntryController() {
    return this._examSubmitEntry || (
      this._examSubmitEntry = createExamSubmitEntryController(
        buildExamSubmitEntryPageCapabilities(this)
      )
    )
  },

  async _performSubmit(auto) {
    try {
      const prepared = await this._examSubmitPreparationController().prepare(auto)
      const result = await this._postSubmitWithRetry(prepared.finalAnswers)
      this._examSubmitOutcomeController().applySuccess(result)
      return
    } catch (error) {
      return this._examSubmitOutcomeController().applyFailure(error, this._lastSubmitAuto)
    }
  },

  _examSubmitPreparationController() {
    return this._examSubmitPreparation || (
      this._examSubmitPreparation = createExamSubmitPreparationController(
        buildExamSubmitPreparationPageCapabilities(this)
      )
    )
  },

  _examSubmitOutcomeController() {
    return this._examSubmitOutcome || (
      this._examSubmitOutcome = createExamSubmitOutcomeController(
        buildExamSubmitOutcomePageCapabilities(this)
      )
    )
  },

  retry() { this.loadAttempt() },
})
