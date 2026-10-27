function commitQuestionView(target, data, shouldResetViewport, questionChanged) {
  // Render from a local snapshot, never directly from the incoming property.
  // This keeps the stem, options and motion in the same view-layer commit.
  var resetViewport = shouldResetViewport && !target.data.flowLayout && !target.data.compactReviewMode && Number(target._lastQuestionScrollTop || 0) > 1
  if (resetViewport) {
    target._lastQuestionScrollTop = 0
    data.questionScrollIntoView = 'runner-scroll-top-anchor'
  }
  var switching = questionChanged && target._switchTargetIndex !== null
  if (switching) {
    clearTimeout(target._switchFallbackTimer)
    target._switchTargetIndex = null
    target._switchPhase = 'enter'
    data.animClass = target._switchDirection === 'left' ? 'slide-in-left' : 'slide-in-right'
  }
  var self = target
  target.setData(data, function() {
    if (self._detached) return
    if (resetViewport) {
      clearTimeout(self._viewportResetTimer)
      self._viewportResetTimer = setTimeout(function() {
        if (!self._detached) self.setData({ questionScrollIntoView: '' })
      }, 0)
    }
    if (switching && self._switchPhase === 'enter') {
      self._switchTimer = setTimeout(function() { self._finishQuestionSwitch() }, 300)
    }
  })
}

module.exports = commitQuestionView
