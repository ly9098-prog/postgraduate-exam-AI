function createRenderInvariantController(options) {
  return {
    check(renderModel) {
      checkImpl(options, renderModel)
    },
  }
}

function checkImpl(options, renderModel) {
  if (!renderModel) return

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

  if (renderModel.mode === 'CODE' && renderModel.rawText) {
    checkCodeMode(renderModel, options)
  }

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
}

function checkCodeMode(renderModel, options) {
  var hasHtmlLeak = /&(?:nbsp|amp|lt|gt|#\d+);/.test(renderModel.rawText)
  if (hasHtmlLeak) {
    console.error(
      '[CODE_HTML_LEAK] CODE rawText contains HTML entities\n' +
      '  tail: ' + renderModel.rawText.slice(-60)
    )
  }
  var hasRenderViolation = renderModel.html.length > 0 || renderModel.richTextNodes.length > 0
  if (hasRenderViolation) {
    console.error(
      '[CODE_RENDER_VIOLATION] CODE mode leaked into html/richTextNodes ' +
      '(html=' + renderModel.html.length + ', nodes=' + renderModel.richTextNodes.length + ')'
    )
  }
  if ((hasHtmlLeak || hasRenderViolation) && !options.isSafeModeActive()) {
    options.enterSafeMode()
  }
}

module.exports = {
  createRenderInvariantController,
}
