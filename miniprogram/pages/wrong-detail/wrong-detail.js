const api = require('../../utils/api')
const config = require('../../config')

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

function _optionTextToHtml(value) {
  return _textToHtml(String(value || '').trim())
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
  },

  onLoad(options) {
    this.setData({ enableMathImage: config.enableMathImage || false })
    this.loadData(options.id)
  },

  async loadData(wqId) {
    this.setData({ loading: true })
    try {
      const wq = await api.get(`/wrong-questions/${wqId}`)
      if (!wq) throw new Error('not found')

      const opts = wq.options || null
      const optionKeys = opts ? Object.keys(opts) : []
      const sourceStemText = (wq.content && (wq.content.text || wq.content.stem)) || (wq.content && _segmentsToText(wq.content.segments)) || ''
      const stemText = _cleanStemText(sourceStemText, opts, optionKeys)
      const stemNeedsRich = _needsRichRender(stemText)
      const stemHtml = stemNeedsRich ? _textToHtml(stemText) : ''
      const stemSegments = (wq.content && wq.content.render_mode === 'segments') ? _textToSegments(stemText) : []
      const optionItems = optionKeys.map((key) => {
        const rawText = (opts && opts[key]) || ''
        let text = _deduplicateLines(rawText)
        text = _stripLeadingOptionLabel(key, text)
        const needsRich = _needsRichRender(text)
        const className = `option-value ${key === wq.answer ? 'right' : ''} ${key === wq.wrong_answer ? 'wrong' : ''}`
        return {
          key,
          text,
          html: needsRich ? _optionTextToHtml(text) : '',
          needsRich,
          className,
        }
      })
      const subjectLabelText = this.subjectLabel(wq.subject)
      const errorTypeLabelText = this.errorTypeLabel(wq.error_type)
      this.setData({ wq, subjectLabelText, errorTypeLabelText, optionKeys, optionItems, stemText, stemNeedsRich, stemHtml, stemSegments, loading: false })
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
