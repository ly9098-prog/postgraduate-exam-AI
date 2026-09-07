const api = require('../../../utils/api')

function fmtTime(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  const pad = (n) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

Page({
  data: { loading: true, errorText: '', rows: [] },
  onLoad() { this.loadHistory() },
  onShow() { if (this._loadedOnce) this.loadHistory({ silent: true }) },
  async loadHistory(options = {}) {
    if (!options.silent) this.setData({ loading: true, errorText: '' })
    try {
      const data = await api.get('/exams/history', { limit: 100 })
      this._loadedOnce = true
      this.setData({
        loading: false,
        errorText: '',
        rows: (Array.isArray(data) ? data : []).map((item) => ({
          ...item,
          startedText: fmtTime(item.started_at),
          scoreText: Number(item.choice_score || 0).toFixed(1),
          totalScoreText: Number(item.total_choice_score || 0).toFixed(1),
          accuracyText: `${Math.round(Number(item.accuracy || 0) * 100)}%`,
          durationText: `${Math.max(1, Math.round(Number(item.duration_sec || 0) / 60))} 分钟`,
        })),
      })
    } catch (error) {
      this.setData({ loading: false, errorText: api.getErrorMessage(error) })
    }
  },
  openResult(e) {
    const id = Number(e.currentTarget.dataset.id)
    if (!id) return
    wx.navigateTo({ url: `/subpackages/exam/result/index?attempt_id=${id}` })
  },
  goBack() { wx.navigateBack({ delta: 1 }) },
})
