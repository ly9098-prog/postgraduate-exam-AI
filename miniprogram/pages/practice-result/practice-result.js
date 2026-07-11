const api = require('../../utils/api')
const { formatInlineMathText } = require('../../utils/math-format')
const {
  toPlainInlineMathText,
  needsRichRender,
  textToHtml,
  cleanStemText,
} = require('../../utils/stem-render')

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

Page({
  data: {
    detailHtmlContainerStyle: 'max-width:100%;overflow-x:hidden;word-break:break-word;overflow-wrap:anywhere;white-space:normal;line-height:1.65;color:#18233A;',
    detailHtmlTagStyle: {
      p: 'color:#18233A;max-width:100%;white-space:normal;word-break:break-word;overflow-wrap:anywhere;line-height:1.65;margin:0;',
      div: 'color:#18233A;max-width:100%;white-space:normal;word-break:break-word;overflow-wrap:anywhere;line-height:1.65;',
      span: 'color:#18233A;max-width:100%;white-space:normal;word-break:break-word;overflow-wrap:anywhere;',
      table: 'max-width:100%;width:100%;table-layout:fixed;word-break:break-word;',
      td: 'word-break:break-word;overflow-wrap:anywhere;white-space:normal;',
      th: 'word-break:break-word;overflow-wrap:anywhere;white-space:normal;',
      pre: 'max-width:100%;white-space:pre-wrap;word-break:break-word;overflow-wrap:anywhere;',
      code: 'white-space:pre-wrap;word-break:break-word;overflow-wrap:anywhere;',
      img: 'max-width:100%;height:auto;',
    },

    /* 核心数据 */
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

    /* 答题详情 */
    results: [],
    showDetail: true,

    /* 视图模型 — 由 _buildResultViewModel 生成 */
    resultLevelClass: '',
    resultTitle: '',
    resultDesc: '',
    nextStepType: '',
    nextStepTitle: '',
    nextStepDesc: '',
    nextStepTag: '',
    shouldShowCelebration: false,

    /* 成长数据 */
    growthTitle: '',
    growthDesc: '',
    growthLevel: '',
    growthExpText: '',
    growthLevelPct: 0,
    /* 庆祝动效 */
    showCelebration: false,
    celebrationTitle: '',
    celebrationDetail: '',
    celebrationMotto: '',
    celebrationRewardText: '',
    celebrationType: 'steady',
  },

  async onLoad(options) {
    const correct = parseInt(options.correct, 10) || 0
    const wrong = parseInt(options.wrong, 10) || 0
    const total = parseInt(options.total, 10) || 0
    const duration = parseInt(options.duration, 10) || 0
    const cacheKey = options._ck || ''
    const passRate = total > 0 ? Math.round(correct / total * 100) : 0
    const answeredCount = correct + wrong

    // 从 storage 读取详细结果，验证缓存匹配
    let results = []
    let stored = null
    try {
      stored = wx.getStorageSync('lastPracticeResult')
      // 验证缓存键和用户 ID：防止跨练习/跨账号读取旧结果
      if (stored) {
        var storedUserId = stored._userId || ''
        var currentUserId = ''
        try {
          var userInfo = wx.getStorageSync('user')
          if (userInfo && userInfo.id) currentUserId = String(userInfo.id)
        } catch (_) {}
        var cacheMatch = cacheKey && stored._cacheKey === cacheKey
        var userMatch = storedUserId && currentUserId && storedUserId === currentUserId
        if (!cacheMatch || !userMatch) {
          stored = null
        }
      }
      if (stored && stored.results) {
        const questions = stored.questions || []
        const questionById = {}
        questions.forEach(function(q) { if (q && q.id) questionById[String(q.id)] = q })
        results = stored.results.map(function(r) {
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

          return {
            ...r,
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
          }
        })
      }
    } catch (_) {}

    const skipped = (stored && stored.skipped) || 0

    // Build compactResults: wrong > skipped > correct, keep original _displayIndex
    const compactResults = []
    const wrongItems = []
    const skippedItems = []
    const correctItems = []
    results.forEach(function(item, index) {
      var compact = Object.assign({}, item, { _displayIndex: index + 1 })
      if (compact._isSkipped) {
        skippedItems.push(compact)
      } else if (compact._isWrong) {
        wrongItems.push(compact)
      } else {
        correctItems.push(compact)
      }
    })
    compactResults.push.apply(compactResults, wrongItems)
    compactResults.push.apply(compactResults, skippedItems)
    compactResults.push.apply(compactResults, correctItems)

    const vm = this._buildResultViewModel(passRate, correct, wrong, total, skipped)
    const celebrationCopy = vm.shouldShowCelebration ? this._celebrationCopy(passRate, correct, wrong, total, answeredCount) : {}

    this.setData({
      correct,
      wrong,
      skipped,
      total,
      answeredCount,
      duration,
      durationText: this._fmt(duration),
      passRate,
      subject: options.subject_id || '',
      subjectDisplay: decodeURIComponent(options.subject_name || '') || '练习',
      results,
      compactResults,
      ...vm,
      ...celebrationCopy,
    })

    if (this.data.shouldShowCelebration) {
      this._showCelebration()
    }
    this._loadGrowth()
  },

  /* ── 视图模型 ── */

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
      shouldShowCelebration: false,
    }

    if (total <= 0) {
      vm.resultLevelClass = 'empty'
      vm.resultTitle = '暂无练习结果'
      vm.resultDesc = '本次没有可统计的答题数据'
      vm.statusText = '未完成'
      vm.statusDesc = '返回练习后再试一次'
      vm.nextStepType = 'start'
      vm.nextStepTitle = '重新开始练习'
      vm.nextStepDesc = '完成一组练习后，这里会生成正确率和答题情况'
      vm.nextStepTag = '未开始'
      vm.shouldShowCelebration = false
      return vm
    }

    // 庆祝动效触发条件：高正确率 或 全小测验满分
    vm.shouldShowCelebration = passRate >= 90 || (total <= 5 && passRate === 100)
    if (wrong > 0 && passRate < 90) {
      vm.shouldShowCelebration = false
    }

    if (passRate >= 90) {
      vm.resultLevelClass = 'excellent'
      vm.resultTitle = '练习完成'
      vm.resultDesc = '这组正确率很高，整体掌握不错'
      vm.statusText = '表现很稳'
      vm.statusDesc = '可以继续保持节奏'
      vm.nextStepType = wrong > 0 ? 'review' : 'continue'
      vm.nextStepTitle = wrong > 0 ? '先复盘少量错题' : '可以继续挑战'
      vm.nextStepDesc = wrong > 0
        ? '本组仍有少量错题，建议先处理后再继续练习'
        : '本组没有明显薄弱点，可以再来一组巩固手感'
      vm.nextStepTag = wrong > 0 ? '推荐' : '继续'
    } else if (passRate >= 70) {
      vm.resultLevelClass = 'good'
      vm.resultTitle = '练习完成'
      vm.resultDesc = '整体掌握较好，但还有可以优化的地方'
      vm.statusText = '完成不错'
      vm.statusDesc = '错题值得复盘'
      vm.nextStepType = wrong > 0 ? 'review' : 'continue'
      vm.nextStepTitle = wrong > 0 ? '建议先复盘错题' : '可以继续练习'
      vm.nextStepDesc = wrong > 0
        ? '把本组错题处理掉，再继续下一组练习'
        : '本组完成情况不错，可以继续保持'
      vm.nextStepTag = wrong > 0 ? '复盘优先' : '继续'
    } else if (passRate >= 50) {
      vm.resultLevelClass = 'normal'
      vm.resultTitle = '练习完成'
      vm.resultDesc = '这组暴露了一些薄弱点'
      vm.statusText = '需要复盘'
      vm.statusDesc = '先看错题更有效'
      vm.nextStepType = 'review'
      vm.nextStepTitle = '优先处理薄弱点'
      vm.nextStepDesc = '建议先查看错题，找出容易失误的知识点'
      vm.nextStepTag = '复盘优先'
    } else {
      vm.resultLevelClass = 'weak'
      vm.resultTitle = '练习完成'
      vm.resultDesc = '本组错题较多，不建议直接继续刷题'
      vm.statusText = '错题较多'
      vm.statusDesc = '先复盘比继续刷题更重要'
      vm.nextStepType = 'review'
      vm.nextStepTitle = '建议立即复盘'
      vm.nextStepDesc = '先把错误原因搞清楚，这次练习才真正有效'
      vm.nextStepTag = '重点'
    }

    // 有 skipped 时补充提示
    if (skipped > 0) {
      vm.resultDesc += ` · ${skipped} 道未作答`
    }

    return vm
  },

  _celebrationCopy(passRate, correct, wrong, total, answeredCount) {
    answeredCount = answeredCount || (correct + wrong)
    const completedPct = total > 0 ? Math.round(answeredCount / total * 100) : 0
    const answeredAccuracy = answeredCount > 0 ? Math.round(correct / answeredCount * 100) : 0
    const detailLines = [`答对 ${correct}/${total} 题`]
    if (answeredCount < total) {
      detailLines.push(`完成率 ${completedPct}%`)
    }
    detailLines.push(answeredCount > 0 ? `已答正确率 ${answeredAccuracy}%` : `正确率 ${passRate}%`)
    const celebrationDetail = detailLines.join(' · ')
    if (passRate >= 80) {
      return {
        celebrationTitle: '高质量挑战完成',
        celebrationDetail,
        celebrationMotto: '这组表现很稳，继续把优势变成习惯',
        celebrationRewardText: `专注星光 +${Math.max(1, correct)}`,
        celebrationType: 'practice',
      }
    }
    if (passRate >= 50) {
      return {
        celebrationTitle: '完成一次有效练习',
        celebrationDetail,
        celebrationMotto: '复盘后再来一组，薄弱点会越来越少',
        celebrationRewardText: `复盘能量 +${Math.max(1, correct)}`,
        celebrationType: 'practice',
      }
    }
    return {
      celebrationTitle: '薄弱点已暴露',
      celebrationDetail,
      celebrationMotto: '先把错题吃透，这次练习就很有价值',
      celebrationRewardText: '错题诊断 +1',
      celebrationType: 'practice',
    }
  },

  /* ── 成长数据 ── */

  async _loadGrowth() {
    try {
      const growth = await api.get('/stats/growth')
      if (!growth) return
      const unlockedBadges = (growth.badges || []).filter(b => b.unlocked).length
      this.setData({
        growthLevel: growth.level_title || 'Lv1 起步',
        growthExpText: `${growth.exp_current || 0} / ${growth.exp_to_next || 0} EXP`,
        growthLevelPct: growth.level_progress_pct || 0,
        growthTitle: `练习经验 +${Math.max(1, this.data.total)}`,
        growthDesc: unlockedBadges > 0
          ? `已点亮 ${unlockedBadges} 个徽章 · ${growth.level_title || ''}`
          : `当前 ${growth.level_title || 'Lv1 起步'} · 继续保持`,
      })
    } catch (_) {}
  },

  /* ── 工具方法 ── */

  _fmt(sec) {
    const s = Math.max(0, sec || 0)
    const m = Math.floor(s / 60)
    const ss = s % 60
    return `${m} 分 ${ss} 秒`
  },

  /* ── 庆祝动效 ── */

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

  /* ── 交互 ── */

  toggleDetail() {
    this.setData({ showDetail: !this.data.showDetail })
  },

  goWrongBook() {
    wx.redirectTo({ url: '/pages/wrong-book/wrong-book' })
  },

  practiceAgain() {
    wx.redirectTo({ url: '/pages/practice/practice' })
  },

  goHome() {
    wx.reLaunch({ url: '/pages/home/home' })
  },
})
