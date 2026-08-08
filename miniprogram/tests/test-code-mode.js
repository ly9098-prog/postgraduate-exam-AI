/**
 * Regression tests for CODE render mode (zero-HTML raw text).
 *
 * Run: node tests/test-code-mode.js
 *
 * Covers:
 *   1. CODE mode routing in buildRenderModel()
 *   2. Raw text preservation (no HTML entities, no escaping)
 *   3. Compressed code reconstruction (shouldReconstructCode + reconstructCode)
 *   4. Render Trace System
 *   5. Render Invariant Guard
 *   6. Auto Self-Healing (SAFE_MODE)
 *   7. Render Regression Diff
 *   8. MIXED mode (text + code blocks)
 */
var { RENDER_MODE, buildRenderModel, buildRichTextNodes, renderDiff, splitInlineTextAndCode } = require('../subpackages/study/utils/stem-render')
var { sanitizeImportedCodeArtifacts, detectCodeLanguageHint, detectDollarArtifactPattern } = require('../subpackages/study/utils/code-reconstructor')

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

group('ReconstructCode — compressed code gets newlines', function () {
  // Single-line compressed code should be conservatively reconstructed
  var code = 'void f(){int sum=0;for(int i=0;i<n;i++)sum++;}'
  var q = { id: 2422, content: { text: code } }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.CODE, 'compressed code → CODE')
  assert(result.rawText.indexOf('\n') >= 0, 'newlines added after reconstruction')
  assert(result.rawText.indexOf('void f()') >= 0, 'function header preserved')
  assert(result.rawText.indexOf('int sum=0') >= 0, 'variable declaration preserved')
  assert(result.rawText.indexOf('for(int i=0') >= 0, 'for loop preserved')
  assert(result.rawText.indexOf('i++)sum++') >= 0, 'loop body preserved')
  // Code semantics must be intact (no removed characters)
  assert(result.rawText.length > code.length * 0.8, 'no significant data loss')
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
// 3.5 Render Trace System
// ==========================================================================

group('Render Trace — CODE mode trace fields', function () {
  var code = 'void f() {\n  int x = 1;\n}'
  var q = { id: 2451, content: { text: code } }
  var result = buildRenderModel(q, null, mockConfig)
  var trace = result.renderTrace
  assert(trace && typeof trace === 'object', 'renderTrace exists on model')
  assertEq(trace.questionId, 2451, 'trace.questionId matches')
  assertEq(trace.renderType, RENDER_MODE.CODE, 'trace.renderType is CODE')
  assert(Array.isArray(trace.pipeline), 'trace.pipeline is array')
  assertEq(trace.pipeline.join(','), 'detect,route,render', 'pipeline steps correct')
  assert(typeof trace.codeHashBefore === 'number', 'codeHashBefore is number')
  assert(typeof trace.codeHashAfter === 'number', 'codeHashAfter is number')
  assertEq(trace.newlineCountBefore, 2, 'newlineCountBefore = 2')
  assertEq(trace.stemLengthBefore, code.length, 'stemLengthBefore matches original')
})

group('Render Trace — non-CODE mode has no code fields', function () {
  var q = { id: 2452, content: { text: '设 $f(x)=x^2$，求零点' } }
  var result = buildRenderModel(q, null, mockConfig)
  var trace = result.renderTrace
  assert(trace && typeof trace === 'object', 'renderTrace exists on model')
  assertEq(trace.renderType, RENDER_MODE.RICH_TEXT, 'trace.renderType is RICH_TEXT')
  assertEq(trace.codeHashBefore, undefined, 'no codeHashBefore for non-CODE')
  assertEq(trace.newlineCountBefore, undefined, 'no newlineCountBefore for non-CODE')
})

// ==========================================================================
// 3.6 Render Invariant Guard — CODE integrity
// ==========================================================================

group('Invariant Guard — CODE mode has empty html and richTextNodes', function () {
  var code = 'void f() { int x; }'
  var q = { id: 2461, content: { text: code } }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.CODE, 'is CODE mode')
  assertEq(result.html, '', 'html is empty')
  assertEq(result.richTextNodes.length, 0, 'richTextNodes is empty')
  assert(result.rawText.length > 0, 'rawText is populated')
})

group('Invariant Guard — CODE rawText has no HTML entities', function () {
  var code = 'void f() {\n  if (x < 10 && x > 0) x++;\n}'
  var q = { id: 2462, content: { text: code } }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.CODE, 'is CODE mode')
  assertEq(result.rawText.indexOf('&amp;'), -1, 'no &amp;')
  assertEq(result.rawText.indexOf('&lt;'), -1, 'no &lt;')
  assertEq(result.rawText.indexOf('&gt;'), -1, 'no &gt;')
  assertEq(result.rawText.indexOf('&nbsp;'), -1, 'no &nbsp;')
  assert(result.rawText.indexOf('<') >= 0, 'raw < is preserved')
  assert(result.rawText.indexOf('>') >= 0, 'raw > is preserved')
})

// ==========================================================================
// 3.7 Auto Self-Healing — SAFE_MODE
// ==========================================================================

group('SAFE_MODE — code + LaTeX bypass → CODE', function () {
  var cfg = Object.assign({}, mockConfig, { SAFE_MODE: true })
  var q = { id: 2471, content: { text: 'int main() { return \\frac{1}{2}; }' } }
  var result = buildRenderModel(q, null, cfg)
  assertEq(result.mode, RENDER_MODE.CODE, 'SAFE_MODE bypasses LATEX for code+frac → CODE')
  assert(result.rawText.length > 0, 'rawText populated')
  assertEq(result.html, '', 'html is empty')
})

group('SAFE_MODE — pure code unchanged → CODE', function () {
  var cfg = Object.assign({}, mockConfig, { SAFE_MODE: true })
  var q = { id: 2472, content: { text: 'void f() { int x; }' } }
  var result = buildRenderModel(q, null, cfg)
  assertEq(result.mode, RENDER_MODE.CODE, 'pure code → CODE even in SAFE_MODE')
  assertEq(result.html, '', 'html is empty')
})

group('SAFE_MODE — plain text unchanged → RICH_TEXT', function () {
  var cfg = Object.assign({}, mockConfig, { SAFE_MODE: true })
  var q = { id: 2473, content: { text: '设 $f(x)=x^2$，求零点' } }
  var result = buildRenderModel(q, null, cfg)
  assertEq(result.mode, RENDER_MODE.RICH_TEXT, 'non-code plain text → RICH_TEXT in SAFE_MODE')
})

// ==========================================================================
// 3.8 Render Regression Diff
// ==========================================================================

group('renderDiff — identical text → no issues', function () {
  var code = 'void f() {\n  int x = 1;\n}'
  var issues = renderDiff(code, code)
  assertEq(issues.length, 0, 'identical text → 0 issues')
})

group('renderDiff — indent mismatch detected', function () {
  var orig = 'void f() {\n  int x = 1;\n}'
  var rend = 'void f() {\n    int x = 1;\n}'
  var issues = renderDiff(orig, rend)
  var indentIssues = issues.filter(function (i) { return i.type === 'INDENT_MISMATCH' })
  assert(indentIssues.length >= 1, 'indent mismatch caught (got ' + indentIssues.length + ')')
})

group('renderDiff — newline mismatch detected', function () {
  var orig = 'line1\nline2\nline3'
  var rend = 'line1\nline2'
  var issues = renderDiff(orig, rend)
  var newlineIssues = issues.filter(function (i) { return i.type === 'NEWLINE_MISMATCH' })
  assert(newlineIssues.length >= 1, 'newline mismatch caught')
})

group('renderDiff — content mismatch detected', function () {
  var orig = 'int x = 1;'
  var rend = 'int y = 2;'
  var issues = renderDiff(orig, rend)
  var contentIssues = issues.filter(function (i) { return i.type === 'CONTENT_MISMATCH' })
  assert(contentIssues.length >= 1, 'content mismatch caught')
})

group('renderDiff — internal space diff allowed (ignored)', function () {
  var orig = 'int  x  =  1;'
  var rend = 'int x = 1;'
  var issues = renderDiff(orig, rend)
  var contentIssues = issues.filter(function (i) { return i.type === 'CONTENT_MISMATCH' })
  var indentIssues = issues.filter(function (i) { return i.type === 'INDENT_MISMATCH' })
  assertEq(contentIssues.length, 0, 'internal space diff allowed: content normalized')
  assertEq(indentIssues.length, 0, 'no indent change')
})

// ==========================================================================
// 3.9 Duplicate Content Protection
// ==========================================================================

group('Dedup — paragraph-level duplicate detected', function () {
  // Simulate content where stem + code is repeated as paragraphs.
  // In RICH_TEXT mode, $...$ is converted by formatInlineMathText, so
  // the plain text check uses the converted form.
  var content = '第一段文字。\n\n分析：计算。\n\n第一段文字。'
  var q = { id: 2481, content: { text: content } }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.RICH_TEXT, 'dedup content → RICH_TEXT')
  var first = '第一段文字。'
  assertEq(result.richTextNodes[0].children.filter(function(c) { return c.text === first }).length, 1,
    'duplicate paragraph removed')
})

group('Dedup — full-stem CODE content duplicate detected', function () {
  // Simulate old data where the full stem + code block is stored twice
  var code = 'int sum = 0;\nfor(int i = 1; i < n; i *= 2)\n    sum++;'
  var duplicated = code + '\n\n' + code
  var q = { id: 2482, content: { text: duplicated } }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.CODE, 'deduped code → CODE')
  var newlines = result.rawText.split('\n').length
  assertEq(newlines, 3, 'exactly 3 lines after dedup (got ' + newlines + ')')
})

group('Dedup — no false positive on unique content', function () {
  var content = '第一段\n\n第二段\n\n第三段'
  var q = { id: 2483, content: { text: content } }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.RICH_TEXT, 'unique content → RICH_TEXT')
  var children = result.richTextNodes[0].children
  var textCount = children.filter(function(c) { return c.text }).length
  assertEq(textCount, 3, 'all 3 paragraphs preserved')
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
// 8. MIXED mode (text + code blocks)
// ==========================================================================

group('MIXED mode — text + code split into blocks', function () {
  var stem = '下列程序段的时间复杂度是（ ）。\n\nint sum = 0;\nfor(int i = 1; i < n; i *= 2)\n    sum++;'
  var q = { id: 2501, content: { text: stem } }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.MIXED, 'text + code → MIXED')
  assert(Array.isArray(result.blocks), 'blocks is array')
  assert(result.blocks.length >= 2, 'at least 2 blocks (got ' + result.blocks.length + ')')
  assertEq(result.blocks[0].type, 'RICH_TEXT', 'first block is RICH_TEXT')
  assert(result.blocks[0].richTextNodes.length > 0, 'RICH_TEXT block has nodes')
  var codeBlock = result.blocks[result.blocks.length - 1]
  assertEq(codeBlock.type, 'CODE', 'last block is CODE')
  assert(codeBlock.rawText.length > 0, 'CODE block has rawText')
  // Text block should NOT contain code
  var firstText = JSON.stringify(result.blocks[0].richTextNodes)
  assert(firstText.indexOf('int') === -1, 'text block does not contain int')
  assert(firstText.indexOf('for') === -1, 'text block does not contain for')
})

group('MIXED mode — Peterson algorithm example', function () {
  var stem = '两个进程 $P_{0}$、$P_{1}$ 互斥的 Peterson 算法如下：\n\nwhile (true) {\n  flag[i] = true;\n}'
  var q = { id: 2502, content: { text: stem } }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.MIXED, 'text + code with inline math → MIXED')
  assert(result.blocks.length >= 2, 'has at least 2 blocks')
  // First block should have inline math converted (no raw $...$)
  assertEq(result.blocks[0].type, 'RICH_TEXT', 'first block is RICH_TEXT')
  // Last block should be CODE
  var lastBlock = result.blocks[result.blocks.length - 1]
  assertEq(lastBlock.type, 'CODE', 'last block is CODE')
  assert(lastBlock.rawText.indexOf('while') >= 0, 'while preserved in code block')
})

group('MIXED mode — inline text+code split on same line', function () {
  var stem = '下列程序的时间复杂度是（ ）。 int m=0; for(i=0;i<n;i++) m++;'
  var q = { id: 2503, content: { text: stem } }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.MIXED, 'inline text+code → MIXED')
  assert(result.blocks.length >= 2, 'at least 2 blocks (got ' + result.blocks.length + ')')
  assertEq(result.blocks[0].type, 'RICH_TEXT', 'first block is RICH_TEXT')
  var codeBlock = result.blocks[result.blocks.length - 1]
  assertEq(codeBlock.type, 'CODE', 'last block is CODE')
  assert(codeBlock.rawText.indexOf('int m=0') >= 0, 'CODE block contains int m=0')
  assert(codeBlock.rawText.indexOf('for(i=0;i<n;i++)') >= 0, 'CODE block contains for loop')
})

group('MIXED mode — render trace has blockTypes', function () {
  var stem = '文字说明。\n\nint x = 1;'
  var q = { id: 2504, content: { text: stem } }
  var result = buildRenderModel(q, null, mockConfig)
  if (result.mode === RENDER_MODE.MIXED) {
    var trace = result.renderTrace
    assert(Array.isArray(trace.blockTypes), 'blockTypes is array')
    assert(trace.blockTypes.length > 0, 'blockTypes non-empty')
    assert(trace.blockTypes.indexOf('CODE') >= 0, 'blockTypes includes CODE')
    assert(trace.blockTypes.indexOf('RICH_TEXT') >= 0, 'blockTypes includes RICH_TEXT')
  }
})

group('MIXED mode — pure code should still be CODE', function () {
  var stem = 'void f() {\n  int x = 1;\n  while (x < 10) {\n    x++;\n  }\n}'
  var q = { id: 2505, content: { text: stem } }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.CODE, 'pure code → CODE (not MIXED)')
  assertEq(result.html, '', 'CODE html is empty')
  assert(result.rawText.indexOf('x++') >= 0, 'code preserved')
})

group('MIXED mode — single root invariant', function () {
  // For MIXED mode, the active fields must follow the invariant:
  // blocks must be populated, html/richTextNodes at top level must be empty
  var stem = '文字说明。\n\nint x = 1;'
  var q = { id: 2506, content: { text: stem } }
  var result = buildRenderModel(q, null, mockConfig)
  if (result.mode === RENDER_MODE.MIXED) {
    assert(result.blocks.length > 0, 'blocks is non-empty for MIXED')
    assertEq(result.html, '', 'top-level html empty')
    assertEq(result.richTextNodes.length, 0, 'top-level richTextNodes empty')
    assertEq(result.rawText, '', 'top-level rawText empty')
  }
})

// ==========================================================================
// 9. Inline text+code splitting (splitInlineTextAndCode)
// ==========================================================================

group('splitInlineTextAndCode — Chinese text + code on same line', function () {
  var blocks = splitInlineTextAndCode('下列程序的时间复杂度是（ ）。 int m=0; for(i=0;i<n;i++) m++;')
  assert(blocks.length >= 2, 'split into at least 2 blocks (got ' + blocks.length + ')')
  assertEq(blocks[0].type, 'RICH_TEXT', 'first block is RICH_TEXT')
  assert(blocks[0].text.indexOf('时间复杂度') >= 0, 'RICH_TEXT contains Chinese text')
  assertEq(blocks[1].type, 'CODE', 'second block is CODE')
  assert(blocks[1].text.indexOf('int m=0') >= 0, 'CODE block contains code')
})

group('splitInlineTextAndCode — colon + function code', function () {
  var blocks = splitInlineTextAndCode('程序如下：void f(){int x=0;return;}')
  assert(blocks.length >= 2, 'split into 2 blocks')
  assertEq(blocks[0].type, 'RICH_TEXT', 'first block is RICH_TEXT')
  assert(blocks[0].text.indexOf('程序如下') >= 0, 'RICH_TEXT contains Chinese')
  assertEq(blocks[1].type, 'CODE', 'second block is CODE')
  assert(blocks[1].text.indexOf('void f()') >= 0, 'CODE contains function')
})

group('splitInlineTextAndCode — natural language "for" not mistaken', function () {
  var blocks = splitInlineTextAndCode('The keyword for is commonly used in programming languages.')
  assertEq(blocks.length, 1, 'single block (no split)')
  assertEq(blocks[0].type, 'RICH_TEXT', 'single RICH_TEXT block')
})

group('splitInlineTextAndCode — Chinese text with "int" not mistaken', function () {
  var blocks = splitInlineTextAndCode('整数 int 的存储空间与编译器有关。')
  assertEq(blocks.length, 1, 'single block (no split)')
  assertEq(blocks[0].type, 'RICH_TEXT', 'single RICH_TEXT block')
})

group('splitInlineTextAndCode — text + inline math + colon + while code', function () {
  var blocks = splitInlineTextAndCode('两个进程 $P_{0}$、$P_{1}$，程序如下：while(true){flag[i]=true;}')
  assert(blocks.length >= 2, 'split into 2 blocks (got ' + blocks.length + ')')
  assertEq(blocks[0].type, 'RICH_TEXT', 'first block is RICH_TEXT')
  assert(blocks[0].text.indexOf('程序如下') >= 0, 'RICH_TEXT contains Chinese text')
  assertEq(blocks[1].type, 'CODE', 'second block is CODE')
  assert(blocks[1].text.indexOf('while(true)') >= 0, 'CODE contains while loop')
})

group('splitInlineTextAndCode — nested for loops after sentence end', function () {
  var blocks = splitInlineTextAndCode('下列语句执行次数为（ ）。 for(i=0;i<n;i++){for(j=0;j<n;j++)m++;}')
  assert(blocks.length >= 2, 'split into 2 blocks (got ' + blocks.length + ')')
  assertEq(blocks[0].type, 'RICH_TEXT', 'first block is RICH_TEXT')
  assert(blocks[0].text.indexOf('执行次数') >= 0, 'RICH_TEXT contains Chinese text')
  assertEq(blocks[1].type, 'CODE', 'second block is CODE')
  assert(blocks[1].text.indexOf('for(i=0') >= 0, 'CODE contains outer for loop')
  assert(blocks[1].text.indexOf('for(j=0') >= 0, 'CODE contains inner for loop')
  assert(blocks[1].text.indexOf('m++') >= 0, 'CODE contains increment')
})

// ==========================================================================
// 10. Inline text+code via buildRenderModel (full pipeline)
// ==========================================================================

group('Inline split — "程序如下：void f()" → MIXED', function () {
  var q = { id: 2601, content: { text: '程序如下：void f(){int x=0;return;}' } }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.MIXED, 'colon+code → MIXED')
  assert(result.blocks.length >= 2, 'at least 2 blocks')
  assertEq(result.blocks[0].type, 'RICH_TEXT', 'first block is RICH_TEXT')
  var codeBlock = result.blocks[result.blocks.length - 1]
  assertEq(codeBlock.type, 'CODE', 'last block is CODE')
  assert(codeBlock.rawText.indexOf('void') >= 0, 'CODE contains void')
})

group('Inline split — English text without code → RICH_TEXT', function () {
  var q = { id: 2602, content: { text: 'The keyword for is commonly used in programming languages.' } }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.RICH_TEXT, 'natural English → RICH_TEXT')
})

group('Inline split — "int" in Chinese context → RICH_TEXT', function () {
  var q = { id: 2603, content: { text: '整数 int 的存储空间与编译器有关。' } }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.RICH_TEXT, 'int in Chinese → RICH_TEXT')
})

group('Inline split — text + $P_{0}$ + colon + while → MIXED', function () {
  var q = { id: 2604, content: { text: '两个进程 $P_{0}$、$P_{1}$，程序如下：while(true){flag[i]=true;}' } }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.MIXED, 'math + colon + while → MIXED')
  assert(result.blocks.length >= 2, 'at least 2 blocks')
  // Text block must not have raw $...$ showing
  var textBlock = result.blocks[0]
  assertEq(textBlock.type, 'RICH_TEXT', 'first block is RICH_TEXT')
  assert(textBlock.richTextNodes.length > 0, 'RICH_TEXT has nodes')
  // Code block must contain the while loop
  var codeBlock = result.blocks[result.blocks.length - 1]
  assertEq(codeBlock.type, 'CODE', 'last block is CODE')
  assert(codeBlock.rawText.indexOf('while(true)') >= 0, 'CODE contains while(true)')
})

group('Inline split — nested for loops after sentence end', function () {
  var q = { id: 2605, content: { text: '下列语句执行次数为（ ）。 for(i=0;i<n;i++){for(j=0;j<n;j++)m++;}' } }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.MIXED, 'nested for → MIXED')
  assert(result.blocks.length >= 2, 'at least 2 blocks')
  var codeBlock = result.blocks[result.blocks.length - 1]
  assertEq(codeBlock.type, 'CODE', 'last block is CODE')
  assert(codeBlock.rawText.indexOf('for(i=0') >= 0, 'outer for preserved')
  assert(codeBlock.rawText.indexOf('for(j=0') >= 0, 'inner for preserved')
  assert(codeBlock.rawText.indexOf('m++') >= 0, 'increment preserved')
})

group('Inline split — English text + colon + code → MIXED', function () {
  var stem = 'Consider the following C function: void test() { int x = 1; }'
  var q = { id: 2606, content: { text: stem } }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.MIXED, 'English colon+code → MIXED')
  assert(result.blocks.length >= 2, 'at least 2 blocks')
  assertEq(result.blocks[0].type, 'RICH_TEXT', 'first block is RICH_TEXT')
  assertEq(result.blocks[result.blocks.length - 1].type, 'CODE', 'last block is CODE')
})

group('Inline split — single root invariant for MIXED', function () {
  var q = { id: 2607, content: { text: '下列程序的时间复杂度是（ ）。 int m=0; for(i=0;i<n;i++) m++;' } }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.MIXED, 'same-line text+code → MIXED')
  assert(result.blocks.length > 0, 'blocks non-empty')
  assertEq(result.html, '', 'top-level html empty')
  assertEq(result.richTextNodes.length, 0, 'top-level richTextNodes empty')
  assertEq(result.rawText, '', 'top-level rawText empty')
})
// ==========================================================================

// ==========================================================================
// 11. Dollar sign artifact sanitization (sanitizeImportedCodeArtifacts)
// ==========================================================================

function assertNoDollar(result, msg) {
  if (result.indexOf('$') === -1) { passed++; return }
  failed++
  console.error('  FAIL:', msg)
  console.error('    unexpected $ in:', JSON.stringify(result))
}

function assertHasDollar(result, msg) {
  if (result.indexOf('$') >= 0) { passed++; return }
  failed++
  console.error('  FAIL:', msg + ' ($ was removed but should be preserved)')
}

group('Code artifact sanitize — Test 1: real printf question with $ pollution', function () {
  var code =
    'if (n>=0) {\n' +
    '    for (int i=0; i<n; i++)\n' +
    '        for (int j=0; j<n; j++)\n' +
    '            printf("value > 0$\\n");\n' +
    '}else {\n' +
    '    for (int i=0; i<n; i++)\n' +
    '        printf("value < 0$\\n");$\n' +
    '}'
  var result = sanitizeImportedCodeArtifacts(code)
  assertNoDollar(result, 'Test 1: no $ after sanitization')
  assert(result.indexOf('\\n') >= 0, 'Test 1: \\n preserved')
})

group('Code artifact sanitize — Test 2: multi-line trailing $', function () {
  var code = 'int x = 0;$\nx++;$\nreturn;$\n'
  var result = sanitizeImportedCodeArtifacts(code)
  assertNoDollar(result, 'Test 2: all trailing $ removed')
})

group('Code artifact sanitize — Test 3: legal C price string preserved', function () {
  var code = 'printf("\\u4ef7\\u683c\\u4e3a $10\\n");'
  var result = sanitizeImportedCodeArtifacts(code)
  assertHasDollar(result, 'Test 3: $10 price preserved')
})

group('Code artifact sanitize — Test 4: legal char literal $ preserved', function () {
  var code = "char currency = '$';"
  var result = sanitizeImportedCodeArtifacts(code)
  assertHasDollar(result, 'Test 4: char literal $ preserved')
})

group('Code artifact sanitize — Test 5: PHP all $ preserved', function () {
  var code = '<?php\n$name = $_GET[\'name\'];\necho $name;'
  var result = sanitizeImportedCodeArtifacts(code)
  assertHasDollar(result, 'Test 5: PHP $ preserved')
  assert(result.indexOf('<?php') >= 0, 'Test 5: <?php preserved')
  assert(result.indexOf('$_GET') >= 0, 'Test 5: $_GET preserved')
})

group('Code artifact sanitize — Test 6: Shell all $ preserved', function () {
  var code = 'echo "$HOME"\necho "${USER}"\nvalue=$(date)'
  var result = sanitizeImportedCodeArtifacts(code)
  assertHasDollar(result, 'Test 6: Shell $ preserved')
})

group('Code artifact sanitize — Test 7: JS $ identifier preserved', function () {
  var code = 'const $el = document.querySelector(\'#app\')\nconst text = `${price}$`'
  var result = sanitizeImportedCodeArtifacts(code)
  assertHasDollar(result, 'Test 7: JS $ preserved')
})

group('Code artifact sanitize — Test 8: regex /...$/ preserved', function () {
  var code = 'var pattern = /^\\d+$/'
  var result = sanitizeImportedCodeArtifacts(code)
  assertHasDollar(result, 'Test 8: regex $ preserved')
})

group('Code artifact sanitize — Test 9: code string LaTeX preserved', function () {
  var code = 'printf("$P_{0}$\\n");'
  var result = sanitizeImportedCodeArtifacts(code)
  // sanitize only removes $ before \n\r\t — $P_{0}$ should be kept
  assertHasDollar(result, 'Test 9: $P_{0}$ preserved in code string')
  assert(result.indexOf('P_{0}') >= 0, 'Test 9: P_{0} content preserved')
})

group('Code artifact sanitize — Test 10: comments with $ preserved', function () {
  var code = '// price is $10\n/* keep $ here */\nprintf("ok\\n");'
  var result = sanitizeImportedCodeArtifacts(code)
  assertHasDollar(result, 'Test 10: comment $ preserved')
  assert(result.indexOf('// price') >= 0, 'Test 10: line comment preserved')
  assert(result.indexOf('/* keep') >= 0, 'Test 10: block comment preserved')
})

group('Code artifact sanitize — detectCodeLanguageHint', function () {
  assertEq(detectCodeLanguageHint('<?php echo $x;'), 'php', 'PHP detected')
  assertEq(detectCodeLanguageHint('#!/bin/bash\necho $HOME'), 'shell', 'Shell shebang detected')
  assertEq(detectCodeLanguageHint('const $el = 1'), 'js', 'JS $ identifier detected')
  assertEq(detectCodeLanguageHint('#include <stdio.h>'), 'c-like', 'C include detected')
  assertEq(detectCodeLanguageHint('printf("hello");'), 'c-like', 'C printf detected')
  assertEq(detectCodeLanguageHint('int main() { return 0; }'), 'c-like', 'C main detected')
})

group('Code artifact sanitize — artifact does not trigger without $', function () {
  var result = detectDollarArtifactPattern('clean code without dollar')
  assertEq(result.isLikelyArtifact, false, 'no artifact on clean code')
})

group('Code artifact sanitize — empty/whitespace returns original', function () {
  assertEq(sanitizeImportedCodeArtifacts(''), '', 'empty string unchanged')
  assertEq(sanitizeImportedCodeArtifacts(null), '', 'null returns empty string')
})

group('Code artifact sanitize — code without $ unchanged', function () {
  var code = 'void f() { int x = 1; }'
  assertEq(sanitizeImportedCodeArtifacts(code), code, 'code without $ unchanged')
})

group('Code artifact sanitize — full pipeline: trailing $ removed, $0 preserved', function () {
  // Realistic case: code with $ pollution + $0 used legitimately in strings
  var stem =
    'if (n>=0) {\n' +
    '    for(int i=0; i<n; i++)\n' +
    '        for(int j=0; j<n; j++)\n' +
    '            printf("input>=$0\\n");$\n' +
    '}else {\n' +
    '    for(int j=0; j<n; j++)\n' +
    '        printf("input<$0\\n");$\n' +
    '}'
  var q = { id: 2701, content: { text: stem } }
  var result = buildRenderModel(q, null, mockConfig)
  assertEq(result.mode, RENDER_MODE.CODE, 'polluted code → CODE mode')
  // Trailing $ after ; should be removed
  assert(result.rawText.indexOf(';$') === -1, 'trailing $ at end of line removed')
  // But $0 inside printf string should be preserved (legitimate usage)
  assert(result.rawText.indexOf('$0') >= 0, '$0 inside string preserved')
  // \n escape sequences preserved
  assert(result.rawText.indexOf('\\n') >= 0, '\\n preserved in printf')
})

// ==========================================================================

console.log('\n' + '='.repeat(50))
console.log('Total: ' + (passed + failed) + '  Passed: ' + passed + '  Failed: ' + failed)
if (failed > 0) {
  console.error('\nSOME TESTS FAILED')
  process.exit(1)
} else {
  console.log('\nAll tests passed.')
}
