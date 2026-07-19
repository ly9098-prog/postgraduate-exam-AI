#!/usr/bin/env node
/**
 * test-relative-require-paths.js
 *
 * Scan all JS files in the miniprogram for relative require() paths
 * and verify they resolve to existing files.
 *
 * Usage: node scripts/test-relative-require-paths.js
 * Exit code: 0 = all paths resolve, 1 = at least one path fails
 */

const fs = require('fs')
const path = require('path')

const MINIPROGRAM_DIR = path.resolve(__dirname, '..', 'miniprogram')
const SKIP_DIRS = ['node_modules', '.git', '__pycache__', '.pytest_cache', '__mocks__']
const SCAN_SUBDIRS = ['pages', 'components', 'subpackages']

let failed = 0
let checked = 0

function collectJsFiles(dir) {
  let files = []
  try {
    const entries = fs.readdirSync(dir, { withFileTypes: true })
    for (const entry of entries) {
      if (SKIP_DIRS.includes(entry.name)) continue
      const fullPath = path.join(dir, entry.name)
      if (entry.isDirectory()) {
        files = files.concat(collectJsFiles(fullPath))
      } else if (entry.isFile() && entry.name.endsWith('.js')) {
        files.push(fullPath)
      }
    }
  } catch (_) {}
  return files
}

// Only scan pages, components, and subpackages for module resolution correctness.
// Utils/scripts may use dynamic require patterns that fail static analysis.
function isInScope(filePath) {
  const rel = path.relative(MINIPROGRAM_DIR, filePath)
  return SCAN_SUBDIRS.some(dir => rel.startsWith(dir + path.sep))
}

function resolveRequire(requiringFile, target) {
  // Handle relative paths only
  if (target[0] !== '.') return null // not a relative path, skip

  const dir = path.dirname(requiringFile)
  const resolved = path.resolve(dir, target)

  // Try exact file
  if (fs.existsSync(resolved)) return resolved
  // Try + .js
  if (fs.existsSync(resolved + '.js')) return resolved + '.js'
  // Try + /index.js
  if (fs.existsSync(path.join(resolved, 'index.js'))) return path.join(resolved, 'index.js')
  // Try + /index.wxss
  if (fs.existsSync(path.join(resolved, 'index.wxss'))) return path.join(resolved, 'index.wxss')
  // Try + /index.json
  if (fs.existsSync(path.join(resolved, 'index.json'))) return path.join(resolved, 'index.json')
  // Try + /index.wxml
  if (fs.existsSync(path.join(resolved, 'index.wxml'))) return path.join(resolved, 'index.wxml')

  return null // not found
}

const requireRegex = /require\s*\(\s*['"](\.\.?\/[^'"]+)['"]\s*\)/g
const allFiles = collectJsFiles(MINIPROGRAM_DIR)

console.log(`Scanning ${allFiles.length} JS files for relative require() paths...\n`)

for (const file of allFiles) {
  if (!isInScope(file)) continue
  const relPath = path.relative(MINIPROGRAM_DIR, file)
  const content = fs.readFileSync(file, 'utf8')
  let match

  while ((match = requireRegex.exec(content)) !== null) {
    const target = match[1]
    const resolved = resolveRequire(file, target)

    checked++

    if (!resolved) {
      failed++
      console.error(`  ✗ ${relPath}`)
      console.error(`    require("${target}") → NOT FOUND`)
      // Show the parsed resolution attempts
      const dir = path.dirname(file)
      const resolvedPath = path.resolve(dir, target)
      console.error(`    tried: ${resolvedPath}`)
      console.error(`    tried: ${resolvedPath}.js`)
      console.error(`    tried: ${path.join(resolvedPath, 'index.js')}`)
    }
  }
}

// Also check WXSS @import paths
const wxssImportRegex = /@import\s+['"](\.\.?\/[^'"]+)['"]/g
const wxssFiles = allFiles.filter(f => f.endsWith('.wxss'))

// Scan WXSS @import paths too (but only in page/component/subpackage dirs)
function collectWxssFiles(dir) {
  let files = []
  try {
    const entries = fs.readdirSync(dir, { withFileTypes: true })
    for (const entry of entries) {
      if (SKIP_DIRS.includes(entry.name)) continue
      const fullPath = path.join(dir, entry.name)
      if (entry.isDirectory()) {
        files = files.concat(collectWxssFiles(fullPath))
      } else if (entry.isFile() && entry.name.endsWith('.wxss')) {
        files.push(fullPath)
      }
    }
  } catch (_) {}
  return files
}

for (const file of collectWxssFiles(MINIPROGRAM_DIR)) {
  if (!isInScope(file)) continue
  const relPath = path.relative(MINIPROGRAM_DIR, file)
  const content = fs.readFileSync(file, 'utf8')
  let match

  while ((match = wxssImportRegex.exec(content)) !== null) {
    const target = match[1]
    const dir = path.dirname(file)
    const resolved = path.resolve(dir, target)

    checked++

    if (!fs.existsSync(resolved)) {
      // Try .wxss
      if (fs.existsSync(resolved + '.wxss')) continue
      failed++
      console.error(`  ✗ ${relPath}`)
      console.error(`    @import "${target}" → NOT FOUND`)
      console.error(`    tried: ${resolved}`)
    }
  }
}

console.log(`\nChecked ${checked} relative paths:`)
if (failed === 0) {
  console.log('  ✓ All paths resolve')
} else {
  console.error(`  ✗ ${failed} path(s) do NOT resolve`)
}

process.exit(failed > 0 ? 1 : 0)
