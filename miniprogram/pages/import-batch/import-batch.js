const api = require('../../utils/api')

Page({
  data: {
    batch: null,
    questions: [],
    loading: false,
    loadError: false,
    expanding: null,
    subjectOpts: [
      { value: 'exam408', label: '408' },
      { value: 'exam408-ds', label: 'DS（数据结构）' },
      { value: 'exam408-os', label: 'OS（操作系统）' },
      { value: 'exam408-co', label: 'CO（计算机组成）' },
      { value: 'exam408-cn', label: 'CN（计算机网络）' },
      { value: 'math2', label: '数学二' },
      { value: 'math2-calculus', label: '高等数学' },
      { value: 'math2-linalg', label: '线性代数' },
      { value: 'english', label: '英语' },
    ],
    editing: {},
    // 批量选择
    selectMode: false,
    selectedIds: {},
    selectedCount: 0,
  },

  onLoad(options) {
    this.batchId = options.batchId
    this.loadBatch()
  },

  async loadBatch() {
    this.setData({ loading: true, loadError: false })
    try {
      const res = await api.get('/import/batches/' + this.batchId)
      var subjectMap = { math2: '数学二', exam408: '408', english: '英语',
        'math2-calculus': '高数', 'math2-linalg': '线代',
        'exam408-ds': 'DS', 'exam408-os': 'OS', 'exam408-co': 'CO', 'exam408-cn': 'CN' }
      var statusMap = { pending: '待审核', approved: '已通过', published: '已发布', rejected: '已拒绝' }
      var questions = (res.questions || []).map(function(q) {
        var meta = (q.ai_metadata && typeof q.ai_metadata === 'object') ? q.ai_metadata : {}
        var aiKps = Array.isArray(meta.knowledge_points) ? meta.knowledge_points : []
        var aiSuggestion = meta.complete_suggestion || null
        var pc = (q.parsed_content && typeof q.parsed_content === 'object') ? q.parsed_content : {}
        var segments = Array.isArray(pc.segments) ? pc.segments : []
        return Object.assign({}, q, {
          _preview: (pc.text || '').slice(0, 80) || '无内容',
          _subjectLabel: subjectMap[q.subject] || q.subject || '-',
          _statusLabel: statusMap[q.status] || q.status,
          _optionKeys: q.parsed_options ? Object.keys(q.parsed_options).sort() : [],
          _aiKps: aiKps,
          _aiSuggestion: aiSuggestion,
          _aiConfidencePct: q.ai_confidence != null ? Math.round(q.ai_confidence * 100) : null,
          _hasMath: segments.some(function(s) { return s.type === 'math_image' }),
          // 规范化 ai_metadata 供 WXML 安全访问（避免 null.chapter 崩溃）
          ai_metadata: meta,
          // 规范化 parsed_content 避免 WXML 访问 null
          parsed_content: pc,
        })
      })
      var editing = {}
      for (var i = 0; i < questions.length; i++) {
        var q = questions[i]
        editing[q.id] = { subject: q.subject || '', parsedAnswer: q.parsed_answer || '' }
      }
      this.setData({
        batch: { batch_id: res.batch_id, source_file: res.source_file, source_type: res.source_type },
        questions: questions,
        hasPending: questions.some(function(q) { return q.status === 'pending' }),
        editing: editing,
        selectMode: false,
        selectedIds: {},
        selectedCount: 0,
      })
    } catch (e) {
      console.error('loadBatch 失败', e)
      this.setData({ loadError: true })
    } finally {
      this.setData({ loading: false })
    }
  },

  // ── 批量选择 ──

  toggleSelectMode() {
    const next = !this.data.selectMode
    this.setData({
      selectMode: next,
      selectedIds: {},
      selectedCount: 0,
      expanding: null,
    })
  },

  onCardTap(e) {
    const id = e.currentTarget.dataset.id
    if (this.data.selectMode) {
      this.toggleSelect(id)
    } else {
      this.toggleExpand(e)
    }
  },

  toggleSelect(e) {
    // 兼容两种调用方式：事件对象（来自 WXML catchtap）和直接传 id（来自 onCardTap）
    const id = typeof e === 'object' ? e.currentTarget.dataset.id : e
    if (!id) return

    const selectedIds = { ...this.data.selectedIds }
    if (selectedIds[id]) {
      delete selectedIds[id]
    } else {
      const q = this.data.questions.find(item => item.id === id)
      if (q && q.status === 'pending') {
        selectedIds[id] = true
      } else {
        wx.showToast({ title: '仅可选择待审核题目', icon: 'none' })
        return
      }
    }
    const selectedCount = Object.keys(selectedIds).length
    this.setData({ selectedIds, selectedCount })
  },

  selectAllPending() {
    const selectedIds = {}
    const pending = this.data.questions.filter(q => q.status === 'pending')
    for (const q of pending) {
      selectedIds[q.id] = true
    }
    this.setData({ selectedIds, selectedCount: Object.keys(selectedIds).length })
  },

  // ── 批量拒绝 ──

  async batchReject() {
    const ids = Object.keys(this.data.selectedIds)
    if (ids.length === 0) {
      wx.showToast({ title: '请先选择题目', icon: 'none' })
      return
    }

    const { confirm } = await wx.showModal({
      title: '批量拒绝',
      content: `确定拒绝选中的 ${ids.length} 道题目吗？`,
      confirmText: '拒绝',
      confirmColor: '#C47A7A',
    })
    if (!confirm) return

    wx.showLoading({ title: '批量拒绝中...' })
    try {
      const res = await api.post(`/import/batches/${this.batchId}/reject`)
      wx.hideLoading()
      wx.showToast({ title: `已拒绝 ${res.rejected_count} 道`, icon: 'success' })
      this.setData({ selectMode: false, selectedIds: {}, selectedCount: 0 })
      this.loadBatch()
    } catch (e) {
      console.error('批量拒绝失败', e)
      wx.hideLoading()
      wx.showToast({ title: e.message || '操作失败', icon: 'none' })
    }
  },

  // ── 批量通过（选中） ──

  async batchApproveSelected() {
    const selectedIds = Object.keys(this.data.selectedIds)
    if (selectedIds.length === 0) {
      wx.showToast({ title: '请先选择题目', icon: 'none' })
      return
    }

    // 逐个通过选中的题目
    wx.showLoading({ title: '批量通过中...' })
    let success = 0
    let fail = 0
    for (const id of selectedIds) {
      const idNum = parseInt(id, 10)
      const edit = this.data.editing[idNum] || {}
      const q = this.data.questions.find(item => item.id === idNum)
      if (!q || q.status !== 'pending') { fail++; continue }
      if (!q.subject && !edit.subject) { fail++; continue }
      if (!q.parsed_answer && !edit.parsedAnswer) { fail++; continue }

      try {
        const body = { status: 'approved' }
        if (!q.subject && edit.subject) body.subject = edit.subject
        if (!q.parsed_answer && edit.parsedAnswer) body.parsed_answer = edit.parsedAnswer
        await api.put(`/import/questions/${idNum}`, body)
        success++
      } catch (err) {
        fail++
      }
    }
    wx.hideLoading()
    wx.showToast({ title: `通过 ${success} 道${fail > 0 ? '，失败 ' + fail + ' 道' : ''}`, icon: 'none' })
    this.setData({ selectMode: false, selectedIds: {}, selectedCount: 0 })
    this.loadBatch()
  },

  toggleExpand(e) {
    const id = e.currentTarget.dataset.id
    const expanding = this.data.expanding === id ? null : id
    this.setData({ expanding, _activeId: expanding ? id : null })
  },

  onSubjectChange(e) {
    const id = this.data._activeId
    if (!id) return
    const idx = e.detail.value
    const opt = this.data.subjectOpts[idx]
    const value = (opt && opt.value) || ''
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

  onAnswerSelect(e) {
    const id = e.currentTarget.dataset.id
    const value = e.currentTarget.dataset.value
    this.setData({
      [`editing.${id}.parsedAnswer`]: value,
    })
  },

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

    if (!q.subject && !edit.subject) {
      wx.showToast({ title: '请先选择科目', icon: 'none' })
      return
    }
    if (!q.parsed_answer && !edit.parsedAnswer) {
      wx.showToast({ title: '请先填写答案', icon: 'none' })
      return
    }

    wx.showLoading({ title: '通过中...' })
    try {
      const body = { status: 'approved' }
      if (!q.subject && edit.subject) body.subject = edit.subject
      if (!q.parsed_answer && edit.parsedAnswer) body.parsed_answer = edit.parsedAnswer

      const res = await api.put(`/import/questions/${id}`, body)
      wx.hideLoading()
      if (res && res.is_duplicate) {
        wx.showToast({ title: '已通过（与题库现有题重复）', icon: 'none' })
      } else {
        wx.showToast({ title: '已通过', icon: 'success' })
      }
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
      const skipped = res.skipped || []
      if (skipped.length > 0) {
        const lines = skipped.slice(0, 5).map(s => `#${s.id} 缺 ${(s.missing || []).join('、')}`)
        const more = skipped.length > 5 ? `\n…还有 ${skipped.length - 5} 道` : ''
        wx.showModal({
          title: `通过 ${res.approved_count} 道，${skipped.length} 道未通过`,
          content: `下列题目缺少必填字段，请逐题审核补充后再通过：\n${lines.join('\n')}${more}`,
          showCancel: false,
        })
      } else {
        wx.showToast({ title: `已通过 ${res.approved_count} 道`, icon: 'success' })
      }
      this.loadBatch()
    } catch (e) {
      console.error('操作失败', e)
      wx.hideLoading()
      wx.showToast({ title: e.message || e.errMsg || '批量操作失败', icon: 'none' })
    }
  },

  goBack() {
    wx.navigateBack()
  },

  async showMathPreview(e) {
    const id = e.currentTarget.dataset.id
    wx.showLoading({ title: '加载公式...' })
    try {
      const res = await api.get(`/import/math-preview/${id}`)
      wx.hideLoading()
      if (!res.has_math || res.formula_count === 0) {
        wx.showToast({ title: '暂无公式截图', icon: 'none' })
        return
      }
      // 找出所有 math_image segment 的 URL
      const mathSegs = (res.segments || []).filter(s => s.type === 'math_image')
      const urls = mathSegs.map(s => s.url).filter(Boolean)
      if (urls.length === 0) {
        wx.showToast({ title: '暂无可预览的公式', icon: 'none' })
        return
      }
      // 用微信图片预览 API 展示
      wx.previewImage({
        current: urls[0],
        urls,
      })
    } catch (err) {
      console.error('公式预览失败', err)
      wx.hideLoading()
      wx.showToast({ title: '预览失败', icon: 'none' })
    }
  },

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
    const map = { pending: '待审核', approved: '已通过', published: '已发布', rejected: '已拒绝' }
    return map[s] || s
  },
})
