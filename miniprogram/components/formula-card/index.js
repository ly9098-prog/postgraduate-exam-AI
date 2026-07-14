const formulaContent = require('../../utils/formula-content')
const katex = require('../mp-html/latex/katex.min')
const Parser = require('../mp-html/parser')
const LatexPlugin = require('../mp-html/latex/index')

function containsRenderError(nodes) {
  var found = false
  function walk(items) {
    if (found || !Array.isArray(items)) return
    for (var i = 0; i < items.length; i++) {
      var node = items[i] || {}
      var style = node.attrs && node.attrs.style
      if (typeof style === 'string' && /(?:^|;)\s*color\s*:\s*red\b/i.test(style)) {
        found = true
        return
      }
      if (node.children) walk(node.children)
    }
  }
  walk(nodes)
  return found
}


function appendNodeStyle(node, declaration) {
  if (!node.attrs) node.attrs = {}
  var style = String(node.attrs.style || '')
  if (style && style.charAt(style.length - 1) !== ';') style += ';'
  node.attrs.style = style + declaration
}

function stabilizeFormulaTree(nodes) {
  function walk(items) {
    if (!Array.isArray(items)) return
    for (var i = 0; i < items.length; i++) {
      var node = items[i] || {}
      var className = node.attrs ? String(node.attrs.class || '') : ''
      var classes = className ? className.split(/\s+/) : []
      if (classes.indexOf('katex') >= 0) {
        appendNodeStyle(node, 'display:inline-block;width:auto;max-width:none;white-space:nowrap;')
      }
      if (classes.indexOf('katex-html') >= 0) {
        appendNodeStyle(node, 'display:inline-block;width:auto;white-space:nowrap;')
      }
      if (classes.indexOf('base') >= 0) {
        appendNodeStyle(node, 'width:auto;white-space:nowrap;')
      }
      if (node.children) walk(node.children)
    }
  }
  walk(nodes)
  return nodes
}

function stabilizeRichMathTree(nodes) {
  function hasDirectKatexChild(node) {
    var children = node && node.children
    if (!Array.isArray(children)) return false
    for (var i = 0; i < children.length; i++) {
      var child = children[i] || {}
      var className = child.attrs ? String(child.attrs.class || '') : ''
      if (className.split(/\s+/).indexOf('katex') >= 0) return true
    }
    return false
  }

  function walk(items) {
    if (!Array.isArray(items)) return
    for (var i = 0; i < items.length; i++) {
      var node = items[i] || {}
      var className = node.attrs ? String(node.attrs.class || '') : ''
      var classes = className ? className.split(/\s+/) : []

      // Only the wrapper created for this exact formula is atomic. Never mark
      // an ancestor span merely because it contains KaTeX: doing that turns the
      // whole Chinese paragraph into one no-wrap inline block and pushes it
      // outside the viewport.
      if (node.l === 'T') {
        appendNodeStyle(node, 'display:inline-block;vertical-align:middle;white-space:nowrap;max-width:100%;overflow-x:auto;overflow-y:hidden;box-sizing:border-box;margin:0 3rpx;padding:5rpx 0 7rpx;')
      } else if (hasDirectKatexChild(node)) {
        // Explicit $$...$$ / \[...\] content is a block formula. Keep its
        // full KaTeX tree, but constrain scrolling to this formula only.
        appendNodeStyle(node, 'display:block;width:100%;max-width:100%;overflow-x:auto;overflow-y:hidden;box-sizing:border-box;white-space:nowrap;')
      }
      if (classes.indexOf('katex') >= 0) {
        appendNodeStyle(node, 'display:inline-block;width:auto;max-width:none;white-space:nowrap;font-size:1.12em;line-height:1.22;vertical-align:middle;')
      }
      if (classes.indexOf('katex-html') >= 0) {
        appendNodeStyle(node, 'display:inline-block;width:auto;white-space:nowrap;')
      }
      if (classes.indexOf('base') >= 0) {
        appendNodeStyle(node, 'width:auto;white-space:nowrap;')
      }
      if (node.children) walk(node.children)
    }
  }

  walk(nodes)
  return nodes
}

function renderFormulaNodes(latex) {
  var source = String(latex || '').trim()
  if (!source) return []
  try {
    // Inline KaTeX plus \displaystyle gives display-size fractions and limits,
    // while keeping one natural-width tree. This avoids the block display tree
    // being split across recursive custom components on some Android clients.
    var nodes = katex.default('\\displaystyle ' + source)
    if (Array.isArray(nodes) && nodes.length && !containsRenderError(nodes)) return stabilizeFormulaTree(nodes)
  } catch (err) {
    console.warn('Formula render failed, falling back to source text', err)
  }
  return [{ type: 'text', text: source }]
}

function parseRichNodes(html) {
  var source = String(html || '')
  if (!source) return []
  try {
    var host = {
      properties: {
        editable: false,
        containerStyle: '',
        mathLayout: '',
      },
      imgList: [],
      plugins: [new LatexPlugin()],
    }
    return stabilizeRichMathTree(new Parser(host).parse(source))
  } catch (err) {
    console.warn('Formula prose render failed, falling back to plain text', err)
    return [{ type: 'text', text: source.replace(/<[^>]+>/g, '') }]
  }
}

function prepareFormulaBlocks(card) {
  return formulaContent.prepareFormulaBlocks(card).map(function (block) {
    return Object.assign({}, block, {
      // The text in the formula block's upper-left corner is block.label, not
      // card.title. Render it through the same mixed prose/LaTeX pipeline used
      // by conditions and error tips so values such as "e^x展开" become KaTeX.
      labelNodes: parseRichNodes(formulaContent.normalizeMixedContent(block.label)),
      mathNodes: renderFormulaNodes(block.latex),
      formulaItems: (block.formulaParts || []).map(function (item) {
        return Object.assign({}, item, { mathNodes: renderFormulaNodes(item.latex) })
      }),
    })
  })
}

function prepareContent(card) {
  var html = formulaContent.prepareContentHtml(card)
  return {
    titleNodes: parseRichNodes(formulaContent.normalizeMixedContent(card && card.title)),
    summaryNodes: parseRichNodes(html.summaryHtml),
    conditionsNodes: parseRichNodes(html.conditionsHtml),
    symbolNotesNodes: parseRichNodes(html.symbolNotesHtml),
    secondaryNodes: parseRichNodes(html.secondaryHtml),
    errorTipsNodes: parseRichNodes(html.errorTipsHtml),
    examples: (html.examples || []).map(function (example, index) {
      return Object.assign({}, example, {
        _key: String(example.id || index) + '-' + index,
        questionNodes: parseRichNodes(example.questionHtml),
        solutionNodes: parseRichNodes(example.solutionHtml),
        answerNodes: parseRichNodes(example.answerHtml),
        errorTipNodes: parseRichNodes(example.errorTipHtml),
      })
    }),
  }
}

Component({
  properties: {
    card: {
      type: Object,
      value: {},
      observer(nextCard, previousCard) {
        var renderKey = formulaContent.createRenderKey(nextCard)
        var idChanged = !nextCard || !previousCard || String(nextCard.id) !== String(previousCard.id)
        var patch = {}

        if (renderKey !== this.data.cardRenderKey) {
          patch.cardRenderKey = renderKey
          patch.formulaBlocks = prepareFormulaBlocks(nextCard)
          patch.content = prepareContent(nextCard)
        }

        if (idChanged) {
          patch.showSymbolNotes = false
          patch.showSecondary = false
          patch.showErrorTips = true
          patch.showExamples = false
          patch.graphLoadError = false
          patch.graphLoaded = false
        }

        if (Object.keys(patch).length) this.setData(patch)
      },
    },
    graphImageUrl: { type: String, value: '' },
  },

  data: {
    cardRenderKey: '',
    formulaBlocks: [],
    content: {
      titleNodes: [],
      summaryNodes: [],
      conditionsNodes: [],
      symbolNotesNodes: [],
      secondaryNodes: [],
      errorTipsNodes: [],
      examples: [],
    },
    showSymbolNotes: false,
    showSecondary: false,
    showErrorTips: true,
    showExamples: false,
    graphLoadError: false,
    graphLoaded: false,
  },

  lifetimes: {
    attached() {
      if (!this.data.cardRenderKey && this.data.card) {
        this.setData({
          cardRenderKey: formulaContent.createRenderKey(this.data.card),
          formulaBlocks: prepareFormulaBlocks(this.data.card),
          content: prepareContent(this.data.card),
        })
      }
    },
  },

  methods: {
    toggleSection(e) {
      const key = e.currentTarget.dataset.key
      if (!key) return
      this.setData({ [key]: !this.data[key] })
    },

    previewGraph() {
      const url = this.data.graphImageUrl
      if (url) wx.previewImage({ urls: [url] })
    },

    onGraphLoad() {
      this.setData({ graphLoadError: false, graphLoaded: true })
    },

    onGraphError() {
      this.setData({ graphLoadError: true, graphLoaded: false })
    },

    onFormulaTouchStart() {
      this.triggerEvent('formulastart', {}, { bubbles: true, composed: true })
    },

    onFormulaTouchEnd() {
      this.triggerEvent('formulaend', {}, { bubbles: true, composed: true })
    },
  },
})
