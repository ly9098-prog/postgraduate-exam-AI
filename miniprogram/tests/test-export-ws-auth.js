/**
 * Export WebSocket must authenticate through the bearer subprotocol, never the URL.
 *
 * Run: node miniprogram/tests/test-export-ws-auth.js
 */
const assert = require('assert')

const TOKEN = 'header.payload.signature'
const store = { token: TOKEN }
const connections = []

global.wx = {
  getAccountInfoSync: () => ({ miniProgram: { envVersion: 'release' } }),
  getSystemInfoSync: () => ({ platform: 'devtools' }),
  getStorageSync: (key) => store[key],
  setStorageSync: (key, value) => { store[key] = value },
  removeStorageSync: (key) => { delete store[key] },
  request: () => {},
  connectSocket: (options) => {
    connections.push(options)
    return { onOpen() {}, onMessage() {}, onError() {}, onClose() {}, close() {}, send() {} }
  },
}

const { ExportStatusSyncManager } = require('../subpackages/export/services/export_status_sync')

const sync = new ExportStatusSyncManager({ onUpdate() {}, onCalibrate() {}, onError() {} })
sync._connectWebSocket()

assert.strictEqual(connections.length, 1, 'connectSocket should be called once')
const options = connections[0]
assert.ok(!options.url.includes(TOKEN), 'token must not appear in the socket URL')
assert.ok(!/[?&]token=/.test(options.url), 'socket URL must not carry a token query parameter')
assert.deepStrictEqual(options.protocols, ['bearer', TOKEN])
sync.stop()

console.log('test-export-ws-auth: passed')
