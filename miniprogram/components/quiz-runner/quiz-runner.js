/**
 * quiz-runner component
 *
 * Unified quiz-taking UI used by practice, review-today, and wrong-detail pages.
 *
 * Properties:
 *   mode, title, subtitle, subjectName
 *   questions, currentQuestion, currentIndex, totalCount
 *   answeredCount, progressPercent, elapsedText
 *   readonly, submitted, submitting, showAnswer, showFeedback
 *   submitText, submitDisabled, prevDisabled, nextDisabled
 *
 * Events:
 *   selectoption, selectblankoption, prev, next, jump, submit, toggleanswercard
 */

Component({
  properties: {
    mode: { type: String, value: 'practice' },
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
    showFeedback: { type: Boolean, value: true },

    submitText: { type: String, value: '提交' },
    submitDisabled: { type: Boolean, value: false },
    prevDisabled: { type: Boolean, value: false },
    nextDisabled: { type: Boolean, value: false },

    showMasterButton: { type: Boolean, value: false },

    showSubmitButton: { type: Boolean, value: true },
    swipeEnabled: { type: Boolean, value: true },
    allowSwipeInReadonly: { type: Boolean, value: false },
  },

  data: {
    showSheet: false,
    animClass: '',
    _animating: false,
    _touchX: undefined,
    _touchY: undefined,
    _touchTime: 0,
    _swiped: false,
    _qTypeLabel: '',
  },

  observers: {
    currentQuestion: function (q) {
      if (!q) { this.setData({ _qTypeLabel: '' }); return }
      var label = q._typeLabel || this._typeLabel(q)
      this.setData({ _qTypeLabel: label })
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
    /* ==================== Option selection ==================== */

    selectOption(e) {
      if (this.data._animating || this.data.readonly || this.data.submitted) return
      if (this.data._swiped) { this.data._swiped = false; return }

      this.triggerEvent('selectoption', {
        option: e.currentTarget.dataset.option,
        question: this.data.currentQuestion,
        index: this.data.currentIndex,
      })
    },

    selectBlankOption(e) {
      if (this.data._animating || this.data.readonly || this.data.submitted) return
      if (this.data._swiped) { this.data._swiped = false; return }

      this.triggerEvent('selectblankoption', {
        blankId: e.currentTarget.dataset.blankId,
        option: e.currentTarget.dataset.option,
        question: this.data.currentQuestion,
        index: this.data.currentIndex,
      })
    },

    /* ==================== Navigation ==================== */

    goPrev() {
      if (this.data._animating || this.data.currentIndex <= 0) return
      this._slideTo(this.data.currentIndex - 1, 'right')
    },

    goNext() {
      if (this.data._animating) return
      if (this.data.currentIndex >= this.data.totalCount - 1) return
      this._slideTo(this.data.currentIndex + 1, 'left')
    },

    goQuestion(e) {
      var idx = parseInt(e.currentTarget.dataset.index, 10)
      if (isNaN(idx) || idx < 0 || idx >= this.data.totalCount) return
      if (idx === this.data.currentIndex) return
      this.setData({ showSheet: false })
      this.triggerEvent('jump', { index: idx })
    },

    _slideTo(nextIdx, dir) {
      this.data._animating = true
      this.setData({ animClass: dir === 'left' ? 'slide-out-left' : 'slide-out-right' })
      setTimeout(() => {
        this.triggerEvent(dir === 'left' ? 'next' : 'prev', { index: nextIdx })
        this.setData({ animClass: 'slide-in' })
        setTimeout(() => {
          this.setData({ animClass: '' })
          this.data._animating = false
        }, 120)
      }, 120)
    },

    /* ==================== Swipe ==================== */

    onTouchStart(e) {
      if (!this.data.swipeEnabled || this.data._animating) return
      if (this.data.submitted) return
      if (this.data.readonly && !this.data.allowSwipeInReadonly) return
      var t = e.touches[0]
      this.data._touchX = t.clientX
      this.data._touchY = t.clientY
      this.data._touchTime = Date.now()
      this.data._swiped = false
    },

    onTouchEnd(e) {
      if (!this.data.swipeEnabled || this.data._animating) return
      if (this.data.submitted) return
      if (this.data.readonly && !this.data.allowSwipeInReadonly) return
      if (this.data._touchX === undefined) return

      var t = e.changedTouches[0]
      var dx = t.clientX - this.data._touchX
      var dy = t.clientY - this.data._touchY

      if (Math.abs(dy) > Math.abs(dx) * 1.5) { this.data._touchX = undefined; return }
      if (Math.abs(dx) < 60) { this.data._touchX = undefined; return }

      this.data._swiped = true
      this.data._touchX = undefined

      if (dx < 0) this.goNext()
      else this.goPrev()
    },

    /* ==================== Answer sheet ==================== */

    toggleSheet() {
      this.setData({ showSheet: !this.data.showSheet })
      this.triggerEvent('toggleanswercard')
    },

    closeSheet() {
      this.setData({ showSheet: false })
    },

    /* ==================== Submit ==================== */

    onMaster() {
      if (this.data.readonly) return
      this.triggerEvent('master', {
        question: this.data.currentQuestion,
        index: this.data.currentIndex,
      })
    },

    onSubmit() {
      if (this.data.submitting || this.data.submitDisabled) return
      this.triggerEvent('submit', {
        questions: this.data.questions,
        currentIndex: this.data.currentIndex,
      })
    },

    /* ==================== Utility ==================== */

    noop() {},
  },
})
