// Capture the original dependency objects and hasOwn exactly once.
var stemRender = require('./stem-render')
var answerLib = require('./answer')
var _hasOwn = Object.prototype.hasOwnProperty

module.exports = { stemRender, answerLib, _hasOwn }
