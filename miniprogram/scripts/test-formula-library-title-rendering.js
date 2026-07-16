const assert = require('node:assert/strict')

global.wx = {
  getWindowInfo() { return { windowWidth: 375 } },
  getDeviceInfo() { return { system: 'iOS 18' } },
  getStorageSync() { return '' },
}

let pageConfig
global.Page = function capturePage(config) {
  pageConfig = config
}

require('../subpackages/formulas/library/index')

assert.ok(pageConfig, 'formula library page should register itself')
assert.equal(typeof pageConfig.decorateFormulaItems, 'function')

function collectClasses(nodes, output = []) {
  ;(nodes || []).forEach((node) => {
    const className = node && node.attrs && node.attrs.class
    if (className) output.push(className)
    if (node && node.children) collectClasses(node.children, output)
  })
  return output
}

function collectText(nodes, output = []) {
  ;(nodes || []).forEach((node) => {
    if (node && node.type === 'text') output.push(node.text || '')
    if (node && node.children) collectText(node.children, output)
  })
  return output.join('')
}

const decorated = pageConfig.decorateFormulaItems.call(
  { data: { favoriteIds: [] } },
  [
    { id: 1, title: '二次函数 y=ax^2+bx+c' },
    { id: 2, title: '函数单调性判断' },
    { id: 3, title: '分段函数典型图像：sgn x 与 \\lfloor x\\rfloor' },
  ],
)

assert.equal(decorated.length, 3)
assert.ok(Array.isArray(decorated[0].titleNodes))
assert.ok(
  collectClasses(decorated[0].titleNodes).some((className) => className.split(/\s+/).includes('katex')),
  'math expression in the title should be converted into a KaTeX node tree',
)
assert.ok(collectText(decorated[0].titleNodes).includes('二次函数'))
assert.ok(!collectText(decorated[0].titleNodes).includes('^2'), 'raw exponent syntax should not remain visible')
assert.ok(
  !collectClasses(decorated[1].titleNodes).some((className) => className.split(/\s+/).includes('katex')),
  'plain Chinese titles should remain plain text',
)
assert.ok(
  collectClasses(decorated[2].titleNodes).filter((className) => className.split(/\s+/).includes('katex')).length >= 2,
  'sgn and floor notation in the title should each be converted into a KaTeX node tree',
)
assert.ok(!collectText(decorated[2].titleNodes).includes('\\lfloor'), 'raw floor command should not remain visible')
assert.ok(!collectText(decorated[2].titleNodes).includes('\\operatorname'), 'raw operatorname command should not remain visible')
assert.ok(!JSON.stringify(decorated[2].titleNodes).includes('color:red'), 'title math should not contain a KaTeX parse error')

console.log('formula library title rendering tests passed')
