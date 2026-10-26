function readSingleQuoted(code, start) {
  var result = "'"
  var i = start + 1
  while (i < code.length) {
    result += code[i]
    if (code[i] === '\\' && i + 1 < code.length) {
      i++
      result += code[i]
    } else if (code[i] === "'") {
      i++
      break
    }
    i++
  }
  return { text: result, next: i }
}

function readDoubleQuoted(code, start) {
  var result = '"'
  var i = start + 1
  while (i < code.length) {
    if (code[i] === '\\') {
      result += code[i]
      i++
      if (i < code.length) {
        result += code[i]
        i++
      }
      continue
    }
    if (code[i] === '"') {
      result += code[i]
      i++
      break
    }
    if (code[i] === '$' && i + 2 < code.length && code[i + 1] === '\\' &&
      (code[i + 2] === 'n' || code[i + 2] === 'r' || code[i + 2] === 't')) {
      i++
      continue
    }
    result += code[i]
    i++
  }
  return { text: result, next: i }
}

function removeDollarBeforeEscapedControlInStrings(code) {
  var result = ''
  var i = 0
  var len = code.length
  while (i < len) {
    var ch = code[i]
    if (ch === '/' && i + 1 < len && code[i + 1] === '/') {
      var eol = code.indexOf('\n', i)
      if (eol === -1) eol = len
      result += code.slice(i, eol)
      i = eol
      continue
    }
    if (ch === '/' && i + 1 < len && code[i + 1] === '*') {
      var endComment = code.indexOf('*/', i + 2)
      if (endComment === -1) endComment = len - 2
      result += code.slice(i, endComment + 2)
      i = endComment + 2
      continue
    }
    if (ch === "'" || ch === '"') {
      var quoted = ch === "'" ? readSingleQuoted(code, i) : readDoubleQuoted(code, i)
      result += quoted.text
      i = quoted.next
      continue
    }
    result += ch
    i++
  }
  return result
}

module.exports = {
  removeDollarBeforeEscapedControlInStrings: removeDollarBeforeEscapedControlInStrings,
}
