const assert = require('node:assert/strict')
const { test } = require('node:test')
const { loadRenderer, codePorts, plain } = require('./exam-stem-render-support')

test('leaf dependencies bind in their historical order before asset-origin capture', () => {
  const order = []
  const config = { DEV: false, get BASE_URL() { order.push('origin'); return '' } }
  const code = new Proxy(codePorts(), { get(target, key) {
    order.push(key)
    return target[key]
  } })
  const loaded = loadRenderer({ config, code })
  const dependencies = ['../../../config', './math-format', './code-reconstructor',
    './table-structure', './question-image-cache']
  assert.deepEqual(loaded.imports.filter(name => dependencies.includes(name)), dependencies)
  assert.deepEqual(order, ['containsCode', 'shouldReconstructCode', 'reconstructCode',
    'sanitizeImportedCodeArtifacts', 'origin'])
})

test('dependency binding errors propagate before origin or render execution', () => {
  const failure = new Error('binding failure')
  const order = []
  const code = new Proxy({}, { get(target, key) {
    order.push(key)
    throw failure
  } })
  const config = { get BASE_URL() { throw Error('origin must not be read') } }
  assert.throws(() => loadRenderer({ config, code }), error => error === failure)
  assert.deepEqual(order, ['containsCode'])
})

test('image resolver remains a live method on its captured cache object', () => {
  const image = { resolve: value => 'first:' + value }
  const { renderer } = loadRenderer({ image })
  assert.equal(renderer.resolveAssetUrl('asset'), 'first:asset')
  image.resolve = function (value) {
    assert.equal(this, image)
    return 'second:' + value
  }
  assert.equal(renderer.resolveAssetUrl('asset'), 'second:asset')
})

test('separate renderer loads do not share guard resets or page labels', () => {
  const config = { DEV: true }
  const first = loadRenderer({ config })
  const second = loadRenderer({ config })
  const q = { id: 501, content: { text: 'plain', render_mode: 'segments' } }
  for (const [name, loaded] of [['first', first], ['second', second]]) {
    loaded.renderer.setRenderGuardPage(name)
    loaded.renderer.buildRenderModel(q, null, { enableMathImage: name === 'second' })
    assert.equal(loaded.events.some(row => String(row[1]).includes('Same stem')), false)
  }
  first.renderer.resetRenderGuard()
  first.events.length = second.events.length = 0
  first.renderer.buildRenderModel(q, null, { enableMathImage: true })
  second.renderer.buildRenderModel(q, null, { enableMathImage: false })
  assert.equal(first.events.some(row => String(row[1]).includes('Same stem')), false)
  const warnings = second.events.filter(row => String(row[1]).includes('Same stem'))
  assert.equal(warnings.length, 1)
  assert.ok(warnings[0][1].includes('page: second'))
})

test('replacing the exported mode field does not replace the internal mode object', () => {
  const { renderer } = loadRenderer()
  const original = renderer.RENDER_MODE
  renderer.RENDER_MODE = { RICH_TEXT: 'ignored' }
  assert.equal(renderer.buildRenderModel({ content: 'plain' }).mode, 'RICH_TEXT')
  original.RICH_TEXT = 'updated'
  assert.equal(renderer.buildRenderModel({ content: 'plain' }).mode, 'updated')
})

test('option image projection preserves metadata and never rewrites its input', () => {
  const nested = { marker: true }
  const segment = { type: 'image', url: '/option.png', metadata: nested }
  const options = { A: { segments: [segment] } }
  const { renderer } = loadRenderer()
  const result = renderer.buildOptionList(options, ['A'], { A: true })
  assert.equal(result[0]._selected, true)
  assert.notEqual(result[0]._segments[0], segment)
  assert.equal(result[0]._segments[0].metadata, nested)
  assert.equal(result[0]._segments[0].url, 'https://fixture.invalid/option.png')
  assert.equal(segment.url, '/option.png')
  assert.deepEqual(plain(Object.keys(segment)), ['type', 'url', 'metadata'])
})
