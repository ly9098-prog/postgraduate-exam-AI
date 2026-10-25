const api = require('../../../utils/api')
const examAttemptCache = require('../utils/exam-attempt-cache')
const { matchesPaper, paperRenderSignature } = require('../utils/paper-search')
const { buildPapers } = require('../utils/paper-list-mapper')
const { createPaperListLoadController } = require('../utils/paper-list-load-controller')
const { createPaperCancelResumeController } = require('../utils/paper-cancel-resume-controller')

const SEARCH_DEBOUNCE_MS = 280

Page({
  data: {
    loading: true,
    errorText: '',
    papers: [],
    visiblePapers: [],
    searchInput: '',
    activeQuery: '',
    searchFocused: false,
    startingId: 0,
    cancellingAttemptId: 0,
    suggestedPaperId: 0,
  },

  onLoad(options = {}) {
    this._pageAlive = true
    this._loadGeneration = 0
    const suggestedPaperId = Number(options.suggested_paper_id) || 0
    this.setData({ suggestedPaperId })
    this.loadPapers()
  },

  onShow() {
    if (!this._loadedOnce) return
    clearTimeout(this._resumeRefreshTimer)
    this._resumeRefreshTimer = setTimeout(() => {
      this._resumeRefreshTimer = null
      this.loadPapers({ silent: true })
    }, 180)
  },

  onUnload() {
    this._pageAlive = false
    this._loadGeneration = (this._loadGeneration || 0) + 1
    this._clearSearchTimer()
    clearTimeout(this._resumeRefreshTimer)
    this._resumeRefreshTimer = null
  },

  async loadPapers(options = {}) {
    return this._paperListLoadController().load(options)
  },

  _paperListLoadController() {
    if (!this._paperListLoad) {
      this._paperListLoad = createPaperListLoadController({
        nextGeneration: () => {
          this._loadGeneration = (this._loadGeneration || 0) + 1
          return this._loadGeneration
        },
        getGeneration: () => this._loadGeneration,
        isPageAlive: () => this._pageAlive,
        wasLoadedOnce: () => !!this._loadedOnce,
        markLoadedOnce: () => { this._loadedOnce = true },
        getErrorText: () => this.data.errorText,
        setData: data => this.setData(data),
        getPapers: () => api.get('/exams/papers'),
        getErrorMessage: error => api.getErrorMessage(error),
        showToast: options => wx.showToast(options),
        buildPapers: rows => buildPapers(rows, this.data.suggestedPaperId),
        commitPapers: (papers, commitOptions) => this._commitPapers(papers, commitOptions),
      })
    }
    return this._paperListLoad
  },

  _commitPapers(papers, options = {}) {
    const query = String(this.data.searchInput || '').trim()
    const nextSignature = paperRenderSignature(papers)
    const visiblePapers = papers.filter((item) => matchesPaper(item, query))

    if (options.silent && nextSignature === this._paperRenderSignature) {
      return
    }

    this._paperRenderSignature = nextSignature
    this.setData({
      papers,
      visiblePapers,
      activeQuery: query,
      loading: false,
      errorText: '',
    })
  },

  _clearSearchTimer() {
    if (!this._searchTimer) return
    clearTimeout(this._searchTimer)
    this._searchTimer = null
  },

  _applySearch(query) {
    const value = String(query == null ? this.data.searchInput : query).trim()
    const visiblePapers = this.data.papers.filter((item) => matchesPaper(item, value))
    this.setData({ activeQuery: value, visiblePapers })
  },

  onSearchInput(e) {
    const value = e && e.detail ? String(e.detail.value || '') : ''
    this.setData({ searchInput: value })
    this._clearSearchTimer()

    if (!value.trim()) {
      this._applySearch('')
      return
    }

    this._searchTimer = setTimeout(() => {
      this._searchTimer = null
      this._applySearch(value)
    }, SEARCH_DEBOUNCE_MS)
  },

  onSearchConfirm() {
    this._clearSearchTimer()
    this._applySearch(this.data.searchInput)
    if (wx.hideKeyboard) wx.hideKeyboard()
  },

  onSearchFocus() {
    if (!this.data.searchFocused) this.setData({ searchFocused: true })
  },

  onSearchBlur() {
    if (this.data.searchFocused) this.setData({ searchFocused: false })
  },

  clearSearch() {
    this._clearSearchTimer()
    this.setData({ searchInput: '' })
    this._applySearch('')
  },


  retryLoad() {
    this.loadPapers()
  },

  _showAppDialog(opts) {
    const dialog = this.selectComponent('#appDialog')
    if (!dialog || typeof dialog.show !== 'function') return Promise.resolve(false)
    return dialog.show(opts || {})
  },

  async openPaper(e) {
    const id = Number(e.currentTarget.dataset.id)
    const paper = this.data.papers.find((item) => Number(item.id) === id)
    if (!paper || this.data.startingId || this.data.cancellingAttemptId) return

    if (paper.canResume) {
      wx.navigateTo({ url: `/subpackages/exam/exam-runner/index?attempt_id=${paper.latest_attempt_id}` })
      return
    }

    const confirmed = await this._showAppDialog({
      scenario: 'all-done',
      layout: 'exam-start',
      iconImage: '/components/app-dialog/assets/exam-start-check.png',
      title: paper.typeLabel,
      subtitle: paper.year ? String(paper.year) : '',
      metaItems: [
        { icon: 'paper', text: `共 ${paper.question_count} 题` },
        { icon: 'score', text: `${paper.scoreText} 分` },
        { icon: 'time', text: paper.durationMinutes ? `限时 ${paper.durationMinutes} 分钟` : '不限时' },
      ],
      confirmText: '开始作答',
      cancelText: '稍后再做',
      hideEyebrow: true,
    })
    if (!confirmed) return

    this.setData({ startingId: id })
    try {
      const attempt = await api.post(`/exams/papers/${id}/attempts`, {
        request_id: api.createRequestId(),
      })
      wx.navigateTo({ url: `/subpackages/exam/exam-runner/index?attempt_id=${attempt.id}` })
    } catch (error) {
      wx.showToast({ title: api.getErrorMessage(error), icon: 'none' })
    } finally {
      this.setData({ startingId: 0 })
    }
  },

  _optimisticallyClearResume(paperId, attemptId) {
    const papers = this.data.papers.map((item) => {
      if (Number(item.id) !== Number(paperId)) return item
      if (Number(item.latest_attempt_id) !== Number(attemptId)) return item
      return {
        ...item,
        canResume: false,
        latest_attempt_id: null,
        latest_attempt_status: 'abandoned',
      }
    })
    this._commitPapers(papers)
  },

  _clearCancelledAttemptCache(attemptId) {
    examAttemptCache.clearPendingAttempt(attemptId)
  },

  async _reconcileCancelledAttemptCache(attemptId) {
    try {
      const attempt = await api.get(
        `/exams/attempts/${attemptId}`,
        {},
        { timeout: 10000, suppressNetworkToast: true }
      )
      const status = attempt && attempt.status
      // A clock-expired attempt can still be stored as in_progress until the
      // atomic submit arrives with locally pending answers. Never discard that
      // cache based only on the paper-list's virtual "expired" presentation.
      if (status === 'abandoned' || status === 'submitted' || status === 'expired') {
        this._clearCancelledAttemptCache(attemptId)
      }
      return status || ''
    } catch (_) {
      // When state cannot be confirmed, preserving the draft is safer than
      // deleting potentially unsynchronised final answers.
      return ''
    }
  },

  async cancelResume(e) {
    return this._paperCancelResumeController().cancel(e)
  },

  _paperCancelResumeController() {
    if (!this._paperCancelResume) {
      this._paperCancelResume = createPaperCancelResumeController({
        getStartingId: () => this.data.startingId,
        getCancellingAttemptId: () => this.data.cancellingAttemptId,
        setCancellingAttemptId: value => this.setData({ cancellingAttemptId: value }),
        isPageAlive: () => this._pageAlive,
        findPaper: paperId => this.data.papers.find(item => Number(item.id) === paperId),
        refreshAfterStateMismatch: () =>
          this.loadPapers({ silent: true, force: true, suppressErrorToast: true }),
        confirmCancel: () => this._showAppDialog({
          scenario: 'danger',
          title: '取消本次作答？',
          message: '当前未提交的作答进度将被放弃，之后会从头开始；本次不会生成考试记录。',
          confirmText: '取消本次',
          cancelText: '继续作答',
          maskClose: false,
        }),
        abandonAttempt: attemptId => api.post(`/exams/attempts/${attemptId}/abandon`),
        clearAttemptCache: attemptId => this._clearCancelledAttemptCache(attemptId),
        optimisticallyClearResume: (paperId, attemptId) =>
          this._optimisticallyClearResume(paperId, attemptId),
        refreshAfterCancel: () =>
          this.loadPapers({ silent: true, force: true, suppressErrorToast: true }),
        reconcileAttemptCache: attemptId => this._reconcileCancelledAttemptCache(attemptId),
        getErrorMessage: error => api.getErrorMessage(error),
        showToast: options => wx.showToast(options),
      })
    }
    return this._paperCancelResume
  },

  goHistory() {
    wx.navigateTo({ url: '/subpackages/exam/history/index' })
  },

  goBack() {
    const pages = typeof getCurrentPages === 'function' ? getCurrentPages() : []
    if (pages && pages.length > 1) {
      wx.navigateBack({ delta: 1 })
      return
    }
    wx.reLaunch({ url: '/pages/home/home' })
  },
})
