// Page capability assembly for miniprogram/subpackages/study/practice-result/index.js.
// Assemble live page ports here; the page keeps lazy controller memoisation.

const { normalizePercent } = require('./format-helpers')
const { buildTrendPlot } = require('./trend-plot-builder')

function buildTrendLoadPageCapabilities(page, deps) {
  return {
    isLoadCurrent: id => page._isDashboardLoadCurrent(id),
    setData: patch => page.setData(patch),
    requestTrends: () => page.requestApi('/api/v1/stats/trends', { days: 7 }),
    normalizePercent,
    buildTrendPlot: data => buildTrendPlot(data),
  }
}

module.exports = {
  buildTrendLoadPageCapabilities,
}
