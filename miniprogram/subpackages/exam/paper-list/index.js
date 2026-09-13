const api = require('../../../utils/api')

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
    suggestedPaperId: 0,
  },

  onLoad(options = {}) {
    const suggestedPaperId = Number(options.suggested_paper_id) || 0
    this.setData({ suggestedPaperId })
    this.loadPapers()
  },

  onShow() {
    if (this._loadedOnce) this.loadPapers({ silent: true })
  },

  onUnload() {
    this._clearSearchTimer()
  },

  async loadPapers(options = {}) {
    if (!options.silent) this.setData({ loading: true, errorText: '' })
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

      this._loadedOnce = true
      this._commitPapers(papers)
    } catch (error) {
      const message = api.getErrorMessage(error)
      if (options.silent && this.data.papers.length) {
        wx.showToast({ title: message, icon: 'none' })
        return
      }
      this.setData({ loading: false, errorText: message })
    }
  },

  _commitPapers(papers) {
    const query = String(this.data.searchInput || '').trim()
    this.setData({
      papers,
      visiblePapers: papers.filter((item) => matchesPaper(item, query)),
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
    if (!paper || this.data.startingId) return

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
