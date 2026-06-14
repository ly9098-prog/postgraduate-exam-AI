const SUBSCRIPT = {
  '0': '₀', '1': '₁', '2': '₂', '3': '₃', '4': '₄',
  '5': '₅', '6': '₆', '7': '₇', '8': '₈', '9': '₉',
  '+': '₊', '-': '₋', 'a': 'ₐ', 'e': 'ₑ', 'h': 'ₕ', 'i': 'ᵢ',
  'j': 'ⱼ', 'k': 'ₖ', 'l': 'ₗ', 'm': 'ₘ', 'n': 'ₙ', 'o': 'ₒ',
  'p': 'ₚ', 'r': 'ᵣ', 's': 'ₛ', 't': 'ₜ', 'u': 'ᵤ', 'v': 'ᵥ', 'x': 'ₓ'
}

const SUPERSCRIPT = {
  '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴',
  '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹',
  '+': '⁺', '-': '⁻', 'n': 'ⁿ'
}

function toScript(value, map) {
  const source = String(value || '')
  let result = ''
  for (let i = 0; i < source.length; i++) {
    const ch = source[i]
    result += map[ch] || ch
  }
  return result
}

function replaceSimpleLatexCommands(text) {
  return String(text || '')
    .replace(/\\{1,}(leq|le)/g, '≤')
    .replace(/\\{1,}(geq|ge)/g, '≥')
    .replace(/\\{1,}neq/g, '≠')
    .replace(/\\{1,}times/g, '×')
    .replace(/\\{1,}div/g, '÷')
    .replace(/\\{1,}cdot/g, '·')
    .replace(/\\{1,}pm/g, '±')
    .replace(/\\{1,}to/g, '→')
    .replace(/\\{1,}lt/g, '<')
    .replace(/\\{1,}gt/g, '>')
    .replace(/\\{1,}(log|ln|sin|cos|tan)/g, '$1')
}

function formatInlineMathText(text) {
  if (!text) return ''
  let value = String(text)
    .replace(/\*\*([^*]+?)\*\*/g, '$1')
    .replace(/\\\(([\s\S]*?)\\\)/g, '$1')
    .replace(/\\\[([\s\S]*?)\\\]/g, '$1')
    .replace(/\$\$([\s\S]*?)\$\$/g, '$1')
    .replace(/\$([^$\n]+?)\$/g, '$1')

  value = replaceSimpleLatexCommands(value)
  value = value
    .replace(/_\{([0-9A-Za-z+-]+)\}/g, function(_, sub) {
      return toScript(sub, SUBSCRIPT)
    })
    .replace(/\^\{([0-9A-Za-z+-]+)\}/g, function(_, sup) {
      return toScript(sup, SUPERSCRIPT)
    })
    .replace(/(log|ln|sin|cos|tan)_([0-9]+)/g, function(_, name, sub) {
      return name + toScript(sub, SUBSCRIPT)
    })
    .replace(/([A-Za-z0-9)])_([0-9A-Za-z])/g, function(_, base, sub) {
      return base + toScript(sub, SUBSCRIPT)
    })
    .replace(/([A-Za-z0-9)])\^([0-9A-Za-z])/g, function(_, base, sup) {
      return base + toScript(sup, SUPERSCRIPT)
    })
    .replace(/([A-Za-z0-9)])\s*(=|\+|×|÷|≤|≥|≠|→)\s*/g, '$1 $2 ')
    .replace(/\s*(-)\s*/g, ' − ')
    .replace(/(?<![*/])\s*([*/])\s*(?![*/])/g, ' $1 ')
    .replace(/([A-Za-z0-9)])(log[₀-₉₊₋]+)/g, '$1 $2')
    .replace(/(log[₀-₉₊₋]+)([A-Za-z])/g, '$1 $2')
    .replace(/[ \t]+/g, ' ')
    .replace(/\s+([，。！？；：,.!?;:)])/g, '$1')
    .replace(/([(])\s+/g, '$1')
    .trim()

  return value
}

module.exports = {
  formatInlineMathText,
  replaceSimpleLatexCommands,
}
