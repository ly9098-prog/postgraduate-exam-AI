
function safeDecodeURIComponent(value, fallback) {
if (typeof value !== 'string') return arguments.length >= 2 ? fallback : ''
try {
return decodeURIComponent(value)
} catch (_) {
return arguments.length >= 2 ? fallback : value
}
}
function parsePositiveInt(value, fallback) {
var n = parseInt(value, 10)
if (isNaN(n) || n <= 0 || !isFinite(n)) return arguments.length >= 2 ? fallback : 0
return n
}
function parseStringParam(value, fallback) {
if (typeof value === 'string') return value
return arguments.length >= 2 ? fallback : ''
}
module.exports = {
safeDecodeURIComponent: safeDecodeURIComponent,
parsePositiveInt: parsePositiveInt,
parseStringParam: parseStringParam,
}
