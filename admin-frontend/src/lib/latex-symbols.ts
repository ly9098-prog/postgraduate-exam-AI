/**
 * Central registry for LaTeX command → Unicode symbol mappings.
 *
 * Add new symbols here instead of scattering .replace() calls across files.
 * All consumers (admin-frontend, miniprogram) derive from this same dataset.
 *
 * Key: LaTeX command name without the leading backslash (e.g. "leq" for \leq).
 * Value: Unicode replacement character.
 */

export const LATEX_SYMBOLS: Record<string, string> = {
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

export const LATEX_FUNCTION_NAMES = ['log', 'ln', 'sin', 'cos', 'tan', 'lim', 'det', 'max', 'min', 'sup', 'inf', 'arg', 'deg'] as const

/**
 * Replace LaTeX commands with their Unicode equivalents.
 *
 * Handles 1+ leading backslashes (covers JSON-escaped content like \\leq).
 * Matches longest command names first to avoid partial overlaps (geq vs ge).
 */
export function applyLatexSymbols(text: string): string {
  const keys = Object.keys(LATEX_SYMBOLS).sort((a, b) => b.length - a.length)
  let result = text
  for (const key of keys) {
    result = result.replace(new RegExp(`\\\\{1,}${key}(?![a-zA-Z])`, 'g'), LATEX_SYMBOLS[key])
  }
  return result
}

/**
 * Strip leading backslashes from known LaTeX function names (log, ln, sin, etc.).
 */
export function unescapeFunctionNames(text: string): string {
  const names = LATEX_FUNCTION_NAMES.join('|')
  return text.replace(new RegExp(`\\\\{1,}(${names})(?![a-zA-Z])`, 'g'), '$1')
}
