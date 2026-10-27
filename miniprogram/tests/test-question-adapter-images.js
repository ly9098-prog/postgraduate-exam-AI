const assert = require('node:assert/strict')
const { test } = require('node:test')
const { loadAdapter, plain } = require('./question-adapter-support')

for (const pkg of ['study', 'exam']) {
  test(`${pkg}: raw image deduplication precedes URL resolution`, () => {
    const calls = []
    const stem = { resolveAssetUrl(url) { assert.equal(this, stem); calls.push(url); return 'resolved' } }
    const { adapter } = loadAdapter(pkg, { stem })
    const q = { image_url: ['/a', '/a', null, 3], content: { image_url: ['/a', '/b'] } }
    assert.deepEqual(plain(adapter.getQuestionImages(q)), ['resolved', 'resolved'])
    assert.deepEqual(calls, ['/a', '/b'])
  })

  test(`${pkg}: embedded table URLs are normalized in encounter order`, () => {
    const { adapter } = loadAdapter(pkg, { stem: { resolveAssetUrl: value => 'https://host' + value } })
    const content = { segments: [
      { type: 'table', url: '/a/', source_image_url: '/b/', fallback_image_url: '/a' },
      { type: 'image', url: '/b' },
      { type: 'table_markdown', source_image_url: '/ignored' },
    ] }
    assert.deepEqual(plain(adapter.getEmbeddedImageUrls(content)), ['https://host/a', 'https://host/b'])
  })

  for (const mode of ['SEGMENTS', 'RICH_TEXT', 'CODE']) {
    test(`${pkg}: ${mode} determines whether embedded images suppress extra images`, () => {
      const { adapter } = loadAdapter(pkg, { stem: { resolveAssetUrl: value => value } })
      const q = { image_url: ['https://host/a/', 'https://host/b'], _renderModel: { mode },
        content: { segments: [{ type: 'image', url: 'https://host/a' }] } }
      assert.deepEqual(plain(adapter.computeExtraImages(q)),
        mode === 'SEGMENTS' ? ['https://host/b'] : q.image_url)
    })
  }

  test(`${pkg}: prefetch recursively collects tables, cells and option images`, () => {
    const { adapter } = loadAdapter(pkg, { stem: { resolveAssetUrl: value => value } })
    const q = {
      image_url: ['https://host/main/'],
      content: { segments: [
        { type: 'table_markdown', source_image_url: 'https://host/source',
          fallback_image_url: 'https://host/main', cells: [
            { blocks: [{ type: 'image', url: 'https://host/cell' }],
              segments: [{ type: 'math_image', url: 'https://host/math' }] },
          ], blocks: [{ type: 'code_image', url: 'https://host/block' }] },
      ] },
      options: { B: { imageUrl: 'https://host/option', segments: [
        { type: 'image', url: 'https://host/cell' },
      ] } },
    }
    assert.deepEqual(plain(adapter.getQuestionPrefetchUrls(q)), [
      'https://host/main', 'https://host/source', 'https://host/block',
      'https://host/cell', 'https://host/math', 'https://host/option',
    ])
  })

  test(`${pkg}: image resolver failure propagates before later image reads`, () => {
    const error = new Error('resolver failure')
    const { adapter } = loadAdapter(pkg, { stem: { resolveAssetUrl() { throw error } } })
    const q = { image_url: ['/first'], get content() { throw Error('late content') } }
    assert.throws(() => adapter.getQuestionImages(q), value => value === error)
  })

  test(`${pkg}: empty image inputs return empty lists`, () => {
    const { adapter } = loadAdapter(pkg)
    for (const name of ['getQuestionImages', 'getEmbeddedImageUrls',
      'computeExtraImages', 'getQuestionPrefetchUrls']) {
      assert.deepEqual(plain(adapter[name](null)), [])
    }
  })
}
