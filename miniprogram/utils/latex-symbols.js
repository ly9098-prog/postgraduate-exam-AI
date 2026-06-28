/**
 * Central registry for LaTeX command -> Unicode symbol mappings.
 *
 * Mirror of admin-frontend/src/lib/latex-symbols.ts for the miniprogram.
 * Add new symbols to both files — the TS version is the source of truth.
 *
 * Key: LaTeX command name without the leading backslash (e.g. "leq" for \leq).
 * Value: Unicode replacement character.
 */

var LATEX_SYMBOLS = {
  leq: '≤',
  le: '≤',
  geq: '≥',
  ge: '≥',
  neq: '≠',
  times: '×',
  div: '÷',
  cdot: '·',
  ldots: '…',
  cdots: '…',
  dots: '…',
  pm: '±',
  to: '→',
  lt: '<',
  gt: '>',
  // Greek lowercase
  alpha: 'α',
  beta: 'β',
  gamma: 'γ',
  delta: 'δ',
  epsilon: 'ε',
  varepsilon: 'ε',
  zeta: 'ζ',
  eta: 'η',
  theta: 'θ',
  vartheta: 'ϑ',
  iota: 'ι',
  kappa: 'κ',
  lambda: 'λ',
  mu: 'μ',
  nu: 'ν',
  xi: 'ξ',
  omicron: 'ο',
  pi: 'π',
  varpi: 'ϖ',
  rho: 'ρ',
  varrho: 'ϱ',
  sigma: 'σ',
  varsigma: 'ς',
  tau: 'τ',
  upsilon: 'υ',
  phi: 'φ',
  varphi: 'φ',
  chi: 'χ',
  psi: 'ψ',
  omega: 'ω',
  // Greek uppercase
  Gamma: 'Γ',
  Delta: 'Δ',
  Theta: 'Θ',
  Lambda: 'Λ',
  Xi: 'Ξ',
  Pi: 'Π',
  Sigma: 'Σ',
  Phi: 'Φ',
  Psi: 'Ψ',
  Omega: 'Ω',
  // Relations
  approx: '≈',
  simeq: '≃',
  cong: '≅',
  equiv: '≡',
  propto: '∝',
  sim: '∼',
  // Arrows
  Rightarrow: '⇒',
  Leftrightarrow: '⇔',
  rightarrow: '→',
  leftarrow: '←',
  leftrightarrow: '↔',
  Longrightarrow: '⟹',
  Longleftrightarrow: '⇔',
  longrightarrow: '⟶',
  longleftarrow: '⟵',
  // Set theory
  subset: '⊂',
  supset: '⊃',
  subseteq: '⊆',
  supseteq: '⊇',
  in: '∈',
  notin: '∉',
  cap: '∩',
  cup: '∪',
  // Misc
  infty: '∞',
  partial: '∂',
  nabla: '∇',
  forall: '∀',
  exists: '∃',
  neg: '¬',
  prime: '′',
  emptyset: '∅',
  angle: '∠',
  triangle: '△',
  circ: '∘',
  bullet: '•',
  mid: '∣',
  parallel: '∥',
  // Structural
  sum: '∑',
  prod: '∏',
  int: '∫',
}

var LATEX_FUNCTION_NAMES = ['log', 'ln', 'sin', 'cos', 'tan', 'lim', 'det', 'max', 'min', 'sup', 'inf', 'arg', 'deg']

/**
 * Replace LaTeX commands with their Unicode equivalents.
 * Handles 1+ leading backslashes. Matches longest names first.
 */
function applyLatexSymbols(text) {
  var keys = Object.keys(LATEX_SYMBOLS).sort(function(a, b) { return b.length - a.length })
  var result = String(text || '')
  for (var i = 0; i < keys.length; i++) {
    result = result.replace(new RegExp('\\\\{1,}' + keys[i] + '(?![a-zA-Z])', 'g'), LATEX_SYMBOLS[keys[i]])
  }
  return result
}

/**
 * Strip leading backslashes from known LaTeX function names (log, ln, sin, etc.).
 */
function unescapeFunctionNames(text) {
  return String(text || '').replace(new RegExp('\\\\{1,}(' + LATEX_FUNCTION_NAMES.join('|') + ')(?![a-zA-Z])', 'g'), '$1')
}

module.exports = {
  LATEX_SYMBOLS: LATEX_SYMBOLS,
  LATEX_FUNCTION_NAMES: LATEX_FUNCTION_NAMES,
  applyLatexSymbols: applyLatexSymbols,
  unescapeFunctionNames: unescapeFunctionNames,
}
