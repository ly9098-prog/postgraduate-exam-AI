const assert = require('node:assert/strict')
const { resolveBreakSec } = require('../pages/pomodoro/utils/celebration-dismiss')

const data = { selectedPreset: 'standard', breakDuration: 5 }

// ── breakSec from completion flag ──
assert.equal(resolveBreakSec({ breakSec: 300 }, null, data), 300)
assert.equal(resolveBreakSec({ breakSec: 0 }, null, data), 0)
assert.equal(resolveBreakSec({ breakSec: '120' }, null, data), 120)

// ── breakSec from completionBreakSec fallback ──
assert.equal(resolveBreakSec(null, 600, data), 600)
assert.equal(resolveBreakSec(null, 0, data), 0)
assert.equal(resolveBreakSec({}, 180, data), 180)

// ── breakSec from data fallback ──
assert.equal(resolveBreakSec(null, null, data), 300)
assert.equal(resolveBreakSec(null, undefined, data), 300)
assert.equal(resolveBreakSec({}, null, data), 300)

// ── debug preset ──
assert.equal(resolveBreakSec(null, null, { selectedPreset: 'debug', breakDuration: 5 }), 5)

// ── invalid values fall through ──
assert.equal(resolveBreakSec({ breakSec: 'invalid' }, null, data), 300)
assert.equal(resolveBreakSec({ breakSec: NaN }, null, data), 300)
assert.equal(resolveBreakSec(null, NaN, data), 300)

// ── negative is clamped to 0 ──
assert.equal(resolveBreakSec({ breakSec: -5 }, null, data), 0)

console.log('Pomodoro celebration dismiss passed: resolveBreakSec')
