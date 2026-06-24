/**
 * Render Invariant regression tests for stem-render.js
 * Run: cd miniprogram && node tests/test-render-invariant.js
 */
var { RENDER_MODE, buildRenderModel, resetRenderGuard, setRenderGuardPage, buildRichTextNodes } = require('../utils/stem-render')

var passed = 0
var failed = 0

function assert(condition, msg) {
  if (condition) { passed++; return }
  failed++
  console.error('  FAIL:', msg)
}

function assertNeq(actual, expected, msg) {
  if (actual !== expected) { passed++; return }
  failed++
  console.error('  FAIL:', msg + ' (should NOT equal ' + JSON.stringify(expected) + ')')
}

function assertEq(actual, expected, msg) {
  if (actual === expected) { passed++; return }
  failed++
  console.error('  FAIL:', msg)
  console.error('    expected:', JSON.stringify(expected))
  console.error('    actual:', JSON.stringify(actual))
}

function group(name, fn) {
  console.log('\n' + name)
  fn()
}

var mockConfig = { enableMathImage: false, DEV: true }

// ── Plain text stems → RICH_TEXT ──

group('Plain text stem', function () {
  var q = { id: 1, content: { text: '1+1等于几？' } }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.RICH_TEXT, 'plain text → RICH_TEXT')
  assert(result.richTextNodes.length > 0, 'richTextNodes is populated')
  assertEq(result.html, '', 'html is empty')
  assertEq(result.segments.length, 0, 'segments is empty')
})

group('Plain text with simple inline math → RICH_TEXT', function () {
  var q = { id: 2, content: { text: '设 $f(x)=x^2$，求零点' } }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.RICH_TEXT, 'simple inline math → RICH_TEXT')
  assert(result.richTextNodes.length > 0, 'richTextNodes is populated')
})

// ── Multi-line stems → RICH_TEXT ──

group('Multi-line code stem → CODE', function () {
  var q = { id: 3, content: { text: 'void main() {\n  printf("hello");\n}' } }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.CODE, 'code → CODE')
  assert(result.rawText.length > 0, 'rawText is populated for code stem')
  assertEq(result.html, '', 'html is empty for code stem')
  assertEq(result.richTextNodes.length, 0, 'richTextNodes is empty for code stem')
})

group('Multi-line plain text → RICH_TEXT', function () {
  var q = { id: 4, content: { text: '第一行\n第二行\n第三行' } }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.RICH_TEXT, 'multiline → RICH_TEXT')
  // Verify br nodes are inserted
  var children = result.richTextNodes[0].children
  var brCount = children.filter(function (c) { return c.name === 'br' }).length
  assertEq(brCount, 2, '2 br nodes for 3 lines')
})

group('Table-like stem → RICH_TEXT', function () {
  var q = { id: 5, content: { text: 'A | B\n---|---\n1 | 2' } }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.RICH_TEXT, 'table → RICH_TEXT')
})

// ── LaTeX stems → LATEX ──

group('Display math $$...$$ → LATEX', function () {
  var q = { id: 6, content: { text: '求 $$\\int_0^1 x^2 dx$$ 的值' } }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.LATEX, 'display LaTeX → LATEX')
  assert(result.html.length > 0, 'html is populated for LATEX')
  assertEq(result.richTextNodes.length, 0, 'richTextNodes is empty')
})

group('Complex LaTeX commands → LATEX', function () {
  var q = { id: 7, content: { text: '设 $\\frac{a}{b}$ 为有理数' } }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.LATEX, '\\frac → LATEX')
})

group('OCR imported display LaTeX → LATEX', function () {
  var q = { id: 8, content: { text: '计算 $$\\frac{1}{2} + \\frac{1}{3}$$ 的结果' } }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.LATEX, 'OCR $$ → LATEX')
})

// ── SEGMENTS mode ──

group('SEGMENTS mode (enableMathImage=true)', function () {
  var cfg = { enableMathImage: true, DEV: true }
  var q = { id: 9, content: { text: 'mixed content here', render_mode: 'segments' } }
  var result = buildRenderModel(q, null, cfg)
  assertEq(result.mode, RENDER_MODE.SEGMENTS, 'render_mode=segments → SEGMENTS')
  assert(result.segments.length > 0, 'segments populated')
})

group('SEGMENTS mode disabled when enableMathImage=false', function () {
  var q = { id: 10, content: { text: 'plain text', render_mode: 'segments' } }
  var result = buildRenderModel(q, null, mockConfig)
  assertNeq(result.mode, RENDER_MODE.SEGMENTS, 'SEGMENTS not selected when disabled')
})

// ── Immutability ──

group('RenderModel is frozen in DEV', function () {
  var q = { id: 11, content: { text: 'test stem' } }
  var result = buildRenderModel(q, null, mockConfig)
  var originalMode = result.mode
  result.mode = 'MUTATED'
  assertEq(result.mode, originalMode, 'mode unchanged after mutation attempt (frozen)')
})

group('RenderModel has renderTrace with correct structure', function () {
  var q = { id: 101, content: { text: 'void f() { int x; }' } }
  var result = buildRenderModel(q, null, mockConfig)
  assert(result.renderTrace, 'renderTrace is present')
  assertEq(result.renderTrace.questionId, 101, 'trace has questionId')
  assert(typeof result.renderTrace.timestamp === 'number', 'trace has timestamp')
  assertEq(result.renderTrace.pipeline.length, 3, 'trace has 3 pipeline steps')
})

// ── Render Invariant: consistency ──

group('Render invariant: same input → same mode', function () {
  resetRenderGuard()
  var q = { id: 12, content: { text: '设 $f(x)=x^2$，求零点' } }
  var r1 = buildRenderModel(q, null, mockConfig)
  var r2 = buildRenderModel(q, null, mockConfig)
  assertEq(r1.mode, r2.mode, 'same input → same mode')
  assertEq(r1.richTextNodes[0].children.length, r2.richTextNodes[0].children.length, 'same nodes count')
})

// ── Single render root invariant ──

function checkSingleRoot(result) {
  var active = [
    result.mode === RENDER_MODE.RICH_TEXT && result.richTextNodes.length > 0,
    result.mode === RENDER_MODE.LATEX && result.html.length > 0,
    result.mode === RENDER_MODE.SEGMENTS && result.segments.length > 0,
    result.mode === RENDER_MODE.CODE && result.rawText.length > 0
  ]
  var count = active.filter(Boolean).length
  return count === 1
}

group('Single render root invariant', function () {
  var cases = [
    { id: 13, content: { text: 'plain' } },
    { id: 14, content: { text: 'line1\nline2' } },
    { id: 15, content: { text: '$$x^2$$' } }
  ]
  cases.forEach(function (c) {
    var r = buildRenderModel(c, null, mockConfig)
    assert(checkSingleRoot(r), 'exactly one render root active for: ' + JSON.stringify(c.content.text).slice(0, 40))
  })
})

// ── Edge cases ──

group('Empty stem → RICH_TEXT', function () {
  var q = { id: 16, content: {} }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.RICH_TEXT, 'empty → RICH_TEXT')
  assert(result.richTextNodes.length > 0, 'has fallback nodes')
})

group('Null question → RICH_TEXT fallback', function () {
  var result = buildRenderModel(null, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.RICH_TEXT, 'null → RICH_TEXT')
})

group('Stem with HTML tags → RICH_TEXT', function () {
  var q = { id: 17, content: { text: '文字<sub>下标</sub>说明' } }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.RICH_TEXT, 'HTML tags → RICH_TEXT')
})

// ── buildRichTextNodes ──

group('buildRichTextNodes helper', function () {
  var nodes = buildRichTextNodes('hello')
  assertEq(nodes.length, 1, 'single paragraph wrapper')
  assertEq(nodes[0].name, 'p', 'wrapper is <p>')
  assertEq(nodes[0].children.length, 1, 'single text child')
  assertEq(nodes[0].children[0].type, 'text', 'child is text type')
  assertEq(nodes[0].children[0].text, 'hello', 'text preserved')
})

// ── Summary ──

console.log('\n' + '='.repeat(50))
console.log('Total: ' + (passed + failed) + '  Passed: ' + passed + '  Failed: ' + failed)
if (failed > 0) {
  console.error('\nSOME TESTS FAILED')
  process.exit(1)
} else {
  console.log('\nAll tests passed.')
}
