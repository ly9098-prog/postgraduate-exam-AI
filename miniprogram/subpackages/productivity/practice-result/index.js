const api = require('../../../utils/api')
const { safeDecodeURIComponent } = require('../../../utils/route-params')
const { formatInlineMathText } = require('../../../utils/math-format')
const {
  toPlainInlineMathText,
  needsRichRender,
  textToHtml,
  cleanStemText,
} = require('../../../utils/stem-render')

function canonicalForResultStem(text) {
  return String(text || '')
    .replace(/<[^>]+>/g, '')
    .replace(/&nbsp;/gi, ' ')
    .replace(/\s+/g, ' ')
    .replace(/[，。、；：！？,.!?;:]/g, ' ')
    .trim()
}

function dedupeRepeatedResultStem(text) {
  const raw = String(text || '').replace(/\r\n/g, '\n').replace(/\r/g, '\n').trim()
  if (!raw) return ''

  // Handle completely duplicated paragraphs: A\nA
  const lines = raw.split('\n').map(function(s) { return s.trim() }).filter(Boolean)
  if (lines.length >= 2) {
    const half = Math.floor(lines.length / 2)
    const left = lines.slice(0, half).join('\n')
    const right = lines.slice(half).join('\n')
    if (half > 0 && canonicalForResultStem(left) === canonicalForResultStem(right)) {
      return left
    }
  }

  // Deduplicate adjacent repeated lines
  const result = []
  for (let i = 0; i < lines.length; i++) {
    const cur = lines[i]
    const prev = result[result.length - 1]
    if (prev && canonicalForResultStem(prev) === canonicalForResultStem(cur)) {
      continue
    }
    result.push(cur)
  }

  // Handle repeated full text: A + A
  const joined = result.join('\n').trim()
  const canon = canonicalForResultStem(joined)
  const len = joined.length

  for (let cut = Math.floor(len / 2) - 5; cut <= Math.floor(len / 2) + 5; cut++) {
    if (cut <= 0 || cut >= len) continue
    const left = joined.slice(0, cut).trim()
    const right = joined.slice(cut).trim()
    if (left && right && canonicalForResultStem(left) === canonicalForResultStem(right)) {
      return left
    }
  }

  return joined
}

function normalizeResultHtml(html) {
  return String(html || '')
    .replace(/white-space\s*:\s*nowrap;?/gi, 'white-space:normal;')
    .replace(/overflow-x\s*:\s*auto;?/gi, 'overflow-x:hidden;')
}

function buildDetailRichText(value) {
  const raw0 = String(value || '').trim()
  const raw = dedupeRepeatedResultStem(raw0)

  if (!raw) {
    return { raw: '', renderType: 'empty', text: '', html: '' }
  }

  const plain = toPlainInlineMathText(raw)

  if (plain) {
    return { raw, renderType: 'text', text: plain, html: '' }
  }

  if (needsRichRender(raw)) {
    return { raw, renderType: 'html', text: '', html: normalizeResultHtml(textToHtml(raw)) }
  }

  return { raw, renderType: 'text', text: formatInlineMathText(raw), html: '' }
}

/**
 * Build per-blank result view model for multi_blank_choice questions.
 *
 * @param {string} userAnswer - User's answer string (canonical "①:B;②:D" or other format)
 * @param {string} correctAnswer - Correct answer string
 * @param {Array} blankOptionGroups - blank_option_groups from question content
 * @returns {Object|null} view model with blankResults, correctBlankCount, totalBlankCount, or null
 */
function buildBlankResultsViewModel(userAnswer, correctAnswer, blankOptionGroups) {
  if (!blankOptionGroups || !Array.isArray(blankOptionGroups) || blankOptionGroups.length < 2) {
    return null
  }

  // Parse user and correct answers into slot→value maps
  var userMap = normalizeBlankAnswer(userAnswer)
  var correctMap = normalizeBlankAnswer(correctAnswer)

  if (Object.keys(correctMap).length === 0) return null

  var blankResults = []
  var correctBlankCount = 0

  blankOptionGroups.forEach(function (group) {
    var groupId = String((group && group.id) || '').trim()
    var options = (group && group.options) || []

    var userKey = userMap[groupId] || ''
    var correctKey = correctMap[groupId] || ''
    var isAnswered = !!userKey
    var isCorrect = isAnswered && userKey.toUpperCase() === correctKey.toUpperCase()

    // Find option text for user and correct keys
    var userText = ''
    var correctText = ''
    options.forEach(function (opt) {
      var key = String((opt && opt.key) || '').trim().toUpperCase()
      var text = String((opt && opt.text) || '').trim()
      if (key === userKey.toUpperCase()) userText = text
      if (key === correctKey.toUpperCase()) correctText = text
    })

    if (isCorrect) correctBlankCount++

    blankResults.push({
      id: groupId,
      userKey: userKey,
      userText: userText,
      correctKey: correctKey,
      correctText: correctText,
      isCorrect: isCorrect,
      isAnswered: isAnswered,
    })
  })

  return {
    blankResults: blankResults,
    correctBlankCount: correctBlankCount,
    totalBlankCount: blankOptionGroups.length,
  }
}

function normalizeBlankAnswer(answer) {
  if (!answer) return {}
  if (typeof answer === 'object') return answer
  var result = {}
  String(answer).split(/[;；,，、\n]+/).forEach(function(part) {
    var m = part.trim().match(/^(.+?)\s*[:：=]\s*([A-Za-z])$/)
    if (m) result[m[1].trim()] = m[2].trim().toUpperCase()
  })
  if (Object.keys(result).length > 0) return result
  // Fallback: circled digits with letters
  var circledPairs = String(answer).match(/[①-⑳]\s*[A-Za-z]/g)
  if (circledPairs) {
    circledPairs.forEach(function(pair) {
      var m = pair.match(/^([①-⑳])\s*([A-Za-z])$/)
      if (m) result[m[1]] = m[2].toUpperCase()
    })
  }
  return result
}

Page({
  data: {
    detailHtmlContainerStyle: 'max-width:100%;overflow-x:hidden;word-break:break-word;overflow-wrap:anywhere;white-space:normal;line-height:1.65;color:#18231C;',
    detailHtmlTagStyle: {
      p: 'color:#18231C;max-width:100%;white-space:normal;word-break:break-word;overflow-wrap:anywhere;line-height:1.65;margin:0;',
      div: 'color:#18231C;max-width:100%;white-space:normal;word-break:break-word;overflow-wrap:anywhere;line-height:1.65;',
      span: 'color:#18231C;max-width:100%;white-space:normal;word-break:break-word;overflow-wrap:anywhere;',
      table: 'max-width:100%;width:100%;table-layout:fixed;word-break:break-word;',
      td: 'word-break:break-word;overflow-wrap:anywhere;white-space:normal;',
      th: 'word-break:break-word;overflow-wrap:anywhere;white-space:normal;',
      pre: 'max-width:100%;white-space:pre-wrap;word-break:break-word;overflow-wrap:anywhere;',
      code: 'white-space:pre-wrap;word-break:break-word;overflow-wrap:anywhere;',
      img: 'max-width:100%;height:auto;',
    },

    statusBarHeight: 20,
    navBarHeight: 44,

    correct: 0,
    wrong: 0,
    skipped: 0,
    total: 0,
    answeredCount: 0,
    passRate: 0,
    subject: '',
    subjectDisplay: '练习',
    duration: 0,
    durationText: '',
    accuracyRingStyle: '',

    results: [],
    compactResults: [],
    reviewResults: [],
    correctResults: [],
    displayResults: [],
    showAllResults: false,

    resultLevelClass: '',
    resultTitle: '',
    resultDesc: '',
    statusText: '',
    statusDesc: '',
    nextStepType: '',
    nextStepTitle: '',
    nextStepDesc: '',
    nextStepTag: '',

    growthTitle: '',
    growthDesc: '',
    growthLevel: '',
    growthExpText: '',
    growthLevelPct: 0,

    showCelebration: false,
    shouldShowCelebration: false,
    celebrationTitle: '',
    celebrationDetail: '',
    celebrationMotto: '',
    celebrationRewardText: '',
    celebrationType: 'practice',

    resolvingWrong: false,
  },

  async onLoad(options) {
    this._initCustomNavigation()

    const correct = parseInt(options.correct, 10) || 0
    const wrong = parseInt(options.wrong, 10) || 0
    const total = parseInt(options.total, 10) || 0
    const duration = parseInt(options.duration, 10) || 0
    const cacheKey = options._ck || ''
    const passRate = total > 0 ? Math.round(correct / total * 100) : 0
    const answeredCount = correct + wrong

    let results = []
    let stored = null
    try {
      stored = wx.getStorageSync('lastPracticeResult')
      if (stored) {
        var storedUserId = stored._userId || ''
        var currentUserId = ''
        try {
          var userInfo = wx.getStorageSync('user')
          if (userInfo && userInfo.id) currentUserId = String(userInfo.id)
        } catch (_) {}
        var cacheMatch = cacheKey && stored._cacheKey === cacheKey
        var userMatch = storedUserId && currentUserId && storedUserId === currentUserId
        if (!cacheMatch || !userMatch) stored = null
      }

      if (stored && stored.results) {
        const questions = stored.questions || []
        const questionById = {}
        questions.forEach(function (q) {
          if (q && q.id) questionById[String(q.id)] = q
        })

        results = stored.results.map(function (r, index) {
          const q = questionById[String(r.question_id)] || {}
          const stemSource = cleanStemText(
            (q.content && (q.content.stem || q.content.text || q.content.title || q.content.question)) ||
            q.stem || q.title || q.question || q.text || ''
          )
          const stemRaw = dedupeRepeatedResultStem(stemSource)
          const isCorrect = r.is_correct === true
          const isSkipped = !isCorrect && (!r.user_answer || r.user_answer === '')
          const stemRich = buildDetailRichText(stemRaw)
          const userAnswerRich = buildDetailRichText(r.user_answer || '')
          const correctAnswerRich = buildDetailRichText(r.correct_answer || '')
          const wrongRecordId = r.wrong_question_id || r.wrong_id || r.wrong_question_record_id || r.error_record_id || ''

          // Detect multi_blank_choice and build per-blank view model
          var blankOptionGroups = null
          if (q.content && Array.isArray(q.content.blank_option_groups)) {
            blankOptionGroups = q.content.blank_option_groups
          } else if (q.question_type === 'multi_blank_choice' && Array.isArray(q.blank_option_groups)) {
            blankOptionGroups = q.blank_option_groups
          }
          var blankViewModel = blankOptionGroups
            ? buildBlankResultsViewModel(r.user_answer || '', r.correct_answer || '', blankOptionGroups)
            : null

          return {
            ...r,
            _displayIndex: index + 1,
            _cls: isSkipped ? 'skipped' : (isCorrect ? 'correct' : 'wrong'),
            _statusText: isSkipped ? '跳过' : (isCorrect ? '正确' : '错误'),
            _stemRaw: stemRaw,
            _stemRich: stemRich,
            _userAnswerRaw: r.user_answer || '',
            _userAnswerText: userAnswerRich.text || '未作答',
            _userAnswerRich: userAnswerRich,
            _correctAnswerRaw: r.correct_answer || '',
            _correctAnswerText: correctAnswerRich.text,
            _correctAnswerRich: correctAnswerRich,
            _isWrong: !isCorrect,
            _isSkipped: isSkipped,
            _isCorrect: isCorrect,
            _wrongRecordId: wrongRecordId,
            _isMultiBlank: !!blankViewModel,
            _blankViewModel: blankViewModel,
          }
        })
      }
    } catch (_) {}

    const skipped = (stored && stored.skipped) || 0
    const wrongItems = []
    const skippedItems = []
    const correctItems = []
    results.forEach(function (item) {
      if (item._isSkipped) skippedItems.push(item)
      else if (item._isWrong) wrongItems.push(item)
      else correctItems.push(item)
    })
    const reviewResults = wrongItems.concat(skippedItems)
    const compactResults = reviewResults.concat(correctItems)

    const vm = this._buildResultViewModel(passRate, correct, wrong, total, skipped)
    const endDeg = Math.max(0, Math.min(360, Math.round(passRate * 3.6)))
    const accuracyRingStyle = `background: conic-gradient(from -90deg, #AEEF00 0deg ${endDeg}deg, rgba(255,255,255,0.13) ${endDeg}deg 360deg);`

    this.setData({
      correct,
      wrong,
      skipped,
      total,
      answeredCount,
      duration,
      durationText: this._fmt(duration),
      passRate,
      accuracyRingStyle,
      subject: options.subject_id || '',
      subjectDisplay: safeDecodeURIComponent(options.subject_name, '') || '练习',
      results,
      compactResults,
      reviewResults,
      correctResults: correctItems,
      displayResults: reviewResults,
      showAllResults: false,
      ...vm,
    })

    this._loadGrowth()
  },

  _initCustomNavigation() {
    try {
      const info = wx.getWindowInfo ? wx.getWindowInfo() : wx.getSystemInfoSync()
      const statusBarHeight = Number(info.statusBarHeight || 20)
      let navBarHeight = 44
      try {
        const capsule = wx.getMenuButtonBoundingClientRect()
        if (capsule && capsule.height && capsule.top) {
          navBarHeight = (capsule.top - statusBarHeight) * 2 + capsule.height
        }
      } catch (_) {}
      this.setData({
        statusBarHeight: Math.max(20, statusBarHeight),
        navBarHeight: Math.max(40, navBarHeight),
      })
    } catch (_) {
      this.setData({ statusBarHeight: 20, navBarHeight: 44 })
    }
  },

  _buildResultViewModel(passRate, correct, wrong, total, skipped) {
    const vm = {
      resultLevelClass: '',
      resultTitle: '',
      resultDesc: '',
      statusText: '',
      statusDesc: '',
      nextStepType: '',
      nextStepTitle: '',
      nextStepDesc: '',
      nextStepTag: '',
    }

    if (total <= 0) {
      vm.resultLevelClass = 'empty'
      vm.resultTitle = '暂无练习结果'
      vm.resultDesc = '本次没有可统计的答题数据'
      vm.statusText = '未完成'
      vm.statusDesc = '返回练习后再试一次'
      vm.nextStepType = 'start'
      vm.nextStepTitle = '重新开始练习'
      vm.nextStepDesc = '完成一组练习后，这里会生成成绩报告与复盘建议'
      vm.nextStepTag = '未开始'
      return vm
    }

    if (passRate >= 90) {
      vm.resultLevelClass = 'excellent'
      vm.resultTitle = '本组练习完成'
      vm.resultDesc = '整体掌握稳定，可以继续保持当前节奏'
      vm.statusText = '表现很稳'
      vm.statusDesc = wrong > 0 ? '少量错题值得及时处理' : '本组没有明显薄弱点'
      vm.nextStepType = wrong > 0 ? 'review' : 'continue'
      vm.nextStepTitle = wrong > 0 ? '先处理少量错题' : '继续巩固当前优势'
      vm.nextStepDesc = wrong > 0
        ? '复盘本组错题后再进入下一组，知识连接会更牢固。'
        : '可以直接再来一组，保持稳定的答题节奏。'
      vm.nextStepTag = wrong > 0 ? '复盘优先' : '继续'
    } else if (passRate >= 70) {
      vm.resultLevelClass = 'good'
      vm.resultTitle = '本组练习完成'
      vm.resultDesc = '整体掌握较好，部分细节仍有提升空间'
      vm.statusText = '完成不错'
      vm.statusDesc = '错题是下一步重点'
      vm.nextStepType = wrong > 0 ? 'review' : 'continue'
      vm.nextStepTitle = wrong > 0 ? '建议先复盘错题' : '可以继续练习'
      vm.nextStepDesc = wrong > 0
        ? '把本组错误原因处理清楚，再继续下一组练习。'
        : '本组完成情况不错，可以继续保持。'
      vm.nextStepTag = wrong > 0 ? '建议' : '继续'
    } else if (passRate >= 50) {
      vm.resultLevelClass = 'normal'
      vm.resultTitle = '本组练习完成'
      vm.resultDesc = '本组暴露出一些需要补强的知识点'
      vm.statusText = '需要复盘'
      vm.statusDesc = '先看错题更有效'
      vm.nextStepType = 'review'
      vm.nextStepTitle = '优先处理薄弱点'
      vm.nextStepDesc = '建议逐题确认错误原因，避免同类问题重复出现。'
      vm.nextStepTag = '重点'
    } else {
      vm.resultLevelClass = 'weak'
      vm.resultTitle = '本组练习完成'
      vm.resultDesc = '本组错题较多，不建议立刻继续刷题'
      vm.statusText = '错题较多'
      vm.statusDesc = '复盘比追加题量更重要'
      vm.nextStepType = 'review'
      vm.nextStepTitle = '建议立即复盘'
      vm.nextStepDesc = '先把错误原因弄清楚，再通过同类题验证掌握情况。'
      vm.nextStepTag = '优先'
    }

    if (skipped > 0) vm.resultDesc += ` · ${skipped} 道未作答`
    return vm
  },

  async _loadGrowth() {
    try {
      const growth = await api.get('/stats/growth')
      if (!growth) return

      const newBadges = growth.new_badges || growth.newly_unlocked_badges || growth.badges_unlocked_now || []
      const hasNewBadge = Array.isArray(newBadges) ? newBadges.length > 0 : !!newBadges
      const levelUp = growth.level_up === true || growth.just_level_up === true || growth.just_leveled_up === true || growth.level_changed === true

      this.setData({
        growthLevel: growth.level_title || 'Lv1 起步',
        growthExpText: `${growth.exp_current || 0} / ${growth.exp_to_next || 0} EXP`,
        growthLevelPct: Math.max(0, Math.min(100, Number(growth.level_progress_pct) || 0)),
        growthTitle: `成长值 +${Math.max(1, this.data.total)}`,
        growthDesc: growth.level_title ? `当前 ${growth.level_title}` : '持续练习，稳步积累',
      })

      // 仅在后端明确返回“升级/新徽章”事件时展示全屏庆祝。
      if (levelUp || hasNewBadge) {
        const badgeCount = Array.isArray(newBadges) ? newBadges.length : 1
        this.setData({
          shouldShowCelebration: true,
          celebrationTitle: levelUp ? '等级提升' : '解锁新徽章',
          celebrationDetail: levelUp
            ? `已升级至 ${growth.level_title || '新等级'}`
            : `本次解锁 ${badgeCount} 个新徽章`,
          celebrationMotto: '真正的进步，来自每一次认真复盘',
          celebrationRewardText: levelUp ? '成长等级 +1' : `新徽章 +${badgeCount}`,
          celebrationType: 'practice',
        }, () => this._showCelebration())
      }
    } catch (_) {}
  },

  _fmt(sec) {
    const s = Math.max(0, sec || 0)
    const m = Math.floor(s / 60)
    const ss = s % 60
    return `${m}分${ss < 10 ? '0' : ''}${ss}秒`
  },

  _showCelebration() {
    this._clearCelebrationTimer()
    this.setData({ showCelebration: true })
    this._celebrationTimer = setTimeout(() => {
      this.setData({ showCelebration: false })
      this._celebrationTimer = null
    }, 2600)
  },

  dismissCelebration() {
    this._clearCelebrationTimer()
    this.setData({ showCelebration: false })
  },

  onHide() {
    this._clearCelebrationTimer()
    if (this.data.showCelebration) this.setData({ showCelebration: false })
  },

  onUnload() {
    this._clearCelebrationTimer()
  },

  _clearCelebrationTimer() {
    if (this._celebrationTimer) {
      clearTimeout(this._celebrationTimer)
      this._celebrationTimer = null
    }
  },

  toggleAllResults() {
    const next = !this.data.showAllResults
    this.setData({
      showAllResults: next,
      displayResults: next ? this.data.compactResults : this.data.reviewResults,
    })
  },

  goBack() {
    const pages = getCurrentPages()
    if (pages && pages.length > 1) {
      wx.navigateBack()
    } else {
      wx.reLaunch({ url: '/pages/home/home' })
    }
  },

  _resultWrongQuestionIds(targetQuestionId) {
    const target = targetQuestionId == null ? '' : String(targetQuestionId)
    return (this.data.reviewResults || [])
      .filter(function (item) {
        if (!item || item._isSkipped || !item._isWrong) return false
        return !target || String(item.question_id) === target
      })
      .map(function (item) { return String(item.question_id) })
      .filter(Boolean)
  },

  _cachedWrongRecordIds(targetQuestionId) {
    const target = targetQuestionId == null ? '' : String(targetQuestionId)
    return (this.data.reviewResults || [])
      .filter(function (item) {
        if (!item || item._isSkipped || !item._isWrong || !item._wrongRecordId) return false
        return !target || String(item.question_id) === target
      })
      .map(function (item) { return Number(item._wrongRecordId) })
      .filter(Number.isFinite)
  },

  async _resolveWrongRecordIds(targetQuestionId) {
    const cached = this._cachedWrongRecordIds(targetQuestionId)
    if (cached.length > 0) return Array.from(new Set(cached))

    const desiredIds = this._resultWrongQuestionIds(targetQuestionId)
    if (!desiredIds.length) return []

    const desiredMap = {}
    desiredIds.forEach(function (id) { desiredMap[String(id)] = true })

    try {
      const params = { page: 1, page_size: 100 }
      if (this.data.subject) params.subject_id = this.data.subject
      const data = await api.get('/wrong-questions', params)
      const items = (data && data.items) || []
      const ids = []
      items.forEach(function (item) {
        if (!item) return
        const sourceQuestionId = item.question_id || item.original_question_id || item.source_question_id || (item.question && item.question.id)
        if (!sourceQuestionId || !desiredMap[String(sourceQuestionId)]) return
        const recordId = Number(item.id || item.wrong_question_id)
        if (Number.isFinite(recordId)) ids.push(recordId)
      })
      return Array.from(new Set(ids))
    } catch (_) {
      return []
    }
  },

  _openWrongDetail(ids) {
    if (!ids || !ids.length) return false
    try {
      wx.setStorageSync('wrong_detail_nav', { ids, ts: Date.now() })
    } catch (_) {}
    wx.redirectTo({
      url: `/pages/wrong-detail/wrong-detail?id=${ids[0]}&idx=0&source=wrong-book`,
    })
    return true
  },

  async goWrongBook() {
    if (this.data.resolvingWrong) return
    this.setData({ resolvingWrong: true })
    wx.showLoading({ title: '准备错题复盘', mask: true })
    const ids = await this._resolveWrongRecordIds()
    wx.hideLoading()
    this.setData({ resolvingWrong: false })
    if (this._openWrongDetail(ids)) return
    wx.showToast({ title: '错题记录正在同步，已打开错题本', icon: 'none' })
    setTimeout(function () {
      wx.redirectTo({ url: '/pages/wrong-book/wrong-book' })
    }, 500)
  },

  async openWrongAnalysis(e) {
    if (this.data.resolvingWrong) return
    const questionId = e.currentTarget.dataset.questionId
    if (!questionId) return
    this.setData({ resolvingWrong: true })
    wx.showLoading({ title: '加载解析', mask: true })
    const ids = await this._resolveWrongRecordIds(questionId)
    wx.hideLoading()
    this.setData({ resolvingWrong: false })
    if (this._openWrongDetail(ids)) return
    wx.showToast({ title: '该错题解析正在同步', icon: 'none' })
  },

  practiceAgain() {
    wx.redirectTo({ url: '/pages/practice/practice' })
  },

  goHome() {
    wx.reLaunch({ url: '/pages/home/home' })
  },
})
