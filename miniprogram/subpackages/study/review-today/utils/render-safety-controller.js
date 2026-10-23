function createRenderSafetyController(options) {
  return {
    checkInvariant(renderModel) {
      checkInvariantImpl(options, renderModel)
    },

    recordTrace(trace) {
      recordTraceImpl(options, trace)
    },

    checkSetDataSize(data) {
      checkSetDataSizeImpl(options, data)
    },
  }
}

function checkInvariantImpl(options, renderModel) {
  if (!renderModel) return

  if (renderModel.mode === 'CODE' && renderModel.rawText) {
    var hasHtmlLeak = /&(?:nbsp|amp|lt|gt|#\d+);/.test(renderModel.rawText)
    if (hasHtmlLeak) {
      console.error('[CODE_HTML_LEAK] review-today CODE rawText contains HTML entities')
    }
    var hasRenderViolation = renderModel.html.length > 0 || renderModel.richTextNodes.length > 0
    if (hasRenderViolation) {
      console.error('[CODE_RENDER_VIOLATION] review-today CODE mode leaked into html/richTextNodes')
    }
    if ((hasHtmlLeak || hasRenderViolation) && !options.isSafeModeActive()) {
      options.enterSafeMode()
    }
  }

  if (renderModel.mode === 'MIXED') {
    if (!renderModel.blocks || renderModel.blocks.length === 0) {
      console.error('[MIXED_RENDER_VIOLATION] review-today MIXED mode but blocks is empty')
      return
    }
    for (var mi = 0; mi < renderModel.blocks.length; mi++) {
      var mBlock = renderModel.blocks[mi]
      if (mBlock.type === 'CODE' && mBlock.rawText) {
        if (/&(?:nbsp|amp|lt|gt|#\d+);/.test(mBlock.rawText)) {
          console.error('[CODE_HTML_LEAK] review-today MIXED CODE block #' + mi + ' contains HTML entities')
        }
      }
    }
  }
}

function recordTraceImpl(options, trace) {
  if (!trace) return
  var traces = options.getRenderTraces()
  traces = traces.concat([trace])
  if (traces.length > 200) traces = traces.slice(-200)
  options.setRenderTraces(traces)
}

function checkSetDataSizeImpl(options, data) {
  if (!options.isDev()) return
  var THRESHOLD = 200 * 1024
  try {
    var size = new Blob([JSON.stringify(data)]).size
    if (size > THRESHOLD) {
      console.warn('[SETDATA_SIZE] payload ~' + (size / 1024).toFixed(0) + 'KB for keys: ' + Object.keys(data).join(', ') + ' (threshold: ' + (THRESHOLD / 1024) + 'KB)')
    }
  } catch (e) {
  }
}

module.exports = {
  createRenderSafetyController,
}
