/*
 * Guard custom-component paths used by the native miniprogram.
 *
 * After dashboard/home were split into subpackages, main-package components
 * such as app-dialog are only referenced from those subpackages. WeChat
 * DevTools with lazyCodeLoading=requiredComponents and ignoreDevUnusedFiles
 * can then drop the component WXML and compile as:
 *   WXML file not found: ./components/app-dialog/index.wxml
 * which cascades into a render-layer `__route__ is not defined`.
 *
 * Run: cd miniprogram && node tests/test-component-paths.js
 */
const fs = require('fs')
const path = require('path')

const miniRoot = path.resolve(__dirname, '..')
const skipDirNames = new Set([
  'node_modules',
  'miniprogram_npm',
  'tests',
  'scripts',
  '__mocks__',
  '.pytest_cache',
  '.ruff_cache',
  '.claude',
])

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, 'utf8'))
}

function walkFiles(directory, suffix, out) {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      if (skipDirNames.has(entry.name)) continue
      walkFiles(path.join(directory, entry.name), suffix, out)
      continue
    }
    if (entry.name.endsWith(suffix)) out.push(path.join(directory, entry.name))
  }
}

function resolveComponentStem(jsonFile, componentPath) {
  const abs = componentPath.startsWith('/')
    ? path.join(miniRoot, componentPath.replace(/^\/+/, ''))
    : path.resolve(path.dirname(jsonFile), componentPath)
  const stems = [abs]
  if (path.basename(abs) !== 'index') stems.push(path.join(abs, 'index'))
  for (const stem of stems) {
    if (
      fs.existsSync(stem + '.js') &&
      fs.existsSync(stem + '.json') &&
      fs.existsSync(stem + '.wxml')
    ) {
      return stem
    }
  }
  return null
}

const appConfig = readJson(path.join(miniRoot, 'app.json'))
const subpackageRoots = (appConfig.subPackages || []).map((item) =>
  path.join(miniRoot, item.root) + path.sep,
)
const globalComponents = appConfig.usingComponents || {}
if (!globalComponents['app-dialog']) {
  throw new Error('app.json must globally register app-dialog for subpackage use')
}
if (!globalComponents['premium-nav']) {
  throw new Error('app.json must globally register premium-nav for subpackage use')
}

const jsonFiles = []
walkFiles(miniRoot, '.json', jsonFiles)

const missing = []
const unregisteredMainComponents = []
let componentRefCount = 0

for (const jsonFile of jsonFiles) {
  let data
  try {
    data = readJson(jsonFile)
  } catch (err) {
    throw new Error('invalid JSON ' + path.relative(miniRoot, jsonFile) + ': ' + err.message)
  }
  const comps = data.usingComponents
  if (!comps || typeof comps !== 'object') continue
  const inSubpackage = subpackageRoots.some((root) => jsonFile.startsWith(root))
  for (const [tag, componentPath] of Object.entries(comps)) {
    if (typeof componentPath !== 'string' || componentPath.startsWith('plugin://')) continue
    componentRefCount += 1
    const stem = resolveComponentStem(jsonFile, componentPath)
    if (!stem) {
      missing.push({
        file: path.relative(miniRoot, jsonFile),
        tag,
        componentPath,
      })
      continue
    }
    const relStem = path.relative(miniRoot, stem).split(path.sep).join('/')
    const isMainPackageComponent = relStem.startsWith('components/')
    if (inSubpackage && isMainPackageComponent && !globalComponents[tag]) {
      unregisteredMainComponents.push({
        file: path.relative(miniRoot, jsonFile),
        tag,
        componentPath,
      })
    }
  }
}

if (missing.length) {
  throw new Error(
    'usingComponents path missing js/json/wxml:\n' +
      missing.map((row) => `  ${row.file} ${row.tag}=${row.componentPath}`).join('\n'),
  )
}

if (unregisteredMainComponents.length) {
  throw new Error(
    'subpackage uses main-package component without app.json usingComponents:\n' +
      unregisteredMainComponents
        .map((row) => `  ${row.file} ${row.tag}=${row.componentPath}`)
        .join('\n'),
  )
}

const wxmlFiles = []
walkFiles(miniRoot, '.wxml', wxmlFiles)
const selfClosingAppDialog = []
const selfClosingRe = /<app-dialog\b[^>]*\/>/
for (const wxmlFile of wxmlFiles) {
  const text = fs.readFileSync(wxmlFile, 'utf8')
  if (selfClosingRe.test(text)) {
    selfClosingAppDialog.push(path.relative(miniRoot, wxmlFile))
  }
}
if (selfClosingAppDialog.length) {
  throw new Error(
    'app-dialog must use an explicit closing tag (glass-easel / requiredComponents):\n' +
      selfClosingAppDialog.map((file) => '  ' + file).join('\n'),
  )
}

const dialogFiles = ['index.js', 'index.json', 'index.wxml', 'index.wxss'].map((name) =>
  path.join(miniRoot, 'components', 'app-dialog', name),
)
for (const filePath of dialogFiles) {
  if (!fs.existsSync(filePath)) {
    throw new Error('missing app-dialog file: ' + path.relative(miniRoot, filePath))
  }
}

console.log(
  'component path check passed: ' +
    componentRefCount +
    ' usingComponents refs, global app-dialog/premium-nav registered',
)
