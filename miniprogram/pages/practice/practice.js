const api = require('../../utils/api')
const config = require('../../config')
const { createTraceId, debugLog, saveDebugSnapshot, shouldDebugQuestion } = require('../../utils/debug')

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

function _deduplicateLines(text) {
  if (!text) return text
  const lines = text.split('\n')
  const out = []
  for (let i = 0; i < lines.length; i++) {
    if (i === 0 || lines[i].trim() !== lines[i - 1].trim()) {
      out.push(lines[i])
    }
  }
  return out.join('\n')
}

function _needsRichRender(text) {
  if (!text) return false
  return /(\$\$[\s\S]*?\$\$|\$[^$\n]+?\$)/.test(text) || /<\/?[a-z][\s\S]*>/i.test(text)
}

function _escapeRegExp(text) {
  return String(text || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function _replaceSimpleLatexCommands(text) {
  return String(text || '')
    .replace(/\\leq/g, '≤')
    .replace(/\\geq/g, '≥')
    .replace(/\\neq/g, '≠')
    .replace(/\\times/g, '×')
    .replace(/\\cdot/g, '·')
    .replace(/\\lt/g, '<')
    .replace(/\\gt/g, '>')
}

function _toPlainInlineMathText(text) {
  if (!text) return ''
  const source = String(text)
  if (/\$\$[\s\S]*?\$\$/.test(source) || /<\/?[a-z][\s\S]*>/i.test(source)) return null
  let plain = source.replace(/\$([^$\n]+?)\$/g, function(_, expr) {
    return _replaceSimpleLatexCommands(expr).trim()
  })
  if (/\\[a-zA-Z]+/.test(plain)) return null
  plain = plain.replace(/[ \t]+/g, ' ').replace(/\s+([，。！？；：,.!?;:])/g, '$1').trim()
  return plain
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

function _containsTrailingOptionBlock(text, optionKeys) {
  const matches = _findOptionLabelMatches(text, optionKeys)
  if (matches.length < 2) return false
  return matches.some(index => _hasTrailingOptionBlock(String(text || '').slice(index), optionKeys))
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
    found.push(String(match[0]).replace(/^[\s\n\r]+/, '').charAt(0).toUpperCase())
  }
  if (found.length < 2) return false
  return found[0] === keys[0].toUpperCase() && found[1] === keys[1].toUpperCase()
}

function _shortText(text) {
  const normalized = String(text || '').replace(/\s+/g, ' ').trim()
  return normalized.length > 80 ? normalized.slice(0, 80) + '...' : normalized
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

function _removeTrailingOptionKeys(text, optionKeys) {
  if (!text || !optionKeys || optionKeys.length === 0) return text
  const keys = optionKeys.map(_escapeRegExp).join('')
  const pattern = new RegExp('\\s+[' + keys + ']\\s*$', 'g')
  return text.replace(pattern, '')
}

function _optionTextToHtml(key, value) {
  const text = String(value || '').trim()
  if (!key) return _textToHtml(text)
  const keyPattern = new RegExp(`^${_escapeRegExp(String(key))}[\\s\\u00A0]*[.．、:：）)]?\\s*`, 'i')
  const normalized = keyPattern.test(text) ? text : `${key}. ${text}`
  return _textToHtml(normalized)
}

function _normalizeBlankAnswer(answer) {
  if (!answer) return {}
  if (typeof answer === 'object') return answer
  const result = {}
  String(answer).split(/[;；,，\n]+/).forEach(function(part) {
    const m = part.trim().match(/^(.+?)\s*[:：=]\s*([A-Za-z])$/)
    if (m) result[m[1].trim()] = m[2].trim().toUpperCase()
  })
  return result
}

function _normalizeBlankOptionList(options) {
  if (Array.isArray(options)) return options
  if (options && typeof options === 'object') {
    return Object.keys(options).map(function(key) {
      return { key, text: options[key] }
    })
  }
  return []
}

function _enrichBlankOptionGroups(groups, answer) {
  const blankAnswers = _normalizeBlankAnswer(answer)
  return (groups || []).map(function(group) {
    const groupId = String((group && group.id) || '').trim()
    return {
      id: groupId,
      options: _normalizeBlankOptionList(group && group.options).map(function(opt) {
        const key = String((opt && opt.key) || '').trim().toUpperCase()
        const text = String((opt && opt.text) || '').trim()
        const optionText = _stripLeadingOptionLabel(key, text)
        const plain = _toPlainInlineMathText(optionText)
        const needsRich = !plain && _needsRichRender(optionText)
        return Object.assign({}, opt, {
          key,
          _text: plain || optionText,
          _selected: blankAnswers[groupId] === key,
          _needsRich: needsRich,
          _html: needsRich ? _optionTextToHtml(key, optionText) : '',
        })
      }).filter(function(opt) {
        return opt.key
      }),
    }
  }).filter(function(group) {
    return group.id && group.options.length > 0
  })
}

function _serializeBlankAnswer(groups, blankAnswers) {
  const parts = []
  ;(groups || []).forEach(function(group) {
    const id = String((group && group.id) || '').trim()
    const value = blankAnswers && blankAnswers[id]
    if (id && value) parts.push(id + ':' + String(value).trim().toUpperCase())
  })
  return parts.join(';')
}

function _getBlankOptionGroups(q) {
  if (!q) return []
  if (q.content && Array.isArray(q.content.blank_option_groups)) return q.content.blank_option_groups
  if (Array.isArray(q.blank_option_groups)) return q.blank_option_groups
  return []
}

function _isMultiBlankChoice(q) {
  return q && (q.question_type === 'multi_blank_choice' || _getBlankOptionGroups(q).length > 0)
}

function _isQuestionAnswered(q, answer) {
  if (!_isMultiBlankChoice(q)) return !!answer
  const groups = _getBlankOptionGroups(q)
  if (!groups.length) return !!answer
  const blankAnswers = _normalizeBlankAnswer(answer)
  return groups.every(function(group) {
    return !!blankAnswers[String((group && group.id) || '').trim()]
  })
}

function _buildAnsweredFlags(questions, answerMap) {
  const flags = {}
  ;(questions || []).forEach(function(q) {
    const id = String(q.id)
    flags[id] = _isQuestionAnswered(q, (answerMap || {})[id] || '')
  })
  return flags
}

function _countAnswered(flags) {
  return Object.keys(flags || {}).filter(function(id) {
    return flags[id]
  }).length
}

function _applyAnsweredFlags(questions, flags) {
  return (questions || []).map(function(q) {
    return Object.assign({}, q, { _answered: !!(flags || {})[String(q.id)] })
  })
}

function _buildBlankSelectedFlags(groups, answer) {
  const blankAnswers = _normalizeBlankAnswer(answer)
  const flags = {}
  ;(groups || []).forEach(function(group) {
    const groupId = String((group && group.id) || '').trim()
    flags[groupId] = {}
    ;(group.options || []).forEach(function(opt) {
      flags[groupId][opt.key] = blankAnswers[groupId] === opt.key
    })
  })
  return flags
}

Page({
  data: {
    // 设置
    selectedSubject: '',
    selectedMode: 'random',
    count: 5,
    started: false,
    loading: false,
    submitting: false,

    // 题目列表
    questions: [],
    currentIndex: 0,
    totalQuestions: 0,
    currentQuestion: null,
    optionKeys: [],
    selectedFlags: {},

    // 答题卡
    answerMap: {},
    answeredFlags: {},
    answeredCount: 0,
    blankSelectedFlags: {},

    // 提交后
    submitted: false,
    results: [],
    correctCount: 0,
    wrongCount: 0,

    // 计时
    startTime: 0,
    elapsedSec: 0,
    elapsedText: '00:00',
    _timer: null,

    // 答题卡弹窗
    showSheet: false,

    // 滑动动画
    animClass: '',

    // 公式图片化
    enableMathImage: false,

    // Debug
    traceId: '',
    renderCount: 0,
  },

  onLoad() {
    this.setData({ enableMathImage: config.enableMathImage || false })
  },

  /* ==================== 设置阶段 ==================== */

  chooseSubject(e) {
    this.setData({ selectedSubject: e.currentTarget.dataset.subject })
  },

  chooseMode(e) {
    this.setData({ selectedMode: e.currentTarget.dataset.mode })
  },

  setCount(e) {
    this.setData({ count: Number(e.currentTarget.dataset.count) })
  },

  async startPractice() {
    const traceId = createTraceId()
    this.setData({
      traceId,
      renderCount: 0,
      started: true,
      currentIndex: 0,
      answerMap: {},
      answeredFlags: {},
      answeredCount: 0,
      blankSelectedFlags: {},
      results: [],
      submitted: false,
      correctCount: 0,
      wrongCount: 0,
      elapsedSec: 0,
      startTime: Date.now(),
    })
    this._startTimer()
    await this._loadQuestions()
  },

  _startTimer() {
    this._clearTimer()
    this._timer = setInterval(() => {
      const sec = Math.floor((Date.now() - this.data.startTime) / 1000)
      this.setData({ elapsedSec: sec, elapsedText: this._fmt(sec) })
    }, 1000)
  },

  _fmt(sec) {
    const s = Math.max(0, sec || 0)
    const m = Math.floor(s / 60)
    const ss = s % 60
    return `${String(m).padStart(2, '0')}:${String(ss).padStart(2, '0')}`
  },

  _clearTimer() {
    if (this._timer) {
      clearInterval(this._timer)
      this._timer = null
    }
  },

  async _loadQuestions() {
    this.setData({ loading: true })
    try {
      const res = await api.get('/practice/questions', {
        subject: this.data.selectedSubject,
        count: this.data.count || 5,
        mode: this.data.selectedMode || 'random',
        _traceId: this.data.traceId,
      })
      const questions = _applyAnsweredFlags(res.questions || [], {})
      debugLog(this.data.traceId, 'STATE_AFTER_API', {
        total: questions.length,
        responseTraceId: res.trace_id,
      })
      saveDebugSnapshot(this.data.traceId, 'state_after_api', {
        total: questions.length,
        questionIds: questions.map(q => q.id),
      })
      this.setData({ questions, totalQuestions: questions.length, loading: false, answeredFlags: {} })
      if (questions.length > 0) {
        this._showQuestion(0)
      } else {
        const label = this.subjectLabel(this.data.selectedSubject) || this.data.selectedSubject
        wx.showModal({
          title: '该科目暂无题目',
          content: `「${label}」目前没有已发布的题目。\n请确认：\n1. 导入批次已审核通过\n2. 题目科目分类是否正确（导入时混合 PDF 可能被错分）\n3. 试试其他科目分类`,
          showCancel: true,
          confirmText: '返回',
          cancelText: '继续等待',
          success: (r) => {
            if (r.confirm) this.setData({ started: false })
          },
        })
      }
    } catch (e) {
      console.error('加载题目失败', e)
      this.setData({ loading: false })
      wx.showToast({ title: '加载题目失败', icon: 'none' })
    }
  },

  _showQuestion(index) {
    const q = this.data.questions[index]
    if (!q) return
    const isBlankChoice = _isMultiBlankChoice(q)
    const answer = this.data.answerMap[String(q.id)] || ''
    const blankOptionGroups = isBlankChoice ? _enrichBlankOptionGroups(_getBlankOptionGroups(q), answer) : []
    const isTrueFalse = q.question_type === 'true_false' || q.question_type === 'judgement'
    const opts = !isBlankChoice && q.options && Object.keys(q.options).length > 0
      ? q.options
      : (!isBlankChoice && isTrueFalse ? { A: '正确', B: '错误' } : null)
    const optionKeys = opts ? Object.keys(opts) : []
    const isMulti = q.question_type === 'multiple_choice'
    const selectedFlags = {}
    for (const key of optionKeys) {
      selectedFlags[key] = isMulti ? answer.split(',').indexOf(key) >= 0 : answer === key
    }
    const blankSelectedFlags = _buildBlankSelectedFlags(blankOptionGroups, answer)
    // 预处理 LaTeX，去重相邻重复段落
    const stemText = (q.content && (q.content.text || q.content.stem)) || ''
    const sourceStemText = stemText || (q.content && _segmentsToText(q.content.segments)) || ''
    const cleanedStem = _cleanStemText(sourceStemText, opts, optionKeys)
    const plainStem = _toPlainInlineMathText(cleanedStem)
    q._stemText = plainStem || cleanedStem
    q._stemNeedsRich = !plainStem && _needsRichRender(cleanedStem)
    q._stemHtml = q._stemNeedsRich ? _textToHtml(cleanedStem) : ''
    q._segments = (q.content && q.content.render_mode === 'segments') ? _textToSegments(q._stemText) : []
    q._opts = opts
    q._blankOptionGroups = blankOptionGroups
    q._hasBlankOptionGroups = blankOptionGroups.length > 0
    const optHtml = {}
    const optText = {}
    const optNeedsRich = {}
    for (const key of optionKeys) {
      const optionText = _stripLeadingOptionLabel(key, (opts && opts[key]) || '')
      const plainOptionText = _toPlainInlineMathText(optionText)
      optText[key] = plainOptionText || optionText
      optNeedsRich[key] = !plainOptionText && _needsRichRender(optionText)
      optHtml[key] = optNeedsRich[key] ? _optionTextToHtml(key, optionText) : ''
    }
    q._optHtml = optHtml
    q._optText = optText
    q._optNeedsRich = optNeedsRich
    const renderCount = (this.data.renderCount || 0) + 1
    if (shouldDebugQuestion(q.id)) {
      debugLog(this.data.traceId || q.trace_id, 'BEFORE_RENDER', {
        questionId: q.id,
        index,
        renderCount,
        optionKeys,
        blankGroupCount: blankOptionGroups.length,
        sourceLen: sourceStemText.length,
        cleanedLen: cleanedStem.length,
        hasEmbeddedOptions: _containsTrailingOptionBlock(sourceStemText, optionKeys),
        hasCleanedOptions: _containsTrailingOptionBlock(cleanedStem, optionKeys),
        sourceTail: _shortText(sourceStemText.slice(-120)),
        cleanedTail: _shortText(cleanedStem.slice(-120)),
      })
      saveDebugSnapshot(this.data.traceId || q.trace_id, 'render', {
        questionId: q.id,
        index,
        renderCount,
        optionKeys,
        blankGroupCount: blankOptionGroups.length,
        stem: cleanedStem,
      })
    }
    this.setData({
      currentIndex: index,
      currentQuestion: q,
      optionKeys,
      selectedFlags,
      blankSelectedFlags,
      renderCount,
    })
  },

  goQuestion(e) {
    const idx = parseInt(e.currentTarget.dataset.index, 10)
    if (!isNaN(idx) && idx >= 0 && idx < this.data.totalQuestions) {
      this.setData({ showSheet: false })
      this._showQuestion(idx)
    }
  },

  toggleSheet() {
    this.setData({ showSheet: !this.data.showSheet })
  },

  closeSheet() {
    this.setData({ showSheet: false })
  },

  /* ==================== 滑动系统 ==================== */

  onTouchStart(e) {
    if (this.data.submitted || this._animating) return
    const t = e.touches[0]
    this._touchX = t.clientX
    this._touchY = t.clientY
    this._touchTime = Date.now()
    this._swiped = false
  },

  onTouchEnd(e) {
    if (this.data.submitted || this._animating) return
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
    const canGo = isLeft
      ? this.data.currentIndex < this.data.totalQuestions - 1
      : this.data.currentIndex > 0

    if (!canGo) {
      this._animating = true
      this.setData({ animClass: isLeft ? 'edge-left' : 'edge-right' })
      setTimeout(() => {
        this.setData({ animClass: '' })
        this._animating = false
      }, 200)
      return
    }

    const animMs = dt < 200 ? 120 : 160
    this._animating = true
    this.setData({ animClass: isLeft ? 'slide-out-left' : 'slide-out-right' })

    setTimeout(() => {
      const next = this.data.currentIndex + (isLeft ? 1 : -1)
      this._showQuestion(next)
      this.setData({ animClass: 'slide-in' })

      setTimeout(() => {
        this.setData({ animClass: '' })
        this._animating = false
        this._swiped = false
      }, animMs)
    }, animMs)
  },

  selectOption(e) {
    if (this._animating || this.data.submitted) return
    if (this._swiped) {
      this._swiped = false
      return
    }

    const opt = e.currentTarget.dataset.option
    const q = this.data.currentQuestion
    if (!q) return

    const isMulti = q.question_type === 'multiple_choice'
    const key = String(q.id)
    const prev = this.data.answerMap[key] || ''

    let newAnswer
    if (isMulti) {
      const sel = prev ? prev.split(',') : []
      const idx = sel.indexOf(opt)
      if (idx >= 0) sel.splice(idx, 1)
      else sel.push(opt)
      newAnswer = sel.join(',')
    } else {
      newAnswer = prev === opt ? '' : opt
    }

    const answerMap = { ...this.data.answerMap }
    if (newAnswer) {
      answerMap[key] = newAnswer
    } else {
      delete answerMap[key]
    }
    const answeredFlags = _buildAnsweredFlags(this.data.questions, answerMap)
    const answeredCount = _countAnswered(answeredFlags)
    const questions = _applyAnsweredFlags(this.data.questions, answeredFlags)
    if (shouldDebugQuestion(q.id)) {
      debugLog(this.data.traceId || q.trace_id, 'STATE_CHANGE', {
        questionId: q.id,
        previousAnswer: prev,
        nextAnswer: newAnswer,
        answeredCount,
      })
      saveDebugSnapshot(this.data.traceId || q.trace_id, 'state_change', {
        questionId: q.id,
        previousAnswer: prev,
        nextAnswer: newAnswer,
        answeredCount,
      })
    }
    const optionKeys = this.data.optionKeys
    const selectedFlags = {}
    for (const k of optionKeys) {
      selectedFlags[k] = isMulti
        ? newAnswer.split(',').indexOf(k) >= 0
        : newAnswer === k
    }
    this.setData({ questions, answerMap, answeredFlags, answeredCount, selectedFlags })
  },

  selectBlankOption(e) {
    if (this._animating || this.data.submitted) return
    if (this._swiped) {
      this._swiped = false
      return
    }

    const blankId = String(e.currentTarget.dataset.blankId || '').trim()
    const opt = String(e.currentTarget.dataset.option || '').trim().toUpperCase()
    const q = this.data.currentQuestion
    if (!q || !_isMultiBlankChoice(q) || !blankId || !opt) return

    const key = String(q.id)
    const prev = this.data.answerMap[key] || ''
    const blankAnswers = _normalizeBlankAnswer(prev)
    if (blankAnswers[blankId] === opt) {
      delete blankAnswers[blankId]
    } else {
      blankAnswers[blankId] = opt
    }

    const groupsForAnswer = q._blankOptionGroups || _enrichBlankOptionGroups(_getBlankOptionGroups(q), prev)
    const newAnswer = _serializeBlankAnswer(groupsForAnswer, blankAnswers)
    const answerMap = { ...this.data.answerMap }
    if (newAnswer) {
      answerMap[key] = newAnswer
    } else {
      delete answerMap[key]
    }
    const answeredFlags = _buildAnsweredFlags(this.data.questions, answerMap)
    const answeredCount = _countAnswered(answeredFlags)
    const questions = _applyAnsweredFlags(this.data.questions, answeredFlags)
    const groups = _enrichBlankOptionGroups(_getBlankOptionGroups(q), newAnswer)
    const blankSelectedFlags = _buildBlankSelectedFlags(groups, newAnswer)
    const currentQuestion = Object.assign({}, q, {
      _blankOptionGroups: groups,
      _hasBlankOptionGroups: groups.length > 0,
    })

    if (shouldDebugQuestion(q.id)) {
      debugLog(this.data.traceId || q.trace_id, 'STATE_CHANGE', {
        questionId: q.id,
        previousAnswer: prev,
        nextAnswer: newAnswer,
        answeredCount,
      })
      saveDebugSnapshot(this.data.traceId || q.trace_id, 'state_change', {
        questionId: q.id,
        previousAnswer: prev,
        nextAnswer: newAnswer,
        answeredCount,
      })
    }

    this.setData({ questions, answerMap, answeredFlags, answeredCount, blankSelectedFlags, currentQuestion })
  },

  goNext() {
    if (this._animating) return
    if (this.data.currentIndex < this.data.totalQuestions - 1) {
      this._animating = true
      this.setData({ animClass: 'slide-out-left' })
      setTimeout(() => {
        this._showQuestion(this.data.currentIndex + 1)
        this.setData({ animClass: 'slide-in' })
        setTimeout(() => {
          this.setData({ animClass: '' })
          this._animating = false
        }, 120)
      }, 120)
    }
  },

  goPrev() {
    if (this._animating) return
    if (this.data.currentIndex > 0) {
      this._animating = true
      this.setData({ animClass: 'slide-out-right' })
      setTimeout(() => {
        this._showQuestion(this.data.currentIndex - 1)
        this.setData({ animClass: 'slide-in' })
        setTimeout(() => {
          this.setData({ animClass: '' })
          this._animating = false
        }, 120)
      }, 120)
    }
  },

  /* ==================== 交卷 ==================== */

  async doSubmit() {
    const { answerMap, questions, startTime, selectedSubject } = this.data
    const total = questions.length || 0
    const answeredFlags = _buildAnsweredFlags(questions, answerMap)
    const answeredCount = _countAnswered(answeredFlags)
    const completedQuestions = questions.filter(function(q) {
      return answeredFlags[String(q.id)]
    })
    const unanswered = total - answeredCount

    if (unanswered > 0) {
      const { confirm } = await wx.showModal({
        title: '还有题目未作答',
        content: `还有 ${unanswered} 道题未作答，确定提交吗？`,
        confirmText: '确定提交',
        cancelText: '继续作答',
      })
      if (!confirm) return
    }

    this._clearTimer()
    this.setData({ submitting: true })
    wx.showLoading({ title: '批改中...' })

    try {
      const answers = completedQuestions.map(q => ({
        question_id: q.id,
        user_answer: answerMap[String(q.id)] || '',
        used_time: Math.floor((Date.now() - startTime) / 1000),
      }))

      debugLog(this.data.traceId, 'SUBMIT', {
        total: answers.length,
        answeredCount,
      })
      saveDebugSnapshot(this.data.traceId, 'submit_before', {
        answers: answers.map(item => ({ question_id: item.question_id, has_answer: !!item.user_answer })),
      })
      const result = await api.post('/practice/batch-submit', {
        answers,
        _traceId: this.data.traceId,
      })

      const duration = Math.floor((Date.now() - startTime) / 1000)
      wx.hideLoading()

      // 存储详细结果供 result 页使用
      wx.setStorageSync('lastPracticeResult', {
        correct: result.total_correct || 0,
        wrong: result.total_wrong || 0,
        total,
        subject: selectedSubject,
        duration,
        traceId: result.trace_id || this.data.traceId,
        results: result.results || [],
      })

      wx.redirectTo({
        url: [
          `/pages/practice-result/practice-result`,
          `?correct=${result.total_correct || 0}`,
          `&wrong=${result.total_wrong || 0}`,
          `&total=${total}`,
          `&subject=${selectedSubject}`,
          `&duration=${duration}`,
        ].join(''),
      })
    } catch (e) {
      console.error('提交失败', e)
      wx.hideLoading()
      this.setData({ submitting: false })
      wx.showToast({ title: '提交失败', icon: 'none' })
    }
  },

  finishEarly() {
    const answeredFlags = _buildAnsweredFlags(this.data.questions, this.data.answerMap)
    const answered = _countAnswered(answeredFlags)
    wx.showModal({
      title: '结束练习',
      content: `已完成 ${answered} / ${this.data.totalQuestions} 题，确定结束吗？`,
      success: (res) => {
        if (res.confirm) this.doSubmit()
      },
    })
  },

  /* ==================== 工具 ==================== */

  subjectLabel(s) {
    const map = {
      math2: '数学二', 'math2-calculus': '数学二·高数', 'math2-linalg': '数学二·线代',
      exam408: '408', 'exam408-ds': '408·DS', 'exam408-os': '408·OS',
      'exam408-co': '408·CO', 'exam408-cn': '408·CN',
      english: '英语',
    }
    return map[s] || s || ''
  },

  modeLabel(m) {
    const map = { random: '随机', sequential: '顺序' }
    return map[m] || m || ''
  },

  noop() {},

  onUnload() {
    this._clearTimer()
  },
})
