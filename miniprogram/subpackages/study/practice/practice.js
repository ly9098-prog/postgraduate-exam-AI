const api = require('../../../utils/api')
const config = require('../../../config')
const { debugLog, saveDebugSnapshot, shouldDebugQuestion } = require('../../../utils/debug')
const { buildRenderModel, setRenderGuardPage, resetRenderGuard } = require('../utils/stem-render')
const adapter = require('../utils/question-runner-adapter')
const questionImageCache = require('../utils/question-image-cache')

const PRACTICE_RECENT_SUBJECTS_KEY = 'practice_recent_subjects_v1'
const PRACTICE_PENDING_SUBMISSION_KEY_PREFIX = 'practice_pending_submission_v1'
const PRACTICE_PENDING_SUBMISSION_TTL_MS = 24 * 60 * 60 * 1000
const SUBJECT_DOUBLE_TAP_INTERVAL = 320

let _practicePerformanceClock = null
function _monotonicNow() {
  try {
    if (!_practicePerformanceClock && typeof wx !== 'undefined' && typeof wx.getPerformance === 'function') {
      _practicePerformanceClock = wx.getPerformance()
    }
    if (_practicePerformanceClock && typeof _practicePerformanceClock.now === 'function') {
      return _practicePerformanceClock.now()
    }
  } catch (_) {}
  // Base-library fallback only. Modern WeChat runtimes expose getPerformance().
  return Date.now()
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
    sequentialProgress: null,

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
    this._subjectsRequestSeq = 0
    this._questionsRequestSeq = 0
    this._lastSubjectOptionTap = null
    this._resetSession()
    this._pendingResultUrl = ''
    this._submittedResultPayload = null
    setRenderGuardPage('practice')
    resetRenderGuard()
    this._initCustomNavigation()
    this._updateComputedFields()
  },

  onUnload() {
    this._setPracticeUnloadGuard(false)
    this._pageAlive = false
    this._subjectsRequestSeq++
    this._questionsRequestSeq++
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
      activeStartedMonoMs: 0,
      startedAtMs: 0,
      questionTimeMap: {},
      currentQuestionStartedMonoMs: 0,
      requestId: '',
      recommendationRequestId: '',
      batchToken: '',
      batchMode: '',
      submissionSnapshot: null,
      backgroundMs: 0,
      _backgroundStartedMonoMs: null,
      optionKeys: [],
      questionRenderCache: Object.create(null),
    }
  },


  _getCurrentUserId() {
    try {
      const user = wx.getStorageSync('user')
      return user && user.id ? String(user.id) : ''
    } catch (_) {
      return ''
    }
  },

  _pendingSubmissionStorageKey() {
    const userId = this._getCurrentUserId()
    return userId ? `${PRACTICE_PENDING_SUBMISSION_KEY_PREFIX}:${userId}` : ''
  },

  _readPendingSubmission() {
    const key = this._pendingSubmissionStorageKey()
    if (!key) return null
    try {
      const item = wx.getStorageSync(key)
      if (!item || item.version !== 1 || !item.submission) return null
      const createdAt = Number(item.createdAt) || 0
      const freshnessAt = Number(item.updatedAt) || createdAt
      if (!freshnessAt || Date.now() - freshnessAt > PRACTICE_PENDING_SUBMISSION_TTL_MS) {
        wx.removeStorageSync(key)
        return null
      }
      return item
    } catch (_) {
      return null
    }
  },

  _persistPendingSubmission(submission, status, resultUrl) {
    const key = this._pendingSubmissionStorageKey()
    if (!key || !submission) return false
    const previousPersisted = !!submission.pendingPersisted
    try {
      const previous = wx.getStorageSync(key)
      const createdAt = previous && previous.submission && previous.submission.requestId === submission.requestId
        ? (Number(previous.createdAt) || Date.now())
        : Date.now()
      submission.pendingPersisted = true
      wx.setStorageSync(key, {
        version: 1,
        createdAt,
        updatedAt: Date.now(),
        status: status || 'pending',
        resultUrl: resultUrl || '',
        submission,
      })
      return true
    } catch (e) {
      submission.pendingPersisted = previousPersisted
      console.warn('保存待确认交卷失败', e)
      return false
    }
  },

  _clearPendingSubmission(requestId) {
    const key = this._pendingSubmissionStorageKey()
    if (!key) return
    try {
      const item = wx.getStorageSync(key)
      if (!requestId || !item || !item.submission || item.submission.requestId === requestId) {
        wx.removeStorageSync(key)
      }
    } catch (_) {}
  },

  async _offerPendingSubmissionRecovery() {
    const pending = this._readPendingSubmission()
    if (!pending || !this._pageAlive) return false

    const submission = pending.submission
    if (pending.status === 'submitted' && pending.resultUrl) {
      const res = await new Promise(resolve => {
        wx.showModal({
          title: '上次练习已交卷',
          content: '检测到上次练习已提交成功，但结果页尚未确认打开。是否继续查看结果？',
          confirmText: '查看结果',
          cancelText: '稍后处理',
          success: resolve,
          fail: () => resolve({ confirm: false }),
        })
      })
      if (res && res.confirm && this._pageAlive) {
        this._practiceSession.submissionSnapshot = submission
        this._practiceSession.requestId = submission.requestId || ''
        this._pendingResultUrl = pending.resultUrl
        this.setData({ submitted: true, submitting: false })
        this._setPracticeUnloadGuard(false)
        this._openSubmittedResult(pending.resultUrl, submission)
        return true
      }
      return false
    }

    if (pending.status === 'blocked' || submission.retryBlocked) {
      const res = await new Promise(resolve => {
        wx.showModal({
          title: '上次交卷无法继续确认',
          content: '服务器已明确拒绝该提交，继续重试不会成功。可清除本地待确认状态后重新开始练习。',
          confirmText: '清除状态',
          cancelText: '暂不处理',
          success: resolve,
          fail: () => resolve({ confirm: false }),
        })
      })
      if (res && res.confirm) this._clearPendingSubmission(submission.requestId)
      return false
    }

    const res = await new Promise(resolve => {
      wx.showModal({
        title: '发现待确认交卷',
        content: '上次交卷可能已被服务器保存。继续确认会复用原答案和 request_id，不会重复计入记录。',
        confirmText: '继续确认',
        cancelText: '稍后处理',
        success: resolve,
        fail: () => resolve({ confirm: false }),
      })
    })
    if (!res || !res.confirm || !this._pageAlive) return false

    this._resetSession()
    this._practiceSession.submissionSnapshot = submission
    this._practiceSession.requestId = submission.requestId || ''
    this._practiceSession.traceId = submission.traceId || ''
    this.setData({ started: true, submitted: false, submitting: false })
    await this.doSubmit(true)
    if (!this.data.submitted && this._pageAlive) {
      // A recovery request can still fail due to network/5xx. Return to the
      // setup shell instead of leaving an empty started runner; startPractice
      // will offer the same persisted snapshot again.
      this.setData({ started: false })
      return false
    }
    return true
  },

  _openSubmittedResult(resultUrl, submission) {
    if (!resultUrl || !this._pageAlive) return

    // If both result-cache and pending-submission persistence failed, redirecting
    // would destroy the only in-memory copy that can render the full review. Try
    // the compact result cache once more and stay on this page if storage is still
    // unavailable.
    if (submission && submission.keepPendingUntilResult && !submission.pendingPersisted) {
      try {
        if (!this._submittedResultPayload) throw new Error('missing in-memory result payload')
        wx.setStorageSync('lastPracticeResult', this._submittedResultPayload)
        submission.keepPendingUntilResult = false
      } catch (storageError) {
        console.warn('结果缓存与待确认快照均不可持久化', storageError)
        wx.showModal({
          title: '已交卷，但无法保存复盘数据',
          content: '服务器已保存本次成绩，但当前设备存储异常。请先不要关闭小程序，清理可用存储后再次点击“交卷复盘”。',
          showCancel: false,
          confirmText: '知道了',
        })
        return
      }
    }

    this._pendingResultUrl = resultUrl
    wx.redirectTo({
      url: resultUrl,
      success: () => {
        if (!submission || !submission.keepPendingUntilResult) {
          this._clearPendingSubmission(submission && submission.requestId)
        }
        if (this._practiceSession && this._practiceSession.submissionSnapshot === submission) {
          this._practiceSession.submissionSnapshot = null
        }
        this._pendingResultUrl = ''
      },
      fail: (err) => {
        console.error('结果页打开失败', err)
        if (!this._pageAlive) return
        this.setData({ submitting: false, submitted: true })
        this._setPracticeUnloadGuard(false)
        wx.showModal({
          title: '已交卷，结果页打开失败',
          content: submission && submission.pendingPersisted
            ? '本次练习已经提交成功，不会再次交卷。请再次点击底部“交卷复盘”按钮重新打开结果页；待确认状态已保存，可稍后恢复。'
            : '本次练习已经提交成功，不会再次交卷。当前恢复快照未能写入设备，请保持本页并再次点击“交卷复盘”。',
          showCancel: false,
          confirmText: '知道了',
        })
      },
    })
  },

  onShow() {
    // 切后台 / 跳转他页回来后，把离开期间从刷题时长中扣除。
    // 页面级 onHide 在微信切后台与本页被覆盖时都会触发，因此不需要额外的
    // app 级监听；first onShow（onLoad 之后）时 activeStartedMonoMs 仍为 0，不会误扣。
    const s = this._practiceSession
    if (s && s.activeStartedMonoMs && s._backgroundStartedMonoMs !== null) {
      s.backgroundMs = (s.backgroundMs || 0) + (_monotonicNow() - s._backgroundStartedMonoMs)
      s._backgroundStartedMonoMs = null
    }
    if (s && s.activeStartedMonoMs && this.data.started && !this.data.loading && !this.data.submitting && !s.submissionSnapshot) {
      s.currentQuestionStartedMonoMs = _monotonicNow()
    }
  },

  onHide() {
    // 记录离开时间点；onShow 回来时结算 backgroundMs。
    const s = this._practiceSession
    if (s && s.activeStartedMonoMs && s._backgroundStartedMonoMs === null) {
      if (this.data.started && !this.data.loading && !this.data.submitting && !s.submissionSnapshot) {
        this._settleQuestionTime(true)
      }
      s._backgroundStartedMonoMs = _monotonicNow()
    }
  },

  async onReady() {
    if (config.DEV) console.log('[LAYER6_ONREADY]', Date.now())
    this.setData({ enableMathImage: config.enableMathImage || false })
    const recoveryHandled = await this._offerPendingSubmissionRecovery()
    if (!recoveryHandled && this._pageAlive) this.loadPracticeSubjects()
  },

  /* ==================== 设置阶段 ==================== */

  async loadPracticeSubjects() {
    const requestSeq = ++this._subjectsRequestSeq
    try {
      const res = await api.get('/practice/subjects')
      if (!this._pageAlive || requestSeq !== this._subjectsRequestSeq) return
      const subjectTree = this.normalizeSubjectTree(res || [])
      this.setData({ subjectTree })
      this.initDefaultSubject(subjectTree)
    } catch (e) {
      if (!this._pageAlive || requestSeq !== this._subjectsRequestSeq) return
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

    // 小程序选择器采用“根科目 + 展开的后代列表”的两层视觉结构，但数据层
    // 支持任意层级。把每个根节点的所有后代预先展平，保留 depth/has_children，
    // 这样三级及更深科目也能被选择，同时中间节点仍可作为“全部范围”。
    const flattenDescendants = (node, depth, out) => {
      const children = Array.isArray(node.children) ? node.children : []
      children.forEach((child) => {
        const hasChildren = Array.isArray(child.children) && child.children.length > 0
        out.push({
          subject_id: Number(child.subject_id),
          display_name: hasChildren ? `${child.display_name}（全部）` : child.display_name,
          raw_display_name: child.display_name,
          parent_id: child.parent_id,
          level: child.level,
          has_children: hasChildren,
          depth,
          indent_rpx: Math.max(0, depth - 1) * 28,
        })
        flattenDescendants(child, depth + 1, out)
      })
    }
    parentItems.forEach((root) => {
      const flatChildren = []
      flattenDescendants(root, 1, flatChildren)
      root.flat_children = flatChildren
      root.descendant_count = flatChildren.length
    })
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
    ;(subjectTree || []).forEach((root) => {
      const rootId = Number(root.subject_id)
      const visit = (node) => {
        const children = Array.isArray(node.children) ? node.children : []
        // 叶子优先，保持首次进入时优先落到“具体可顺序刷”的科目。
        children.forEach(visit)
        result.push({
          subject_id: Number(node.subject_id),
          display_name: children.length > 0 ? `${node.display_name}（全部）` : node.display_name,
          parent_subject_id: rootId,
          has_children: children.length > 0,
        })
      }
      const children = Array.isArray(root.children) ? root.children : []
      children.forEach(visit)
      result.push({
        subject_id: rootId,
        display_name: children.length > 0 ? `${root.display_name}（全部）` : root.display_name,
        parent_subject_id: rootId,
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
      const root = tree[i]
      if (Number(root.subject_id) === id) return Number(root.subject_id)
      const stack = (root.children || []).slice()
      while (stack.length) {
        const node = stack.pop()
        if (Number(node.subject_id) === id) return Number(root.subject_id)
        if (Array.isArray(node.children)) stack.push(...node.children)
      }
    }
    return null
  },

  _subjectHasChildren(subjectId) {
    const id = Number(subjectId)
    const tree = this.data.subjectTree || []
    const stack = tree.slice()
    while (stack.length) {
      const node = stack.pop()
      if (Number(node.subject_id) === id) {
        return Array.isArray(node.children) && node.children.length > 0
      }
      if (Array.isArray(node.children)) stack.push(...node.children)
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
    const hasChildren = ds.hasChildren === true || ds.hasChildren === 'true'
    if (!subjectId || !subjectName) return
    this._selectSubject(subjectId, subjectName, this._findParentSubjectId(subjectId), hasChildren)
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
    if (this.data.loading || this.data.submitting) return
    if (this._readPendingSubmission()) {
      await this._offerPendingSubmissionRecovery()
      if (this._readPendingSubmission()) return
    }
    if (!this.data.selectedSubjectId) {
      this.openSubjectSheet()
      return
    }
    if (this.data.selectedMode === 'sequential' && this.data.selectedSubjectHasChildren) {
      wx.showToast({ title: '顺序练习仅支持具体科目', icon: 'none' })
      return
    }
    const traceId = api.createTraceId()
    this._submittedResultPayload = null
    this._resetSession()
    this._practiceSession.traceId = traceId
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
      sequentialProgress: null,
      feedbackVisible: false,
      feedbackType: '',
      feedbackTitle: '',
      feedbackDetail: '',
      feedbackComboText: '',
    })
    this._flushPendingRecentSubject()
    await this._loadQuestions()
  },

  _startTimer() {
    this._clearTimer()
    this._timer = setInterval(() => {
      if (!this._pageAlive || !this._practiceSession.activeStartedMonoMs) return
      const now = _monotonicNow()
      const backgroundMs = (this._practiceSession.backgroundMs || 0) + (
        this._practiceSession._backgroundStartedMonoMs !== null
          ? Math.max(0, now - this._practiceSession._backgroundStartedMonoMs)
          : 0
      )
      const sec = Math.max(0, Math.floor((now - this._practiceSession.activeStartedMonoMs - backgroundMs) / 1000))
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

  _setPracticeUnloadGuard(enabled, message) {
    try {
      if (enabled && wx.enableAlertBeforeUnload) {
        wx.enableAlertBeforeUnload({
          message: message || '当前练习尚未交卷，退出将丢失本组作答。',
        })
      } else if (!enabled && wx.disableAlertBeforeUnload) {
        wx.disableAlertBeforeUnload()
      }
    } catch (e) {
      // 低版本基础库不支持该能力时，仍保留页面内自定义退出确认。
    }
  },

  async _loadQuestions() {
    const loadSeq = ++this._questionsRequestSeq
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
        _traceId: this._practiceSession.traceId,
      }
      if (mode === 'sequential') {
        // 顺序模式由后端维护独立的题库进度，不参与 Leitner / 近期去重。
        // 即使未来公共接口默认值变化，也明确告诉后端这里要严格顺序取题。
        params.exclude_answered = false
        params.use_leitner = false
      } else {
        params.exclude_answered = true
        params.no_repeat_days = 30
        params.use_leitner = true
      }
      // smart 策略由后端统一解析（默认 weakness_vector，并可被实验配置覆盖）。
      // 小程序不再强制 scored，避免绕过 pgvector 召回链路。
      const res = await api.get('/practice/questions', params)
      if (!this._pageAlive || loadSeq !== this._questionsRequestSeq) return
      const questions = adapter.applyAnsweredFlags(res.questions || [], {}, 'id')
      const sequentialProgress = mode === 'sequential'
        ? (res.sequential_progress || null)
        : null
      this.setData({ sequentialProgress })

      // 顺序模式完成一整轮后不自动绕回第一题，避免用户无感重复刷。
      // 由用户显式确认“重新开始一轮”，后端写入 reset marker 后再从头推进。
      if (
        mode === 'sequential' &&
        questions.length === 0 &&
        sequentialProgress &&
        sequentialProgress.cycle_completed
      ) {
        const total = Number(sequentialProgress.total_questions || 0)
        const name = this.data.selectedSubjectName || String(subjectId)
        this._clearTimer()
        this.setData({
          loading: false,
          started: false,
          questions: [],
          totalQuestions: 0,
          currentQuestion: null,
          currentAnswerState: null,
        })

        const restart = await this._showSubmitConfirm({
          scenario: 'info',
          eyebrow: 'ROUND COMPLETE',
          title: '本轮顺序刷题已完成',
          message: `「${name}」本轮 ${total} 题已全部完成。\n重新开始后会从第一道题按顺序再刷一轮。`,
          confirmText: '重新开始一轮',
          cancelText: '返回选题',
        })
        if (!this._pageAlive || loadSeq !== this._questionsRequestSeq) return
        if (!restart) return

        try {
          await api.post('/practice/sequential/reset', {
            subject_id: subjectId,
            _traceId: this._practiceSession.traceId,
          })
          if (!this._pageAlive || loadSeq !== this._questionsRequestSeq) return
        } catch (resetErr) {
          if (!this._pageAlive || loadSeq !== this._questionsRequestSeq) return
          console.error('重置顺序刷题进度失败', resetErr)
          this.setData({ errorText: '重置顺序进度失败，请稍后重试' })
          wx.showToast({ title: '重置进度失败', icon: 'none' })
          return
        }

        // 新一轮等首题真正展示后再开始计时；题目接口等待不计入学习时长。
        this._practiceSession.activeStartedMonoMs = 0
        this._practiceSession.startedAtMs = 0
        this._practiceSession.backgroundMs = 0
        this._practiceSession._backgroundStartedMonoMs = null
        this.setData({
          started: true,
          errorText: '',
          sequentialProgress: null,
        })
        await this._loadQuestions()
        return
      }

      debugLog(this._practiceSession.traceId, 'STATE_AFTER_API', {
        total: questions.length,
        responseTraceId: res.trace_id,
      })
      saveDebugSnapshot(this._practiceSession.traceId, 'state_after_api', {
        total: questions.length,
        questionIds: questions.map(q => q.id),
      })
      this._practiceSession.comboCount = 0
      // 推荐批次 request_id 只用于 recommendation_logs 归因；不要复用为
      // 交卷幂等 key，否则推荐链路与提交重试语义被耦合。
      this._practiceSession.recommendationRequestId = res.request_id || ''
      this._practiceSession.batchToken = res.batch_token || ''
      this._practiceSession.batchMode = res.mode || mode
      if (res.submission_request_id) this._practiceSession.requestId = res.submission_request_id
      if (questions.length > 0 && (!this._practiceSession.batchToken || !this._practiceSession.requestId)) {
        throw new Error('服务器未返回可提交的练习批次凭据')
      }

      // Start image decoding before the first question enters the view. The
      // current question gets highest priority; adjacent questions warm in the
      // background so swiping does not wait on the network.
      if (questions.length > 0) this._warmQuestionImages(questions, 0)

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
        // 首题已完成解析并进入页面后才开始计时，排除首次拉题/渲染等待。
        if (!this._practiceSession.activeStartedMonoMs) {
          this._practiceSession.activeStartedMonoMs = _monotonicNow()
          this._practiceSession.startedAtMs = api.now()
          this._practiceSession.backgroundMs = 0
          this._practiceSession._backgroundStartedMonoMs = null
          this._practiceSession.elapsedSec = 0
        }
        this._practiceSession.optionKeys = viewModelResult.optionKeys
        this._practiceSession.currentQuestionStartedMonoMs = _monotonicNow()
        this._setPracticeUnloadGuard(true)
        this._startTimer()
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
      if (!this._pageAlive || loadSeq !== this._questionsRequestSeq) return
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

  _warmQuestionImages(questions, index) {
    if (!Array.isArray(questions) || !questions.length) return
    const current = questions[index]
    if (!current || typeof adapter.getQuestionPrefetchUrls !== 'function') return

    const currentId = String(current.id == null ? '' : current.id)
    const currentUrls = adapter.getQuestionPrefetchUrls(current)
    if (currentUrls.length) {
      questionImageCache.preloadMany(currentUrls, 3).then(() => {
        // Once decoded, refresh only if the user is still on the same question.
        // forceRebuild makes stem/option URLs re-resolve to wx local temp paths.
        if (!this._pageAlive || this.data.currentIndex !== index) return
        const visible = this.data.questions[index]
        if (!visible || String(visible.id == null ? '' : visible.id) !== currentId) return
        try {
          const refreshed = this._buildQuestionViewModel(visible, true)
          if (!refreshed) return
          this._practiceSession.optionKeys = refreshed.optionKeys
          this.setData({
            currentQuestion: refreshed.question,
            currentAnswerState: refreshed.answerState,
          })
        } catch (err) {
          if (config.DEV) console.warn('[practice] image cache refresh failed', err)
        }
      })
    }

    // Warm the next two questions first (normal forward navigation), plus the
    // previous question for back-swipes. Pending/cache entries deduplicate work.
    const neighborIndexes = [index + 1, index + 2, index - 1]
    const neighborUrls = []
    for (let i = 0; i < neighborIndexes.length; i++) {
      const q = questions[neighborIndexes[i]]
      if (!q) continue
      const urls = adapter.getQuestionPrefetchUrls(q)
      for (let j = 0; j < urls.length; j++) neighborUrls.push(urls[j])
    }
    if (neighborUrls.length) questionImageCache.preloadMany(neighborUrls, 2)
  },

  _settleQuestionTime(pause) {
    const { currentIndex, questions } = this.data
    const { currentQuestionStartedMonoMs, questionTimeMap } = this._practiceSession
    if (!currentQuestionStartedMonoMs || !questions.length) return
    const q = questions[currentIndex]
    if (!q) return
    const elapsed = Math.max(0, Math.floor((_monotonicNow() - currentQuestionStartedMonoMs) / 1000))
    const key = String(q.id)
    const map = { ...questionTimeMap }
    map[key] = (map[key] || 0) + elapsed
    this._practiceSession.questionTimeMap = map
    this._practiceSession.currentQuestionStartedMonoMs = pause ? 0 : _monotonicNow()
  },

  _showQuestion(index) {
    // 结算上一题的用时
    this._settleQuestionTime()

    const q = this.data.questions[index]
    if (!q) return
    this._warmQuestionImages(this.data.questions, index)
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
    this._practiceSession.currentQuestionStartedMonoMs = _monotonicNow()
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

    const submission = this._practiceSession && this._practiceSession.submissionSnapshot
    if (this.data.submitted && this._pendingResultUrl && submission) {
      this._openSubmittedResult(this._pendingResultUrl, submission)
      return
    }

    const hasPendingSubmit = !!submission
    const retryBlocked = !!(submission && submission.retryBlocked)
    const confirmed = await this._showSubmitConfirm({
      scenario: 'danger',
      eyebrow: hasPendingSubmit ? 'SUBMISSION PENDING' : 'EXIT PRACTICE',
      title: retryBlocked ? '退出本组练习？' : (hasPendingSubmit ? '退出待确认交卷？' : '退出本组练习？'),
      message: retryBlocked
        ? '服务器已明确拒绝本次提交，本地待确认状态会保留到你清除或重新进入处理。'
        : (hasPendingSubmit
          ? '本次交卷状态尚未确认。退出不会撤销服务器上可能已经保存的结果；待确认提交会保留，可下次继续确认。'
          : '退出后，本组尚未提交的练习不会计入结果。'),
      confirmText: hasPendingSubmit ? '退出页面' : '退出练习',
      cancelText: retryBlocked ? '返回查看' : (hasPendingSubmit ? '继续确认' : '继续作答'),
    })
    if (!confirmed) return
    if (!this._pageAlive) return
    this._setPracticeUnloadGuard(false)
    this._questionsRequestSeq++
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

  _isSubmissionLocked() {
    if (!this._practiceSession || !this._practiceSession.submissionSnapshot) return false
    const submission = this._practiceSession.submissionSnapshot
    wx.showToast({
      title: submission.serverAccepted
        ? '本次已交卷，请查看结果'
        : (submission.retryBlocked ? '提交已被拒绝，请退出后重试' : '交卷内容已锁定，请确认提交'),
      icon: 'none',
    })
    return true
  },

  selectOption(e) {
    if (this.data.submitted || this._isSubmissionLocked()) return
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
    const answered = !!answeredFlags[key]
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
    if (this.data.submitted || this._isSubmissionLocked()) return
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
    const answered = !!answeredFlags[key]
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

    let submission = this._practiceSession.submissionSnapshot
    if (this.data.submitted && this._pendingResultUrl && submission) {
      this._openSubmittedResult(this._pendingResultUrl, submission)
      return
    }
    if (submission && submission.retryBlocked) {
      wx.showModal({
        title: '本次提交无法继续重试',
        content: '服务器已明确拒绝该提交，继续使用相同内容重试不会成功。请退出本组练习后重新开始。',
        showCancel: false,
        confirmText: '知道了',
      })
      return
    }

    const questions = this.data.questions || []

    // The first submit attempt freezes one immutable submission. Network/5xx
    // retries and process-recovery retries must reuse the exact same payload.
    if (!submission) {
      const selectedSubjectId = this.data.selectedSubjectId
      const selectedSubjectName = this.data.selectedSubjectName
      const answerMap = this._practiceSession.answerMap
      const activeStartedMonoMs = this._practiceSession.activeStartedMonoMs
      const comboCount = this._practiceSession.comboCount
      const total = questions.length || 0
      const answeredFlags = adapter.buildAnsweredFlags(questions, answerMap, 'id')
      const answeredCount = adapter.countAnswered(answeredFlags)
      const completedQuestions = questions.filter(function(q) {
        return answeredFlags[String(q.id)]
      })
      const partialQuestionIds = questions
        .filter(function(q) {
          const key = String(q.id)
          return !answeredFlags[key] && adapter.isMultiBlankChoice(q) && !!answerMap[key]
        })
        .map(function(q) { return q.id })
      const skippedQuestionIds = questions
        .filter(function(q) { return !answeredFlags[String(q.id)] })
        .map(function(q) { return q.id })
      const unanswered = total - answeredCount

      if (answeredCount === 0 && partialQuestionIds.length === 0) {
        wx.showToast({ title: '请至少完成或填写 1 题再提交', icon: 'none' })
        return
      }

      var confirmed = false
      if (unanswered > 0) {
        confirmed = await this._showSubmitConfirm({
          scenario: 'unanswered',
          title: `还有 ${unanswered} 题未完成`,
          message: '现在交卷会将未完成题记为跳过。',
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
      this._settleQuestionTime(true)

      const finishedMonoMs = _monotonicNow()
      const finishedAtMs = api.now()
      const duration = Math.max(0, Math.floor(
        (finishedMonoMs - activeStartedMonoMs - (this._practiceSession.backgroundMs || 0)) / 1000,
      ))
      const requestId = this._practiceSession.requestId || ('req_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8))
      this._practiceSession.requestId = requestId
      const recommendationRequestId = this._practiceSession.recommendationRequestId || null
      const questionTimeMap = this._practiceSession.questionTimeMap
      const answers = completedQuestions.map(q => ({
        question_id: q.id,
        user_answer: answerMap[String(q.id)] || '',
        used_time: questionTimeMap[String(q.id)] || 0,
        request_id: recommendationRequestId,
      }))
      const session = {
        request_id: requestId,
        subject_id: selectedSubjectId,
        mode: this._practiceSession.batchMode || this.data.selectedMode || 'random',
        started_at: new Date(this._practiceSession.startedAtMs || (finishedAtMs - duration * 1000)).toISOString(),
        finished_at: new Date(finishedAtMs).toISOString(),
        duration_sec: duration,
        question_count: total,
        answered_count: answeredCount,
        status: 'completed',
      }
      const recoveryQuestions = questions.map(function(q) {
        const stem = (q && q.content && (q.content.stem || q.content.text)) || (q && q.stem) || ''
        return {
          id: q && q.id,
          subject_id: q && q.subject_id,
          subject_code: (q && q.subject_code) || '',
          subject_name: (q && q.subject_name) || '',
          question_type: (q && q.question_type) || '',
          content: (q && q.content) || {},
          options: (q && q.options) || null,
          image_url: (q && q.image_url) || null,
          knowledge_points: (q && q.knowledge_points) || [],
          difficulty: (q && q.difficulty) || 3,
          stem: String(stem || ''),
        }
      }).filter(function(q) { return !!q.id })

      if (!this._practiceSession.batchToken) {
        wx.showModal({
          title: '练习批次已失效',
          content: '当前题目缺少服务器签发的提交凭据，请返回重新获取题目。',
          showCancel: false,
          confirmText: '知道了',
        })
        return
      }

      submission = {
        requestId,
        traceId: this._practiceSession.traceId || '',
        answers,
        skippedQuestionIds: skippedQuestionIds.slice(),
        partialQuestionIds: partialQuestionIds.slice(),
        session,
        duration,
        total,
        unanswered,
        selectedSubjectId,
        selectedSubjectName,
        comboCount,
        answerMap: Object.assign({}, answerMap),
        answeredFlags: Object.assign({}, answeredFlags),
        recoveryQuestions,
        batchToken: this._practiceSession.batchToken || '',
        retryBlocked: false,
        serverAccepted: false,
        pendingPersisted: false,
        keepPendingUntilResult: false,
      }
      this._practiceSession.submissionSnapshot = submission
      submission.pendingPersisted = this._persistPendingSubmission(submission, 'pending', '')
      this._setPracticeUnloadGuard(
        true,
        '本次交卷状态尚未确认。退出不会撤销服务器上可能已经保存的结果。',
      )
    } else {
      this._clearTimer()
      submission.pendingPersisted = this._persistPendingSubmission(submission, 'pending', '') || submission.pendingPersisted
    }

    this.setData({ submitting: true })

    let submitResult
    try {
      const submitPayload = {
        answers: submission.answers,
        skipped_question_ids: submission.skippedQuestionIds,
        session: submission.session,
        _traceId: submission.traceId || this._practiceSession.traceId,
      }
      submitPayload.batch_token = submission.batchToken
      submitResult = await api.post('/practice/batch-submit', submitPayload)
      if (!this._pageAlive) return
    } catch (e) {
      if (!this._pageAlive) return
      console.error('提交失败', e)
      this._practiceSession.currentQuestionStartedMonoMs = 0
      this.setData({ submitting: false })

      const statusCode = Number(e && e.statusCode) || 0
      const errorCode = String((e && e.code) || '')
      const deterministicReject = (
        errorCode === 'PRACTICE_SUBMISSION_CONFLICT' ||
        errorCode === 'PRACTICE_QUESTION_VERSION_CONFLICT' ||
        errorCode === 'PRACTICE_BATCH_INVALID' ||
        errorCode === 'PRACTICE_PAYLOAD_INVALID' ||
        (statusCode >= 400 && statusCode < 500 && ![401, 408, 429].includes(statusCode))
      )

      if (deterministicReject) {
        submission.retryBlocked = true
        submission.pendingPersisted = this._persistPendingSubmission(submission, 'blocked', '') || submission.pendingPersisted
        this._setPracticeUnloadGuard(false)
        let rejectTitle = '交卷内容未通过校验'
        let rejectContent = '服务器已明确拒绝本次提交，继续重试相同内容不会成功。请退出后重新开始。'
        if (errorCode === 'PRACTICE_SUBMISSION_CONFLICT') {
          rejectTitle = '交卷标识冲突'
          rejectContent = '该 request_id 已对应另一份提交。为避免结果串单，本次内容不会继续重试，请退出后重新开始。'
        } else if (errorCode === 'PRACTICE_QUESTION_VERSION_CONFLICT') {
          rejectTitle = '题目版本无法恢复'
          rejectContent = '本组练习中有题目的历史版本无法恢复。为避免使用错误版本判题，本次提交已停止，请返回重新获取题目。'
        } else if (errorCode === 'PRACTICE_BATCH_INVALID') {
          rejectTitle = '练习批次已失效'
          rejectContent = '本次题目批次已过期或与提交内容不一致。为避免串题，请退出后重新获取题目。'
        }
        wx.showModal({
          title: rejectTitle,
          content: rejectContent,
          showCancel: false,
          confirmText: '知道了',
        })
      } else {
        const persisted = this._persistPendingSubmission(submission, 'pending', '')
        submission.pendingPersisted = persisted || submission.pendingPersisted
        this._setPracticeUnloadGuard(
          true,
          '本次交卷状态尚未确认。退出不会撤销服务器上可能已经保存的结果。',
        )
        wx.showModal({
          title: '交卷结果未确认',
          content: submission.pendingPersisted
            ? '已保存本次交卷快照。请重试确认；即使小程序被关闭，下次进入也可使用同一 request_id 恢复，不会重复计入答题记录。'
            : '当前设备未能保存恢复快照。当前页面内仍可使用同一 request_id 重试，但请勿关闭小程序，否则无法保证恢复本次交卷状态。',
          showCancel: false,
          confirmText: '知道了',
        })
      }
      return
    }

    submission.serverAccepted = true
    submission.retryBlocked = false
    const snapshotAnswerMap = submission.answerMap || {}
    const snapshotAnsweredFlags = submission.answeredFlags || {}
    const total = Number(submission.total) || 0
    const unanswered = Number(submission.unanswered) || 0
    const selectedSubjectId = submission.selectedSubjectId
    const selectedSubjectName = submission.selectedSubjectName
    const duration = Number(submission.duration) || 0
    const comboCount = Number(submission.comboCount) || 0

    // ═══════════════════════════════════════════════════
    // 阶段二：本地结果缓存 — 失败不阻断已完成的服务端提交
    // ═══════════════════════════════════════════════════
    const partialQuestionIdSet = {}
    ;(submission.partialQuestionIds || []).forEach(function(id) { partialQuestionIdSet[String(id)] = true })
    let storedResults = (submitResult.results || []).map(function(rr) {
      const questionId = String(rr.question_id)
      const isPartial = rr.status === 'skipped' && partialQuestionIdSet[questionId]
      return Object.assign({}, rr, {
        status: isPartial ? 'partial' : rr.status,
        _local_partial: !!isPartial,
        user_answer: snapshotAnswerMap[questionId] || '',
      })
    })
    var submittedResultMap = {}
    storedResults.forEach(function(rr) { submittedResultMap[String(rr.question_id)] = true })
    const questionSource = questions.length ? questions : (submission.recoveryQuestions || [])
    questionSource.forEach(function(q) {
      if (!q || !q.id || submittedResultMap[String(q.id)] || snapshotAnsweredFlags[String(q.id)]) return
      const isPartial = !!partialQuestionIdSet[String(q.id)]
      storedResults.push({
        question_id: q.id,
        user_answer: snapshotAnswerMap[String(q.id)] || '',
        is_correct: false,
        status: isPartial ? 'partial' : 'skipped',
        _local_partial: isPartial,
        _local_skipped: !isPartial,
      })
    })

    var lightQuestions = []
    for (var qi = 0; qi < questionSource.length; qi++) {
      var qq = questionSource[qi]
      if (qq && qq.id) {
        lightQuestions.push({
          id: qq.id,
          stem: (qq.content && (qq.content.stem || qq.content.text)) || qq.stem || '',
          options: qq.options || null,
          question_type: qq.question_type || '',
        })
      }
    }
    const partialCount = (submission.partialQuestionIds || []).length
    const serverSkippedCount = Number(submitResult.total_skipped ?? unanswered) || 0
    const displaySkippedCount = Math.max(0, serverSkippedCount - partialCount)
    var userId = this._getCurrentUserId()
    var cacheCreatedAt = Date.now()
    var cacheKey = 'pr_' + cacheCreatedAt + '_' + Math.random().toString(36).slice(2, 8)
    const localResultPayload = {
      correct: submitResult.total_correct || 0,
      wrong: submitResult.total_wrong || 0,
      skipped: displaySkippedCount,
      partial: partialCount,
      total,
      subject_id: selectedSubjectId,
      subject_name: selectedSubjectName,
      duration,
      traceId: submitResult.trace_id || submission.traceId || this._practiceSession.traceId,
      results: storedResults,
      questions: lightQuestions,
      comboCount,
      _cacheKey: cacheKey,
      _userId: userId,
      _createdAt: cacheCreatedAt,
    }
    this._submittedResultPayload = localResultPayload
    var resultCacheStored = false
    try {
      wx.setStorageSync('lastPracticeResult', localResultPayload)
      resultCacheStored = true
    } catch (storageError) {
      console.warn('答题已提交成功，但本地结果缓存失败', storageError)
    }

    const resultUrl = [
      `/subpackages/study/practice-result/index`,
      `?correct=${submitResult.total_correct || 0}`,
      `&wrong=${submitResult.total_wrong || 0}`,
      `&skipped=${displaySkippedCount}`,
      `&partial=${partialCount}`,
      `&total=${total}`,
      `&subject_id=${selectedSubjectId}`,
      `&subject_name=${encodeURIComponent(selectedSubjectName || '')}`,
      `&duration=${duration}`,
      `&_ck=${cacheKey}`,
      `&_rid=${encodeURIComponent(submission.requestId || '')}`,
      `&_recover=${resultCacheStored ? '0' : '1'}`,
    ].join('')

    submission.keepPendingUntilResult = !resultCacheStored
    this._pendingResultUrl = resultUrl
    submission.pendingPersisted = this._persistPendingSubmission(submission, 'submitted', resultUrl) || submission.pendingPersisted
    this._setPracticeUnloadGuard(false)
    this.setData({ submitting: false, submitted: true })
    this._openSubmittedResult(resultUrl, submission)
  },

})
