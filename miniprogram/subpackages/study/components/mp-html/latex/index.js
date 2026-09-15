/**
 * @fileoverview latex 插件
 * katex.min.js来源 https://github.com/rojer95/katex-mini
 */
const parse = require('./katex.min')

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
              var rendered = parse.__renderToDomTree(part[i], { displayMode: status === 2, throwOnError: true })
              nodes = [Object.assign({}, rendered, { name: 'span', attrs: { class: 'katex' }, type: 'node' })]
            } catch (_e) {
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
                f: 'display:inline-block',
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

module.exports = Latex
