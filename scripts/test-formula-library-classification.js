#!/usr/bin/env node
/**
 * test-formula-library-classification.js
 *
 * Regression tests for formula library chapter filtering fix:
 * - Always uses /formulas for both normal and favorites mode
 * - Chapter filtering correctly normalized
 * - Catalog handling
 * - Pagination correctness
 *
 * Usage: node scripts/test-formula-library-classification.js
 * Exit code: 0 = pass, 1 = fail
 */

const fs = require('fs')
const path = require('path')

const PAGE_DIR = path.resolve(__dirname, '..', 'miniprogram', 'subpackages', 'formulas', 'library')
const JS_FILE = path.join(PAGE_DIR, 'index.js')
const WXML_FILE = path.join(PAGE_DIR, 'index.wxml')
const WXSS_FILE = path.join(PAGE_DIR, 'index.wxss')

let failed = 0
let passed = 0

function assert(condition, message) {
  if (condition) {
    passed++
    console.log('  ✓ ' + message)
  } else {
    failed++
    console.log('  ✗ FAIL: ' + message)
  }
}

// Read source files
const jsSource = fs.readFileSync(JS_FILE, 'utf-8')
const wxmlSource = fs.readFileSync(WXML_FILE, 'utf-8')
const wxssSource = fs.readFileSync(WXSS_FILE, 'utf-8')

console.log('=== URL 和 API 调用 ===')

// Check that loadFormulas always uses /formulas (not favorites/list)
const favoritesListUsage = jsSource.match(/\/formulas\/favorites\/list/g)
assert(
  !favoritesListUsage || favoritesListUsage.length === 0,
  `loadFormulas 不直接使用 /formulas/favorites/list（出现 ${favoritesListUsage ? favoritesListUsage.length : 0} 次）`
)

// Still allowed for other purposes (e.g. loadFavoriteIds)
assert(
  jsSource.includes("'/formulas'"),
  '请求路径包含 /formulas'
)

// Check favorite_only param is sent
assert(
  jsSource.includes('favorite_only'),
  '使用 favorite_only=true 参数代替接口切换'
)

console.log('')
console.log('=== 章节筛选 ===')

// Chapter selection normalizes dataset.id to number
assert(
  jsSource.includes('Number(rawId)'),
  'onChapterSelect 将 dataset.id 标准化为数字'
)

// Chapter select uses setData callback with loadFormulas
assert(
  jsSource.includes('function () {\n      this.loadFormulas(true)'),
  '章节选择在 setData 回调中调用 loadFormulas'
)

// Chapter select resets page, hasMore, formulas, total
assert(
  jsSource.includes('page: 1') && jsSource.includes('formulas: []') && jsSource.includes('hasMore: true'),
  '章节选择时重置 page/hasMore/formulas'
)

console.log('')
console.log('=== 分页 ===')

// hasMore uses page * pageSize < totalItems instead of rawItems.length === pageSize
assert(
  jsSource.includes('requestPage * pageSize < totalItems'),
  'hasMore 使用 page * pageSize < total 判断'
)

// Uses filtered_total or total from response
assert(
  jsSource.includes('filtered_total') && jsSource.includes('.total'),
  '使用 filtered_total / total 计算分页'
)

console.log('')
console.log('=== catalog 结构 ===')

// Catalog endpoint includes library_type parameter
assert(
  jsSource.includes('library_type'),
  'loadCatalog 传递 library_type 参数'
)

// Chapters include available_count
assert(
  jsSource.includes('available_count'),
  '章节数据包含 available_count'
)

console.log('')
console.log('=== 内容类型切换 ===')

// Library type change reloads catalog
assert(
  jsSource.match(/this\.loadCatalog\(\)/g),
  '内容类型切换时重新加载目录'
)

console.log('')
console.log('=== 收藏切换 ===')

// Favorites toggle reloads catalog
assert(
  jsSource.includes('this.loadFavo') && jsSource.includes('loadCatalog'),
  '收藏切换时调用 loadCatalog'
)

console.log('')
console.log('=== 样式检查 ===')

// Chapter count display style
assert(
  wxssSource.includes('fl-chapter-count'),
  '存在 fl-chapter-count 样式'
)

// Chapter chip shows count in WXML
assert(
  wxmlSource.includes('available_count'),
  'WXML 渲染 available_count'
)

console.log('')
console.log(`=== 结果: ${passed} passed, ${failed} failed ===`)

if (failed > 0) {
  process.exit(1)
}
