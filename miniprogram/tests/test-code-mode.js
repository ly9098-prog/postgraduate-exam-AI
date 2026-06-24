/**
 * Regression tests for CODE render mode (zero-HTML raw text).
 *
 * Run: node tests/test-code-mode.js
 *
 * Covers:
 *   1. CODE mode routing in buildRenderModel()
 *   2. Raw text preservation (no HTML entities, no escaping)
 *   3. No reconstructCode in render pipeline (code passes through unchanged)
 *   4. Edge cases: code + inline math, mixed content
 */
var { RENDER_MODE, buildRenderModel, buildRichTextNodes } = require('../utils/stem-render')

var passed = 0
var failed = 0

function assert(condition, msg) {
  if (condition) { passed++; return }
  failed++
  console.error('  FAIL:', msg)
}

function assertEq(actual, expected, msg) {
  if (actual === expected) { passed++; return }
  failed++
  console.error('  FAIL:', msg)
  console.error('    expected:', JSON.stringify(expected))
  console.error('    actual:', JSON.stringify(actual))
}

function assertNeq(actual, expected, msg) {
  if (actual !== expected) { passed++; return }
  failed++
  console.error('  FAIL:', msg + ' (should NOT equal ' + JSON.stringify(expected) + ')')
}

function assertIn(haystack, needle, msg) {
  if (haystack.indexOf(needle) !== -1) { passed++; return }
  failed++
  console.error('  FAIL:', msg)
  console.error('    needle:', JSON.stringify(needle))
  console.error('    haystack was:', JSON.stringify(haystack.slice(0, 200)))
}

function group(name, fn) {
  console.log('\n' + name)
  fn()
}

var mockConfig = { enableMathImage: false, DEV: true }

// ==========================================================================
// 1. CODE mode routing
// ==========================================================================

group('CODE mode — well-formatted DS code → CODE', function () {
  var q = {
    id: 2401,
    content: { text: 'void f() {\n  int sum = 0;\n  for(int i = 1; i < n; i *= 2)\n    for(int j = 0; j < i; j++)\n      sum++;\n}' }
  }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.CODE, 'DS code → CODE')
  assert(result.rawText.length > 0, 'rawText populated')
  assert(result.rawText.indexOf('  int sum') >= 0, 'rawText preserves leading spaces')
  assertEq(result.html, '', 'html is empty (zero-HTML)')
  assertEq(result.richTextNodes.length, 0, 'richTextNodes empty')
})

group('CODE mode — tree recursion function → CODE', function () {
  var q = {
    id: 2402,
    content: { text: 'void countLeaf(BiTree T) {\n  if (T == NULL) return;\n  count++;\n  countLeaf(T->lchild);\n}' }
  }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.CODE, 'BiTree code → CODE')
  assert(result.rawText.indexOf('BiTree') >= 0, 'BiTree keyword preserved')
  // raw text preserves -> as-is (no HTML escaping)
  assert(result.rawText.indexOf('->') >= 0, '-> preserved in raw text')
})

group('CODE mode — while loop linked list → CODE', function () {
  var q = {
    id: 2403,
    content: { text: 'while (p) {\n  p = p->next;\n  count++;\n}' }
  }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.CODE, 'linked list code → CODE')
})

// ==========================================================================
// 2. CODE raw text preservation (no transformation)
// ==========================================================================

group('CODE rawText — identity preservation', function () {
  // Code must pass through without HTML entities or escaping.
  // Note: _cleanStemText may deduplicate consecutive lines with identical
  // trimmed content (e.g., "  }" and "}") — that's pre-existing behavior.
  var code = 'void f() {\n  int x = 1;\n  while (x < 10 && x > 0) {\n    x++;\n  }\n}'
  var q = { id: 2411, content: { text: code } }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.CODE, 'code → CODE')
  assert(result.rawText.length > 0, 'rawText populated')
  assert(result.rawText.indexOf('<') >= 0, 'raw < preserved (not HTML-escaped)')
  assert(result.rawText.indexOf('>') >= 0, 'raw > preserved (not HTML-escaped)')
  assert(result.rawText.indexOf('&nbsp;') === -1, 'no &nbsp; HTML entities injected')
  assert(result.rawText.indexOf('&amp;') === -1, 'no &amp; HTML escaping')
  assert(result.rawText.indexOf('&lt;') === -1, 'no &lt; entity injected')
  assert(result.rawText.indexOf('&gt;') === -1, 'no &gt; entity injected')
})

group('CODE rawText — tab preservation', function () {
  var code = 'void f() {\n\tint x;\n\tif (x < 10) x++;\n}'
  var q = { id: 2412, content: { text: code } }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.CODE, 'code with tabs → CODE')
  assertEq(result.rawText, code, 'tabs preserved verbatim')
})

// ==========================================================================
// 3. No reconstructCode in render pipeline
// ==========================================================================

group('No reconstructCode — well-formatted code unchanged', function () {
  // Code with proper newlines must pass through entirely unchanged
  var code = 'void f() {\n  int sum = 0;\n  for(int i = 1; i < n; i *= 2)\n    for(int j = 0; j < i; j++)\n      sum++;\n}'
  var q = { id: 2421, content: { text: code } }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.CODE, 'well-formatted code → CODE')
  assertEq(result.rawText, code, 'rawText equals original — no restructuring')
  // Count newlines match
  var newlines = result.rawText.split('\n').length
  assertEq(newlines, 6, 'exactly 6 lines preserved (got ' + newlines + ')')
})

group('No reconstructCode — compressed code stays compressed', function () {
  // Single-line compressed code should NOT be split
  var code = 'void f(){int sum=0;for(int i=0;i<n;i++)sum++;}'
  var q = { id: 2422, content: { text: code } }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.CODE, 'compressed code → CODE')
  assertEq(result.rawText, code, 'compressed code unchanged (no newlines inserted)')
  assert(result.rawText.indexOf('\n') === -1, 'no newlines added')
})

group('No reconstructCode — broken operators preserved as-is', function () {
  // OCR-broken operators should NOT be fixed in render pipeline
  var code = 'void f() {\n  for(i = 0; i < = n; i + +)\n    sum + = i;\n}'
  var q = { id: 2423, content: { text: code } }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.CODE, 'broken op code → CODE')
  assertEq(result.rawText, code, 'broken operators preserved as-is')
  assert(result.rawText.indexOf('< =') >= 0, '< = not merged to <=')
  assert(result.rawText.indexOf('+ +') >= 0, '+ + not merged to ++')
})

// ==========================================================================
// 4. Mode priority: CODE vs LATEX vs RICH_TEXT
// ==========================================================================

group('Mode priority — code + LaTeX → LATEX (not CODE)', function () {
  // Has both code signals AND \frac LaTeX command — LATEX wins
  var q = {
    id: 2431,
    content: { text: 'int main() { return \\frac{1}{2}; }' }
  }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.LATEX, 'code + \\frac → LATEX')
})

group('Mode priority — code + inline math without LaTeX commands → CODE', function () {
  // Has $P_1$ but no \commands — containsCode matches but hasLatex doesn't
  var q = {
    id: 2432,
    content: { text: 'void main() {\n  int $P_1$ = 0;\n}' }
  }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.CODE, 'code + simple inline math → CODE')
  assert(result.rawText.indexOf('$') >= 0, '$ preserved for mp-html/KaTeX')
})

group('Mode priority — plain text without code → RICH_TEXT', function () {
  var q = {
    id: 2433,
    content: { text: '设 $f(x)=x^2$，求零点' }
  }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.RICH_TEXT, 'plain text → RICH_TEXT')
})

group('Mode priority — multi-line plain text no code → RICH_TEXT', function () {
  var q = {
    id: 2434,
    content: { text: '第一行\n第二行\n第三行' }
  }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.RICH_TEXT, 'plain multiline → RICH_TEXT')
})

// ==========================================================================
// 5. Render invariant: single root
// ==========================================================================

group('CODE mode — single render root invariant', function () {
  var cases = [
    { id: 2441, content: { text: 'void f() {\n  int sum = 0;\n  for(;;) {}\n}' } },
    { id: 2442, content: { text: 'void f() {\n  int x = 1;\n}' } },
    { id: 2443, content: { text: 'void f() {\n  while(p) { p = p->next; }\n}' } },
  ]
  cases.forEach(function (c) {
    var r = buildRenderModel(c, null, mockConfig)
    var active = [
      r.mode === RENDER_MODE.RICH_TEXT && r.richTextNodes.length > 0,
      r.mode === RENDER_MODE.LATEX && r.html.length > 0,
      r.mode === RENDER_MODE.SEGMENTS && r.segments.length > 0,
      r.mode === RENDER_MODE.CODE && r.rawText.length > 0
    ].filter(Boolean).length
    assertEq(active, 1, 'exactly one render root active for: ' + JSON.stringify(c.content.text).slice(0, 50))
  })
})

// ==========================================================================
// 6. buildRichTextNodes unchanged for non-code
// ==========================================================================

group('buildRichTextNodes — unchanged for non-code', function () {
  var nodes = buildRichTextNodes('hello world')
  assertEq(nodes.length, 1, 'single paragraph')
  assertEq(nodes[0].name, 'p', 'wrapper is <p>')
  assertEq(nodes[0].children.length, 1, 'single text child')
  assertEq(nodes[0].children[0].type, 'text', 'child is text type')
  assertEq(nodes[0].children[0].text, 'hello world', 'text preserved')

  var multi = buildRichTextNodes('line1\nline2\nline3')
  var brCount = multi[0].children.filter(function (c) { return c.name === 'br' }).length
  assertEq(brCount, 2, '2 br nodes for 3 lines')
  assertEq(multi[0].children[0].text, 'line1', 'first text child correct')
})

// ==========================================================================
// Summary
// ==========================================================================

console.log('\n' + '='.repeat(50))
console.log('Total: ' + (passed + failed) + '  Passed: ' + passed + '  Failed: ' + failed)
if (failed > 0) {
  console.error('\nSOME TESTS FAILED')
  process.exit(1)
} else {
  console.log('\nAll tests passed.')
}
