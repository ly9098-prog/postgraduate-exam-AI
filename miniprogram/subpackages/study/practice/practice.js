const api = require('../../../utils/api')
const config = require('../../../config')
const { createTraceId, debugLog, saveDebugSnapshot, shouldDebugQuestion } = require('../../../utils/debug')
const { buildRenderModel, setRenderGuardPage, resetRenderGuard } = require('../utils/stem-render')
const adapter = require('../utils/question-runner-adapter')

const PRACTICE_RECENT_SUBJECTS_KEY = 'practice_recent_subjects_v1'
const SUBJECT_DOUBLE_TAP_INTERVAL = 320

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

Page({
  _pageAlive: false,
  _practiceSession: {},
  _lastSubjectOptionTap: null,

  data: {
    // 设置
    subjectTree: [],
    selectedSubjectId: null,
    selectedSubjectName: '',
    selectedSubjectHasChildren: false,
    expandedSubjectId: null,
    selectedMode: 'random',
    selectedModeLabel: '随机挑战',
    count: 5,
    countDisplay: '05',
    estimatedMinutes: 10,
    settingsExpanded: false,
    subjectSheetVisible: false,
    subjectSheetClosing: false,
    recentSubjects: [],
    statusBarHeight: 20,
    navBarHeight: 44,
    started: false,
    loading: false,
    submitting: false,

    // computed
    progressPercent: 0,
    errorText: '',

    // 题目列表
    questions: [],
    currentIndex: 0,
    totalQuestions: 0,
    currentQuestion: null,
    currentAnswerState: null,

    // 答题卡
    answeredCount: 0,
    // 提交后
    submitted: false,
    feedbackVisible: false,
    feedbackType: '',
    feedbackTitle: '',
    feedbackDetail: '',
    feedbackComboText: '',
    feedbackComboLevel: '',
    feedbackStarCount: 0,

    // 计时
    elapsedText: '00:00',
    _timer: null,

    // 公式图片化
    enableMathImage: false,

  },

  onLoad() {
    this._pageAlive = true
    this._lastSubjectOptionTap = null
    this._resetSession()
    this._pendingResultUrl = ''
    setRenderGuardPage('practice')
    resetRenderGuard()
    this._initCustomNavigation()
    this._updateComputedFields()
  },

  onUnload() {
    this._pageAlive = false
    this._lastSubjectOptionTap = null
    resetRenderGuard()
    this._clearTimer()
    if (this._feedbackTimer) {
      clearTimeout(this._feedbackTimer)
      this._feedbackTimer = null
    }
    if (this._subjectSheetCloseTimer) {
      clearTimeout(this._subjectSheetCloseTimer)
      this._subjectSheetCloseTimer = null
    }
  },

  _resetSession() {
    this._practiceSession = {
      traceId: '',
      safeModeActive: false,
      answerMap: {},
      answeredFlags: {},
      correctCount: 0,
      comboCount: 0,
      elapsedSec: 0,
      startTime: 0,
      questionTimeMap: {},
      currentQuestionStartedAt: 0,
      requestId: '',
      optionKeys: [],
      questionRenderCache: Object.create(null),
    }
  },

  onShow() {
  },

  onReady() {
    if (config.DEV) console.log('[LAYER6_ONREADY]', Date.now())
    this.setData({ enableMathImage: config.enableMathImage || false })
    this.loadPracticeSubjects()
  },

  /* ==================== 设置阶段 ==================== */

  async loadPracticeSubjects() {
    try {
      const res = await api.get('/practice/subjects')
      const subjectTree = this.normalizeSubjectTree(res || [])
      this.setData({ subjectTree })
      this.initDefaultSubject(subjectTree)
    } catch (e) {
      console.error('加载科目树失败', e)
      wx.showToast({ title: '加载科目失败', icon: 'none' })
    }
  },

  /**
   * 规范化科目树。保留后端返回的已有树结构，不做展平-重建。
   * - 如果节点已带 children，递归归一化每个子节点
   * - 如果原始是平铺列表（含 parent_id），按 parent_id 组装树
   * - 顶层只保留 level=1 或 parent_id 为空的节点
   * - 过滤 is_active=false
   * - 父级与子级均按 sort_order 升序
   */
  normalizeSubjectTree(raw) {
    if (!Array.isArray(raw) || raw.length === 0) return []

    const toId = (n) => (n.subject_id != null ? n.subject_id : n.id)
    const toName = (n) => (n.display_name != null ? n.display_name : (n.name != null ? n.name : ''))
    const toCode = (n) => (n.subject_code != null ? n.subject_code : (n.code != null ? n.code : ''))
    const bySort = (a, b) => (a.sort_order - b.sort_order) || (a.subject_id - b.subject_id)

    const normalize = (n) => {
      if (!n) return null
      if (n.is_active === false) return null
      return {
        subject_id: Number(toId(n)),
        display_name: toName(n),
        subject_code: toCode(n),
        parent_id: n.parent_id != null ? Number(n.parent_id) : null,
        level: n.level != null ? Number(n.level) : null,
        path: n.path || '',
        sort_order: n.sort_order != null ? Number(n.sort_order) : 0,
        is_active: true,
        children: Array.isArray(n.children)
          ? n.children.map(normalize).filter(Boolean).sort(bySort)
          : [],
      }
    }

    // 先递归归一化（保留已有 children 结构）
    const items = raw.map(normalize).filter(Boolean)
    if (items.length === 0) return []

    // 拆分父级与子级
    const parentItems = []
    const childItems = []
    const nodes = {}

    items.forEach((n) => {
      nodes[n.subject_id] = n
      const isParent = n.level === 1 || n.parent_id == null
      if (isParent) parentItems.push(n)
      else childItems.push(n)
    })

    // 将无父级 children 的子级挂到对应父级
    childItems.forEach((child) => {
      const parent = child.parent_id != null ? nodes[child.parent_id] : null
      if (parent) {
        if (!parent.children.some((c) => c.subject_id === child.subject_id)) {
          parent.children.push(child)
        }
        parent.children.sort(bySort)
      } else {
        // 找不到父级，升级为根节点
        parentItems.push(child)
      }
    })

    parentItems.sort(bySort)
    return parentItems
  },

  /**
   * 初始化默认选中（方案 2：默认展开第一个父级并选中第一个子级）
   * 保证 expandedSubjectId / selectedSubjectId / selectedSubjectName 同时被正确设置，
   * 避免出现 selectedSubjectId 为空但页面看起来已选择的不一致状态。
   */
  initDefaultSubject(subjectTree) {
    if (!subjectTree || subjectTree.length === 0) {
      this.setData({
        selectedSubjectId: null,
        selectedSubjectName: '',
        selectedSubjectHasChildren: false,
        expandedSubjectId: null,
        recentSubjects: [],
      })
      return
    }

    const availableSubjects = this._flattenSelectableSubjects(subjectTree)
    let stored = []
    try {
      const value = wx.getStorageSync(PRACTICE_RECENT_SUBJECTS_KEY)
      stored = Array.isArray(value) ? value : []
    } catch (e) {
      stored = []
    }

    const availableMap = {}
    availableSubjects.forEach((item) => { availableMap[item.subject_id] = item })
    const validStored = stored
      .map((item) => availableMap[Number(item.subject_id)])
      .filter(Boolean)

    const fallback = availableSubjects[0]
    const selected = validStored[0] || fallback
    if (!selected) return

    const recentBase = validStored.length > 0
      ? validStored
      : [selected]
    const recentSubjects = this._decorateRecentSubjects(recentBase.slice(0, 4))

    this.setData({
      expandedSubjectId: selected.parent_subject_id || selected.subject_id,
      selectedSubjectId: selected.subject_id,
      selectedSubjectName: selected.display_name,
      selectedSubjectHasChildren: Boolean(selected.has_children),
      recentSubjects,
    })
  },

  _initCustomNavigation() {
    try {
      const windowInfo = wx.getWindowInfo ? wx.getWindowInfo() : wx.getSystemInfoSync()
      const statusBarHeight = Number(windowInfo.statusBarHeight || 20)
      let navBarHeight = 44
      if (wx.getMenuButtonBoundingClientRect) {
        const capsule = wx.getMenuButtonBoundingClientRect()
        if (capsule && capsule.height && capsule.top) {
          navBarHeight = (capsule.top - statusBarHeight) * 2 + capsule.height
        }
      }
      this.setData({
        statusBarHeight: Math.max(20, statusBarHeight),
        navBarHeight: Math.max(40, navBarHeight),
      })
    } catch (e) {
      this.setData({ statusBarHeight: 20, navBarHeight: 44 })
    }
  },

  _flattenSelectableSubjects(subjectTree) {
    const result = []
    ;(subjectTree || []).forEach((parent) => {
      const parentId = Number(parent.subject_id)
      const children = Array.isArray(parent.children) ? parent.children : []

      // 保持原默认体验：优先使用第一个具体子科目作为首次进入的 fallback。
      children.forEach((child) => {
        result.push({
          subject_id: Number(child.subject_id),
          display_name: child.display_name,
          parent_subject_id: parentId,
          has_children: false,
        })
      })

      // 父级也可直接选择，表示“该科目（全部）”。
      result.push({
        subject_id: parentId,
        display_name: children.length > 0 ? `${parent.display_name}（全部）` : parent.display_name,
        parent_subject_id: parentId,
        has_children: children.length > 0,
      })
    })
    return result.filter((item) => item.subject_id && item.display_name)
  },

  _subjectMark(name) {
    const text = String(name || '')
    if (/数据|计算机|程序|代码|网络|操作系统/.test(text)) return '</>'
    if (/数学|代数|高数|概率|统计/.test(text)) return 'Σ'
    if (/英语|外语/.test(text)) return 'A'
    if (/政治|思政/.test(text)) return '政'
    return text.slice(0, 1) || '·'
  },

  _decorateRecentSubjects(subjects) {
    return (subjects || []).map((item) => {
      const subjectId = Number(item.subject_id)
      const hasChildren = item.has_children != null
        ? Boolean(item.has_children)
        : this._subjectHasChildren(subjectId)
      return {
        subject_id: subjectId,
        display_name: item.display_name,
        parent_subject_id: Number(item.parent_subject_id || item.subject_id),
        has_children: hasChildren,
        mark: this._subjectMark(item.display_name),
        scope_label: hasChildren ? '全部范围' : '继续练习',
      }
    })
  },

  _rememberSubject(subjectId, subjectName) {
    const id = Number(subjectId)
    if (!id || !subjectName) return
    const parentId = this._findParentSubjectId(id)
    const hasChildren = this._subjectHasChildren(id)
    const base = [{
      subject_id: id,
      display_name: subjectName,
      parent_subject_id: parentId || id,
      has_children: hasChildren,
    }].concat((this.data.recentSubjects || []).filter((item) => Number(item.subject_id) !== id))
    const recentSubjects = this._decorateRecentSubjects(base.slice(0, 4))
    this.setData({ recentSubjects })
    try {
      wx.setStorageSync(PRACTICE_RECENT_SUBJECTS_KEY, recentSubjects.map((item) => ({
        subject_id: item.subject_id,
        display_name: item.display_name,
        parent_subject_id: item.parent_subject_id,
      })))
    } catch (e) {
      console.warn('保存最近使用科目失败', e)
    }
  },

  _queueRememberSubject(subjectId, subjectName) {
    const id = Number(subjectId)
    if (!id || !subjectName) return
    this._pendingRememberSubject = { subjectId: id, subjectName }
  },

  _flushPendingRecentSubject() {
    const pending = this._pendingRememberSubject
    this._pendingRememberSubject = null
    if (!pending) return
    this._rememberSubject(pending.subjectId, pending.subjectName)
  },

  _findParentSubjectId(subjectId) {
    const id = Number(subjectId)
    const tree = this.data.subjectTree || []
    for (let i = 0; i < tree.length; i += 1) {
      const parent = tree[i]
      if (Number(parent.subject_id) === id) return Number(parent.subject_id)
      const children = Array.isArray(parent.children) ? parent.children : []
      if (children.some((child) => Number(child.subject_id) === id)) {
        return Number(parent.subject_id)
      }
    }
    return null
  },

  _subjectHasChildren(subjectId) {
    const id = Number(subjectId)
    const tree = this.data.subjectTree || []
    for (let i = 0; i < tree.length; i += 1) {
      const parent = tree[i]
      if (Number(parent.subject_id) === id) {
        return Array.isArray(parent.children) && parent.children.length > 0
      }
    }
    return false
  },

  toggleSettings() {
    this.setData({ settingsExpanded: !this.data.settingsExpanded })
  },

  openSubjectSheet() {
    if (this._subjectSheetCloseTimer) {
      clearTimeout(this._subjectSheetCloseTimer)
      this._subjectSheetCloseTimer = null
    }
    this.setData({
      subjectSheetVisible: true,
      subjectSheetClosing: false,
    })
  },

  _hideSubjectSheet(afterClose) {
    if (!this.data.subjectSheetVisible) {
      if (typeof afterClose === 'function') afterClose()
      return
    }
    if (this.data.subjectSheetClosing) return

    if (this._subjectSheetCloseTimer) clearTimeout(this._subjectSheetCloseTimer)
    this.setData({ subjectSheetClosing: true }, () => {
      this._subjectSheetCloseTimer = setTimeout(() => {
        this._subjectSheetCloseTimer = null
        if (!this._pageAlive) return
        this.setData({
          subjectSheetVisible: false,
          subjectSheetClosing: false,
        }, () => {
          if (typeof afterClose === 'function') afterClose()
        })
      }, 180)
    })
  },

  closeSubjectSheet() {
    this._hideSubjectSheet(() => this._flushPendingRecentSubject())
  },

  _handleSubjectOptionTap(subjectId, source) {
    const id = Number(subjectId)
    if (!id || !this.data.subjectSheetVisible || this.data.subjectSheetClosing) return

    const now = Date.now()
    const key = `${source || 'subject'}:${id}`
    const lastTap = this._lastSubjectOptionTap
    const isDoubleTap = Boolean(
      lastTap &&
      lastTap.key === key &&
      now - lastTap.time <= SUBJECT_DOUBLE_TAP_INTERVAL
    )

    this._lastSubjectOptionTap = isDoubleTap ? null : { key, time: now }
    if (isDoubleTap) {
      this.closeSubjectSheet()
    }
  },

  _selectSubject(subjectId, subjectName, expandedSubjectId, hasChildren) {
    const id = Number(subjectId)
    if (!id || !subjectName) return

    const resolvedHasChildren = hasChildren != null
      ? Boolean(hasChildren)
      : this._subjectHasChildren(id)
    const patch = {
      selectedSubjectId: id,
      selectedSubjectName: subjectName,
      selectedSubjectHasChildren: resolvedHasChildren,
    }
    if (expandedSubjectId != null) {
      patch.expandedSubjectId = Number(expandedSubjectId)
    } else if (resolvedHasChildren) {
      // 选择“父级（全部）”时默认展开该父级，立即展示其子科目。
      patch.expandedSubjectId = id
    }

    // 只切换选中态，不立刻重排 recentSubjects，避免卡片节点重建导致频闪。
    // 弹层关闭或开始练习时，再更新最近使用顺序。
    this._queueRememberSubject(id, subjectName)
    this.setData(patch)
  },

  chooseRecentSubject(e) {
    const ds = e.currentTarget.dataset || {}
    const subjectId = Number(ds.subjectId)
    const subjectName = ds.subjectName
    const hasChildren = ds.hasChildren === true || ds.hasChildren === 'true'
    if (!subjectId || !subjectName) return

    const parentId = this._findParentSubjectId(subjectId)
    this._selectSubject(subjectId, subjectName, parentId || subjectId, hasChildren)
    this._handleSubjectOptionTap(subjectId, 'recent')
  },

  goBack() {
    const pages = getCurrentPages()
    if (pages && pages.length > 1) {
      wx.navigateBack({ delta: 1 })
      return
    }
    wx.reLaunch({ url: '/pages/home/home' })
  },

  /**
   * 点击父级名称区域：选择父级本身。有子级时表示“父级（全部）”。
   * 展开/收起由右侧箭头独立处理，避免选择与折叠互相干扰。
   */
  chooseParentSubject(e) {
    const ds = e.currentTarget.dataset || {}
    const subjectId = Number(ds.subjectId)
    const subjectName = ds.subjectName
    const hasChildren = ds.hasChildren === true || ds.hasChildren === 'true'
    if (!subjectId || !subjectName) return

    const selectedName = hasChildren ? `${subjectName}（全部）` : subjectName
    this._selectSubject(subjectId, selectedName, undefined, hasChildren)
    this._handleSubjectOptionTap(subjectId, 'parent')
  },

  toggleParentExpansion(e) {
    const subjectId = Number((e.currentTarget.dataset || {}).subjectId)
    if (!subjectId) return
    const next = this.data.expandedSubjectId === subjectId ? null : subjectId
    this.setData({ expandedSubjectId: next })
  },

  /**
   * 点击子级科目：更新当前选中科目，弹层保持打开。
   */
  chooseChildSubject(e) {
    const ds = e.currentTarget.dataset || {}
    const subjectId = Number(ds.subjectId)
    const subjectName = ds.subjectName
    if (!subjectId || !subjectName) return
    this._selectSubject(subjectId, subjectName, this._findParentSubjectId(subjectId), false)
    this._handleSubjectOptionTap(subjectId, 'child')
  },

  chooseMode(e) {
    this.setData({ selectedMode: e.currentTarget.dataset.mode }, () => {
      this._updateComputedFields()
    })
  },

  setCount(e) {
    this.setData({ count: Number(e.currentTarget.dataset.count) }, () => {
      this._updateComputedFields()
    })
  },

  async startPractice() {
    if (!this.data.selectedSubjectId) {
      this.openSubjectSheet()
      return
    }
    if (this.data.selectedMode === 'sequential' && this.data.selectedSubjectHasChildren) {
      wx.showToast({ title: '顺序练习仅支持具体科目', icon: 'none' })
      return
    }
    const traceId = createTraceId()
    this._resetSession()
    this._practiceSession.traceId = traceId
    this._practiceSession.startTime = Date.now()
    this.setData({
      traceId,
      renderCount: 0,
      started: true,
      currentIndex: 0,
      answeredCount: 0,
      results: [],
      submitted: false,
      wrongCount: 0,
      errorText: '',
      feedbackVisible: false,
      feedbackType: '',
      feedbackTitle: '',
      feedbackDetail: '',
      feedbackComboText: '',
    })
    this._flushPendingRecentSubject()
    this._startTimer()
    await this._loadQuestions()
  },

  _startTimer() {
    this._clearTimer()
    this._timer = setInterval(() => {
      const sec = Math.floor((Date.now() - this._practiceSession.startTime) / 1000)
      this._practiceSession.elapsedSec = sec
      this.setData({ elapsedText: this._fmt(sec) })
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
      const subjectId = this.data.selectedSubjectId
      if (!subjectId) {
        this._clearTimer()
        this.setData({
          loading: false,
          started: false,
          questions: [],
          totalQuestions: 0,
          currentQuestion: null,
          currentAnswerState: null,
        })
        wx.showToast({ title: '请选择科目', icon: 'none' })
        return
      }
      const mode = this.data.selectedMode || 'random'
      const params = {
        subject_id: subjectId,
        include_children: Boolean(
          this.data.selectedSubjectHasChildren && (mode === 'random' || mode === 'smart')
        ),
        count: this.data.count || 5,
        mode,
        exclude_answered: true,
        no_repeat_days: 30,
        use_leitner: true,
        _traceId: this._practiceSession.traceId,
      }
      // smart 策略由后端统一解析（默认 weakness_vector，并可被实验配置覆盖）。
      // 小程序不再强制 scored，避免绕过 pgvector 召回链路。
      const res = await api.get('/practice/questions', params)
      const questions = adapter.applyAnsweredFlags(res.questions || [], {}, 'id')
      debugLog(this._practiceSession.traceId, 'STATE_AFTER_API', {
        total: questions.length,
        responseTraceId: res.trace_id,
      })
      saveDebugSnapshot(this._practiceSession.traceId, 'state_after_api', {
        total: questions.length,
        questionIds: questions.map(q => q.id),
      })
      this._practiceSession.comboCount = 0
      this._practiceSession.requestId = res.request_id || ''

      // Build first question's render model synchronously, with error fallback
      var firstQuestion = null
      var firstIndex = 0
      if (questions.length > 0) {
        try {
          var viewModelResult = this._buildQuestionViewModel(questions[0])
          if (!viewModelResult) throw new Error('_buildQuestionViewModel returned null')
          firstQuestion = viewModelResult.question
        } catch (renderErr) {
          console.error('首题渲染失败', renderErr)
          this._clearTimer()
          this.setData({
            loading: false,
            started: false,
            questions: [],
            totalQuestions: 0,
            currentQuestion: null,
            currentAnswerState: null,
            errorText: '题目解析失败，可重试或返回选题',
          })
          return
        }
      }

      this.setData({
        questions,
        totalQuestions: questions.length,
        currentIndex: firstIndex,
        currentQuestion: firstQuestion,
        currentAnswerState: viewModelResult ? viewModelResult.answerState : null,
        loading: false,
      })
      if (questions.length > 0 && firstQuestion) {
        this._practiceSession.optionKeys = viewModelResult.optionKeys
        this._practiceSession.currentQuestionStartedAt = Date.now()
        this._updateComputedFields()
        this._checkRenderInvariant(firstQuestion._renderModel)
      } else if (questions.length === 0) {
        const name = this.data.selectedSubjectName || String(subjectId)
        this._clearTimer()
        this.setData({ started: false, loading: false, questions: [], totalQuestions: 0, currentQuestion: null, currentAnswerState: null })
        await this._showSubmitConfirm({
          scenario: 'info',
          eyebrow: 'NO QUESTIONS',
          title: '该科目暂无题目',
          message: `「${name}」目前没有已发布的题目。\n可检查导入审核状态、题目分类，或选择其他科目。`,
          confirmText: '返回选择科目',
          hideCancel: true,
        })
      }
    } catch (e) {
      console.error('加载题目失败', e)
      this._clearTimer()
      this.setData({
        loading: false,
        started: false,
        questions: [],
        totalQuestions: 0,
        currentQuestion: null,
        currentAnswerState: null,
        errorText: '加载题目失败，请重试或返回重新选择科目',
      })
      wx.showToast({ title: '加载题目失败', icon: 'none' })
    }
  },

  /**
   * Build and cache the immutable half of a quiz question.
   *
   * Stem parsing, math/code rendering and option-source normalization are
   * content work. They must not be repeated when the user only toggles an
   * answer, otherwise the component receives a new render payload and may
   * treat the update like navigation.
   */
  _getQuestionRenderView(q, forceRebuild) {
    if (!q) return null
    const session = this._practiceSession
    if (!session.questionRenderCache) session.questionRenderCache = Object.create(null)
    const questionId = String(q.id == null ? '' : q.id)
    const cacheKey = [
      questionId || 'anonymous',
      session.safeModeActive ? 'safe' : 'normal',
      config.enableMathImage ? 'math-image' : 'math-native',
    ].join(':')
    if (!forceRebuild && session.questionRenderCache[cacheKey]) {
      return session.questionRenderCache[cacheKey]
    }

    const isBlankChoice = adapter.isMultiBlankChoice(q)
    const rawBlankOptionGroups = isBlankChoice
      ? adapter.getBlankOptionGroups(q)
      : []
    const isTrueFalse = q.question_type === 'true_false' || q.question_type === 'judgement'
    // Older multi-blank records may only contain a flat options map. If no
    // usable groups exist, keep that map on the ordinary option path.
    const flatOptions = typeof adapter.getQuestionOptions === 'function'
      ? adapter.getQuestionOptions(q)
      : q.options
    const hasFlatOptions = flatOptions && Object.keys(flatOptions).length > 0
    const opts = (!isBlankChoice || rawBlankOptionGroups.length === 0) && hasFlatOptions
      ? flatOptions
      : (!isBlankChoice && isTrueFalse ? { A: '正确', B: '错误' } : null)
    const optionKeys = opts ? Object.keys(opts) : []
    const renderCfg = { enableMathImage: config.enableMathImage || false, DEV: config.DEV }
    if (session.safeModeActive) renderCfg.SAFE_MODE = true
    const renderModel = buildRenderModel(q, opts, renderCfg)
    const result = {
      question: Object.assign({}, q, {
        _renderModel: renderModel,
        _opts: opts,
        _optionKeys: optionKeys,
        _hasBlankOptionGroups: rawBlankOptionGroups.length > 0,
      }),
      optionKeys,
      rawBlankOptionGroups,
    }
    session.questionRenderCache[cacheKey] = result
    return result
  },

  /**
   * Build only the mutable answer half. This object is passed through the
   * dedicated quiz-runner answerState property and can change without
   * replacing currentQuestion or its _renderModel.
   */
  _buildQuestionAnswerState(renderView, answer) {
    if (!renderView || !renderView.question) return null
    const q = renderView.question
    const normalizedAnswer = answer || ''
    const blankOptionGroups = renderView.rawBlankOptionGroups.length > 0
      ? adapter.enrichBlankOptionGroups(renderView.rawBlankOptionGroups, normalizedAnswer)
      : []
    const isMulti = q.question_type === 'multiple_choice'
    const selectedFlags = {}
    for (const key of renderView.optionKeys) {
      selectedFlags[key] = isMulti
        ? normalizedAnswer.split(',').indexOf(key) >= 0
        : normalizedAnswer === key
    }
    return {
      questionId: String(q.id == null ? '' : q.id),
      optionList: blankOptionGroups.length > 0
        ? []
        : adapter.buildOptionListFromFlags(q._opts, renderView.optionKeys, selectedFlags),
      blankOptionGroups,
      hasBlankOptionGroups: blankOptionGroups.length > 0,
    }
  },

  /**
   * Compose the immutable render view and mutable answer state for initial
   * display/navigation while keeping the two lifecycles independent.
   */
  _buildQuestionViewModel(q, forceRebuild) {
    const renderView = this._getQuestionRenderView(q, forceRebuild)
    if (!renderView) return null
    const answer = this._practiceSession.answerMap[String(q.id)] || ''
    return {
      question: renderView.question,
      answerState: this._buildQuestionAnswerState(renderView, answer),
      optionKeys: renderView.optionKeys,
      renderView,
    }
  },

  _settleQuestionTime() {
    const { currentIndex, questions } = this.data
    const { currentQuestionStartedAt, questionTimeMap } = this._practiceSession
    if (!currentQuestionStartedAt || !questions.length) return
    const q = questions[currentIndex]
    if (!q) return
    const elapsed = Math.floor((Date.now() - currentQuestionStartedAt) / 1000)
    const key = String(q.id)
    const map = { ...questionTimeMap }
    map[key] = (map[key] || 0) + elapsed
    this._practiceSession.questionTimeMap = map
  },

  _showQuestion(index) {
    // 结算上一题的用时
    this._settleQuestionTime()

    const q = this.data.questions[index]
    if (!q) return
    var viewModelResult
    try {
      viewModelResult = this._buildQuestionViewModel(q)
    } catch (renderErr) {
      console.error('切题渲染失败 index=' + index + ' id=' + q.id, renderErr)
      wx.showToast({ title: '题目渲染失败，已保留上一题', icon: 'none' })
      return
    }
    if (!viewModelResult) {
      console.error('切题渲染失败 index=' + index + ' id=' + q.id)
      wx.showToast({ title: '题目渲染失败，已保留上一题', icon: 'none' })
      return
    }
    const currentQuestion = viewModelResult.question
    const optionKeys = viewModelResult.optionKeys

    if (shouldDebugQuestion(q.id)) {
      debugLog(this._practiceSession.traceId || q.trace_id, 'BEFORE_RENDER', {
        questionId: q.id,
        index,
        optionKeys,
        blankGroupCount: (viewModelResult.answerState.blankOptionGroups || []).length,
        renderMode: (currentQuestion._renderModel || {}).mode,
        sourceLen: ((q.content && (q.content.stem || q.content.text)) || '').length,
      })
    }
    this._practiceSession.optionKeys = optionKeys
    this._practiceSession.currentQuestionStartedAt = Date.now()
    this.setData({
      currentIndex: index,
      currentQuestion: currentQuestion,
      currentAnswerState: viewModelResult.answerState,
    }, () => {
      this._updateComputedFields()
    })

    // Render invariant: verify only one render mode is active
    this._checkRenderInvariant(currentQuestion._renderModel)
  },

  goQuestion(e) {
    const idx = e.detail.index
    if (idx >= 0 && idx < this.data.totalQuestions) {
      this._showQuestion(idx)
    }
  },

  /* ==================== 导航事件（来自 quiz-runner 组件） ==================== */

  goNext(e) {
    this._showQuestion(e.detail.index)
  },

  goPrev(e) {
    this._showQuestion(e.detail.index)
  },

  async requestExitPractice() {
    if (this.data.submitting) return
    const confirmed = await this._showSubmitConfirm({
      scenario: 'danger',
      eyebrow: 'EXIT PRACTICE',
      title: '退出本组练习？',
      message: '退出后，本组练习不会计入结果。',
      confirmText: '退出练习',
      cancelText: '继续作答',
    })
    if (!confirmed) return
    this._clearTimer()
    if (this._feedbackTimer) {
      clearTimeout(this._feedbackTimer)
      this._feedbackTimer = null
    }
    this._resetSession()
    this._pendingResultUrl = ''
    this.setData({
      started: false,
      loading: false,
      submitting: false,
      submitted: false,
      questions: [],
      currentQuestion: null,
      currentAnswerState: null,
      currentIndex: 0,
      totalQuestions: 0,
      answeredCount: 0,
      progressPercent: 0,
      elapsedText: '00:00',
      feedbackVisible: false,
    })
  },

  selectOption(e) {
    if (this.data.submitted) return
    const opt = e.detail.option
    const q = this.data.currentQuestion
    if (!q) return

    const isMulti = q.question_type === 'multiple_choice'
    const key = String(q.id)
    const prev = this._practiceSession.answerMap[key] || ''

    let newAnswer
    if (isMulti) {
      const sel = prev ? prev.split(',') : []
      const idx = sel.indexOf(opt)
      if (idx >= 0) sel.splice(idx, 1)
      else sel.push(opt)
      sel.sort()
      newAnswer = sel.join(',')
    } else {
      newAnswer = prev === opt ? '' : opt
    }

    const answerMap = { ...this._practiceSession.answerMap }
    if (newAnswer) {
      answerMap[key] = newAnswer
    } else {
      delete answerMap[key]
    }
    const answeredFlags = adapter.buildAnsweredFlags(this.data.questions, answerMap, 'id')
    const answeredCount = adapter.countAnswered(answeredFlags)
    // 使用精确数据路径更新，避免每次传输完整 questions 大对象
    const currentIdx = this.data.currentIndex
    const answered = !!newAnswer
    if (shouldDebugQuestion(q.id)) {
      debugLog(this._practiceSession.traceId || q.trace_id, 'STATE_CHANGE', {
        questionId: q.id,
        previousAnswer: prev,
        nextAnswer: newAnswer,
        answeredCount,
      })
      saveDebugSnapshot(this._practiceSession.traceId || q.trace_id, 'state_change', {
        questionId: q.id,
        previousAnswer: prev,
        nextAnswer: newAnswer,
        answeredCount,
      })
    }
    const renderView = this._getQuestionRenderView(q)
    const answerState = this._buildQuestionAnswerState(renderView, newAnswer)
    this._practiceSession.answerMap = answerMap
    this._practiceSession.answeredFlags = answeredFlags
    this.setData({
      [`questions[${currentIdx}]._answered`]: answered,
      answeredCount,
      currentAnswerState: answerState,
    }, () => {
      this._updateComputedFields()
    })
  },

  selectBlankOption(e) {
    if (this.data.submitted) return
    const blankId = String(e.detail.blankId || '').trim()
    const opt = String(e.detail.option || '').trim().toUpperCase()
    const q = this.data.currentQuestion
    if (!q || !adapter.isMultiBlankChoice(q) || !blankId || !opt) return

    const key = String(q.id)
    const prev = this._practiceSession.answerMap[key] || ''
    const blankAnswers = adapter.normalizeBlankAnswer(prev)
    if (blankAnswers[blankId] === opt) {
      delete blankAnswers[blankId]
    } else {
      blankAnswers[blankId] = opt
    }

    const renderView = this._getQuestionRenderView(q)
    const rawGroups = renderView ? renderView.rawBlankOptionGroups : adapter.getBlankOptionGroups(q)
    const newAnswer = adapter.serializeBlankAnswer(rawGroups, blankAnswers)
    const answerMap = { ...this._practiceSession.answerMap }
    if (newAnswer) {
      answerMap[key] = newAnswer
    } else {
      delete answerMap[key]
    }
    const answeredFlags = adapter.buildAnsweredFlags(this.data.questions, answerMap, 'id')
    const answeredCount = adapter.countAnswered(answeredFlags)
    const answerState = this._buildQuestionAnswerState(renderView, newAnswer)

    if (shouldDebugQuestion(q.id)) {
      debugLog(this._practiceSession.traceId || q.trace_id, 'STATE_CHANGE', {
        questionId: q.id,
        previousAnswer: prev,
        nextAnswer: newAnswer,
        answeredCount,
      })
      saveDebugSnapshot(this._practiceSession.traceId || q.trace_id, 'state_change', {
        questionId: q.id,
        previousAnswer: prev,
        nextAnswer: newAnswer,
        answeredCount,
      })
    }

    this._practiceSession.answerMap = answerMap
    this._practiceSession.answeredFlags = answeredFlags
    // Selection state travels through its own component property. The
    // immutable currentQuestion/render model is deliberately untouched.
    const currentIdx = this.data.currentIndex
    const answered = !!newAnswer
    const totalQuestions = this.data.totalQuestions || 0
    this.setData({
      [`questions[${currentIdx}]._answered`]: answered,
      answeredCount,
      progressPercent: totalQuestions > 0 ? Math.round(answeredCount / totalQuestions * 100) : 0,
      currentAnswerState: answerState,
    })
  },

  /* ==================== computed fields ==================== */

  _modeLabel: function(m) {
    var map = { random: '随机挑战', sequential: '顺序推进', smart: '智能推荐' }
    return map[m] || m || ''
  },

  _updateComputedFields: function(extras) {
    var data = {}
    // selectedModeLabel
    data.selectedModeLabel = this._modeLabel(this.data.selectedMode)
    // setup display fields
    var count = Number(this.data.count || 5)
    var minutesMap = { 5: 10, 10: 20, 20: 40 }
    data.countDisplay = count < 10 ? ('0' + count) : String(count)
    data.estimatedMinutes = minutesMap[count] || Math.max(5, count * 2)
    // progressPercent
    var total = this.data.totalQuestions || 0
    var answered = this.data.answeredCount || 0
    data.progressPercent = total > 0 ? Math.round(answered / total * 100) : 0
    if (extras) Object.assign(data, extras)
    this.setData(data)
  },

  noop() {},

  _showAnswerFeedback(q, answer) {
    const isCorrect = adapter.isAnswerCorrect(q, answer)
    const hasAnswer = !!answer
    const nextCombo = isCorrect === true ? this._practiceSession.comboCount + 1 : (isCorrect === false ? 0 : this._practiceSession.comboCount)
    if (!hasAnswer) {
      this._practiceSession.comboCount = nextCombo
      this.setData({ feedbackVisible: false })
      return
    }

    // 仅在明确判对/判错时弹出反馈，无法判定则不弹
    if (isCorrect !== true && isCorrect !== false) {
      this._practiceSession.comboCount = nextCombo
      return
    }

    const feedbackType = isCorrect === true ? 'correct' : 'wrong'
    let feedbackTitle, feedbackDetail, feedbackComboText, feedbackComboLevel, feedbackStarCount

    if (isCorrect === true) {
      if (nextCombo >= 10) {
        feedbackTitle = '学霸连击'
        feedbackDetail = '状态火热，无人能挡'
        feedbackComboText = `🔥 ${nextCombo} 连对`
        feedbackComboLevel = 'fire'
        feedbackStarCount = 6
      } else if (nextCombo >= 5) {
        feedbackTitle = '五连斩'
        feedbackDetail = '进入心流状态，继续推进'
        feedbackComboText = `⚡ ${nextCombo} 连对`
        feedbackComboLevel = 'hot'
        feedbackStarCount = 5
      } else if (nextCombo >= 3) {
        feedbackTitle = '三连对'
        feedbackDetail = '手感正热，保持这个状态'
        feedbackComboText = `${nextCombo} 连对`
        feedbackComboLevel = 'warm'
        feedbackStarCount = 3
      } else {
        feedbackTitle = '回答正确'
        feedbackDetail = '这题很稳，保持当前节奏'
        feedbackComboText = ''
        feedbackComboLevel = ''
        feedbackStarCount = 0
      }
    } else {
      feedbackTitle = '继续加油'
      feedbackDetail = '先记录选择，交卷后集中复盘'
      feedbackComboText = ''
      feedbackComboLevel = ''
      feedbackStarCount = 0
    }

    if (this._feedbackTimer) clearTimeout(this._feedbackTimer)
    this._practiceSession.comboCount = nextCombo
    this.setData({
      feedbackVisible: true,
      feedbackType,
      feedbackTitle,
      feedbackDetail,
      feedbackComboText,
      feedbackComboLevel,
      feedbackStarCount,
    })
    this._feedbackTimer = setTimeout(() => {
      this.setData({ feedbackVisible: false })
      this._feedbackTimer = null
    }, feedbackComboText ? 2000 : 1200)
  },

  /* ==================== Render Invariant ==================== */

  _checkRenderInvariant(renderModel) {
    if (!renderModel) return
    // Count how many render paths would activate
    let activePaths = 0
    if (renderModel.mode === 'SEGMENTS') activePaths++
    if (renderModel.mode === 'RICH_TEXT') activePaths++
    if (renderModel.mode === 'CODE') activePaths++
    if (renderModel.mode === 'LATEX') activePaths++
    if (renderModel.mode === 'MIXED') {
      activePaths++
      if (!renderModel.blocks || renderModel.blocks.length === 0) {
        console.error('[MIXED_RENDER_VIOLATION] MIXED mode but blocks is empty')
      }
    }
    if (activePaths !== 1) {
      console.error('[RENDER_INVARIANT] _renderModel.mode="' + renderModel.mode + '" yields ' + activePaths + ' active paths (expected 1)')
    }
    // CODE_HTML_LEAK: code rawText must not contain HTML entities
    if (renderModel.mode === 'CODE' && renderModel.rawText) {
      var hasHtmlLeak = /&(?:nbsp|amp|lt|gt|#\d+);/.test(renderModel.rawText)
      if (hasHtmlLeak) {
        console.error(
          '[CODE_HTML_LEAK] CODE rawText contains HTML entities\n' +
          '  tail: ' + renderModel.rawText.slice(-60)
        )
      }
      // CODE_RENDER_VIOLATION: html or richTextNodes must be empty
      var hasRenderViolation = renderModel.html.length > 0 || renderModel.richTextNodes.length > 0
      if (hasRenderViolation) {
        console.error(
          '[CODE_RENDER_VIOLATION] CODE mode leaked into html/richTextNodes ' +
          '(html=' + renderModel.html.length + ', nodes=' + renderModel.richTextNodes.length + ')'
        )
      }
      // Auto self-heal: enter safe mode on any violation
      if ((hasHtmlLeak || hasRenderViolation) && !this._practiceSession.safeModeActive) {
        this._enterSafeMode()
      }
    }
    // MIXED mode: check each CODE block for HTML entity leaks
    if (renderModel.mode === 'MIXED' && renderModel.blocks) {
      for (var mi = 0; mi < renderModel.blocks.length; mi++) {
        var mBlock = renderModel.blocks[mi]
        if (mBlock.type === 'CODE' && mBlock.rawText) {
          if (/&(?:nbsp|amp|lt|gt|#\d+);/.test(mBlock.rawText)) {
            console.error('[CODE_HTML_LEAK] MIXED CODE block #' + mi + ' contains HTML entities')
          }
        }
      }
    }
  },

  _enterSafeMode() {
    console.warn('[SELF_HEAL] CODE render violation detected — entering SAFE_MODE')
    this._practiceSession.safeModeActive = true
    // Re-render current question in safe mode
    this._reRenderCurrentQuestion()
  },

  _reRenderCurrentQuestion() {
    const q = this.data.questions[this.data.currentIndex]
    if (!q) return
    this._practiceSession.questionRenderCache = Object.create(null)
    const viewModelResult = this._buildQuestionViewModel(q, true)
    if (!viewModelResult) return
    this.setData({
      currentQuestion: viewModelResult.question,
      currentAnswerState: viewModelResult.answerState,
    })
    console.warn('[SELF_HEAL] Re-rendered q' + q.id + ' in SAFE_MODE, mode=' + viewModelResult.question._renderModel.mode)
  },


  /* ==================== 交卷 ==================== */

  _showSubmitConfirm(opts) {
    var comp = this.selectComponent('#submitConfirm')
    if (!comp || typeof comp.show !== 'function') {
      wx.showToast({ title: opts.title || '请稍后重试', icon: 'none' })
      return Promise.resolve(false)
    }
    return comp.show(opts)
  },

  async doSubmit(skipConfirm) {
    if (this.data.submitting) return
    const { questions, selectedSubjectId, selectedSubjectName } = this.data
    const { answerMap, startTime, comboCount } = this._practiceSession
    const total = questions.length || 0
    const answeredFlags = adapter.buildAnsweredFlags(questions, answerMap, 'id')
    const answeredCount = adapter.countAnswered(answeredFlags)
    const completedQuestions = questions.filter(function(q) {
      return answeredFlags[String(q.id)]
    })
    const unanswered = total - answeredCount

    if (answeredCount === 0) {
      wx.showToast({ title: '请至少作答 1 题再提交', icon: 'none' })
      return
    }

    var confirmed = false
    if (unanswered > 0) {
      confirmed = await this._showSubmitConfirm({
        scenario: 'unanswered',
        title: `还有 ${unanswered} 题未作答`,
        message: '现在交卷会将未答题记为跳过。',
        confirmText: '仍然交卷',
        cancelText: '继续答题',
      })
    } else if (skipConfirm !== true) {
      confirmed = await this._showSubmitConfirm({
        scenario: 'all-done',
        title: '确认交卷？',
        message: `已完成 ${answeredCount} / ${total} 题`,
        confirmText: '确认交卷',
        cancelText: '继续检查',
      })
    } else {
      confirmed = true
    }
    if (!confirmed) return

    this._clearTimer()
    // 结算最后一题的用时
    this._settleQuestionTime()
    this.setData({ submitting: true })

    const questionTimeMap = this._practiceSession.questionTimeMap

    // ═══════════════════════════════════════════════════
    // 阶段一：服务器提交 — 只有此步骤失败才提示"提交失败"
    // ═══════════════════════════════════════════════════
    var submitResult, storedResults, duration
    const requestId = this._practiceSession.requestId || ('req_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8))
    // 持久化 requestId 供重试时复用
    if (!this._practiceSession.requestId) {
      this._practiceSession.requestId = requestId
    }
    const answers = completedQuestions.map(q => ({
      question_id: q.id,
      user_answer: answerMap[String(q.id)] || '',
      used_time: questionTimeMap[String(q.id)] || 0,
      request_id: requestId,
    }))

    try {
      submitResult = await api.post('/practice/batch-submit', {
        answers,
        _traceId: this._practiceSession.traceId,
      })
    } catch (e) {
      console.error('提交失败', e)
      // 恢复页面可操作状态和计时器
      this._startTimer()
      this.setData({ submitting: false })
      wx.showToast({ title: '提交失败', icon: 'none' })
      return
    }

    // ═══════════════════════════════════════════════════
    // 阶段二：本地结果缓存 — 失败不阻断流程
    // ═══════════════════════════════════════════════════
    duration = Math.floor((Date.now() - startTime) / 1000)
    storedResults = (submitResult.results || []).map(function(rr) {
      return Object.assign({}, rr, {
        user_answer: answerMap[String(rr.question_id)] || '',
      })
    })
    // 将未作答题也写入本地结果视图，结果页才能优先展示“错题 + 跳过题”。
    var submittedResultMap = {}
    storedResults.forEach(function(rr) { submittedResultMap[String(rr.question_id)] = true })
    questions.forEach(function(q) {
      if (!q || !q.id || submittedResultMap[String(q.id)] || answeredFlags[String(q.id)]) return
      storedResults.push({
        question_id: q.id,
        user_answer: '',
        correct_answer: q.correct_answer || q.answer || '',
        is_correct: false,
        _local_skipped: true,
      })
    })
    // 只保存结果页必需的最小数据，不缓存整套题目对象
    // 但需要保留轻量题目数组（id + stem + options）供结果页渲染题干
    var lightQuestions = []
    for (var qi = 0; qi < questions.length; qi++) {
      var qq = questions[qi]
      if (qq && qq.id) {
        lightQuestions.push({
          id: qq.id,
          stem: (qq.content && (qq.content.stem || qq.content.text)) || qq.stem || '',
          options: qq.options || null,
          question_type: qq.question_type || '',
        })
      }
    }
    var userId = ''
    try {
      var userInfo = wx.getStorageSync('user')
      if (userInfo && userInfo.id) userId = String(userInfo.id)
    } catch (_) {}
    // 生成唯一缓存键，用于结果页验证
    var cacheKey = 'pr_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8)
    try {
      wx.setStorageSync('lastPracticeResult', {
        correct: submitResult.total_correct || 0,
        wrong: submitResult.total_wrong || 0,
        skipped: unanswered,
        total,
        subject_id: selectedSubjectId,
        subject_name: selectedSubjectName,
        duration,
        traceId: submitResult.trace_id || this._practiceSession.traceId,
        results: storedResults,
        questions: lightQuestions,
        comboCount,
        _cacheKey: cacheKey,
        _userId: userId,
      })
    } catch (storageError) {
      console.warn('答题已提交成功，但本地结果缓存失败', storageError)
    }

    // ═══════════════════════════════════════════════════
    // 阶段三：进入结果页
    // ═══════════════════════════════════════════════════
    const resultUrl = [
      `/subpackages/study/practice-result/index`,
      `?correct=${submitResult.total_correct || 0}`,
      `&wrong=${submitResult.total_wrong || 0}`,
      `&total=${total}`,
      `&subject_id=${selectedSubjectId}`,
      `&subject_name=${encodeURIComponent(selectedSubjectName || '')}`,
      `&duration=${duration}`,
      `&_ck=${cacheKey}`,
    ].join('')

    // 常规完成直接进入结果页；全屏庆祝仅由结果页在真实升级/解锁时触发。
    this.setData({ submitting: false })
    wx.redirectTo({ url: resultUrl })
  },

})
