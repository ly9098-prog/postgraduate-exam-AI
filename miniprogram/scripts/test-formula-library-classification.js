const assert = require('node:assert/strict')

const api = require('../utils/api')

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

function createPageInstance(dataPatch = {}) {
  return {
    ...pageConfig,
    data: {
      ...pageConfig.data,
      initialLoading: false,
      loadingMore: false,
      hasMore: true,
      tags: [],
      activeTags: [],
      favoriteIds: [],
      ...dataPatch,
    },
    setData(patch, callback) {
      Object.assign(this.data, patch)
      if (typeof callback === 'function') callback()
    },
  }
}

async function run() {
  assert.ok(pageConfig, 'formula library page should register itself')
  assert.equal(typeof pageConfig.isFunctionGraphItem, 'function')
  assert.equal(typeof pageConfig.filterFormulaItemsByLibraryType, 'function')

  assert.equal(
    pageConfig.isFunctionGraphItem({ card_type: 'function_graph' }),
    true,
    'an explicitly marked function graph must stay in the graph category even without an image',
  )
  assert.equal(
    pageConfig.isFunctionGraphItem({ card_type: 'pure_formula', graph_image_url: 'https://example.com/graph.png' }),
    false,
    'an explicit pure-formula override must win over automatic image detection',
  )
  assert.equal(
    pageConfig.isFunctionGraphItem({ graph_asset: { image_url: 'https://example.com/graph.png' } }),
    true,
    'legacy data with a graph asset should be detected automatically',
  )
  assert.equal(
    pageConfig.isFunctionGraphItem({ graph_thumbnail_url: 'https://example.com/thumb.png' }),
    true,
    'legacy flat thumbnail fields should be detected automatically',
  )
  assert.equal(
    pageConfig.isFunctionGraphItem({ title: '极限公式' }),
    false,
    'a plain formula without graph metadata should not enter the graph category',
  )

  const context = { data: { favoriteIds: [] } }
  const decorated = pageConfig.decorateFormulaItems.call(context, [
    { id: 1, title: '显式图像', card_type: 'function_graph' },
    { id: 2, title: '纯公式覆盖', card_type: 'pure_formula', graph_image_url: 'https://example.com/ignored.png' },
    { id: 3, title: '自动识别', graph_asset: { thumbnail_url: 'https://example.com/auto.png' } },
    { id: 4, title: '普通公式' },
  ])

  assert.deepEqual(
    decorated.map((item) => item.isFunctionGraph),
    [true, false, true, false],
  )
  assert.equal(decorated[0].graphPreviewUrl, '', 'explicit graph entries may intentionally have no image yet')
  assert.equal(decorated[2].graphPreviewUrl, 'https://example.com/auto.png')

  const formulaItems = pageConfig.filterFormulaItemsByLibraryType(decorated, 'formula')
  const graphItems = pageConfig.filterFormulaItemsByLibraryType(decorated, 'function_graph')
  assert.equal(formulaItems.length, 4, 'the formula tab should include every formula, including graph entries')
  assert.deepEqual(graphItems.map((item) => item.id), [1, 3], 'the graph tab should only contain resolved graph entries')

  const originalRequest = api.request
  const requests = []
  api.request = async (method, url, params) => {
    requests.push({ method, url, params })
    return {
      total: 1,
      items: [
        { id: 10, title: '普通公式', card_type: 'pure_formula' },
        { id: 11, title: '函数图像', card_type: 'function_graph' },
      ],
    }
  }

  try {
    const page = createPageInstance({
      activeLibraryType: 'function_graph',
      page: 1,
      pageSize: 20,
      formulas: [],
    })
    await page.loadFormulas(true)

    assert.equal(requests.length, 1)
    assert.equal(requests[0].url, '/formulas')
    assert.equal(requests[0].params.library_type, 'function_graph', 'the selected category must be sent to the API')
    assert.deepEqual(page.data.formulas.map((item) => item.id), [11], 'client fallback must prevent mixed cards')
  } finally {
    api.request = originalRequest
  }

  console.log('formula library classification tests passed')
}

run().catch((error) => {
  console.error(error)
  process.exitCode = 1
})
