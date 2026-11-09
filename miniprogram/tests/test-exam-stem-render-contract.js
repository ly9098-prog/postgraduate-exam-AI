const assert = require('node:assert/strict')
const { test } = require('node:test')
const { loadRenderer, exportedNames, plain, codePorts } = require('./exam-stem-render-support')

test('exports, function arity, mode identity and per-load state remain stable', () => {
  const first = loadRenderer().renderer
  const second = loadRenderer().renderer
  assert.deepEqual(Object.keys(first), exportedNames)
  assert.equal(first.buildRenderModel.length, 3)
  assert.equal(first.buildOptionList.length, 3)
  assert.notEqual(first.RENDER_MODE, second.RENDER_MODE)
  first.RENDER_MODE.RICH_TEXT = 'CUSTOM_RICH'
  assert.equal(first.buildRenderModel({ content: 'plain' }).mode, 'CUSTOM_RICH')
  assert.equal(second.RENDER_MODE.RICH_TEXT, 'RICH_TEXT')
})

const modes = [
  ['plain', { text: 'plain' }, {}, 'RICH_TEXT'],
  ['empty', {}, {}, 'RICH_TEXT'],
  ['latex', { text: '$$\\int x dx$$' }, {}, 'LATEX'],
  ['code', { text: 'int f() {\n  return 1;\n}' }, {}, 'CODE'],
  ['mixed', { text: 'Explain.\n\nint f() {\n  return 1;\n}' }, {}, 'MIXED'],
  ['segments', { text: 'plain', render_mode: 'segments',
    segments: [{ type: 'text', text: 'plain' }] }, { enableMathImage: true }, 'SEGMENTS'],
  ['stale segments', { text: 'current', render_mode: 'segments',
    segments: [{ type: 'text', text: 'old' }] }, { enableMathImage: true }, 'RICH_TEXT'],
  ['code segments', { text: 'int x = 1;', render_mode: 'segments',
    segments: [{ type: 'code', code: 'int x = 1;' }] }, {}, 'SEGMENTS'],
  ['image segments', { text: 'see the table below', render_mode: 'segments',
    segments: [
      { type: 'text', text: 'see the table below' },
      { type: 'image', url: '/static/question-assets/t.webp', alt: '进程调度表', display: true },
    ] }, {}, 'SEGMENTS'],
  ['code_image segments', { text: 'see the snippet', render_mode: 'segments',
    segments: [
      { type: 'text', text: 'see the snippet' },
      { type: 'code_image', url: '/static/question-assets/c.webp' },
    ] }, {}, 'SEGMENTS'],
  ['stale segments with image extension', { text: 'current', render_mode: 'segments',
    segments: [
      { type: 'text', text: 'old' },
      { type: 'image', url: '/static/question-assets/t.webp', alt: '进程调度表' },
    ] }, {}, 'RICH_TEXT'],
  ['visual-only segments without text', { text: '见下表，选出正确选项', render_mode: 'segments',
    segments: [
      { type: 'newline' },
      { type: 'image', url: '/static/question-assets/t.webp', alt: '表1' },
    ] }, {}, 'SEGMENTS'],
  ['mixed math_image stays gated', { text: '求 x 的值', render_mode: 'segments',
    segments: [
      { type: 'text', text: '求 x 的值' },
      { type: 'math_image', url: '/static/m.png', alt: 'x' },
      { type: 'image', url: '/static/i.png', alt: '图1' },
    ] }, {}, 'SEGMENTS'],
  ['code image alt extension', { text: '见下表 进程调度表', render_mode: 'segments',
    segments: [
      { type: 'text', text: '见下表 ' },
      { type: 'image', url: '/static/t.webp', alt: '进程调度表' },
      { type: 'code', code: 'for(;;){}' },
    ] }, {}, 'SEGMENTS'],
  ['ocr placeholder differences', {
    text: '代码如下：[代码区域见上图]输出是什么？', render_mode: 'segments',
    segments: [
      { type: 'text', text: '34.代码如下：输出是什么？' },
      { type: 'image', url: '/static/c.webp', alt: '代码' },
    ] }, {}, 'SEGMENTS'],
]

for (const [name, content, config, mode] of modes) {
  test(`${name} retains exclusive payloads and trace`, () => {
    const { renderer } = loadRenderer()
    const model = renderer.buildRenderModel({ id: 7, content }, null, config)
    assert.equal(model.mode, mode)
    assert.deepEqual(Object.keys(model), [
      'mode', 'richTextNodes', 'html', 'segments', 'rawText', 'blocks', 'renderTrace',
    ])
    assert.equal(model.renderTrace.questionId, 7)
    assert.equal(model.renderTrace.timestamp, 1700000000000)
    assert.deepEqual(plain(model.renderTrace.pipeline), ['detect', 'route', 'render'])
    assert.equal(model.html.length > 0, mode === 'LATEX')
    assert.equal(model.rawText.length > 0, mode === 'CODE')
    assert.equal(model.richTextNodes.length > 0, mode === 'RICH_TEXT')
    assert.equal(model.segments.length > 0, mode === 'SEGMENTS')
    assert.equal(model.blocks.length > 0, mode === 'MIXED')
  })
}

test('visual-only segments prepend the canonical stem text', () => {
  const { renderer } = loadRenderer()
  const model = renderer.buildRenderModel({ id: 21, content: {
    text: '见下表，选出正确选项', render_mode: 'segments',
    segments: [{ type: 'newline' }, { type: 'image', url: '/static/x.webp', alt: '表1' }],
  } }, null, {})
  assert.equal(model.mode, 'SEGMENTS')
  assert.equal(model.segments[0].type, 'text')
  assert.equal(model.segments[0].text, '见下表，选出正确选项')
})

test('math_image segments stay gated when enableMathImage is false', () => {
  const { renderer } = loadRenderer()
  const model = renderer.buildRenderModel({ id: 22, content: {
    text: '求 x 的值', render_mode: 'segments',
    segments: [
      { type: 'text', text: '求 x 的值' },
      { type: 'math_image', url: '/static/m.png', alt: 'x' },
      { type: 'image', url: '/static/i.png', alt: '图1' },
    ],
  } }, null, {})
  assert.equal(model.mode, 'SEGMENTS')
  assert.equal(model.segments.some((segment) => segment.type === 'math_image'), false)
})

test('canonical line breaks are restored into matching segment text', () => {
  const { renderer } = loadRenderer()
  const model = renderer.buildRenderModel({ id: 23, content: {
    text: '则图中\n①、\n②、\n③阶段分别使用的协议是？', render_mode: 'segments',
    segments: [
      { type: 'text', text: '则图中①、②、③阶段分别使用的协议是？' },
      { type: 'image', url: '/static/d.png', alt: '流程图' },
    ],
  } }, null, {})
  assert.equal(model.mode, 'SEGMENTS')
  assert(model.segments[0].text.includes('\n'),
    'restored text must keep canonical line breaks: ' + model.segments[0].text)
})

test('content and question getters retain their count and final id timing', () => {
  const seen = []
  const content = { get text() { seen.push('text'); return 'plain' },
    get segments() { seen.push('segments'); return [] },
    get render_mode() { seen.push('render_mode'); return 'plain' } }
  const q = { get content() { seen.push('content'); return content },
    get id() { seen.push('id'); return seen.length } }
  const { renderer } = loadRenderer()
  const model = renderer.buildRenderModel(q, null, {})
  assert.deepEqual(seen, ['content', 'text', 'segments', 'render_mode', 'id', 'id'])
  assert.equal(model.renderTrace.questionId, 6)
})

test('option enumeration failure precedes reading content.text', () => {
  const error = new Error('enumerate')
  const seen = []
  const options = new Proxy({}, { ownKeys() { seen.push('keys'); throw error } })
  const q = { get content() { seen.push('content'); return {
    get text() { throw new Error('late text') },
  } } }
  const { renderer } = loadRenderer()
  assert.throws(() => renderer.buildRenderModel(q, options), value => value === error)
  assert.deepEqual(seen, ['content', 'keys'])
})

test('segment repair clones top-level objects and preserves nested references', () => {
  const nested = { opaque: true }
  const original = { type: 'image', url: '/asset', metadata: nested }
  const content = { text: 'caption', render_mode: 'segments', segments: [original] }
  const { renderer } = loadRenderer()
  const result = renderer.buildRenderModel({ content }, null, { enableMathImage: true })
  assert.equal(result.segments[0].text, 'caption')
  assert.notEqual(result.segments[1], original)
  assert.equal(result.segments[1].metadata, nested)
  assert.equal(original.url, '/asset')
  assert.deepEqual(Object.keys(original), ['type', 'url', 'metadata'])
})

test('successive segment reads are not replaced with a cached snapshot', () => {
  let reads = 0
  const content = { text: 'plain', render_mode: 'segments', get segments() {
    reads++
    return reads === 1 ? [{ type: 'text', text: 'plain' }] : [{ type: 'text', text: '1~\n2' }]
  } }
  const { renderer } = loadRenderer()
  const model = renderer.buildRenderModel({ content }, null, { enableMathImage: true })
  assert.equal(reads, 4)
  assert.equal(model.segments[0].text, '1~2')
})

test('SAFE_MODE is read before DISABLE_CODE_RECONSTRUCT and DEV twice', () => {
  const seen = []
  const config = new Proxy({}, { get(_, key) { seen.push(key); return false } })
  const { renderer } = loadRenderer({ code: codePorts({ containsCode: () => true }) })
  renderer.buildRenderModel({ content: 'int x = 1;' }, null, config)
  assert.deepEqual(seen, ['SAFE_MODE', 'DISABLE_CODE_RECONSTRUCT', 'DEV', 'DEV'])
})

test('reconstruction receives exact options, plain this and preserves failures', () => {
  const seen = []
  const failure = new Error('reconstruct')
  const code = codePorts({
    containsCode: () => true,
    shouldReconstructCode(value) { seen.push(['should', value]); return true },
    sanitizeImportedCodeArtifacts(value) { seen.push(['sanitize', value]); return value },
    reconstructCode: function (value, options) {
      'use strict'
      assert.equal(this, undefined)
      seen.push(['reconstruct', value, plain(options)])
      throw failure
    },
  })
  const { renderer } = loadRenderer({ code })
  assert.throws(() => renderer.buildRenderModel({ content: 'int x = 1;' }),
    error => error === failure)
  assert.deepEqual(seen, [
    ['sanitize', 'int x = 1;'], ['should', 'int x = 1;'],
    ['reconstruct', 'int x = 1;',
      { fixOperators: false, fixStructure: true, fixIndent: false }],
  ])
})

test('DEV freezes only the model, uses original config for guard, swallows freeze errors', () => {
  let frozen
  const { renderer, events } = loadRenderer({ freeze(model) {
    frozen = model
    throw new Error('freeze unavailable')
  } })
  const model = renderer.buildRenderModel({ id: 1, content: 'plain' }, null, { DEV: true })
  assert.equal(frozen, model)
  assert.deepEqual(events, [])
  const ordinary = loadRenderer().renderer.buildRenderModel({ content: 'plain' }, null, { DEV: true })
  assert.equal(Object.isFrozen(ordinary), true)
  assert.equal(Object.isFrozen(ordinary.richTextNodes), false)
})

test('guard warning state resets and page labels survive calls', () => {
  const { renderer, events } = loadRenderer({ config: { DEV: true, BASE_URL: '' } })
  const q = { id: 1, content: { text: 'plain', render_mode: 'segments' } }
  renderer.setRenderGuardPage('first')
  renderer.buildRenderModel(q, null, { enableMathImage: false })
  renderer.setRenderGuardPage('second')
  renderer.buildRenderModel(q, null, { enableMathImage: true })
  assert.ok(events.some(row => row[0] === 'error' &&
    row[1].includes('Same stem') && row[1].includes('page: second')))
  renderer.resetRenderGuard()
  events.length = 0
  renderer.buildRenderModel(q, null, { enableMathImage: false })
  assert.deepEqual(events, [])
})

for (const [label, text] of [['number', 7], ['symbol', Symbol('text')]]) {
  test(`${label} text retains explicit string conversion`, () => {
    const { renderer } = loadRenderer()
    const model = renderer.buildRenderModel({ content: { text } })
    assert.equal(model.mode, 'RICH_TEXT')
    assert.equal(model.richTextNodes[0].children[0].text, String(text))
  })
}

test('stem coercion failure preserves identity and precedes id reads', () => {
  const failure = new Error('coercion')
  const text = { toString() { throw failure } }
  const { renderer } = loadRenderer()
  const q = { content: { text }, get id() { throw new Error('late id') } }
  assert.throws(() => renderer.buildRenderModel(q), error => error === failure)
})

for (const target of ['content', 'text', 'segments', 'render_mode',
  'SAFE_MODE', 'enableMathImage', 'DEV:1', 'DEV:2', 'id:1', 'id:2']) {
  test(`throwing ${target} getter propagates its exact error at the original read`, () => {
    const failure = new Error(target)
    const seen = []
    const counts = {}
    function trace(owner, values) {
      return new Proxy(values, { get(object, key) {
        const name = String(key)
        const count = counts[name] = (counts[name] || 0) + 1
        seen.push([owner, name, count])
        if (target === name || target === `${name}:${count}`) throw failure
        return object[key]
      } })
    }
    const content = trace('content', { text: 'plain', render_mode: 'segments',
      segments: [{ type: 'text', text: 'plain' }] })
    const q = trace('question', { content, id: 1 })
    const config = trace('config', { enableMathImage: false })
    const { renderer } = loadRenderer()
    assert.throws(() => renderer.buildRenderModel(q, null, config),
      error => error === failure)
    assert.ok(seen.length > 0)
    const [name, nth] = target.split(':')
    assert.equal(seen.at(-1)[1], name)
    if (nth) assert.equal(seen.at(-1)[2], Number(nth))
  })
}

test('static dependency exports are captured once with their original receivers', () => {
  const events = []
  const code = new Proxy(codePorts(), { get(target, key) {
    events.push(key)
    return target[key]
  } })
  const { renderer } = loadRenderer({ code })
  renderer.buildRenderModel({ content: 'plain' })
  assert.deepEqual(events, ['containsCode', 'shouldReconstructCode',
    'reconstructCode', 'sanitizeImportedCodeArtifacts'])
})

test('asset origin is captured at load time and the cache resolver retains its receiver', () => {
  const calls = []
  const config = { DEV: false, BASE_URL: 'https://before.invalid/api/v1' }
  const image = { resolve(value) {
    assert.equal(this, image)
    calls.push(value)
    return { value }
  } }
  const { renderer } = loadRenderer({ config, image })
  config.BASE_URL = 'https://after.invalid/api/v1'
  assert.deepEqual(renderer.resolveAssetUrl('/asset'), { value: 'https://before.invalid/asset' })
  assert.deepEqual(renderer.resolveAssetUrl('relative'), { value: 'relative' })
  assert.equal(renderer.resolveAssetUrl(null), '')
  assert.deepEqual(calls, ['https://before.invalid/asset', 'relative'])
})
