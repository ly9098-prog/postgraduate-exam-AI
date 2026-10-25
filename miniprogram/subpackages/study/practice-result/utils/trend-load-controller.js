// Pure controller for loading practice trends. Extracted from
// subpackages/study/practice-result/index.js loadTrends.

function createTrendLoadController(options) {
  return {
    load: loadImpl.bind(null, options),
  }
}

async function loadImpl(options, loadId) {
  if (!options.isLoadCurrent(loadId)) return
  options.setData({ trendLoading: true })
  try {
    const raw = await options.requestTrends()
    if (!options.isLoadCurrent(loadId)) return
    const list = extractTrendList(raw)
    if (list.length) {
      options.setData(buildTrendSuccessPatch(options, list))
    } else {
      options.setData(buildTrendEmptyPatch('暂无历史数据', false))
    }
  } catch (e) {
    if (!options.isLoadCurrent(loadId)) return
    options.setData(buildTrendEmptyPatch('趋势暂不可用', false))
  } finally {
    if (!options.isLoadCurrent(loadId)) return
    options.setData({ trendLoading: false })
  }
}

function extractTrendList(raw) {
  return Array.isArray(raw) ? raw
    : Array.isArray(raw && raw.items) ? raw.items
    : Array.isArray(raw && raw.data) ? raw.data
    : []
}

function buildTrendSuccessPatch(options, list) {
  const trendData = list.slice(-7).map(item => ({
    date: item.date || '',
    accuracy: options.normalizePercent(item.accuracy),
    questions: Number(item.questions ?? item.answer_count ?? item.answered ?? 0) || 0,
  }))
  const trendSummary = computeTrendSummary(trendData)
  const plot = options.buildTrendPlot(trendData)
  return {
    trendData,
    trendPoints: plot.points,
    trendSegments: plot.segments,
    trendLastPoint: plot.lastPoint,
    trendAreaStyle: plot.areaStyle,
    trendSummary,
    trendAvailable: true,
  }
}

function computeTrendSummary(trendData) {
  const nonEmpty = trendData.filter(item => item.questions > 0)
  if (nonEmpty.length >= 2) {
    const first = nonEmpty[0].accuracy
    const last = nonEmpty[nonEmpty.length - 1].accuracy
    const diff = last - first
    return diff > 0 ? `提升 ${diff}%` : diff < 0 ? `下降 ${Math.abs(diff)}%` : '表现稳定'
  }
  if (nonEmpty.length === 1) return `当前 ${nonEmpty[0].accuracy}%`
  return '暂无作答记录'
}

function buildTrendEmptyPatch(summary, available) {
  return {
    trendData: [],
    trendPoints: [],
    trendSegments: [],
    trendLastPoint: null,
    trendAreaStyle: '',
    trendSummary: summary,
    trendAvailable: available,
  }
}

module.exports = {
  createTrendLoadController,
}
