const api = require('../../utils/api')

// 将纯文本（可能含 $...$ LaTeX）转为 mp-html 可接受的 HTML 字符串。
// $...$ 内部保持原样，外部普通文本做 HTML 转义，换行转 <br>。
function _textToHtml(text) {
  if (!text) return ''
  const parts = text.split(/(\$\$[\s\S]*?\$\$|\$[^$\n]+?\$)/)
  const out = parts.map((part, i) => {
    if (i % 2 === 1) return part
    return part
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/\n/g, '<br>')
  })
  return '<p>' + out.join('') + '</p>'
}

Page({
  data: {
    wq: null,
    optionKeys: [],
    stemHtml: '',
    optHtml: {},
    aiResult: null,
    aiLoading: false,
    aiFallback: false,
    loading: true,
  },

  onLoad(options) {
    this.loadData(options.id)
  },

  async loadData(wqId) {
    this.setData({ loading: true })
    try {
      const wq = await api.get(`/wrong-questions/${wqId}`)
      if (!wq) throw new Error('not found')

      const optionKeys = wq.options ? Object.keys(wq.options) : []
      const stemHtml = _textToHtml((wq.content && wq.content.text) || '')
      const optHtml = {}
      for (const k of optionKeys) {
        optHtml[k] = _textToHtml(wq.options[k] || '')
      }
      this.setData({ wq, optionKeys, stemHtml, optHtml, loading: false })
      this.loadAiAnalysis(wqId)
    } catch (e) {
      console.error('加载错题详情失败', e)
      wx.showToast({ title: '加载失败', icon: 'none' })
      this.setData({ loading: false })
    }
  },

  async loadAiAnalysis(wqId) {
    this.setData({ aiLoading: true })
    try {
      const result = await api.post('/ai/error-analysis', { wrong_question_id: wqId })
      this.setData({
        aiResult: result.content,
        aiFallback: result.from_fallback,
        aiLoading: false,
      })
    } catch (e) {
      console.error('加载 AI 分析失败', e)
      this.setData({ aiLoading: false, aiFallback: true })
    }
  },

  async markMastered() {
    try {
      await api.put(`/wrong-questions/${this.data.wq.id}`, { mastered: true })
      wx.showToast({ title: '已标记掌握', icon: 'success' })
      this.setData({ 'wq.mastered': true })
    } catch (e) {
      console.error('标记掌握失败', e)
      wx.showToast({ title: '操作失败', icon: 'none' })
    }
  },

  subjectLabel(s) {
    var map = {
      math2: '数学二', 'math2-calculus': '数学二·高数', 'math2-linalg': '数学二·线代',
      exam408: '408', 'exam408-ds': '408·DS', 'exam408-os': '408·OS',
      'exam408-co': '408·CO', 'exam408-cn': '408·CN',
      english: '英语',
    }
    return map[s] || s
  },

  errorTypeLabel(t) {
    const map = { concept_mistake: '概念错误', calculation: '计算错误', careless: '粗心', method: '方法错误', other: '其他' }
    return map[t] || t
  },
})
