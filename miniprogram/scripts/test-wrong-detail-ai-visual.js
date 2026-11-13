const fs = require('fs')
const path = require('path')

function assert(cond, msg) {
  if (!cond) throw new Error(msg)
}

const root = path.resolve(__dirname, '..')
const js = fs.readFileSync(path.join(root, 'subpackages/study/wrong-detail/wrong-detail.js'), 'utf8')
const aiState = fs.readFileSync(path.join(root, 'subpackages/study/wrong-detail/utils/wrong-detail-ai-state.js'), 'utf8')
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
assert(js.includes("wq.ai_analysis_status && wq.ai_analysis_status !== 'ready'"), 'stale/generating AI caches must not be treated as ready')
assert(aiState.includes("!wq.ai_analysis_status || wq.ai_analysis_status === 'ready'"), 'only ready/legacy caches may render directly')
assert(js.includes('return aiState._resolvePreferredAnalysis(wq, _hasStoredAnalysisValue, _normalizeAiPayload)'), 'page must delegate preferred cache selection')
assert(wxml.includes('<template name="ai-loading-sections">'), 'regeneration skeleton template is present')
assert(wxml.includes('ai-regenerating-skeleton'), 'regeneration renders skeleton sections')
assert(wxml.includes('wx:if="{{aiRegenerating}}"'), 'regeneration state swaps sections for the skeleton')
assert(!wxml.includes('ai-regenerating-banner'), 'duplicate regeneration banner is removed')
assert(wxml.includes('正在重新生成，先保留当前解析'), 'regeneration status stays exposed to assistive technology')

console.log('wrong-detail AI DB-image-only regression passed')
