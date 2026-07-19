/**
 * quiz-runner component
 *
 * Unified quiz-taking UI used by practice, review-today, and wrong-detail.
 * The visual language follows the practice setup page: deep ink green,
 * fluorescent lime accents, restrained cards, and large numeric progress.
 */

Component({
  properties: {
    mode: { type: String, value: 'practice' },
    theme: { type: String, value: 'default' },
    title: { type: String, value: '' },
    subtitle: { type: String, value: '' },
    subjectName: { type: String, value: '' },

    questions: { type: Array, value: [] },
    currentQuestion: { type: Object, value: null },
    currentIndex: { type: Number, value: 0 },
    totalCount: { type: Number, value: 0 },

    answeredCount: { type: Number, value: 0 },
    progressPercent: { type: Number, value: 0 },
    elapsedText: { type: String, value: '00:00' },

    readonly: { type: Boolean, value: false },
    submitted: { type: Boolean, value: false },
    submitting: { type: Boolean, value: false },
    showAnswer: { type: Boolean, value: false },
    showFeedback: { type: Boolean, value: false },

    submitText: { type: String, value: '提交' },
    submitDisabled: { type: Boolean, value: false },
    prevDisabled: { type: Boolean, value: false },
    nextDisabled: { type: Boolean, value: false },

    showMasterButton: { type: Boolean, value: false },
    showSubmitButton: { type: Boolean, value: true },
    showBackButton: { type: Boolean, value: false },
    customNavigation: { type: Boolean, value: false },

    swipeEnabled: { type: Boolean, value: true },
    // 仅由需要的页面显式开启：允许从选项区域横滑切题，同时保留轻点选项。
    swipeThroughOptions: { type: Boolean, value: false },
    allowSwipeInReadonly: { type: Boolean, value: false },
    compactReviewMode: { type: Boolean, value: false },

    flowLayout: { type: Boolean, value: false },
    compactBottom: { type: Boolean, value: false },
  },

  data: {
    showSheet: false,
    heroCollapsed: false,
    questionScrollTop: 0,
    animClass: '',
    _animating: false,
    _touchX: undefined,
    _touchY: undefined,
    _touchTime: 0,
    _swipeTapLockUntil: 0,
    _qTypeLabel: '',
    _codeLines: [],
    _mixedBlocks: [],
    _questionImages: [],
    _blankOptionGroups: [],
    _hasBlankOptionGroups: false,
  },

  created: function () {
    this._lastRenderModel = null
  },

  observers: {
    currentQuestion: function (q) {
      if (!q) {
        this.setData({ _qTypeLabel: '', _codeLines: [], _mixedBlocks: [], _questionImages: [], _blankOptionGroups: [], _hasBlankOptionGroups: false })
        this._lastRenderModel = null
        return
      }
      var model = q._renderModel || {}
      // _renderModel reference is stable when only blank selection changes
      var renderModelChanged = this._lastRenderModel !== model
      this._lastRenderModel = model

      var data = {}

      if (renderModelChanged) {
        var label = q._typeLabel || this._typeLabel(q)
        var codeLines = model.mode === 'CODE' ? this._splitCodeLines(model.rawText) : []
        var mixedBlocks = model.mode === 'MIXED' ? this._decorateMixedBlocks(model.blocks) : []

        // Extract image URLs — use adapter for dedup against inline-rendered segments
        var images = []
        var adapter
        try { adapter = require('../../utils/question-runner-adapter') } catch (e) {}
        if (adapter && typeof adapter.computeExtraImages === 'function') {
          images = adapter.computeExtraImages(q)
        } else if (adapter && typeof adapter.getQuestionImages === 'function') {
          images = adapter.getQuestionImages(q)
        } else if (Array.isArray(q.image_url)) {
          images = q.image_url.filter(function (u) { return u && typeof u === 'string' })
        } else if (q.content && Array.isArray(q.content.image_url)) {
          images = q.content.image_url.filter(function (u) { return u && typeof u === 'string' })
        }

        data._qTypeLabel = label
        data._codeLines = codeLines
        data._mixedBlocks = mixedBlocks
        data._questionImages = images
      }

      // Always update blank option groups (change on every selection)
      data._blankOptionGroups = q._blankOptionGroups || []
      data._hasBlankOptionGroups = !!(q._hasBlankOptionGroups && q._blankOptionGroups && q._blankOptionGroups.length > 0)

      this.setData(data)
    },
    currentIndex: function () {
      // 新题回到阅读起点，并恢复紧凑完整顶部；向下阅读后再自动收起。
      var self = this
      this.setData({ heroCollapsed: false, questionScrollTop: 1 }, function () {
        self.setData({ questionScrollTop: 0 })
      })
    },
  },

  methods: {
    _typeLabel: function (q) {
      if (!q) return ''
      if (q._hasBlankOptionGroups || q.question_type === 'multi_blank_choice') return '多空选择题'
      if (q.question_type === 'multiple_choice') return '多选题'
      if (q.question_type === 'true_false' || q.question_type === 'judgement') return '判断题'
      return '单选题'
    },

    _splitCodeLines: function (value) {
      var raw = String(value == null ? '' : value)
        .replace(/\r\n/g, '\n')
        .replace(/\r/g, '\n')
      var parts = raw.split('\n')
      if (!parts.length) parts = ['']
      return parts.map(function (text, index) {
        return { no: index + 1, text: text || ' ' }
      })
    },

    _decorateMixedBlocks: function (blocks) {
      var self = this
      return (Array.isArray(blocks) ? blocks : []).map(function (block) {
        if (!block || block.type !== 'CODE') return block
        return Object.assign({}, block, {
          _codeLines: self._splitCodeLines(block.rawText),
        })
      })
    },

    /* ==================== Option selection ==================== */

    selectOption: function (e) {
      if (this.data._animating || this.data.readonly || this.data.submitted) return
      // 仅拦截滑动结束后紧邻产生的合成 tap，不再吞掉用户随后真正的第一次点击。
      if (this.data._swipeTapLockUntil && Date.now() < this.data._swipeTapLockUntil) return

      this.triggerEvent('selectoption', {
        option: e.currentTarget.dataset.option,
        question: this.data.currentQuestion,
        index: this.data.currentIndex,
      })
    },

    selectBlankOption: function (e) {
      if (this.data._animating || this.data.readonly || this.data.submitted) return
      if (this.data._swipeTapLockUntil && Date.now() < this.data._swipeTapLockUntil) return

      this.triggerEvent('selectblankoption', {
        blankId: e.currentTarget.dataset.blankId,
        option: e.currentTarget.dataset.option,
        question: this.data.currentQuestion,
        index: this.data.currentIndex,
      })
    },

    /* ==================== Navigation ==================== */

    requestExit: function () {
      this.triggerEvent('exit', {
        answeredCount: this.data.answeredCount,
        totalCount: this.data.totalCount,
        currentIndex: this.data.currentIndex,
      })
    },

    goPrev: function () {
      if (this.data._animating || this.data.currentIndex <= 0 || this.data.prevDisabled) return
      this._slideTo(this.data.currentIndex - 1, 'right')
    },

    goNext: function () {
      if (this.data._animating || this.data.nextDisabled) return
      if (this.data.currentIndex >= this.data.totalCount - 1) return
      this._slideTo(this.data.currentIndex + 1, 'left')
    },

    goQuestion: function (e) {
      var idx = parseInt(e.currentTarget.dataset.index, 10)
      if (isNaN(idx) || idx < 0 || idx >= this.data.totalCount) return
      if (idx === this.data.currentIndex) {
        this.setData({ showSheet: false })
        return
      }
      this.setData({ showSheet: false })
      this.triggerEvent('jump', { index: idx })
    },

    _slideTo: function (nextIdx, dir) {
      var self = this
      this.data._animating = true
      this.setData({ animClass: dir === 'left' ? 'slide-out-left' : 'slide-out-right' })
      setTimeout(function () {
        self.triggerEvent(dir === 'left' ? 'next' : 'prev', { index: nextIdx })
        // 新题挂载后立即解除选项点击锁；视觉入场动画继续播放，但不再吞掉第一次作答。
        self.setData({ animClass: 'slide-in' }, function () {
          self.data._animating = false
        })
        setTimeout(function () {
          self.setData({ animClass: '' })
        }, 150)
      }, 110)
    },

    /* ==================== Swipe ==================== */

    onTouchStart: function (e) {
      if (!this.data.swipeEnabled || this.data._animating) return
      if (this.data.submitted) return
      if (this.data.readonly && !this.data.allowSwipeInReadonly) return

      var target = e && e.target ? e.target : {}
      var dataset = target.dataset || {}
      if (dataset.swipeBlock === true || dataset.swipeBlock === 'true' || dataset.swipeBlock === '1') {
        // 新的一次选项触摸是真实用户操作，可立即解除上次 swipe 的合成 tap 锁。
        this.data._swipeTapLockUntil = 0
        this.data._touchX = undefined
        this.data._touchY = undefined
        return
      }

      var t = e.touches && e.touches[0]
      if (!t) return
      this.data._touchX = t.clientX
      this.data._touchY = t.clientY
      this.data._touchTime = Date.now()
    },

    onTouchEnd: function (e) {
      if (!this.data.swipeEnabled || this.data._animating) return
      if (this.data.submitted) return
      if (this.data.readonly && !this.data.allowSwipeInReadonly) return
      if (this.data._touchX === undefined) return

      var t = e.changedTouches && e.changedTouches[0]
      if (!t) return
      var dx = t.clientX - this.data._touchX
      var dy = t.clientY - this.data._touchY

      var absDx = Math.abs(dx)
      var absDy = Math.abs(dy)

      // 只有明确的横向手势才切题：横向至少 44px，且大于纵向位移。
      // 阈值适当降低，保证在选项卡片区域也能自然触发；轻点仍交给选项 tap。
      if (absDx < 44 || absDx <= absDy * 1.10) {
        this.data._touchX = undefined
        this.data._touchY = undefined
        return
      }

      this.data._touchX = undefined
      this.data._touchY = undefined
      // 某些基础库会在 swipe 的 touchend 后补发 tap，只短暂拦截该合成事件。
      this.data._swipeTapLockUntil = Date.now() + 100

      if (dx < 0) this.goNext()
      else this.goPrev()
    },

    onTouchCancel: function () {
      this.data._touchX = undefined
      this.data._touchY = undefined
    },

    onQuestionScroll: function (e) {
      if (this.data.flowLayout || this.data.compactReviewMode) return
      var top = e && e.detail ? Number(e.detail.scrollTop || 0) : 0
      var nextCollapsed = this.data.heroCollapsed ? top > 8 : top > 34
      if (nextCollapsed !== this.data.heroCollapsed) {
        this.setData({ heroCollapsed: nextCollapsed })
      }
    },

    /* ==================== Answer sheet ==================== */

    toggleSheet: function () {
      this.setData({ showSheet: !this.data.showSheet })
      this.triggerEvent('toggleanswercard')
    },

    closeSheet: function () {
      this.setData({ showSheet: false })
    },

    /* ==================== Submit ==================== */

    onMaster: function () {
      if (this.data.readonly) return
      this.triggerEvent('master', {
        question: this.data.currentQuestion,
        index: this.data.currentIndex,
      })
    },

    onSubmit: function () {
      if (this.data.submitting || this.data.submitDisabled) return
      this.triggerEvent('submit', {
        questions: this.data.questions,
        currentIndex: this.data.currentIndex,
      })
    },

    /* ==================== Image preview ==================== */

    previewQuestionImage: function (e) {
      var urls = this.data._questionImages
      var src = e && e.currentTarget && e.currentTarget.dataset && e.currentTarget.dataset.src
      if (!urls || !urls.length) return
      wx.previewImage({ current: src || urls[0], urls: urls })
    },

    /**
     * Preview an option image. Collects all option image URLs from the current
     * question so the user can swipe through them in full-screen mode.
     */
    previewOptionImage: function (e) {
      var src = e && e.currentTarget && e.currentTarget.dataset && e.currentTarget.dataset.src
      if (!src) return
      var cq = this.data.currentQuestion
      var list = cq && cq._optionList
      if (!Array.isArray(list)) { wx.previewImage({ current: src, urls: [src] }); return }
      var seen = {}
      var urls = []
      for (var i = 0; i < list.length; i++) {
        var segs = list[i]._segments
        if (!Array.isArray(segs)) continue
        for (var j = 0; j < segs.length; j++) {
          var url = segs[j] && segs[j].url
          if (url && !seen[url]) { seen[url] = true; urls.push(url) }
        }
      }
      if (!urls.length) urls = [src]
      wx.previewImage({ current: src, urls: urls })
    },

    noop: function () {},
  },
})
