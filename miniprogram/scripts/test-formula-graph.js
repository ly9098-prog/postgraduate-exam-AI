/* eslint-disable no-console */
const assert = require('assert')
const {
  resolveGraphImageUrl,
  resolveGraphThumbnailUrl,
  resolveGraphPreviewUrl,
  computeDisplayGraphUrl,
} = require('../subpackages/formulas/utils/formula-graph')

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

// Test 8: preview URL prefers the thumbnail over the master image
const card8 = {
  id: 8,
  card_type: 'function_graph',
  graph_asset: {
    image_url: 'https://example.com/graphs/8/uploaded/full.png',
    thumbnail_url: 'https://example.com/graphs/8/uploaded/full-thumb.png',
  },
}
assert.strictEqual(resolveGraphPreviewUrl(card8), 'https://example.com/graphs/8/uploaded/full-thumb.png')

// Test 9: preview URL falls back to master when no thumbnail
const card9 = { id: 9, graph_asset: { image_url: 'https://example.com/only.png' } }
assert.strictEqual(resolveGraphPreviewUrl(card9), 'https://example.com/only.png')

// Test 10: progressive display URL state machine
const FULL = 'https://example.com/full.png'
const THUMB = 'https://example.com/full-thumb.png'
// No master image → whatever thumbnail exists
assert.strictEqual(computeDisplayGraphUrl('', THUMB, false), THUMB)
assert.strictEqual(computeDisplayGraphUrl('', '', false), '')
// Distinct thumbnail available and master not ready yet → thumbnail first
assert.strictEqual(computeDisplayGraphUrl(FULL, THUMB, false), THUMB)
// Master ready (preloader finished) → swap to master
assert.strictEqual(computeDisplayGraphUrl(FULL, THUMB, true), FULL)
// No distinct thumbnail → master directly
assert.strictEqual(computeDisplayGraphUrl(FULL, '', false), FULL)
assert.strictEqual(computeDisplayGraphUrl(FULL, FULL, false), FULL)
// Null inputs tolerated
assert.strictEqual(computeDisplayGraphUrl(null, null, false), '')

console.log('All formula-graph tests passed.')
