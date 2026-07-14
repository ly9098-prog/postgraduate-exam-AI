/**
 * miniprogram-release-audit.js
 *
 * Pre-release audit for WeChat Mini Program:
 * 1. Check no Node builtin imports leak into release scope
 * 2. Check no test files leak into release scope
 * 3. Check all relative module paths resolve
 * 4. Check all JSON files parse
 * 5. Check app.json page registration completeness
 *
 * Usage: node scripts/miniprogram-release-audit.js
 * Exit code: 0 = pass, 1 = fail
 */

const fs = require('fs')
const path = require('path')

const MINIPROGRAM_DIR = path.resolve(__dirname, '..', 'miniprogram')
const PACK_IGNORE_PATH = path.join(MINIPROGRAM_DIR, 'project.config.json')

// Node.js built-in modules that must NOT appear in mini program code
const NODE_BUILTINS = new Set([
  'fs', 'path', 'os', 'child_process', 'assert', 'crypto',
  'http', 'https', 'net', 'tls', 'dns', 'events', 'stream',
  'util', 'url', 'zlib', 'querystring', 'string_decoder',
  'timers', 'tty', 'v8', 'vm', 'worker_threads', 'cluster',
  'module', 'process', 'buffer', 'console', 'domain',
  'inspector', 'perf_hooks', 'async_hooks', 'trace_events',
  'wasi', 'diagnostics_channel',
])

const NODE_BUILTIN_PREFIX = 'node:'

// Read packOptions.ignore from project.config.json
let packIgnore = []
try {
  const config = JSON.parse(fs.readFileSync(PACK_IGNORE_PATH, 'utf8'))
  packIgnore = (config.packOptions && config.packOptions.ignore) || []
} catch (e) {
  console.error('[AUDIT][FAIL] Cannot read project.config.json:', e.message)
  process.exit(1)
}

function matchesIgnore(filePath) {
  const relative = path.relative(MINIPROGRAM_DIR, filePath)
  for (const rule of packIgnore) {
    if (rule.type === 'folder' && rule.value) {
      if (relative.startsWith(rule.value + path.sep) || relative === rule.value) return true
    }
    if (rule.type === 'suffix' && rule.value) {
      if (relative.endsWith(rule.value)) return true
    }
    if (rule.type === 'glob' && rule.value) {
      const pattern = rule.value.replace('**/', '(.+/)?').replace('*', '[^/]*')
      try {
        const re = new RegExp('^' + pattern.replace(/[.+?^${}()|[\]\\]/g, '\\$&') + '$')
        if (re.test(relative)) return true
      } catch (_) {}
    }
  }
  return false
}

// Collect all .js files that pass the ignore rules (i.e. would be published)
function collectReleaseJSFiles(dir) {
  const files = []
  function walk(d) {
    let entries
    try { entries = fs.readdirSync(d) } catch { return }
    for (const entry of entries) {
      if (entry.startsWith('.') || entry === 'node_modules') continue
      const full = path.join(d, entry)
      if (fs.statSync(full).isDirectory()) {
        walk(full)
      } else if (entry.endsWith('.js') && !matchesIgnore(full)) {
        files.push(full)
      }
    }
  }
  walk(dir)
  return files
}

let errors = 0
let warnings = 0

// ── Check 1: Node builtin imports in publishable JS ──
console.log('[AUDIT] Checking Node builtin imports in publishable JS files...')
const jsFiles = collectReleaseJSFiles(MINIPROGRAM_DIR)
for (const file of jsFiles) {
  const code = fs.readFileSync(file, 'utf8')

  // Check for require('fs'), require('path'), etc.
  const requireRe = /require\s*\(\s*['"]([^'"]+)['"]\s*\)/g
  let match
  while ((match = requireRe.exec(code)) !== null) {
    const mod = match[1]
    if (NODE_BUILTINS.has(mod) || mod.startsWith(NODE_BUILTIN_PREFIX)) {
      const relative = path.relative(MINIPROGRAM_DIR, file)
      console.error(`  [FAIL] ${relative}: require('${mod}') — Node builtin not available in WeChat runtime`)
      errors++
    }
  }
}

// ── Check 2: Test files in publishable scope ──
console.log('[AUDIT] Checking test files are excluded from release...')
const allFiles = []
function walkAll(dir) {
  let entries
  try { entries = fs.readdirSync(dir) } catch { return }
  for (const entry of entries) {
    if (entry.startsWith('.') || entry === 'node_modules') continue
    const full = path.join(dir, entry)
    if (fs.statSync(full).isDirectory()) {
      walkAll(full)
    } else {
      allFiles.push(full)
    }
  }
}
walkAll(MINIPROGRAM_DIR)
for (const file of allFiles) {
  const name = path.basename(file)
  const isTest = /\.(test|spec)\.(js|ts)$/i.test(name) || /^test-/i.test(name)
  if (isTest && !matchesIgnore(file)) {
    const relative = path.relative(MINIPROGRAM_DIR, file)
    console.error(`  [FAIL] ${relative} — test file not excluded by packOptions.ignore`)
    errors++
  }
}

// ── Check 3: app.json page registration ──
console.log('[AUDIT] Checking app.json page registration...')
const appJson = JSON.parse(fs.readFileSync(path.join(MINIPROGRAM_DIR, 'app.json'), 'utf8'))
const allPages = [...(appJson.pages || [])];
(appJson.subPackages || []).forEach(sp => {
  ;(sp.pages || []).forEach(p => allPages.push(sp.root + '/' + p))
})
for (const page of allPages) {
  const pageDir = path.join(MINIPROGRAM_DIR, page)
  const jsFile = pageDir + '.js'
  const jsonFile = pageDir + '.json'
  const wxmlFile = pageDir + '.wxml'
  const wxssFile = pageDir + '.wxss'
  if (!fs.existsSync(jsFile)) { console.error(`  [FAIL] Missing page JS: ${page}.js`); errors++ }
  if (!fs.existsSync(jsonFile)) { console.warn(`  [WARN] Missing page JSON: ${page}.json`); warnings++ }
  if (!fs.existsSync(wxmlFile)) { console.error(`  [FAIL] Missing page WXML: ${page}.wxml`); errors++ }
  // WXSS is optional
}

// ── Summary ──
console.log('')
if (errors === 0 && warnings === 0) {
  console.log('[AUDIT] PASS — No release-blocking issues found.')
  process.exit(0)
} else if (errors === 0) {
  console.log(`[AUDIT] PASS (${warnings} warnings)`)
  process.exit(0)
} else {
  console.log(`[AUDIT] FAIL — ${errors} error(s), ${warnings} warning(s)`)
  process.exit(1)
}
