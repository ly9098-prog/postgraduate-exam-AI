function splitCodeLines(value) {
var raw = String(value == null ? '' : value)
.replace(/\r\n/g, '\n')
.replace(/\r/g, '\n')
var parts = raw.split('\n')
if (!parts.length) parts = ['']
return parts.map(function (text, index) {
return { no: index + 1, text: text || ' ' }
})
}

module.exports = {
splitCodeLines: splitCodeLines,
}
