/**
 * @fileoverview latex 插件
 * KaTeX split into chunks to satisfy the 200 KiB single-file limit.
 */
const katex = require('./katex.min')
const Parser = require('../mp-html-parser')

function parseKatexToNodes(source, options) {
  // Native <rich-text> expects the documented node schema:
  // { name, attrs, children } / { type:'text', text }. KaTeX's private DOM
  // tree instead exposes `attributes` objects and class/style instances; passing
  // that tree directly makes WeChat call `attributes.forEach` on a plain object.
  // Render to ordinary HTML first, then reuse the project's hardened HTML parser
  // to normalize it into native rich-text nodes (including SVG -> safe image).
  const markup = katex.renderToString(String(source || ''), {
    ...options,
    output: 'html',
  })
  const host = {
    properties: {
      editable: false,
      containerStyle: '',
      mathLayout: '',
    },
    imgList: [],
    plugins: [],
  }
  return new Parser(host).parse(markup)
}

function Latex () {

}

function isKatexDiagnosticText(value) {
  return /KaTeX\s+parse\s+error|Expected\s+['"]?EOF|Undefined\s+control\s+sequence|ParseError/i.test(String(value || ''))
}

function containsKatexError(items) {
  var found = false
  function walk(items) {
    if (found || !Array.isArray(items)) return
    for (var i = 0; i < items.length; i++) {
      var item = items[i] || {}
      var attrs = item.attrs || {}
      if (typeof attrs.style === 'string' && /(?:^|;)\s*color\s*:\s*red\b/i.test(attrs.style)) {
        found = true
        return
      }
      if (/katex-error|katex-parse-error/i.test(String(attrs.class || ''))) {
        found = true
        return
      }
      if (attrs['data-error'] !== undefined || attrs['data-error-type'] !== undefined) {
        found = true
        return
      }
      if (item.type === 'text' && isKatexDiagnosticText(item.text)) {
        found = true
        return
      }
      if (item.children) walk(item.children)
    }
  }
  walk(items)
  return found
}

function readableLatexFallback(value) {
  var source = String(value || '')
    .replace(/^\s*\\displaystyle\s*/, '')
    .replace(/\\(?:text|textrm|textbf|textit|mathrm|operatorname)\s*\{([^{}]*)\}/g, '$1')
    .replace(/\\to\b/g, '→')
    .replace(/\\ne\b/g, '≠')
    .replace(/\\le\b/g, '≤')
    .replace(/\\ge\b/g, '≥')
    .replace(/\\infty\b/g, '∞')
    .replace(/\s+/g, ' ')
    .trim()
  return isKatexDiagnosticText(source) ? '' : source
}

function renderLatex(source, displayMode) {
  var nodes = parseKatexToNodes(source, {
    displayMode: Boolean(displayMode),
    throwOnError: true,
  })
  return nodes
}


Latex.prototype.onParse = function (node, vm) {
  // $...$包裹的内容为latex公式
  if (!vm.options.editable && node.type === 'text' && node.text.includes('$')) {
    const part = node.text.split(/(\${1,2})/)
    const children = []
    let status = 0
    for (let i = 0; i < part.length; i++) {
      if (i % 2 === 0) {
        // 文本内容
        if (part[i]) {
          if (status === 0) {
            children.push({
              type: 'text',
              text: part[i]
            })
          } else {
            // katex-mini may return a red error tree instead of throwing. Treat
            // either behaviour as a parse failure and fall back to the source,
            // never to KaTeX's internal diagnostic message.
            let nodes
            try {
              nodes = renderLatex(part[i], status === 2)
            } catch (_e) {
              nodes = null
            }
            if (!nodes) {
              const fallback = readableLatexFallback(part[i])
              if (fallback) children.push({ type: 'text', text: fallback })
              status = 0
              continue
            }
            if (status === 1) {
              // 行内公式
              const wrapper = {
                name: 'span',
                attrs: {},
                l: 'T',
                f: 'display:inline-block',
                children: nodes
              }
              // Preserve the original source for defensive fallback without
              // leaking raw LaTeX into rich-text serialisation or rendering.
              try {
                Object.defineProperty(wrapper, 'latexSource', {
                  value: part[i],
                  enumerable: false,
                  configurable: true
                })
              } catch (_e) {
                // Old JS runtimes may reject defineProperty on plain objects;
                // the plugin already handled the parse error before this point.
              }
              children.push(wrapper)
            } else {
              // 块公式
              const naturalWidth = vm && vm.properties && vm.properties.mathLayout === 'natural'
              children.push({
                name: naturalWidth ? 'span' : 'div',
                attrs: {
                  // In formula-reader mode the outer scroll-view owns overflow. Keep the
                  // KaTeX tree at its natural width so short formulas can be centered and
                  // long formulas begin at the left edge without a huge empty canvas.
                  style: naturalWidth
                    ? 'display:inline-block;width:auto;min-width:0;max-width:none;text-align:left;white-space:nowrap;overflow:visible;vertical-align:middle'
                    : 'display:inline-table;width:auto;min-width:100%;text-align:center;white-space:nowrap;overflow:visible'
                },
                children: nodes
              })
            }
          }
        }
      } else {
        // 分隔符
        if (part[i] === '$' && part[i + 2] === '$') {
          // 行内公式
          status = 1
          part[i + 2] = ''
        } else if (part[i] === '$$' && part[i + 2] === '$$') {
          // 块公式
          status = 2
          part[i + 2] = ''
        } else {
          if (part[i] && part[i] !== '$$') {
            // 普通$符号
            part[i + 1] = part[i] + part[i + 1]
          }
          // 重置状态
          status = 0
        }
      }
    }
    delete node.type
    delete node.text
    node.name = 'span'
    node.attrs = {}
    node.children = children
  }
}

module.exports = Latex
