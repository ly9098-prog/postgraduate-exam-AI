const assert = require('assert')
const fs = require('fs')
const path = require('path')

const js = fs.readFileSync(path.join(__dirname, '../subpackages/study/wrong-detail/wrong-detail.js'), 'utf8')
const wxml = fs.readFileSync(path.join(__dirname, '../subpackages/study/wrong-detail/wrong-detail.wxml'), 'utf8')

assert(js.includes('wx.chooseMedia({'), 'wrong-detail should allow choosing a supplemental visual')
assert(js.includes("'/ai/error-analysis/with-image'"), 'supplemental visual should use multipart AI endpoint')
assert(js.includes("formData: {\n          wrong_question_id"), 'multipart request must bind the wrong-question id')
assert(js.includes("model === 'vision_input_missing'"), 'missing visual input must have a dedicated failure state')
assert(js.includes("model === 'vision_parse_failed'"), 'unconfirmed visual reading must have a dedicated failure state')
assert(js.includes('const attachment = this.data.aiAttachment'), 'selected attachment must be read at request time')

// Regression guard: request-start/loading reset must not delete the selected screenshot
// before _requestAiAnalysis() can upload it.
const loadStart = js.slice(js.indexOf('async loadAiAnalysis'), js.indexOf('async regenerateAiAnalysis'))
assert(!/aiLoading:\s*true[\s\S]{0,350}aiAttachment:\s*null/.test(loadStart), 'loadAiAnalysis must preserve selected screenshot')
const resetMethod = js.slice(js.indexOf('  _resetAiLoadingState() {'), js.indexOf('/** 将最新 AI 结果'))
assert(!resetMethod.includes('aiAttachment: null'), '_resetAiLoadingState must not clear selected screenshot')

assert(wxml.includes('视觉上下文'), 'AI card should expose visual context')
assert(wxml.includes('添加题图 / 表格'), 'AI card should expose image/table upload control')
assert(wxml.includes('aiAttachment.tempFilePath'), 'selected screenshot should have a preview')
assert(wxml.includes("aiNeedsVisualAttachment && !aiAttachment"), 'visual parse failures should offer attachment-first recovery')

console.log('✓ wrong-detail AI visual-context regression tests passed')
