const api = require('../../../utils/api')

const PAGE_SIZE = 20

function cleanUiLabel(value, fallback = '') {
  return String(value || fallback).replace(/408/g, '').replace(/\s{2,}/g, ' ').trim()
}

function toDate(value) {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

function formatDateParts(value) {
  const date = toDate(value)
  if (!date) return { monthDay: '-- --', year: '----', time: '--:--' }
  const pad = (n) => String(n).padStart(2, '0')
  return {
    monthDay: `${pad(date.getMonth() + 1)}-${pad(date.getDate())}`,
    year: String(date.getFullYear()),
    time: `${pad(date.getHours())}:${pad(date.getMinutes())}`,
  }
}

function formatScore(value) {
  const number = Number(value || 0)
  if (!Number.isFinite(number)) return '0'
  if (Math.abs(number - Math.round(number)) < 0.001) return String(Math.round(number))
  return number.toFixed(1).replace(/\.0$/, '')
}

function formatPercent(value) {
  const number = Number(value || 0)
  const normalized = number > 1 ? number : number * 100
  if (!Number.isFinite(normalized)) return '0%'
  return `${Math.round(normalized)}%`
}

function paperTypeLabel(type) {
  return type === 'past_exam_choice' ? '真题选择卷' : '模拟选择卷'
}

function buildPaperDisplayTitle(item) {
  const title = cleanUiLabel(item.paper_title, '选择题考试')
  const typeLabel = paperTypeLabel(item.paper_type)
  if (!title) return typeLabel
  if (title.includes(typeLabel)) return title
  if (/^\d{4}$/.test(title)) return `${title} · ${typeLabel}`
  return title
}

function normalizeSummary(summary = {}) {
  return {
    completedCount: Math.max(0, Number(summary.completed_count || 0)),
    averageScoreText: formatScore(summary.average_choice_score),
    averageTotalScoreText: formatScore(summary.average_total_choice_score),
    averageAccuracyText: formatPercent(summary.average_accuracy),
  }
}

function normalizeRows(rows) {
  return (Array.isArray(rows) ? rows : []).map((item) => {
    const date = formatDateParts(item.submitted_at || item.started_at)
    return {
      ...item,
      paperDisplayTitle: buildPaperDisplayTitle(item),
      paperTypeText: paperTypeLabel(item.paper_type),
      dateMonthDay: date.monthDay,
      dateYear: date.year,
      submittedTimeText: date.time,
      scoreText: formatScore(item.choice_score),
      totalScoreText: formatScore(item.total_choice_score),
      accuracyText: formatPercent(item.accuracy),
    }
  })
}

function mergeRows(current, incoming) {
  const merged = []
  const seen = new Set()
  ;[...(Array.isArray(current) ? current : []), ...(Array.isArray(incoming) ? incoming : [])].forEach((item) => {
    const key = String(item && item.attempt_id || '')
    if (!key || seen.has(key)) return
    seen.add(key)
    merged.push(item)
  })
  return merged
}

function buildLegacyOverview(rows) {
  const list = Array.isArray(rows) ? rows : []
  const count = list.length
  const average = (getter) => {
    if (!count) return 0
    return list.reduce((sum, item) => sum + Number(getter(item) || 0), 0) / count
  }
  return {
    summary: {
      completed_count: count,
      average_choice_score: average((item) => item.choice_score),
      average_total_choice_score: average((item) => item.total_choice_score),
      average_accuracy: average((item) => item.accuracy),
    },
    items: list,
    total: count,
    has_more: false,
  }
}

Page({
  data: {
    loading: true,
    loadingMore: false,
    errorText: '',
    rows: [],
    total: 0,
    hasMore: false,
    summary: normalizeSummary(),
  },

  onLoad() {
    this.loadHistory({ reset: true })
  },

  onShow() {
    if (this._loadedOnce && !this._historyLoading) {
      this.loadHistory({ reset: true, silent: true })
    }
  },

  onPullDownRefresh() {
    Promise.resolve(this.loadHistory({ reset: true, silent: true })).finally(() => {
      if (wx.stopPullDownRefresh) wx.stopPullDownRefresh()
    })
  },

  onReachBottom() {
    if (this.data.hasMore && !this._historyLoading) {
      this.loadHistory({ append: true })
    }
  },

  async _requestOverview(offset) {
    if (this._legacyHistoryApi) {
      const legacyRows = await api.get('/exams/history', { limit: 100 })
      return buildLegacyOverview(legacyRows)
    }

    try {
      return await api.get('/exams/history/overview', {
        limit: PAGE_SIZE,
        offset,
      })
    } catch (error) {
      // Allows a mini-program release to be deployed slightly before the API
      // release without breaking the history page.
      if (Number(error && error.statusCode) !== 404) throw error
      this._legacyHistoryApi = true
      const legacyRows = await api.get('/exams/history', { limit: 100 })
      return buildLegacyOverview(legacyRows)
    }
  },

  loadHistory(options = {}) {
    if (this._historyLoading) return this._historyLoading

    const reset = options.reset === true
    const append = options.append === true && !reset
    const offset = append ? this.data.rows.length : 0

    if (!options.silent) {
      this.setData({
        loading: !append,
        loadingMore: append,
        errorText: append ? this.data.errorText : '',
      })
    } else if (append) {
      this.setData({ loadingMore: true })
    }

    const task = (async () => {
      try {
        const payload = await this._requestOverview(offset)
        const incoming = normalizeRows(payload && payload.items)
        const rows = append ? mergeRows(this.data.rows, incoming) : incoming
        this._loadedOnce = true
        this.setData({
          loading: false,
          loadingMore: false,
          errorText: '',
          rows,
          total: Number(payload && payload.total) || rows.length,
          hasMore: Boolean(payload && payload.has_more),
          summary: normalizeSummary(payload && payload.summary),
        })
      } catch (error) {
        this.setData({
          loading: false,
          loadingMore: false,
          errorText: api.getErrorMessage(error),
        })
      }
    })()

    this._historyLoading = task.finally(() => {
      this._historyLoading = null
    })
    return this._historyLoading
  },

  openResult(e) {
    const id = Number(e.currentTarget.dataset.id)
    if (!id || this._navigatingAttemptId) return

    this._navigatingAttemptId = id
    wx.navigateTo({
      url: `/subpackages/exam/result/index?attempt_id=${id}`,
      complete: () => {
        setTimeout(() => {
          if (this._navigatingAttemptId === id) this._navigatingAttemptId = null
        }, 240)
      },
    })
  },

  retryLoad() {
    this.loadHistory({ reset: true })
  },

  goBack() {
    wx.navigateBack({ delta: 1 })
  },
})
