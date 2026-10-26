var _CONTROL_KEYWORDS = [
  'for', 'while', 'if', 'else if', 'else', 'switch',
  'return', 'break', 'continue', 'struct', 'class', 'typedef',
  'enum', 'case', 'default', 'catch', 'finally', 'try', 'do',
]
var _CODE_SIGNALS = [
  'return', 'printf', 'scanf', 'malloc', 'free', 'NULL',
  'struct', 'typedef', 'enum', 'union',
  'int ', 'void ', 'char ', 'float ', 'double ',
  'bool', 'const', 'static', 'sizeof',
  '->', '::', '{', '}', ';',
  '++', '--', '+=', '-=', '*=', '/=',
  '#include', '#define', 'main(',
]
var _DS_KEYWORDS = [
  'LNode', 'TNode', 'BiTNode', 'BiTree', 'BSTNode', 'LinkList',
  'SqList', 'Stack', 'Queue', 'SqStack', 'ElemType', 'Status',
]
function containsCode(text) {
  if (!text) return false
  var score = 0
  for (var i = 0;i < _CODE_SIGNALS.length;i++) {
    if (text.indexOf(_CODE_SIGNALS[i]) !== -1) score++
  }
  for (var j = 0;j < _DS_KEYWORDS.length;j++) {
    if (text.indexOf(_DS_KEYWORDS[j]) !== -1) score += 2
  }
  for (var k = 0;k < _CONTROL_KEYWORDS.length;k++) {
    var kw = _CONTROL_KEYWORDS[k]
    var re = new RegExp('\\b' + kw + '\\b')
    if (re.test(text)) score++
  }
  return score >= 3
}

module.exports = {
  containsCode: containsCode,
  controlKeywords: _CONTROL_KEYWORDS,
  dataStructureKeywords: _DS_KEYWORDS,
}
