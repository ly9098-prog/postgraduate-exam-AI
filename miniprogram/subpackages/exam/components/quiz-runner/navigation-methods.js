module.exports = {
  goPrev: function() {
    if (this.data._animating || this.data.currentIndex <= 0 || this.data.prevDisabled) return
    this._slideTo(this.data.currentIndex - 1, 'right')
  },
  goNext: function() {
    if (this.data._animating || this.data.nextDisabled) return
    if (this.data.currentIndex >= this.data.totalCount - 1) return
    this._slideTo(this.data.currentIndex + 1, 'left')
  },
  goQuestion: function(e) {
    if (this.data._animating) return
    var idx = parseInt(e.currentTarget.dataset.index, 10)
    if (isNaN(idx) || idx < 0 || idx >= this.data.totalCount) return
    if (idx === this.data.currentIndex) {
      this.setData({ showSheet: false })
      return
    }
    this.setData({ showSheet: false })
    this._slideTo(idx, idx > this.data.currentIndex ? 'left' : 'right', 'jump')
  },
  onQuestionAnimationEnd: function(e) {
    var name = e && e.detail && e.detail.animationName
    if (this._switchPhase === 'enter' && (name === 'runnerQuestionInLeft' || name === 'runnerQuestionInRight')) {
      this._finishQuestionSwitch()
    }
  },
  _finishQuestionSwitch: function() {
    this._switchPhase = ''
    clearTimeout(this._switchTimer)
    clearTimeout(this._switchFallbackTimer)
    this._switchTargetIndex = null
    if (this._detached) return
    this.setData({ animClass: '', _animating: false })
  },
  _slideTo: function(nextIdx, dir, eventName) {
    if (this.data._animating) return
    var event = eventName || (dir === 'left' ? 'next' : 'prev')
    // Compact review and parents with their own animation keep their existing flow.
    if (this.data.externalSwitchAnimation || this.data.compactReviewMode ||
      (this.data.mode !== 'practice' && this.data.mode !== 'review' && this.data.mode !== 'exam')) {
      this.triggerEvent(event, { index: nextIdx })
      return
    }
    var self = this
    this._switchTargetIndex = nextIdx
    this._switchDirection = dir
    this._switchPhase = 'exit'
    this.setData({ _animating: true, animClass: 'question-fade-out', questionDirection: dir }, function() {
      if (self._detached) return
      self._switchTimer = setTimeout(function() {
        if (self._detached) return
        // Recover visibility and unlock input if a parent rejects the switch.
        self._switchFallbackTimer = setTimeout(function() { self._finishQuestionSwitch() }, 800)
        self.triggerEvent(event, { index: nextIdx })
      }, 100)
    })
  },
}
