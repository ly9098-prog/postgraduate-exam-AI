/*
 * Guard the WeChat main package size.  Files below a subpackage root are not
 * part of the main package; local test/tooling directories are excluded from
 * uploads by project.config.json and are skipped here as well.
 */
const fs = require('fs')
const path = require('path')

const miniRoot = path.resolve(__dirname, '..')
const appConfig = JSON.parse(fs.readFileSync(path.join(miniRoot, 'app.json'), 'utf8'))
const subpackageRoots = (appConfig.subPackages || []).map((item) =>
  path.join(miniRoot, item.root) + path.sep,
)
const ignoredDirectories = new Set([
  'node_modules',
  'tests',
  'scripts',
  '__mocks__',
  '.pytest_cache',
  '.ruff_cache',
  '.claude',
])

const MAX_PACKAGE_BYTES = 1.4 * 1024 * 1024
const packageSizes = { __APP__: { bytes: 0, files: 0 } }

function walk(directory) {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    if (entry.isDirectory() && ignoredDirectories.has(entry.name)) continue
    const filePath = path.join(directory, entry.name)
    if (entry.isDirectory()) {
      walk(filePath)
      continue
    }
    const subpackageRoot = subpackageRoots.find((root) => filePath.startsWith(root))
    const packageName = subpackageRoot ? subpackageRoot.slice(miniRoot.length + 1, -1) : '__APP__'
    packageSizes[packageName] ||= { bytes: 0, files: 0 }
    packageSizes[packageName].bytes += fs.statSync(filePath).size
    packageSizes[packageName].files += 1
  }
}

walk(miniRoot)

const oversized = Object.entries(packageSizes).filter(([, info]) => info.bytes > MAX_PACKAGE_BYTES)
if (oversized.length) {
  const detail = oversized
    .map(([name, info]) => `${name}: ${(info.bytes / 1024).toFixed(1)} KiB`)
    .join(', ')
  throw new Error(`package size exceeds ${(MAX_PACKAGE_BYTES / 1024).toFixed(1)} KiB: ${detail}`)
}

for (const [name, info] of Object.entries(packageSizes)) {
  console.log(
    `${name === '__APP__' ? 'main' : name} package size check passed: ` +
      `${(info.bytes / 1024).toFixed(1)} KiB across ${info.files} files`,
  )
}
