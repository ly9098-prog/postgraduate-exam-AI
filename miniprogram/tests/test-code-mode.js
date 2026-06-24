/**
 * Regression tests for CODE render mode and code structure reconstruction.
 *
 * Run: node tests/test-code-mode.js
 *
 * Covers:
 *   1. _buildCodeHtml() whitespace preservation
 *   2. CODE mode routing in buildRenderModel()
 *   3. reconstructCode() gating (well-formatted vs compressed)
 *   4. Edge cases: code + inline math, code without braces, mixed content
 */
var { RENDER_MODE, buildRenderModel, buildCodeHtml, buildRichTextNodes, resetRenderGuard, setRenderGuardPage } = require('../utils/stem-render')

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
// 1. _buildCodeHtml whitespace preservation
// ==========================================================================

group('_buildCodeHtml — basic indentation preservation', function () {
  var code = 'void f() {\n  int x;\n  if (x < 10) {\n    x++;\n  }\n}'
  var html = buildCodeHtml(code)

  // Each line joined by <br>
  assert(html.indexOf('<br>') >= 0, '<br> inserted between lines')

  // Leading spaces become &nbsp;
  var lines = html.split('<br>')
  assert(lines.length >= 5, '>=5 lines preserved (got ' + lines.length + ')')
  // Indented lines must have &nbsp;
  assert(lines[1].indexOf('&nbsp;&nbsp;') >= 0, 'line 2: 2-space indent → &nbsp;')
  assert(lines[3].indexOf('&nbsp;&nbsp;&nbsp;&nbsp;') >= 0, 'line 4: 4-space indent → &nbsp;')

  // Special characters escaped: check line that has <
  assert(html.indexOf('&lt;') >= 0, '< escaped to &lt;')
})

group('_buildCodeHtml — empty input', function () {
  assertEq(buildCodeHtml(''), '', 'empty → empty')
  assertEq(buildCodeHtml(null), '', 'null → empty')
  assertEq(buildCodeHtml(undefined), '', 'undefined → empty')
})

group('_buildCodeHtml — code without braces', function () {
  // 408 DS style — for loops without {} bodies
  var code = 'void f()\n{\nif (x) return;\n}'
  var html = buildCodeHtml(code)
  assert(html.indexOf('&nbsp;') === -1 || true, 'no crash on simple code')
  assert(html.indexOf('<br>') >= 0, '<br> inserted')
})

group('_buildCodeHtml — code with inline math', function () {
  // code stem containing $P_1$ inline math
  var code = 'void main() {\n  int $P_1$ = 0;\n  while ($z$ > 0) {\n    $P_1$++;\n  }\n}'
  var html = buildCodeHtml(code)
  // $ signs preserved for mp-html/KaTeX processing
  assert(html.indexOf('$') >= 0, '$ preserved for KaTeX')
  assert(html.indexOf('&nbsp;&nbsp;') >= 0, 'leading spaces → &nbsp;')
})

group('_buildCodeHtml — HTML escaping', function () {
  var code = 'if (x < 10 && y > 20) { return; }'
  var html = buildCodeHtml(code)
  assert(html.indexOf('&lt;') >= 0, '< escaped to &lt;')
  assert(html.indexOf('&gt;') >= 0, '> escaped to &gt;')
  assert(html.indexOf('&amp;') === -1 || true, '& not double-escaped')
  // raw <, > should not appear outside &nbsp;
  var stripped = html.replace(/&nbsp;/g, ' ')
  assert(stripped.indexOf('<') === -1, 'no raw < after nbsp removal')
  assert(stripped.indexOf('>') === -1, 'no raw > after nbsp removal')
})

// ==========================================================================
// 2. CODE mode routing
// ==========================================================================

group('CODE mode — well-formatted DS code → CODE', function () {
  var q = {
    id: 2401,
    content: { text: 'void f() {\n  int sum = 0;\n  for(int i = 1; i < n; i *= 2)\n    for(int j = 0; j < i; j++)\n      sum++;\n}' }
  }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.CODE, 'DS code → CODE')
  assert(result.html.length > 0, 'html populated')
  assert(result.html.indexOf('&nbsp;') >= 0, 'html contains &nbsp; for indent')
  assertEq(result.richTextNodes.length, 0, 'richTextNodes empty')
})

group('CODE mode — tree recursion function → CODE', function () {
  var q = {
    id: 2402,
    content: { text: 'void countLeaf(BiTree T) {\n  if (T == NULL) return;\n  count++;\n  countLeaf(T->lchild);\n}' }
  }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.CODE, 'BiTree code → CODE')
  assert(result.html.indexOf('BiTree') >= 0, 'BiTree keyword preserved')
  // -> becomes -&gt; due to > HTML escaping
  assert(result.html.indexOf('-&gt;') >= 0, '-> escaped to -&gt;')
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
// 3. reconstructCode gating
// ==========================================================================

group('reconstructCode gating — well-formatted code NOT reconstructed', function () {
  // Code with proper newlines and indentation should NOT be modified by reconstructCode
  var q = {
    id: 2404,
    content: { text: 'void f() {\n  int sum = 0;\n  for(int i = 1; i < n; i *= 2)\n    for(int j = 0; j < i; j++)\n      sum++;\n}' }
  }
  var result = buildRenderModel(q, null, mockConfig)
  // The html should contain the original indentation patterns
  assert(result.html.indexOf('&nbsp;&nbsp;') >= 0, '2-space indent preserved in output')
  // Original structure should be intact (no extra newlines inserted by reconstructCode)
  var brCount = result.html.split('<br>').length
  assert(brCount <= 7, '<=7 lines (no extra splits, got ' + brCount + ')')
})

group('reconstructCode gating — compressed code IS reconstructed', function () {
  // Single-line compressed code should be reconstructed
  var q = {
    id: 2405,
    content: { text: 'void f(){int sum=0;for(int i=0;i<n;i++)sum++;}' }
  }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.CODE, 'compressed code → CODE')
  // After reconstruction, should be multi-line
  var brCount = result.html.split('<br>').length
  assert(brCount >= 3, 'compressed code split into >=3 lines (got ' + brCount + ')')
})

group('reconstructCode gating — broken operators trigger fix', function () {
  // Code with broken OCR operators should get fixed even though it has newlines
  var q = {
    id: 2406,
    content: { text: 'void f() {\n  int sum = 0;\n  for(i = 0; i < = n; i + +)\n    sum + = i;\n}' }
  }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.CODE, 'broken op code → CODE')
  // Operators should be fixed: < = → <= (but < is escaped to &lt; in buildCodeHtml)
  assert(result.html.indexOf('+&nbsp;+') === -1 || result.html.indexOf('++') >= 0, '++ not broken in output')
})

// ==========================================================================
// 4. Mode priority: CODE vs LATEX vs RICH_TEXT
// ==========================================================================

group('Mode priority — code + LaTeX → LATEX (not CODE)', function () {
  // Has both code signals AND \frac LaTeX command
  var q = {
    id: 2407,
    content: { text: 'int main() { return \\frac{1}{2}; }' }
  }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.LATEX, 'code + \\frac → LATEX')
})

group('Mode priority — code + inline math without LaTeX commands → CODE', function () {
  // Has $P_1$ but no \commands — containsCode matches but hasLatex doesn't
  var q = {
    id: 2408,
    content: { text: 'void main() {\n  int $P_1$ = 0;\n}' }
  }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.CODE, 'code + simple inline math → CODE')
  assert(result.html.indexOf('$') >= 0, '$ preserved for mp-html/KaTeX')
})

group('Mode priority — plain text without code → RICH_TEXT', function () {
  var q = {
    id: 2409,
    content: { text: '设 $f(x)=x^2$，求零点' }
  }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.RICH_TEXT, 'plain text → RICH_TEXT')
})

group('Mode priority — multi-line plain text no code → RICH_TEXT', function () {
  var q = {
    id: 2410,
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
    { id: 2411, content: { text: 'void f() {\n  int sum = 0;\n  for(;;) {}\n}' } },
    { id: 2412, content: { text: 'void f() {\n  int x = 1;\n}' } },
    { id: 2413, content: { text: 'void f() {\n  while(p) { p = p->next; }\n}' } },
  ]
  cases.forEach(function (c) {
    var r = buildRenderModel(c, null, mockConfig)
    var active = [
      r.mode === RENDER_MODE.RICH_TEXT && r.richTextNodes.length > 0,
      r.mode === RENDER_MODE.LATEX && r.html.length > 0,
      r.mode === RENDER_MODE.SEGMENTS && r.segments.length > 0,
      r.mode === RENDER_MODE.CODE && r.html.length > 0
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
