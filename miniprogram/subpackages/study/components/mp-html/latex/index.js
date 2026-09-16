/**
 * @fileoverview latex 插件
 * katex.min.js来源 https://github.com/rojer95/katex-mini
 */
const katex = require('./katex.min')

function hyphenateStyleName (name) {
  return String(name || '').replace(/([A-Z])/g, '-$1').toLowerCase()
}

function encodeSvgDataUri (svg) {
  return 'data:image/svg+xml,' + encodeURIComponent(String(svg || '').replace(/\s+/g, ' '))
}

function classNameOf (classes, includeKatexSpan) {
  const list = Array.isArray(classes) ? classes.filter(Boolean).slice() : []
  // katex.wxss intentionally targets .katex-span for anonymous KaTeX spans.
  // renderToString + generic HTML parsing loses this compatibility class and
  // breaks vlist positioning (subscripts/fractions appear in the wrong place).
  if (includeKatexSpan && list.indexOf('katex-span') < 0) list.push('katex-span')
  return list.join(' ')
}

function styleTextOf (dom, includeItalic) {
  let style = ''
  if (includeItalic && dom && Number(dom.italic) > 0) {
    style += 'margin-right:' + dom.italic + 'em;'
  }
  const source = dom && dom.style && typeof dom.style === 'object' ? dom.style : {}
  Object.keys(source).forEach(function (key) {
    if (source[key] === undefined || source[key] === null || source[key] === '') return
    style += hyphenateStyleName(key) + ':' + source[key] + ';'
  })
  return style
}

function attrsOf (dom, className, styleText) {
  const attrs = {}
  const source = dom && dom.attributes && typeof dom.attributes === 'object' ? dom.attributes : {}
  Object.keys(source).forEach(function (key) {
    if (source[key] !== undefined && source[key] !== null) attrs[key] = String(source[key])
  })
  if (className) attrs.class = className
  if (styleText) attrs.style = styleText
  return attrs
}

function katexDomToRichNodes (items) {
  const result = []
  const domTree = katex.__domTree || {}
  const Span = domTree.Span
  const SymbolNode = domTree.SymbolNode
  const SvgNode = domTree.SvgNode

  ;(Array.isArray(items) ? items : [items]).forEach(function (dom) {
    if (!dom) return

    // Keep SVG as one data-uri image. Converting its private Path/Line nodes
    // directly would leak unsupported KaTeX internals into native rich-text.
    if (SvgNode && dom instanceof SvgNode) {
      result.push({
        name: 'img',
        attrs: {
          src: encodeSvgDataUri(dom.toMarkup()),
          class: 'katex-svg'
        }
      })
      return
    }

    if (SymbolNode && dom instanceof SymbolNode) {
      const className = classNameOf(dom.classes, false)
      const styleText = styleTextOf(dom, true)
      const textNode = { type: 'text', text: String(dom.text == null ? '' : dom.text) }
      if (className || styleText) {
        result.push({
          name: 'span',
          attrs: attrsOf(dom, className, styleText),
          children: [textNode]
        })
      } else if (textNode.text) {
        result.push(textNode)
      }
      return
    }

    const children = dom.children ? katexDomToRichNodes(dom.children) : []
    if (Span && dom instanceof Span) {
      result.push({
        name: 'span',
        attrs: attrsOf(dom, classNameOf(dom.classes, true), styleTextOf(dom, false)),
        children: children
      })
      return
    }

    // Unknown wrapper nodes are flattened. Supported visual primitives either
    // arrive as Span/SymbolNode or are contained by SvgNode above.
    for (let i = 0; i < children.length; i++) result.push(children[i])
  })

  return result
}

function parseKatexToNodes (source, options) {
  const tree = katex.__renderToDomTree(String(source || ''), Object.assign({}, options, {
    output: 'html'
  }))
  return katexDomToRichNodes([tree])
}

function Latex () {

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
            // 安全解析：捕获 KaTeX 异常，失败时回退为纯文本
            let nodes
            try {
              nodes = parseKatexToNodes(part[i], {
                displayMode: status === 2,
                throwOnError: true
              })
            } catch (_e) {
              children.push({ type: 'text', text: part[i] })
              status = 0
              continue
            }
            if (!nodes || !nodes.length) {
              children.push({ type: 'text', text: part[i] })
              status = 0
              continue
            }
            if (status === 1) {
              // 行内公式
              children.push({
                name: 'span',
                attrs: {},
                l: 'T',
                f: 'display:inline-block;vertical-align:middle;line-height:normal',
                children: nodes
              })
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

// Exposed only for regression tests; page code still uses the plugin lifecycle.
Latex.parseKatexToNodes = parseKatexToNodes

module.exports = Latex
