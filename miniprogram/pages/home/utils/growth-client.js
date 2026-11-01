function fetchGrowthResponses(apiClient) {
  if (!apiClient || typeof apiClient.get !== 'function') {
    return Promise.reject(new TypeError('growth API client must expose get()'))
  }
  return Promise.all([
    apiClient.get('/stats/dashboard'),
    apiClient.get('/stats/growth').catch(() => null),
    apiClient.get('/study-hub/overview').catch((error) => {
      console.warn('加载智能学习中心失败，回退基础首页', error)
      return null
    }),
    apiClient.get('/study-plan/overview').catch((error) => {
      console.warn('加载长期学习计划失败', error)
      return null
    }),
  ]).then((responses) => ({
    dashboard: responses[0],
    growth: responses[1],
    hub: responses[2],
    plan: responses[3],
  }))
}

function isGrowthStale(options = {}) {
  return !(
    options.alive &&
    options.visible &&
    options.requestSeq === options.growthSeq &&
    options.showSeq === options.currentShowSeq
  )
}

module.exports = { fetchGrowthResponses, isGrowthStale }
