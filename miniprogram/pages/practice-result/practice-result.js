const api = require('../../utils/api')
const { formatInlineMathText } = require('../../utils/math-format')
Page({
  data: {
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
    showDetail: false,

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
    growthBadgeCount: 0,

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
    const passRate = total > 0 ? Math.round(correct / total * 100) : 0
    const answeredCount = correct + wrong

    // 从 storage 读取详细结果
    let results = []
    let stored = null
    try {
      stored = wx.getStorageSync('lastPracticeResult')
      if (stored && stored.results) {
        const questions = stored.questions || []
        const questionById = {}
        questions.forEach(function(q) { if (q && q.id) questionById[String(q.id)] = q })
        results = stored.results.map(function(r) {
          const q = questionById[String(r.question_id)] || {}
          const stemText = (q.content && (q.content.stem || q.content.text || q.content.title || q.content.question)) || q.stem || q.title || q.question || q.text || ''
          return {
            ...r,
            correct_answer: formatInlineMathText(r.correct_answer),
            _label: r.is_correct ? '✓' : '✗',
            _cls: r.is_correct ? 'correct' : 'wrong',
            _stemPreview: stemText ? (stemText.length > 50 ? stemText.slice(0, 50) + '...' : stemText) : '',
            _userAnswer: r.user_answer || '',
            _isWrong: !r.is_correct,
          }
        })
      }
    } catch (_) {}

    const skipped = (stored && stored.skipped) || 0
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
      vm.nextStepType = 'practice'
      vm.nextStepTitle = '去练一组'
      vm.nextStepDesc = '请完成一组练习后查看结果'
      vm.nextStepTag = '开始'
      return vm
    }

    // 庆祝动效触发条件：高正确率 或 全小测验满分
    vm.shouldShowCelebration = passRate >= 80 || (total <= 5 && passRate === 100)

    if (passRate >= 90) {
      vm.resultLevelClass = 'excellent'
      vm.resultTitle = '表现很稳'
      vm.resultDesc = '这组正确率很高，可以继续保持节奏'
      vm.nextStepType = 'continue'
      vm.nextStepTitle = '建议继续挑战'
      vm.nextStepDesc = '可以再来一组，扩大优势题型的熟练度'
      vm.nextStepTag = '继续练习'
    } else if (passRate >= 70) {
      vm.resultLevelClass = 'good'
      vm.resultTitle = '完成得不错'
      vm.resultDesc = '整体掌握较好，建议复盘少量错题'
      vm.nextStepType = 'review'
      vm.nextStepTitle = '建议先复盘错题'
      vm.nextStepDesc = wrong > 0
        ? `本次 ${wrong} 道错题，处理掉再继续下一组`
        : '本组没有错题，可以继续下一组练习'
      vm.nextStepTag = '推荐'
    } else if (passRate >= 50) {
      vm.resultLevelClass = 'normal'
      vm.resultTitle = '还有提升空间'
      vm.resultDesc = '这组暴露了一些薄弱点，复盘价值较高'
      vm.nextStepType = 'review'
      vm.nextStepTitle = '优先处理薄弱点'
      vm.nextStepDesc = `建议先看 ${wrong} 道错题，再开启下一组练习`
      vm.nextStepTag = '复盘优先'
    } else {
      vm.resultLevelClass = 'weak'
      vm.resultTitle = '先别急着下一组'
      vm.resultDesc = `本组错题较多（${wrong}/${total}），建议先集中复盘`
      vm.nextStepType = 'review'
      vm.nextStepTitle = '建议立即复盘'
      vm.nextStepDesc = '先把错题原因搞清楚，这次练习才真正有效'
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
        growthBadgeCount: unlockedBadges,
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
    wx.redirectTo({ url: '/pages/home/home' })
  },
})
