/* eslint-disable no-console */
const assert = require('assert')
const { resolveGraphImageUrl, resolveGraphThumbnailUrl } = require('../subpackages/formulas/utils/formula-graph')

// Test 1: Standard backend response (graph_asset.image_url)
const card1 = {
  id: 1,
  card_type: 'function_graph',
  graph_asset: {
    image_url: 'https://example.com/graphs/1/template/abc.png',
    thumbnail_url: 'https://example.com/graphs/1/template/abc-thumb.png',
  },
}
assert.strictEqual(resolveGraphImageUrl(card1), 'https://example.com/graphs/1/template/abc.png')
assert.strictEqual(resolveGraphThumbnailUrl(card1), 'https://example.com/graphs/1/template/abc-thumb.png')

// Test 2: No graph_asset at all
const card2 = { id: 2, card_type: 'pure_formula' }
assert.strictEqual(resolveGraphImageUrl(card2), '')
assert.strictEqual(resolveGraphThumbnailUrl(card2), '')

// Test 3: graph_asset with only image_url (no thumbnail)
const card3 = {
  id: 3,
  card_type: 'function_graph',
  graph_asset: { image_url: 'https://example.com/graph.png' },
}
assert.strictEqual(resolveGraphImageUrl(card3), 'https://example.com/graph.png')
assert.strictEqual(resolveGraphThumbnailUrl(card3), 'https://example.com/graph.png')

// Test 4: Legacy flat field
const card4 = { id: 4, graphImageUrl: 'https://example.com/legacy.png' }
assert.strictEqual(resolveGraphImageUrl(card4), 'https://example.com/legacy.png')

// Test 5: null/undefined card
assert.strictEqual(resolveGraphImageUrl(null), '')
assert.strictEqual(resolveGraphImageUrl(undefined), '')
assert.strictEqual(resolveGraphImageUrl({}), '')

// Test 6: graph_asset with null image_url
const card6 = { id: 6, graph_asset: { image_url: null } }
assert.strictEqual(resolveGraphImageUrl(card6), '')

// Test 7: graph_image_url flat legacy field
const card7 = { id: 7, graph_image_url: 'https://example.com/legacy2.png' }
assert.strictEqual(resolveGraphImageUrl(card7), 'https://example.com/legacy2.png')

console.log('All formula-graph tests passed.')
