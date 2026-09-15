const api = require('../../../utils/api')
const examAttemptCache = require('../utils/exam-attempt-cache')

const SEARCH_DEBOUNCE_MS = 280

function minutes(sec) {
  const value = Number(sec || 0)
  return value > 0 ? Math.max(1, Math.round(value / 60)) : 0
}

function cleanUiLabel(value, fallback = '') {
  return String(value || fallback).replace(/408/g, '').replace(/\s{2,}/g, ' ').trim()
}

function typeLabel(type) {
  return type === 'past_exam_choice' ? '真题选择题' : '选择题模拟卷'
}

function typeHint(type) {
  return type === 'past_exam_choice'
    ? '历年真题 · 只做适合手机作答的选择题'
    : '模拟训练 · 只做适合手机作答的选择题'
}

function normalizeSearchValue(value) {
  return String(value || '')
    .toLowerCase()
    .replace(/408/g, '')
    .replace(/[\s\-_/.,，。:：;；|｜()[\]{}【】（）'"“”‘’·]+/g, '')
}

function fuzzyIncludes(target, term) {
  if (!term) return true
  if (target.indexOf(term) !== -1) return true

  let termIndex = 0
  for (let i = 0; i < target.length && termIndex < term.length; i += 1) {
    if (target[i] === term[termIndex]) termIndex += 1
  }
  return termIndex === term.length
}

function matchesPaper(paper, query) {
  const rawTerms = String(query || '').trim().split(/\s+/).filter(Boolean)
  if (!rawTerms.length) return true

  const target = normalizeSearchValue([
    paper.title,
    paper.source,
    paper.typeLabel,
    paper.typeHint,
    paper.year,
    paper.question_count ? `${paper.question_count}题` : '',
    paper.scoreText ? `${paper.scoreText}分` : '',
    paper.durationMinutes ? `${paper.durationMinutes}分钟` : '',
  ].join(' '))

  return rawTerms.every((rawTerm) => fuzzyIncludes(target, normalizeSearchValue(rawTerm)))
}

function paperRenderSignature(papers) {
  return (Array.isArray(papers) ? papers : []).map((item) => [
    item.id,
    item.title,
    item.source,
    item.typeLabel,
    item.year,
    item.question_count,
    item.scoreText,
    item.durationMinutes,
    item.bestScoreText,
    item.canResume ? 1 : 0,
    item.latest_attempt_id || '',
    item.isSuggested ? 1 : 0,
    item.isLatestYear ? 1 : 0,
  ].join('|')).join('||')
}

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
    const silent = !!options.silent
    const force = !!options.force
    const suppressErrorToast = !!options.suppressErrorToast
    if (this._loadPromise && !force) return this._loadPromise

    if (!silent && !this._loadedOnce) {
      this.setData({ loading: true, errorText: '' })
    }

    // A cancellation can happen while an onShow refresh is still in flight.
    // Allow the post-cancel force refresh to overtake it, and only let the
    // newest generation commit. This prevents stale responses from restoring
    // a just-cancelled "继续作答" state.
    const generation = (this._loadGeneration || 0) + 1
    this._loadGeneration = generation

    const request = (async () => {
      try {
        const rows = await api.get('/exams/papers')
        const basePapers = (Array.isArray(rows) ? rows : []).map((item) => ({
          ...item,
          title: cleanUiLabel(item.title, '选择题套卷'),
          source: cleanUiLabel(item.source, 'MemoGrad'),
          typeLabel: typeLabel(item.paper_type),
          typeHint: typeHint(item.paper_type),
          durationMinutes: minutes(item.duration_sec),
          scoreText: Number(item.total_choice_score || 0).toFixed(0),
          bestScoreText: item.best_choice_score == null ? '' : Number(item.best_choice_score).toFixed(1),
          canResume: item.latest_attempt_status === 'in_progress' && !!item.latest_attempt_id,
          isSuggested: Number(item.id) === Number(this.data.suggestedPaperId),
        }))

        const latestYear = basePapers.reduce((maxYear, item) => {
          const year = Number(item.year) || 0
          return year > maxYear ? year : maxYear
        }, 0)

        const papers = basePapers.map((item) => ({
          ...item,
          isLatestYear: !!latestYear && Number(item.year) === latestYear,
        }))

        if (!this._pageAlive || generation !== this._loadGeneration) return
        const wasLoaded = this._loadedOnce
        this._loadedOnce = true
        this._commitPapers(papers, { silent: silent || wasLoaded })
      } catch (error) {
        if (!this._pageAlive || generation !== this._loadGeneration) return
        const message = api.getErrorMessage(error)
        if ((silent || this._loadedOnce) && !this.data.errorText) {
          if (!suppressErrorToast) wx.showToast({ title: message, icon: 'none' })
          return
        }
        this.setData({ loading: false, errorText: message })
      }
    })()

    this._loadPromise = request
    try {
      await request
    } finally {
      if (this._loadPromise === request) this._loadPromise = null
    }
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
    const paperId = Number(e.currentTarget.dataset.id)
    const attemptId = Number(e.currentTarget.dataset.attemptId)
    if (!paperId || !attemptId || this.data.startingId || this.data.cancellingAttemptId) return

    const paper = this.data.papers.find((item) => Number(item.id) === paperId)
    if (!paper || !paper.canResume || Number(paper.latest_attempt_id) !== attemptId) {
      await this.loadPapers({ silent: true, force: true, suppressErrorToast: true })
      return
    }

    const confirmed = await this._showAppDialog({
      scenario: 'danger',
      title: '取消本次作答？',
      message: '当前未提交的作答进度将被放弃，之后会从头开始；本次不会生成考试记录。',
      confirmText: '取消本次',
      cancelText: '继续作答',
      maskClose: false,
    })
    if (!confirmed || !this._pageAlive) return

    this.setData({ cancellingAttemptId: attemptId })
    try {
      const result = await api.post(`/exams/attempts/${attemptId}/abandon`)
      if (!result || result.status !== 'abandoned' || Number(result.id) !== attemptId) {
        throw new Error('INVALID_ABANDON_RESPONSE')
      }

      // Only clear local drafts after the server has durably accepted the
      // cancellation. A network failure must leave the cache intact so the
      // user can still resume safely.
      this._clearCancelledAttemptCache(attemptId)
      if (!this._pageAlive) return
      this._optimisticallyClearResume(paperId, attemptId)
      wx.showToast({ title: '已取消本次作答', icon: 'success' })

      // Reconcile with the server after the optimistic update. force=true is
      // important when an older onShow request is still running.
      await this.loadPapers({ silent: true, force: true, suppressErrorToast: true })
    } catch (error) {
      if (!this._pageAlive) return

      // A 409 means another request/device won a terminal-state race, or the
      // countdown has just elapsed. Confirm the real attempt state before
      // touching local drafts: list_papers may *present* an elapsed in_progress
      // row as expired even though its pending answers still need atomic submit.
      if (Number(error && error.statusCode) === 409) {
        await this._reconcileCancelledAttemptCache(attemptId)
        await this.loadPapers({ silent: true, force: true, suppressErrorToast: true })
        wx.showToast({ title: '作答状态已变化，请重新确认', icon: 'none' })
      } else {
        wx.showToast({ title: api.getErrorMessage(error), icon: 'none' })
      }
    } finally {
      if (this._pageAlive && Number(this.data.cancellingAttemptId) === attemptId) {
        this.setData({ cancellingAttemptId: 0 })
      }
    }
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
