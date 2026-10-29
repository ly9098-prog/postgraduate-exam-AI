async function toggleAiInsight(pageContext, { getPlatform }) {
if (pageContext.data.aiInsightExpanded) {
pageContext.setData({ aiInsightExpanded: false })
return
}
if (pageContext.data.aiDiagnosisLoading || pageContext.data.aiDiagnosisRefreshing) {
getPlatform().showToast({ title: 'AI 正在分析，请稍候', icon: 'none' })
return
}
if (!pageContext.data.aiDiagnosis) {
getPlatform().showLoading({ title: '正在生成洞察', mask: false })
try {
const diagnosis = await pageContext.ensureAiDiagnosis({ force: false })
if (!diagnosis) {
getPlatform().showToast({ title: '暂未生成有效洞察', icon: 'none' })
return
}
} finally {
getPlatform().hideLoading()
}
}
pageContext.setData({ aiInsightExpanded: true })
}

function refreshAiDiagnosis(pageContext, { getPlatform }) {
if (pageContext._aiDiagnosisPromise || pageContext.data.aiDiagnosisRefreshing || pageContext.data.aiDiagnosisLoading) {
getPlatform().showToast({ title: pageContext.data.aiDiagnosisRefreshing ? '正在更新中...' : '正在分析中...', icon: 'none' })
return
}
if (pageContext._aiStatsLoaded) {
var total = (pageContext.data.stats || {}).total
if (total === 0) {
getPlatform().showToast({ title: '暂无错题数据', icon: 'none' })
return
}
}
pageContext.ensureAiDiagnosis({ force: true })
}

async function onAiFeedback(pageContext, { requestClient, getPlatform }) {
const types = ['分析不准确', '遗漏薄弱点', '建议不合理', '其他问题']
const index = await pageContext._showAppOptions({ title: '反馈这次分析', items: types })
if (index < 0) return
const feedbackType = types[index] || '其他问题'
try {
await requestClient.post('/ai/feedback', { source: 'wrong_book', feedback_type: feedbackType })
getPlatform().showToast({ title: '反馈已提交，感谢您的帮助', icon: 'success' })
} catch (_) {
getPlatform().showToast({ title: '反馈提交失败，请稍后重试', icon: 'none' })
}
}

module.exports = { toggleAiInsight, refreshAiDiagnosis, onAiFeedback }
