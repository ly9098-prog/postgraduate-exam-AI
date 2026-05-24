const api = require('../../utils/api')

Page({
  data: {
    batch: null,
    questions: [],
    loading: false,
    expanding: null,
    subjectOpts: [
      { value: 'exam408', label: '408' },
      { value: 'math2', label: '数学二' },
      { value: 'english', label: '英语' },
    ],
    // 编辑态：{ [questionId]: { subject, parsedAnswer } }
    editing: {},
  },

  onLoad(options) {
    this.batchId = options.batchId
    this.loadBatch()
  },

  async loadBatch() {
    this.setData({ loading: true })
    try {
      const res = await api.get(`/import/batches/${this.batchId}`)
      const subjectMap = { math2: '数学二', exam408: '408', english: '英语' }
      const statusMap = { pending: '待审核', approved: '已通过', rejected: '已拒绝' }
      const questions = (res.questions || []).map(q => {
        const meta = q.ai_metadata || {}
        const aiKps = Array.isArray(meta.knowledge_points) ? meta.knowledge_points : []
        const aiSuggestion = meta.complete_suggestion || null
        return {
          ...q,
          _preview: (q.parsed_content?.text || '').slice(0, 80) || '无内容',
          _subjectLabel: subjectMap[q.subject] || q.subject || '-',
          _statusLabel: statusMap[q.status] || q.status,
          _optionKeys: q.parsed_options ? Object.keys(q.parsed_options).sort() : [],
          _aiKps: aiKps,
          _aiSuggestion: aiSuggestion,
          _aiConfidencePct: q.ai_confidence != null ? Math.round(q.ai_confidence * 100) : null,
        }
      })
      const editing = {}
      for (const q of questions) {
        editing[q.id] = { subject: q.subject || '', parsedAnswer: q.parsed_answer || '' }
      }
      this.setData({
        batch: { batch_id: res.batch_id, source_file: res.source_file, source_type: res.source_type },
        questions,
        hasPending: questions.some(q => q.status === 'pending'),
        editing,
      })
    } catch (e) {
      console.error('操作失败', e)
      wx.showToast({ title: '加载失败', icon: 'none' })
    } finally {
      this.setData({ loading: false })
    }
  },

  toggleExpand(e) {
    const id = e.currentTarget.dataset.id
    const expanding = this.data.expanding === id ? null : id
    this.setData({ expanding, _activeId: expanding ? id : null })
  },

  // 科目选择
  onSubjectChange(e) {
    const id = this.data._activeId
    if (!id) return
    const idx = e.detail.value
    const value = this.data.subjectOpts[idx]?.value || ''
    if (!value) return

    const questions = [...this.data.questions]
    const q = questions.find(item => item.id === id)
    if (q) {
      q.subject = value
      q._subjectLabel = this.subjectLabel(value)
    }

    this.setData({
      questions,
      [`editing.${id}.subject`]: value,
    })
  },

  // 答案快捷选择
  onAnswerSelect(e) {
    const id = e.currentTarget.dataset.id
    const value = e.currentTarget.dataset.value
    this.setData({
      [`editing.${id}.parsedAnswer`]: value,
    })
  },

  // 答案输入
  onAnswerInput(e) {
    const id = e.currentTarget.dataset.id
    const value = e.detail.value
    this.setData({
      [`editing.${id}.parsedAnswer`]: value,
    })
  },

  async approve(e) {
    const id = e.currentTarget.dataset.id
    const edit = this.data.editing[id] || {}
    const q = this.data.questions.find(item => item.id === id)

    // 缺少科目时检查
    if (!q.subject && !edit.subject) {
      wx.showToast({ title: '请先选择科目', icon: 'none' })
      return
    }
    // 缺少答案时检查
    if (!q.parsed_answer && !edit.parsedAnswer) {
      wx.showToast({ title: '请先填写答案', icon: 'none' })
      return
    }

    wx.showLoading({ title: '通过中...' })
    try {
      const body = { status: 'approved' }
      if (!q.subject && edit.subject) body.subject = edit.subject
      if (!q.parsed_answer && edit.parsedAnswer) body.parsed_answer = edit.parsedAnswer

      await api.put(`/import/questions/${id}`, body)
      wx.hideLoading()
      wx.showToast({ title: '已通过', icon: 'success' })
      this.loadBatch()
    } catch (e) {
      console.error('操作失败', e)
      wx.hideLoading()
      wx.showToast({ title: '操作失败', icon: 'none' })
    }
  },

  async reject(e) {
    const id = e.currentTarget.dataset.id
    const { confirm } = await wx.showModal({ title: '拒绝原因', content: '确定拒绝该题目？', confirmText: '拒绝', confirmColor: '#C47A7A' })
    if (!confirm) return
    wx.showLoading({ title: '处理中...' })
    try {
      await api.put(`/import/questions/${id}`, { status: 'rejected', review_note: '' })
      wx.hideLoading()
      wx.showToast({ title: '已拒绝', icon: 'none' })
      this.loadBatch()
    } catch (e) {
      console.error('操作失败', e)
      wx.hideLoading()
      wx.showToast({ title: '操作失败', icon: 'none' })
    }
  },

  async batchApprove() {
    const pending = this.data.questions.filter(q => q.status === 'pending')
    if (pending.length === 0) {
      wx.showToast({ title: '没有待审核的题目', icon: 'none' })
      return
    }

    // 检查哪些题目缺少字段
    const willFail = pending.filter(q => !q.subject || !q.parsed_answer)
    if (willFail.length > 0) {
      const hints = willFail.map(q => {
        const fields = []
        if (!q.subject) fields.push('科目')
        if (!q.parsed_answer) fields.push('答案')
        return `#${q.id} 缺 ${fields.join('、')}`
      })
      wx.showModal({
        title: '无法批量通过',
        content: `${willFail.length} 道题缺少必填字段，请逐题审核补充：\n${hints.join('\n')}`,
        showCancel: false,
      })
      return
    }

    const { confirm } = await wx.showModal({
      title: '批量通过',
      content: `确定通过全部 ${pending.length} 道待审核题目？`,
      confirmText: '全部通过',
    })
    if (!confirm) return

    wx.showLoading({ title: '批量处理中...' })
    try {
      const res = await api.post(`/import/batches/${this.batchId}/approve`)
      wx.hideLoading()
      wx.showToast({ title: `已通过 ${res.approved_count} 道`, icon: 'success' })
      this.loadBatch()
    } catch (e) {
      console.error('操作失败', e)
      wx.hideLoading()
      wx.showToast({ title: e.errMsg || '批量操作失败', icon: 'none' })
    }
  },

  goBack() {
    wx.navigateBack()
  },

  // ── 阶段七：AI 辅助导题 ──
  async aiEnrichOne(e) {
    const id = e.currentTarget.dataset.id
    wx.showLoading({ title: 'AI 补全中...' })
    try {
      const res = await api.post(`/ai-import/enrich/${id}`)
      wx.hideLoading()
      if (res.from_fallback) {
        wx.showToast({ title: 'AI 暂不可用', icon: 'none' })
      } else {
        wx.showToast({ title: 'AI 已补全', icon: 'success' })
      }
      this.loadBatch()
    } catch (err) {
      console.error('AI enrich 失败', err)
      wx.hideLoading()
      wx.showToast({ title: 'AI 操作失败', icon: 'none' })
    }
  },

  async aiCompleteOne(e) {
    const id = e.currentTarget.dataset.id
    wx.showLoading({ title: 'AI 补全中...' })
    try {
      const res = await api.post(`/ai-import/complete/${id}`)
      wx.hideLoading()
      if (res.from_fallback) {
        wx.showToast({ title: 'AI 暂不可用', icon: 'none' })
      } else if ((res.missing || []).length === 0) {
        wx.showToast({ title: '无缺失字段', icon: 'none' })
      } else {
        wx.showToast({ title: 'AI 已给出建议', icon: 'success' })
      }
      this.loadBatch()
    } catch (err) {
      console.error('AI complete 失败', err)
      wx.hideLoading()
      wx.showToast({ title: 'AI 操作失败', icon: 'none' })
    }
  },

  async aiEnrichBatch() {
    const pending = this.data.questions.filter(q => q.status === 'pending')
    if (pending.length === 0) {
      wx.showToast({ title: '没有待审核的题目', icon: 'none' })
      return
    }
    const { confirm } = await wx.showModal({
      title: 'AI 批量补全',
      content: `调用 AI 为 ${pending.length} 道题补全学科/知识点/难度等字段。\n结果仍需人工审核。`,
      confirmText: '开始',
    })
    if (!confirm) return

    wx.showLoading({ title: 'AI 处理中...' })
    try {
      const res = await api.post(`/ai-import/enrich-batch/${this.batchId}`)
      wx.hideLoading()
      wx.showToast({
        title: `AI 完成 ${res.succeeded}/${res.processed}`,
        icon: 'none',
      })
      this.loadBatch()
    } catch (err) {
      console.error('AI batch 失败', err)
      wx.hideLoading()
      wx.showToast({ title: 'AI 批量失败', icon: 'none' })
    }
  },

  async applyAiSuggestion(e) {
    const id = e.currentTarget.dataset.id
    const q = this.data.questions.find(item => item.id === id)
    if (!q || !q._aiSuggestion) return

    const sg = q._aiSuggestion
    const previewLines = []
    if (sg.subject) previewLines.push(`科目：${this.subjectLabel(sg.subject)}`)
    if (sg.question_type) previewLines.push(`题型：${sg.question_type}`)
    if (sg.answer) previewLines.push(`答案：${sg.answer}（AI 建议）`)
    if (sg.analysis) previewLines.push(`解析：${sg.analysis.slice(0, 40)}...`)

    const { confirm } = await wx.showModal({
      title: '采纳 AI 建议',
      content: `将以下字段填入暂存表（仍需人工通过）：\n${previewLines.join('\n')}`,
      confirmText: '采纳',
    })
    if (!confirm) return

    const editingPatch = {}
    if (sg.subject) editingPatch[`editing.${id}.subject`] = sg.subject
    if (sg.answer) editingPatch[`editing.${id}.parsedAnswer`] = sg.answer

    if (Object.keys(editingPatch).length > 0) {
      this.setData(editingPatch)
      wx.showToast({ title: '已填入暂存', icon: 'success' })
    } else {
      wx.showToast({ title: '无可采纳字段', icon: 'none' })
    }
  },

  subjectLabel(s) {
    const map = { math2: '数学二', exam408: '408', english: '英语' }
    return map[s] || s || '-'
  },

  statusLabel(s) {
    const map = { pending: '待审核', approved: '已通过', rejected: '已拒绝' }
    return map[s] || s
  },
})
