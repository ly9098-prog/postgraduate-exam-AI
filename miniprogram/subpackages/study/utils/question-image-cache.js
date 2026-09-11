
var _localPathByUrl = Object.create(null)
var _pendingByUrl = Object.create(null)
var _order = []
var MAX_ENTRIES = 96
function _isRemote(url) {
return /^https?:\/\//i.test(String(url || ''))
}
function resolve(url) {
var key = String(url || '')
return _localPathByUrl[key] || key
}
function _remember(url, localPath) {
if (!url || !localPath) return
if (!_localPathByUrl[url]) _order.push(url)
_localPathByUrl[url] = localPath
while (_order.length > MAX_ENTRIES) {
var oldest = _order.shift()
if (oldest) delete _localPathByUrl[oldest]
}
}
function preload(url) {
var key = String(url || '').trim()
if (!key || !_isRemote(key)) return Promise.resolve(resolve(key))
if (_localPathByUrl[key]) return Promise.resolve(_localPathByUrl[key])
if (_pendingByUrl[key]) return _pendingByUrl[key]
if (typeof wx === 'undefined' || !wx || typeof wx.getImageInfo !== 'function') {
return Promise.resolve(key)
}
var task = new Promise(function (done) {
wx.getImageInfo({
src: key,
success: function (res) {
var localPath = res && res.path ? String(res.path) : ''
if (localPath) _remember(key, localPath)
done(localPath || key)
},
fail: function () {
done(key)
},
complete: function () {
delete _pendingByUrl[key]
},
})
})
_pendingByUrl[key] = task
return task
}
function preloadMany(urls, concurrency) {
var input = Array.isArray(urls) ? urls : []
var seen = Object.create(null)
var queue = []
for (var i = 0; i < input.length; i++) {
var url = String(input[i] || '').trim()
if (!url || seen[url] || !_isRemote(url) || _localPathByUrl[url]) continue
seen[url] = true
queue.push(url)
}
if (!queue.length) return Promise.resolve([])
var limit = Math.max(1, Math.min(Number(concurrency) || 3, 4))
var cursor = 0
var results = new Array(queue.length)
function worker() {
function next() {
var index = cursor++
if (index >= queue.length) return Promise.resolve()
return preload(queue[index]).then(function (path) {
results[index] = path
return next()
})
}
return next()
}
var workers = []
for (var w = 0; w < Math.min(limit, queue.length); w++) workers.push(worker())
return Promise.all(workers).then(function () { return results })
}
function clear() {
_localPathByUrl = Object.create(null)
_pendingByUrl = Object.create(null)
_order = []
}
module.exports = {
resolve: resolve,
preload: preload,
preloadMany: preloadMany,
clear: clear,
}
