/*
 * Conservative source-package and aggregate media budgets.
 * This is not a substitute for DevTools' compiled-package quality scan.
 * Run: cd miniprogram && node tests/test-main-package-size.js
 */
const fs = require('fs')
const path = require('path')

const MAX_PACKAGE_BYTES = 1.4 * 1024 * 1024
// Leave room for the expansion observed in the study package's DevTools compilation.
// 2026-11-05: guest mode reuses subpackages/study/practice and practice-result; the extra
// text-input/notice markup leaves 1484.3 KiB, under 1 KiB below the old 1.45 MiB ceiling,
// so the ceiling is 1.50 MiB. Recorded in prompts/tasks/current_task.md.
const SOURCE_PACKAGE_LIMITS = { 'subpackages/study': 1.5 * 1024 * 1024 }
const MAX_MEDIA_BYTES = 190 * 1024 // DevTools checks the aggregate against 200 KiB.
const MEDIA_EXTENSIONS = new Set([
  '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.svg',
  '.mp3', '.wav', '.aac', '.m4a', '.ogg', '.flac', '.ape', '.amr', '.wma', '.mp4', '.aiff', '.caf',
])

function matchesPackIgnore(relativePath, rule) {
  const value = rule.value.replace(/\\/g, '/').replace(/^\.\//, '')
  if (rule.type === 'folder') return relativePath === value || relativePath.startsWith(value + '/')
  if (rule.type === 'file') return relativePath === value
  if (rule.type === 'suffix') return relativePath.endsWith(value)
  if (rule.type !== 'glob') throw new Error('Unsupported pack ignore type: ' + rule.type)
  const escaped = value.replace(/[.+^${}()|[\]\\]/g, '\\$&')
  const pattern = escaped.replace(/\*\*\//g, '\u0001').replace(/\*\*/g, '\u0002')
    .replace(/\*/g, '[^/]*').replace(/\?/g, '[^/]')
    .replace(/\u0001/g, '(?:.*/)?').replace(/\u0002/g, '.*')
  return new RegExp('^' + pattern + '$').test(relativePath)
}

function collectPackageSizes(miniRoot, appConfig, projectConfig) {
  const packOptions = projectConfig.packOptions || {}
  if ((packOptions.include || []).length) {
    throw new Error('Explicit pack include rules require updating this source-only guard')
  }
  const ignored = packOptions.ignore || []
  const subpackageRoots = (appConfig.subPackages || appConfig.subpackages || [])
    .map(item => item.root.replace(/\/$/, '') + '/')
  const packages = { __APP__: { bytes: 0, files: 0 } }
  const media = []
  function walk(directory) {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const filePath = path.join(directory, entry.name)
      const relativePath = path.relative(miniRoot, filePath).split(path.sep).join('/')
      if (ignored.some(rule => matchesPackIgnore(relativePath, rule))) continue
      if (entry.isDirectory()) { walk(filePath); continue }
      const root = subpackageRoots.find(prefix => relativePath.startsWith(prefix))
      const packageName = root ? root.slice(0, -1) : '__APP__'
      const bytes = fs.statSync(filePath).size
      packages[packageName] ||= { bytes: 0, files: 0 }
      packages[packageName].bytes += bytes
      packages[packageName].files += 1
      if (MEDIA_EXTENSIONS.has(path.extname(entry.name).toLowerCase())) {
        media.push({ path: relativePath, bytes })
      }
    }
  }
  walk(miniRoot)
  return { packages, media, mediaBytes: media.reduce((sum, file) => sum + file.bytes, 0) }
}

function checkBudgets(summary) {
  const oversized = Object.entries(summary.packages).filter(([name, info]) =>
    info.bytes > (SOURCE_PACKAGE_LIMITS[name] || MAX_PACKAGE_BYTES),
  )
  if (oversized.length) {
    throw new Error('Source package budget exceeded: ' + oversized.map(([name, info]) =>
      `${name}: ${(info.bytes / 1024).toFixed(1)} KiB`,
    ).join(', '))
  }
  if (summary.mediaBytes > MAX_MEDIA_BYTES) {
    const largest = [...summary.media].sort((a, b) => b.bytes - a.bytes).slice(0, 5)
    throw new Error(`Aggregate media budget exceeded: ${(summary.mediaBytes / 1024).toFixed(1)} KiB ` +
      `(source guard: ${MAX_MEDIA_BYTES / 1024} KiB; DevTools: 200 KiB). Largest: ` +
      largest.map(file => `${file.path} (${(file.bytes / 1024).toFixed(1)} KiB)`).join(', '))
  }
}

if (require.main === module) {
  const miniRoot = path.resolve(__dirname, '..')
  const readJson = file => JSON.parse(fs.readFileSync(path.join(miniRoot, file), 'utf8'))
  const summary = collectPackageSizes(miniRoot, readJson('app.json'), readJson('project.config.json'))
  checkBudgets(summary)
  for (const [name, info] of Object.entries(summary.packages)) {
    console.log(`${name === '__APP__' ? 'main' : name} source size check passed: ` +
      `${(info.bytes / 1024).toFixed(1)} KiB across ${info.files} files`)
  }
  console.log(`Aggregate media source check passed: ${(summary.mediaBytes / 1024).toFixed(1)} KiB`)
}

module.exports = { matchesPackIgnore, collectPackageSizes, checkBudgets, MAX_MEDIA_BYTES }
