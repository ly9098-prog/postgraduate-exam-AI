const api = require('../../utils/api')

const RISK_LABELS = {
  no_exercise_regions: '未检出习题区',
  book_pdf_prose_like: '疑似正文',
  low_confidence: '低置信',
  fallback_low_confidence: '兜底题目',
  non_question_like: '疑似非题目',
}

function textToHtml(text) {
  if (!text) return ''
  var parts = String(text).split(/(\$\$[\s\S]*?\$\$|\$[^$\n]+?\$)/)
  var out = parts.map(function(part, i) {
    if (i % 2 === 1) return part
    return part
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/\n/g, '<br>')
  })
  return '<p>' + out.join('') + '</p>'
}

function needsRichRender(text) {
  if (!text) return false
  return /(\$\$[\s\S]*?\$\$|\$[^$\n]+?\$)/.test(text) || /<\/?[a-z][\s\S]*>/i.test(text)
}

function replaceSimpleLatexCommands(text) {
  return String(text || '')
    .replace(/\\leq/g, '≤')
    .replace(/\\geq/g, '≥')
    .replace(/\\neq/g, '≠')
    .replace(/\\times/g, '×')
    .replace(/\\cdot/g, '·')
    .replace(/\\lt/g, '<')
    .replace(/\\gt/g, '>')
}

function toPlainInlineMathText(text) {
  if (!text) return ''
  var source = String(text)
  if (/\$\$[\s\S]*?\$\$/.test(source) || /<\/?[a-z][\s\S]*>/i.test(source)) return null
  var plain = source.replace(/\$([^$\n]+?)\$/g, function(_, expr) {
    return replaceSimpleLatexCommands(expr).trim()
  })
  if (/\\[a-zA-Z]+/.test(plain)) return null
  plain = plain.replace(/[ \t]+/g, ' ').replace(/\s+([，。！？；：,.!?;:])/g, '$1').trim()
  return plain
}

function enrichOptionText(opt) {
  var text = String((opt && opt.text) || '').trim()
  var plain = toPlainInlineMathText(text)
  return Object.assign({}, opt, {
    _text: plain || text,
    _needsRich: !plain && needsRichRender(text),
    _html: (!plain && needsRichRender(text)) ? textToHtml(text) : '',
  })
}

function normalizeBlankOptionList(options) {
  if (Array.isArray(options)) return options
  if (options && typeof options === 'object') {
    return Object.keys(options).map(function(key) {
      return { key: key, text: options[key] }
    })
  }
  return []
}

function normalizeResponseObject(value) {
  if (value && typeof value === 'object') return value
  if (typeof value === 'string') {
    try {
      var parsed = JSON.parse(value)
      return parsed && typeof parsed === 'object' ? parsed : {}
    } catch (e) {
      return {}
    }
  }
  return {}
}

function enrichBlankOptionGroups(groups) {
  return (groups || []).map(function(group) {
    return Object.assign({}, group, {
      options: normalizeBlankOptionList(group.options).map(enrichOptionText),
    })
  })
}

function summarizeBlankOptionGroups(groups) {
  return (groups || []).filter(function(g) { return g && typeof g === 'object' }).map(function(g, index) {
    var options = g.options || {}
    var optionKeys = []
    if (Array.isArray(options)) {
      optionKeys = options.map(function(o) { return o && o.key }).filter(Boolean)
    } else if (options && typeof options === 'object') {
      optionKeys = Object.keys(options)
    }
    return {
      id: g.id || g.blank_id || g.label || index + 1,
      optionKeys: optionKeys.map(function(k) { return String(k).toUpperCase() }).sort(),
    }
  })
}

function debugMultiBlankQuestions(questions, batchId) {
  if (typeof console === 'undefined') return
  ;(questions || []).forEach(function(q) {
    var groups = q._blankOptionGroups || []
    if (q.question_type !== 'multi_blank_choice' && groups.length === 0) return
    var pc = normalizeResponseObject(q.parsed_content)
    var raw = normalizeResponseObject(q.raw_data)
    console.info('[import-batch] multi_blank_choice loaded', {
      batchId: batchId,
      questionId: q.id,
      questionType: q.question_type,
      stemPreview: String(pc.text || '').slice(0, 80),
      blankOptionGroupCount: groups.length,
      blankOptionGroups: summarizeBlankOptionGroups(groups),
      parsedContentHasBlankOptionGroups: Array.isArray(pc.blank_option_groups),
      rawDataHasBlankOptionGroups: Array.isArray(raw.blank_option_groups),
    })
  })
}

Page({
  data: {
    batch: null,
    questions: [],
    loading: false,
    loadError: false,
    expanding: null,
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
      var typeMap = { choice: '选择题', single_choice: '单选题', multiple_choice: '多选题', fill: '填空题', fill_blank: '填空题', multi_blank_choice: '多空选择题', true_false: '判断题', subjective: '主观题' }
      var questions = (res.questions || []).map(function(q) {
        var meta = (q.ai_metadata && typeof q.ai_metadata === 'object') ? q.ai_metadata : {}
        var aiKps = Array.isArray(meta.knowledge_points) ? meta.knowledge_points : []
        var pc = normalizeResponseObject(q.parsed_content)
        var rawData = normalizeResponseObject(q.raw_data)
        var blankOptionGroups = Array.isArray(pc.blank_option_groups) ? pc.blank_option_groups : (Array.isArray(rawData.blank_option_groups) ? rawData.blank_option_groups : [])
        var segments = Array.isArray(pc.segments) ? pc.segments : []
        var riskFlags = Array.isArray(meta.risk_flags) ? meta.risk_flags : []
        var riskLabels = riskFlags.map(function(flag) { return RISK_LABELS[flag] || flag })
        return Object.assign({}, q, {
          _preview: (pc.text || '').slice(0, 80) || '无内容',
          _subjectLabel: subjectMap[q.subject] || q.subject || '-',
          _statusLabel: statusMap[q.status] || q.status,
          _typeLabel: typeMap[q.question_type] || (blankOptionGroups.length ? '多空选择题' : q.question_type || '-'),
          _blankOptionGroups: enrichBlankOptionGroups(blankOptionGroups),
          _hasBlankOptionGroups: blankOptionGroups.length > 0,
          _aiKps: aiKps,
          _aiConfidencePct: q.ai_confidence != null ? Math.round(q.ai_confidence * 100) : null,
          _hasMath: segments.some(function(s) { return s.type === 'math_image' }),
          _riskFlags: riskLabels,
          ai_metadata: meta,
          parsed_content: pc,
        })
      })
      this.setData({
        batch: { batch_id: res.batch_id, source_file: res.source_file, source_type: res.source_type },
        questions: questions,
      })
      debugMultiBlankQuestions(questions, this.batchId)
    } catch (e) {
      console.error('loadBatch 失败', e)
      this.setData({ loadError: true })
    } finally {
      this.setData({ loading: false })
      wx.stopPullDownRefresh()
    }
  },

  onCardTap(e) {
    this.toggleExpand(e)
  },

  toggleExpand(e) {
    const id = e.currentTarget.dataset.id
    const expanding = this.data.expanding === id ? null : id
    this.setData({ expanding })
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
      const mathSegs = (res.segments || []).filter(s => s.type === 'math_image')
      const urls = mathSegs.map(s => s.url).filter(Boolean)
      if (urls.length === 0) {
        wx.showToast({ title: '暂无可预览的公式', icon: 'none' })
        return
      }
      wx.previewImage({ current: urls[0], urls })
    } catch (err) {
      console.error('公式预览失败', err)
      wx.hideLoading()
      wx.showToast({ title: '预览失败', icon: 'none' })
    }
  },

  onPullDownRefresh() {
    this.loadBatch()
  },
})
