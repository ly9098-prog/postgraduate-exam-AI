/**
 * Unit tests for miniprogram/subpackages/study/utils/latex-symbols.js
 * Run: node test-latex-symbols.js
 */
const ls = require('../subpackages/study/utils/latex-symbols')
const mf = require('../subpackages/study/utils/math-format')

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

function group(name, fn) {
  console.log('\n' + name)
  fn()
}

// ── applyLatexSymbols ──

group('applyLatexSymbols — basic symbols', function() {
  assertEq(ls.applyLatexSymbols('\\leq'), '≤', '\\leq → ≤')
  assertEq(ls.applyLatexSymbols('\\geq'), '≥', '\\geq → ≥')
  assertEq(ls.applyLatexSymbols('\\neq'), '≠', '\\neq → ≠')
  assertEq(ls.applyLatexSymbols('\\times'), '×', '\\times → ×')
  assertEq(ls.applyLatexSymbols('\\div'), '÷', '\\div → ÷')
  assertEq(ls.applyLatexSymbols('\\cdot'), '·', '\\cdot → ·')
  assertEq(ls.applyLatexSymbols('\\pm'), '±', '\\pm → ±')
  assertEq(ls.applyLatexSymbols('\\ldots'), '…', '\\ldots → …')
  assertEq(ls.applyLatexSymbols('\\cdots'), '…', '\\cdots → …')
  assertEq(ls.applyLatexSymbols('\\dots'), '…', '\\dots → …')
  assertEq(ls.applyLatexSymbols('\\to'), '→', '\\to → →')
})

group('applyLatexSymbols — overlapping keys (longest first)', function() {
  assertEq(ls.applyLatexSymbols('\\ge'), '≥', '\\ge → ≥')
  assertEq(ls.applyLatexSymbols('\\geq'), '≥', '\\geq → ≥ (not ge+q)')
  assertEq(ls.applyLatexSymbols('\\le'), '≤', '\\le → ≤')
  assertEq(ls.applyLatexSymbols('\\leq'), '≤', '\\leq → ≤ (not le+q)')
})

group('applyLatexSymbols — multi-backslash (JSON-escaped)', function() {
  assertEq(ls.applyLatexSymbols('\\\\leq'), '≤', '\\\\leq → ≤')
  assertEq(ls.applyLatexSymbols('\\\\neq'), '≠', '\\\\neq → ≠')
})

group('applyLatexSymbols — Greek lowercase', function() {
  assertEq(ls.applyLatexSymbols('\\alpha'), 'α', '\\alpha → α')
  assertEq(ls.applyLatexSymbols('\\beta'), 'β', '\\beta → β')
  assertEq(ls.applyLatexSymbols('\\gamma'), 'γ', '\\gamma → γ')
  assertEq(ls.applyLatexSymbols('\\delta'), 'δ', '\\delta → δ')
  assertEq(ls.applyLatexSymbols('\\epsilon'), 'ε', '\\epsilon → ε')
  assertEq(ls.applyLatexSymbols('\\theta'), 'θ', '\\theta → θ')
  assertEq(ls.applyLatexSymbols('\\lambda'), 'λ', '\\lambda → λ')
  assertEq(ls.applyLatexSymbols('\\mu'), 'μ', '\\mu → μ')
  assertEq(ls.applyLatexSymbols('\\pi'), 'π', '\\pi → π')
  assertEq(ls.applyLatexSymbols('\\sigma'), 'σ', '\\sigma → σ')
  assertEq(ls.applyLatexSymbols('\\phi'), 'φ', '\\phi → φ')
  assertEq(ls.applyLatexSymbols('\\psi'), 'ψ', '\\psi → ψ')
  assertEq(ls.applyLatexSymbols('\\omega'), 'ω', '\\omega → ω')
})

group('applyLatexSymbols — Greek variants', function() {
  assertEq(ls.applyLatexSymbols('\\varepsilon'), 'ε', '\\varepsilon → ε')
  assertEq(ls.applyLatexSymbols('\\varphi'), 'φ', '\\varphi → φ')
  assertEq(ls.applyLatexSymbols('\\vartheta'), 'ϑ', '\\vartheta → ϑ')
  assertEq(ls.applyLatexSymbols('\\varpi'), 'ϖ', '\\varpi → ϖ')
  // epsilon is prefix of varepsilon, so varepsilon must match first (length desc)
  assertEq(ls.applyLatexSymbols('\\varepsilon\\epsilon'), 'εε', '\\varepsilon\\epsilon → εε')
})

group('applyLatexSymbols — Greek uppercase', function() {
  assertEq(ls.applyLatexSymbols('\\Gamma'), 'Γ', '\\Gamma → Γ')
  assertEq(ls.applyLatexSymbols('\\Delta'), 'Δ', '\\Delta → Δ')
  assertEq(ls.applyLatexSymbols('\\Theta'), 'Θ', '\\Theta → Θ')
  assertEq(ls.applyLatexSymbols('\\Lambda'), 'Λ', '\\Lambda → Λ')
  assertEq(ls.applyLatexSymbols('\\Pi'), 'Π', '\\Pi → Π')
  assertEq(ls.applyLatexSymbols('\\Sigma'), 'Σ', '\\Sigma → Σ')
  assertEq(ls.applyLatexSymbols('\\Phi'), 'Φ', '\\Phi → Φ')
  assertEq(ls.applyLatexSymbols('\\Omega'), 'Ω', '\\Omega → Ω')
})

group('applyLatexSymbols — relations', function() {
  assertEq(ls.applyLatexSymbols('\\approx'), '≈', '\\approx → ≈')
  assertEq(ls.applyLatexSymbols('\\equiv'), '≡', '\\equiv → ≡')
  assertEq(ls.applyLatexSymbols('\\sim'), '∼', '\\sim → ∼')
  assertEq(ls.applyLatexSymbols('\\propto'), '∝', '\\propto → ∝')
})

group('applyLatexSymbols — arrows', function() {
  assertEq(ls.applyLatexSymbols('\\Rightarrow'), '⇒', '\\Rightarrow → ⇒')
  assertEq(ls.applyLatexSymbols('\\Leftrightarrow'), '⇔', '\\Leftrightarrow → ⇔')
  assertEq(ls.applyLatexSymbols('\\rightarrow'), '→', '\\rightarrow → →')
  assertEq(ls.applyLatexSymbols('\\leftarrow'), '←', '\\leftarrow → ←')
})

group('applyLatexSymbols — set theory', function() {
  assertEq(ls.applyLatexSymbols('\\in'), '∈', '\\in → ∈')
  assertEq(ls.applyLatexSymbols('\\notin'), '∉', '\\notin → ∉')
  assertEq(ls.applyLatexSymbols('\\subset'), '⊂', '\\subset → ⊂')
  assertEq(ls.applyLatexSymbols('\\supset'), '⊃', '\\supset → ⊃')
  assertEq(ls.applyLatexSymbols('\\subseteq'), '⊆', '\\subseteq → ⊆')
  assertEq(ls.applyLatexSymbols('\\supseteq'), '⊇', '\\supseteq → ⊇')
  assertEq(ls.applyLatexSymbols('\\cap'), '∩', '\\cap → ∩')
  assertEq(ls.applyLatexSymbols('\\cup'), '∪', '\\cup → ∪')
})

group('applyLatexSymbols — misc', function() {
  assertEq(ls.applyLatexSymbols('\\infty'), '∞', '\\infty → ∞')
  assertEq(ls.applyLatexSymbols('\\partial'), '∂', '\\partial → ∂')
  assertEq(ls.applyLatexSymbols('\\nabla'), '∇', '\\nabla → ∇')
  assertEq(ls.applyLatexSymbols('\\forall'), '∀', '\\forall → ∀')
  assertEq(ls.applyLatexSymbols('\\exists'), '∃', '\\exists → ∃')
  assertEq(ls.applyLatexSymbols('\\emptyset'), '∅', '\\emptyset → ∅')
})

group('applyLatexSymbols — compound expressions', function() {
  assertEq(ls.applyLatexSymbols('\\alpha + \\beta = \\gamma'), 'α + β = γ', 'compound Greek')
  assertEq(ls.applyLatexSymbols('\\lim_{x \\to \\infty}'), '\\lim_{x → ∞}', 'limit with to+infty')
  assertEq(ls.applyLatexSymbols('\\Delta = b^2 - 4ac'), 'Δ = b^2 - 4ac', 'Delta unchanged')
  assertEq(ls.applyLatexSymbols('x \\in \\mathbb{R}'), 'x ∈ \\mathbb{R}', 'in converted, mathbb stays')
  assertEq(ls.applyLatexSymbols('\\sum_{i=1}^{n}'), '∑_{i=1}^{n}', 'sum symbol')
  assertEq(ls.applyLatexSymbols('\\int_{a}^{b}'), '∫_{a}^{b}', 'int symbol')
  assertEq(ls.applyLatexSymbols('\\prod_{i=1}^{n}'), '∏_{i=1}^{n}', 'prod symbol')
})

group('applyLatexSymbols — no false positives', function() {
  assertNeq(ls.applyLatexSymbols('\\left'), '≤ft', '\\left should NOT become ≤ft (partial \\le)')
  assertEq(ls.applyLatexSymbols('\\left'), '\\left', '\\left stays as-is (no \\le match in \\left)')
})

// ── unescapeFunctionNames ──

group('unescapeFunctionNames', function() {
  assertEq(ls.unescapeFunctionNames('\\log'), 'log', '\\log → log')
  assertEq(ls.unescapeFunctionNames('\\ln'), 'ln', '\\ln → ln')
  assertEq(ls.unescapeFunctionNames('\\sin'), 'sin', '\\sin → sin')
  assertEq(ls.unescapeFunctionNames('\\cos'), 'cos', '\\cos → cos')
  assertEq(ls.unescapeFunctionNames('\\tan'), 'tan', '\\tan → tan')
  assertEq(ls.unescapeFunctionNames('\\lim'), 'lim', '\\lim → lim')
  assertEq(ls.unescapeFunctionNames('\\det'), 'det', '\\det → det')
  assertEq(ls.unescapeFunctionNames('\\max'), 'max', '\\max → max')
  assertEq(ls.unescapeFunctionNames('\\min'), 'min', '\\min → min')
  assertEq(ls.unescapeFunctionNames('\\sup'), 'sup', '\\sup → sup')
  assertEq(ls.unescapeFunctionNames('\\inf'), 'inf', '\\inf → inf')
  assertEq(ls.unescapeFunctionNames('\\\\log'), 'log', '\\\\log → log (multi-backslash)')
  assertEq(ls.unescapeFunctionNames('\\log_{2}'), 'log_{2}', '\\log_{2} → log_{2}')
  assertEq(ls.unescapeFunctionNames('\\sin x'), 'sin x', '\\sin x → sin x')
  assertEq(ls.unescapeFunctionNames('\\alpha'), '\\alpha', '\\alpha unchanged (not a function name)')
  assertEq(ls.unescapeFunctionNames('\\logarithm'), '\\logarithm', '\\logarithm unchanged (\\log not prefix of logarithm)')
  assertEq(ls.unescapeFunctionNames('\\log_{2}'), 'log_{2}', '\\log_{2} → log_{2} (still works with _)')
})

// ── replaceSimpleLatexCommands (integration) ──

group('replaceSimpleLatexCommands', function() {
  assertEq(mf.replaceSimpleLatexCommands('\\alpha \\leq \\beta'), 'α ≤ β', 'symbols + Greek')
  assertEq(mf.replaceSimpleLatexCommands('\\frac{1}{2}'), '1/2', 'frac rendering')
  assertEq(mf.replaceSimpleLatexCommands('\\sqrt{2}'), '√2', 'sqrt rendering')
})

group('formatInlineMathText (integration)', function() {
  var s = mf.formatInlineMathText('在线性表 $a_0, a_1, \\ldots, a_{100}$ 中')
  assert(s.includes('…'), '\\ldots converted to … in formatted text: ' + JSON.stringify(s))
  assert(s.includes('a₀'), 'subscript 0 rendered: ' + JSON.stringify(s))
  assert(s.includes('a₁₀₀'), 'multi-digit subscript: ' + JSON.stringify(s))

  var t = mf.formatInlineMathText('$\\Delta = b^2 - 4ac$')
  assertEq(t, 'Δ = b² − 4ac', 'discriminant formula')

  // Subscript/superscript via formatInlineMathText (not replaceSimpleLatexCommands)
  var u = mf.formatInlineMathText('$\\log_{2} x$')
  assertEq(u, 'log₂ x', 'log subscript via formatInlineMathText')

  var v = mf.formatInlineMathText('$\\sin^2 x + \\cos^2 x = 1$')
  assertEq(v, 'sin² x + cos² x = 1', 'trig identity via formatInlineMathText')

  // Structural LaTeX
  var w = mf.formatInlineMathText('$\\sum_{i=1}^{n} x_i$')
  assert(w.includes('∑'), 'sum symbol rendered: ' + JSON.stringify(w))

  var x = mf.formatInlineMathText('$\\int_{a}^{b} f(x) dx$')
  assert(x.includes('∫'), 'int symbol rendered: ' + JSON.stringify(x))

  var y = mf.formatInlineMathText('$\\lim_{x \\to \\infty} \\frac{1}{x} = 0$')
  assert(y.includes('lim'), 'lim unescaped: ' + JSON.stringify(y))
  assert(y.includes('∞'), 'infty rendered: ' + JSON.stringify(y))
  assert(y.includes('→'), 'to rendered: ' + JSON.stringify(y))
})

// ── Key set verification against TypeScript source of truth ──

group('key set consistency', function() {
  var tsKeys = Object.keys(ls.LATEX_SYMBOLS).sort()
  assert(tsKeys.length >= 85, 'at least 85 symbol entries (got ' + tsKeys.length + ')')
  assert(tsKeys.indexOf('alpha') >= 0, 'alpha key exists')
  assert(tsKeys.indexOf('infty') >= 0, 'infty key exists')
  assert(tsKeys.indexOf('leq') >= 0, 'leq key exists')
  assert(tsKeys.indexOf('rightarrow') >= 0, 'rightarrow key exists')
  assert(tsKeys.indexOf('subseteq') >= 0, 'subseteq key exists')
  assert(tsKeys.indexOf('sum') >= 0, 'sum key exists')
  assert(tsKeys.indexOf('int') >= 0, 'int key exists')
  assert(tsKeys.indexOf('prod') >= 0, 'prod key exists')
})

// ── Cross-check with TypeScript source of truth ──

group('TS/JS sync check', function() {
  var cp = require('child_process')
  var result = cp.spawnSync('node', [
    require('path').resolve(__dirname, '../../scripts/check-latex-symbols-sync.js')
  ], { cwd: require('path').resolve(__dirname, '../..'), encoding: 'utf-8' })
  if (result.status !== 0) {
    console.error('  Sync check stderr:', result.stderr.trim())
  }
  assertEq(result.status, 0, 'TS/JS symbol table sync (exit code 0)')
})

// ── Summary ──

console.log('\n' + '='.repeat(40))
console.log('Total: ' + (passed + failed) + '  Passed: ' + passed + '  Failed: ' + failed)
if (failed > 0) process.exit(1)
