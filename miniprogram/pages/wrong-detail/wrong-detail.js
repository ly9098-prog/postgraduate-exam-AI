const api = require('../../utils/api')
const config = require('../../config')
const { formatInlineMathText } = require('../../utils/math-format')

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

function _needsRichRender(text) {
  if (!text) return false
  return /(\$\$[\s\S]*?\$\$|\$[^$\n]+?\$)/.test(text) || /<\/?[a-z][\s\S]*>/i.test(text)
}

function _deduplicateLines(text) {
  if (!text) return text
  const lines = text.split('\n')
  const seen = new Set()
  const out = []
  for (let i = 0; i < lines.length; i++) {
    const trimmed = lines[i].trim()
    if (trimmed && seen.has(trimmed)) continue
    if (trimmed) seen.add(trimmed)
    out.push(lines[i])
  }
  return out.join('\n')
}

function _escapeRegExp(text) {
  return String(text || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function _normalizeOptionText(text) {
  return String(text || '')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/gi, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function _buildOptionPattern(key, value) {
  const label = _escapeRegExp(String(key || '').trim())
  const normalizedValue = _normalizeOptionText(value)
  if (!label || !normalizedValue) return ''

  const spaces = '[\\s\\u00A0]*'
  const separator = '[.．、:：）)]'
  const valuePattern = _escapeRegExp(normalizedValue).replace(/\s+/g, '[\\s\\u00A0]+')
  return `${label}${spaces}${separator}${spaces}${valuePattern}`
}

function _stripLeadingOptionLabel(key, value) {
  const text = String(value || '').trim()
  if (!key || !text) return text
  const label = _escapeRegExp(String(key).trim())
  const labelPattern = new RegExp(`^${label}[\\s\\u00A0]*[.．、:：）)]\\s*`, 'i')
  if (/^\s*\$/.test(text)) {
    const inner = text.replace(/^\s*\$\s*/, '')
    return '$' + inner.replace(labelPattern, '')
  }
  return text.replace(labelPattern, '')
}

function _stripEmbeddedOptionBlock(stemText, options) {
  if (!stemText || !options) return stemText
  const patterns = Object.keys(options)
    .sort()
    .map((key) => _buildOptionPattern(key, options[key]))
    .filter(Boolean)

  if (patterns.length < 2) return stemText

  const gap = '(?:\\s|<br>|\\n|\\r|&nbsp;)*'
  const blockRegex = new RegExp(`${gap}${patterns.join(gap)}\\s*$`, 'i')
  return blockRegex.test(stemText) ? stemText.replace(blockRegex, '').trim() : stemText
}

function _findOptionLabelMatches(text, optionKeys) {
  if (!text || !optionKeys || optionKeys.length < 2) return []
  const labels = optionKeys.map(_escapeRegExp).join('|')
  const labelMarker = `(?:^|[\\s\\n\\r])(?:${labels})[\\s\\u00A0]*[.．、:：）)]`
  const labelRegex = new RegExp(labelMarker, 'g')
  const matches = []
  let match
  while ((match = labelRegex.exec(text)) !== null) {
    const index = match.index + (match[0].match(/^[\s\n\r]/) ? 1 : 0)
    matches.push(index)
  }
  return matches
}

function _hasTrailingOptionBlock(text, optionKeys) {
  if (!text || !optionKeys || optionKeys.length < 2) return false
  const keys = optionKeys.map(key => String(key || '').trim()).filter(Boolean)
  if (keys.length < 2) return false

  const spaces = '[\\s\\u00A0]*'
  const separator = '[.．、:：）)]'
  const marker = (key, prefix) => `${prefix}${_escapeRegExp(key)}${spaces}${separator}`
  const first = marker(keys[0], '^' + spaces)
  const second = marker(keys[1], '[\\s\\n\\r]+')
  const required = new RegExp(first + '[\\s\\S]+?' + second, 'i')
  if (!required.test(text)) return false

  const labels = keys.map(_escapeRegExp).join('|')
  const labelRegex = new RegExp(`(?:^|[\\s\\n\\r])(?:${labels})${spaces}${separator}`, 'g')
  const found = []
  let match
  while ((match = labelRegex.exec(text)) !== null) {
    found.push(String(match[0]).replace(/^[\\s\\n\\r]+/, '').charAt(0).toUpperCase())
  }
  if (found.length < 2) return false
  return found[0] === keys[0].toUpperCase() && found[1] === keys[1].toUpperCase()
}

function _stripTrailingOptionBlockByLabels(stemText, optionKeys) {
  if (!stemText || !optionKeys || optionKeys.length < 2) return stemText
  const matches = _findOptionLabelMatches(stemText, optionKeys)

  if (matches.length < 2) return stemText

  for (const index of matches) {
    const suffix = stemText.slice(index)
    if (_hasTrailingOptionBlock(suffix, optionKeys)) return stemText.slice(0, index).trim()
  }

  return stemText
}

function _removeTrailingOptionKeys(text, optionKeys) {
  if (!text || !optionKeys || optionKeys.length === 0) return text
  const keys = optionKeys.map(_escapeRegExp).join('')
  const pattern = new RegExp('\\s+[' + keys + ']\\s*$', 'g')
  return text.replace(pattern, '')
}

function _segmentsToText(segments) {
  if (!Array.isArray(segments)) return ''
  return segments.map((seg) => {
    if (!seg) return ''
    if (seg.type === 'text' || seg.type === 'newline') return seg.text || ''
    return seg.alt ? `$${seg.alt}$` : ''
  }).join('')
}

function _textToSegments(text) {
  if (!text) return []
  const lines = String(text).split('\n')
  const segments = []
  lines.forEach((line, index) => {
    if (line) segments.push({ type: 'text', text: line })
    if (index < lines.length - 1) segments.push({ type: 'newline' })
  })
  return segments
}

function _cleanStemText(stemText, options, optionKeys) {
  const dedupedStem = _deduplicateLines(stemText)
  const withoutExactOptions = _stripEmbeddedOptionBlock(dedupedStem, options)
  const withoutLabelOptions = _stripTrailingOptionBlockByLabels(withoutExactOptions, optionKeys)
  return _removeTrailingOptionKeys(withoutLabelOptions, optionKeys)
}

function _toPlainInlineMathText(text) {
  if (!text) return text
  const plain = formatInlineMathText(text)
  return plain === String(text) ? null : plain
}

function _plainOptionText(key, value) {
  const stripped = _stripLeadingOptionLabel(key, value)
  const plain = _toPlainInlineMathText(stripped)
  return plain !== null ? plain : stripped
}

function _normalizeBlankAnswer(answer) {
  if (!answer) return {}
  if (typeof answer === 'object') return answer
  const result = {}
  String(answer).split(/[;；,，\n]+/).forEach((part) => {
    const match = part.trim().match(/^(.+?)\s*[:：=]\s*([A-Za-z])$/)
    if (match) result[match[1].trim()] = match[2].trim().toUpperCase()
  })
  return result
}

function _normalizeBlankOptionList(options) {
  if (Array.isArray(options)) return options
  if (options && typeof options === 'object') {
    return Object.keys(options).map((key) => ({ key, text: options[key] }))
  }
  return []
}

function _optionTextToHtml(text) {
  return _textToHtml(text)
}

function _subjectLabel(s) {
  var map = {
    math2: '数学二', 'math2-calculus': '数学二·高数', 'math2-linalg': '数学二·线代',
    exam408: '408', 'exam408-ds': '408·DS', 'exam408-os': '408·OS',
    'exam408-co': '408·CO', 'exam408-cn': '408·CN',
    english: '英语',
  }
  return map[s] || s
}

function _errorTypeLabel(t) {
  const map = { concept_mistake: '概念错误', calculation: '计算错误', careless: '粗心', method: '方法错误', other: '其他' }
  return map[t] || t
}

function _processWqData(wq) {
  const opts = wq.options || null
  const optionKeys = opts ? Object.keys(opts) : []
  const sourceStemText = (wq.content && (wq.content.text || wq.content.stem)) || (wq.content && _segmentsToText(wq.content.segments)) || ''
  const stemText = _cleanStemText(sourceStemText, opts, optionKeys)
  const plainStem = _toPlainInlineMathText(stemText)
  const stemNeedsRich = !plainStem && _needsRichRender(stemText)
  const stemHtml = stemNeedsRich ? _textToHtml(stemText) : ''
  const stemSegments = (wq.content && wq.content.render_mode === 'segments') ? _textToSegments(stemText) : []
  const blankOptionGroups = _enrichBlankOptionGroups(wq.content && wq.content.blank_option_groups, wq.answer, wq.wrong_answer)
  const optionItems = optionKeys.map((key) => {
    const rawText = (opts && opts[key]) || ''
    const text = _deduplicateLines(_plainOptionText(key, rawText))
    const needsRich = _needsRichRender(text)
    const isCorrect = key === wq.answer
    const isUserAnswer = key === wq.wrong_answer
    let lineClass = ''
    let valueClass = 'option-value'
    if (isCorrect) {
      lineClass = 'correct'
      valueClass += ' right'
    } else if (isUserAnswer) {
      lineClass = 'user-answer'
      valueClass += ' wrong'
    }
    return {
      key,
      text,
      html: needsRich ? _optionTextToHtml(text) : '',
      needsRich,
      className: valueClass,
      lineClass,
    }
  })
  return {
    wq,
    optionKeys,
    optionItems,
    blankOptionGroups,
    stemText,
    stemNeedsRich,
    stemHtml,
    stemSegments,
    subjectLabelText: _subjectLabel(wq.subject),
    errorTypeLabelText: _errorTypeLabel(wq.error_type),
  }
}

function _enrichBlankOptionGroups(groups, answer, wrongAnswer) {
  const blankAnswers = _normalizeBlankAnswer(answer)
  const wrongAnswers = _normalizeBlankAnswer(wrongAnswer)
  return (groups || []).map((group) => {
    const groupId = String((group && group.id) || '').trim()
    const options = _normalizeBlankOptionList(group && group.options).map((opt) => {
      const key = String((opt && opt.key) || '').trim().toUpperCase()
      const text = String((opt && opt.text) || '').trim()
      const optionText = _stripLeadingOptionLabel(key, text)
      const plain = _toPlainInlineMathText(optionText)
      const needsRich = !plain && _needsRichRender(optionText)
      const isCorrect = blankAnswers[groupId] === key
      return Object.assign({}, opt, {
        key,
        _text: plain || optionText,
        _isCorrect: isCorrect,
        _isUserAnswer: !isCorrect && wrongAnswers[groupId] === key,
        _needsRich: needsRich,
        _html: needsRich ? _optionTextToHtml(optionText) : '',
      })
    }).filter((opt) => opt.key)
    return { id: groupId, options }
  }).filter((group) => group.id && group.options.length > 0)
}

Page({
  data: {
    wq: null,
    optionKeys: [],
    stemHtml: '',
    optionItems: [],
    stemText: '',
    stemNeedsRich: false,
    stemSegments: [],
    enableMathImage: false,
    aiResult: null,
    aiLoading: false,
    aiFallback: false,
    loading: true,
    questionIds: [],
    currentIdx: 0,
    totalQuestions: 0,
    swiperEnabled: false,
    contentState: '',
    showSwipeHint: false,
  },

  onLoad(options) {
    const { id, ids } = options
    const questionIds = ids ? ids.split(',').map(Number).filter(Boolean) : []
    const currentId = Number(id)
    const currentIdx = questionIds.indexOf(currentId)
    const swiperEnabled = questionIds.length > 1
    this.setData({
      enableMathImage: config.enableMathImage || false,
      questionIds,
      currentIdx: currentIdx >= 0 ? currentIdx : 0,
      totalQuestions: questionIds.length,
      swiperEnabled,
      showSwipeHint: swiperEnabled,
    })
    if (swiperEnabled) {
      setTimeout(() => { this.setData({ showSwipeHint: false }) }, 3000)
    }
    this.loadData(currentId)
  },

  async loadData(wqId) {
    this.setData({ loading: true })
    try {
      const wq = await api.get(`/wrong-questions/${wqId}`)
      if (!wq) throw new Error('not found')
      const data = _processWqData(wq)
      data.aiResult = null
      data.aiFallback = false
      this.setData(data)
      this.setData({ loading: false })
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
      const content = result.content
      if (content) {
        if (content.error_analysis) {
          content.error_analysis = content.error_analysis.replace(/^切入点[：:]\s*/, '')
        }
        if (content.knowledge_weakness) {
          content.knowledge_weakness = content.knowledge_weakness.replace(/^核心考点[：:]\s*/, '')
        }
      }
      this.setData({
        aiResult: content,
        aiFallback: result.from_fallback,
        aiLoading: false,
      })
    } catch (e) {
      console.error('加载 AI 分析失败', e)
      this.setData({ aiLoading: false, aiFallback: true })
    }
  },

  // ---- 左滑/右滑切换 ----
  onTouchStart(e) {
    if (this._animating || !this.data.swiperEnabled) return
    const t = e.touches[0]
    this._touchX = t.clientX
    this._touchY = t.clientY
    this._touchTime = Date.now()
    this._swiped = false
  },

  onTouchEnd(e) {
    if (this._animating || !this.data.swiperEnabled) return
    if (this._touchX === undefined) return

    const t = e.changedTouches[0]
    const dx = t.clientX - this._touchX
    const dy = t.clientY - this._touchY
    const dt = Date.now() - this._touchTime

    if (Math.abs(dy) > Math.abs(dx) * 1.5) {
      this._touchX = undefined
      return
    }

    if (Math.abs(dx) < 60) {
      this._touchX = undefined
      return
    }

    this._swiped = true
    this._touchX = undefined

    const isLeft = dx < 0
    const currentIdx = this.data.currentIdx
    const total = this.data.totalQuestions
    const canGo = isLeft ? currentIdx < total - 1 : currentIdx > 0

    if (!canGo) {
      this._animating = true
      this.setData({ contentState: isLeft ? 'edge-left' : 'edge-right' })
      setTimeout(() => {
        this.setData({ contentState: '' })
        this._animating = false
      }, 250)
      return
    }

    const animMs = Math.min(Math.max(dt * 0.5, 120), 200)
    this._animating = true
    this._swipeDir = isLeft ? 'left' : 'right'
    this.setData({ contentState: isLeft ? 'slide-out-left' : 'slide-out-right' })

    const nextIdx = currentIdx + (isLeft ? 1 : -1)
    setTimeout(() => {
      this._navigateTo(nextIdx, animMs)
    }, animMs)
  },

  async _navigateTo(idx, animMs) {
    const wqId = this.data.questionIds[idx]
    try {
      const wq = await api.get(`/wrong-questions/${wqId}`)
      if (!wq) throw new Error('not found')
      const data = _processWqData(wq)
      data.currentIdx = idx
      data.aiResult = null
      data.aiFallback = false

      // 先瞬间定位到滑入起始位置（transition: none）
      const fromState = this._swipeDir === 'left' ? 'from-right' : 'from-left'
      this.setData(Object.assign({ contentState: fromState }, data))

      // 下一帧启用过渡，滑入目标位置
      setTimeout(() => {
        this.setData({ contentState: '' })
        setTimeout(() => { this._animating = false }, animMs)
      }, 50)

      this.loadAiAnalysis(wqId)
    } catch (e) {
      console.error('切换题目失败', e)
      wx.showToast({ title: '加载失败', icon: 'none' })
      this.setData({ contentState: '' })
      this._animating = false
    }
  },
})
