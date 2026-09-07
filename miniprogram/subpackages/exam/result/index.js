const api = require('../../../utils/api')
const stemRender = require('../../study/utils/stem-render')
const errorDiagnosis = require('../../../utils/error-diagnosis')

function percent(value) { return `${Math.round(Number(value || 0) * 100)}%` }
function durationText(sec) {
  sec = Math.max(0, Number(sec || 0))
  const min = Math.floor(sec / 60)
  const remain = sec % 60
  return `${min}分${remain ? `${remain}秒` : ''}`
}
function previewStem(q) {
  const content = q && q.content || {}
  let text = content.stem || content.text || ''
  if (!text && Array.isArray(content.segments)) text = stemRender.segmentsToText(content.segments)
  text = stemRender.toPlainInlineMathText(String(text || '')) || String(text || '').replace(/<[^>]+>/g, ' ')
  text = text.replace(/\s+/g, ' ').trim()
  return text.length > 86 ? `${text.slice(0, 86)}…` : (text || '题目内容')
}

Page({
  data: {
    loading: true,
    errorText: '',
    attemptId: 0,
    result: null,
    subjectRows: [],
    weakPoints: [],
    reviewRows: [],
  },

  onLoad(options) {
    const attemptId = Number(options && options.attempt_id)
    this.setData({ attemptId })
    if (!attemptId) this.setData({ loading: false, errorText: '缺少考试记录 ID' })
    else this.loadResult()
  },

  async loadResult() {
    this.setData({ loading: true, errorText: '' })
    try {
      const r = await api.get(`/exams/attempts/${this.data.attemptId}/result`)
      const subjectRows = (r.subject_breakdown || []).map((item) => ({
        ...item,
        scoreText: Number(item.score || 0).toFixed(1),
        totalText: Number(item.total_score || 0).toFixed(1),
        accuracyText: percent(item.accuracy),
      }))
      const weakPoints = (r.weak_knowledge_points || []).slice(0, 8).map((item) => ({
        name: item.name || item.knowledge_point || '未命名知识点',
        wrongCount: Number(item.miss_count || item.wrong_count || item.count || 0),
      }))
      const reviewRows = (r.questions || []).filter((q) => q.status !== 'correct').map((q) => ({
        ...q,
        stemPreview: previewStem(q),
        userAnswerText: q.selected_answer || '未作答',
        knowledgeText: (q.knowledge_points || []).slice(0, 3).join(' · '),
        analysisPreview: String(q.analysis || '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 120),
        errorDiagnosis: errorDiagnosis.normalizeDiagnosis(q.error_diagnosis),
        errorDiagnosisLabel: errorDiagnosis.labelOf(q.error_diagnosis && q.error_diagnosis.primary_type),
      }))
      this.setData({
        loading: false,
        result: {
          ...r,
          scoreText: Number(r.choice_score || 0).toFixed(1),
          totalScoreText: Number(r.total_choice_score || 0).toFixed(1),
          accuracyText: percent(r.accuracy),
          durationText: durationText(r.duration_sec),
        },
        subjectRows,
        weakPoints,
        reviewRows,
      })
    } catch (error) {
      this.setData({ loading: false, errorText: api.getErrorMessage(error) })
    }
  },

  quickClassifyWrong(e) {
    const wqId = Number(e.currentTarget.dataset.wqid || 0)
    if (!wqId) {
      wx.showToast({ title: '未答题不生成错题记录', icon: 'none' })
      return
    }
    const options = errorDiagnosis.QUICK_TYPES
    wx.showActionSheet({
      itemList: options.map(item => item.label),
      success: async (res) => {
        const picked = options[Number(res.tapIndex)]
        if (!picked) return
        try {
          const target = (this.data.reviewRows || []).find(item => Number(item.wrong_question_id) === wqId)
          const raw = await api.put(`/wrong-questions/${wqId}/diagnosis`, {
            diagnosis_id: target && target.errorDiagnosis ? Number(target.errorDiagnosis.id || 0) || undefined : undefined,
            primary_type: picked.type,
            secondary_types: [],
          })
          const normalized = errorDiagnosis.normalizeDiagnosis(raw)
          const reviewRows = (this.data.reviewRows || []).map(item => Number(item.wrong_question_id) === wqId
            ? Object.assign({}, item, { errorDiagnosis: normalized, errorDiagnosisLabel: picked.label })
            : item)
          this.setData({ reviewRows })
          wx.showToast({ title: '错因已记录', icon: 'success' })
        } catch (err) {
          wx.showToast({ title: api.getErrorMessage(err), icon: 'none' })
        }
      }
    })
  },

  openWrongDetail(e) {
    const wqId = Number(e.currentTarget.dataset.wqid || 0)
    if (!wqId) return
    wx.navigateTo({ url: `/subpackages/study/wrong-detail/wrong-detail?id=${wqId}&source=practice-result` })
  },

  goWrongBook() { wx.navigateTo({ url: '/subpackages/study/wrong-book/wrong-book' }) },
  goPaperList() { wx.redirectTo({ url: '/subpackages/exam/paper-list/index' }) },
  goHistory() { wx.navigateTo({ url: '/subpackages/exam/history/index' }) },
  goBack() { this.goPaperList() },
})
