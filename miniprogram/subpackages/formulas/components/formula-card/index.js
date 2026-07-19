const formulaContent = require('../../utils/formula-content')
const katex = require('../../utils/katex/katex.min')
const Parser = require('../../../components/mp-html/parser')
const LatexPlugin = require('../../utils/katex/index')

/**
 * Check whether a rich-text node tree contains any KaTeX error indicator.
 *
 * Detects:
 *  - style containing "color: red" (katex-mini error styling)
 *  - class containing "katex-error" or "katex-parse-error"
 *  - text content matching "KaTeX parse error"
 *  - data-error or data-error-type attribute (katex-mini extended output)
 */
function containsRenderError(nodes) {
  var found = false
  function walk(items) {
    if (found || !Array.isArray(items)) return
    for (var i = 0; i < items.length; i++) {
      var node = items[i] || {}
      var attrs = node.attrs || {}
      var style = attrs.style
      if (typeof style === 'string' && /(?:^|;)\s*color\s*:\s*red\b/i.test(style)) {
        found = true
        return
      }
      var className = String(attrs.class || '')
      if (/katex-error|katex-parse-error/i.test(className)) {
        found = true
        return
      }
      if (attrs['data-error'] !== undefined || attrs['data-error-type'] !== undefined) {
        found = true
        return
      }
      if (node.type === 'text' && /KaTeX\s+parse\s+error/i.test(node.text)) {
        found = true
        return
      }
      if (node.children) walk(node.children)
    }
  }
  walk(nodes)
  return found
}

/**
 * Walk a rich-text node tree and surgically replace only the individual
 * KaTeX error fragments (spans tagged with l="T" that contain error nodes)
 * with sanitized plain text.  Other formula fragments and Chinese prose
 * in the same tree are left untouched, so one broken formula never causes
 * an entire paragraph to degrade to plain text.
 */
function cleanFormulaErrorNodes(nodes) {
  if (!Array.isArray(nodes)) return nodes
  var result = []
  for (var i = 0; i < nodes.length; i++) {
    var node = nodes[i] || {}
    // Text node that IS the error message → drop it
    if (node.type === 'text' && /KaTeX\s+parse\s+error/i.test(node.text)) {
      continue
    }
    // A formula-span (l === 'T' from LatexPlugin) that contains
    // an error → replace the whole span with readable text.
    if (node.l === 'T' && node.children && containsRenderError(node.children)) {
      var cleaned = extractReadableText(node)
      if (cleaned) result.push({ type: 'text', text: cleaned })
      continue
    }
    // Non-error node with children → recurse
    if (node.children && Array.isArray(node.children)) {
      var cleanedChildren = cleanFormulaErrorNodes(node.children)
      if (cleanedChildren !== node.children || containsRenderError(node.children)) {
        result.push(Object.assign({}, node, { children: cleanedChildren }))
      } else {
        result.push(node)
      }
    } else {
      result.push(node)
    }
  }
  return result
}

/**
 * Extract readable plain text from a rich-text node subtree, intended as
 * fallback for a single broken formula fragment.
 *
 * Returns a plain-text approximation that a reader can still understand even
 * when the original LaTeX was malformed:
 *  - \text{Hello}          → Hello
 *  - \operatorname{sgn}    → sgn
 *  - \frac{a}{b}           → a/b
 *  - \displaystyle         → (removed)
 *  - \sqrt{x}              → sqrt(x)
 *  - Other \command        → (removed, but its brace-delimited args kept)
 */
function extractReadableText(node) {
  var parts = []
  function walk(item) {
    if (!item) return
    if (item.type === 'text') {
      var text = String(item.text || '')
      // Phase 1: preserve content inside known container commands
      text = text
        .replace(/\\text\s*\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}/g, function (_, inner) {
          // Recursively handle nested braces inside \text
          return walkNestedText(inner)
        })
        .replace(/\\operatorname\s*\{([^{}]*)\}/g, '$1')
        .replace(/\\textbf\s*\{([^{}]*)\}/g, '$1')
        .replace(/\\textit\s*\{([^{}]*)\}/g, '$1')
        .replace(/\\displaystyle\s*/g, '')
        .replace(/\\;\s*/g, ' ')
        .replace(/\\,\s*/g, ' ')
        .replace(/\\quad\s*/g, ' ')
        .replace(/\\qquad\s*/g, '  ')
      // Phase 2: convert common structures to readable approximations
      text = text
        .replace(/\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}/g, '$1/$2')
        .replace(/\\sqrt\s*(?:\[([^\]]*)\])?\s*\{([^{}]*)\}/g, function (_, root, radicand) {
          return 'sqrt' + (root ? '[' + root + ']' : '') + '(' + radicand + ')'
        })
        .replace(/\\sum\s*(?:\{([^}]*)\})?\s*(?:\{([^}]*)\})?/g, 'sum')
        .replace(/\\int\s*(?:\{([^}]*)\})?\s*(?:\{([^}]*)\})?/g, 'int')
      // Phase 3: strip remaining LaTeX commands and braces
      text = text
        .replace(/\\[A-Za-z]+\s*/g, '')
        .replace(/[\{\}]+/g, '')
        .replace(/\s+/g, ' ')
        .trim()
      if (text) parts.push(text)
    }
    if (item.children && Array.isArray(item.children)) {
      item.children.forEach(walk)
    }
  }
  function walkNestedText(s) {
    // Handle one level of nesting inside \text{}
    return s.replace(/\\text\s*\{([^{}]*)\}/g, '$1')
  }
  walk(node)
  return parts.join(' ').replace(/\s+/g, ' ').trim()
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
    var nodes = stabilizeRichMathTree(new Parser(host).parse(source))
    // Post-process: detect and replace KaTeX error nodes that escaped the
    // per-formula try/catch (e.g. incomplete \text{... macros that katex-mini
    // renders as red-error spans instead of throwing). Replace each error
    // node's content with sanitized plain text so "KaTeX parse error" never
    // appears in the UI.
    return cleanFormulaErrorNodes(nodes)
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
      // block.note (the explainer text below each formula, e.g.
      // "y=x^n（n为正整数）与 y=x^{-n}（n为正整数）对比") contains mixed
      // Chinese prose and inline LaTeX. Render it through the same pipeline so
      // ^, _{}, \frac etc. are not shown as raw source.
      noteNodes: block.note
        ? parseRichNodes(formulaContent.normalizeMixedContent(block.note))
        : [],
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
