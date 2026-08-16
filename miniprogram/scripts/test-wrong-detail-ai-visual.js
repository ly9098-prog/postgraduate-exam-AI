const fs = require('fs')
const path = require('path')

function assert(cond, msg) {
  if (!cond) throw new Error(msg)
}

const root = path.resolve(__dirname, '..')
const js = fs.readFileSync(path.join(root, 'subpackages/study/wrong-detail/wrong-detail.js'), 'utf8')
const wxml = fs.readFileSync(path.join(root, 'subpackages/study/wrong-detail/wrong-detail.wxml'), 'utf8')
const wxss = fs.readFileSync(path.join(root, 'subpackages/study/wrong-detail/wrong-detail.wxss'), 'utf8')

assert(js.includes("api.post('/ai/error-analysis'"), 'wrong-detail should use the normal AI analysis endpoint')
assert(!js.includes('/ai/error-analysis/with-image'), 'manual image upload endpoint must not be used')
assert(!js.includes('wx.chooseMedia'), 'wrong-detail must not ask the user to upload a screenshot')
assert(!js.includes('aiAttachment'), 'manual AI attachment state should be removed')
assert(!wxml.includes('视觉上下文'), 'visual context upload panel should be removed')
assert(!wxml.includes('添加题图 / 表格'), 'manual upload CTA should be removed')
assert(!wxml.includes('aiAttachment'), 'attachment-dependent rendering should be removed')
assert(!wxss.includes('.ai-visual-context'), 'unused visual upload styles should be removed')

console.log('wrong-detail AI DB-image-only regression passed')
