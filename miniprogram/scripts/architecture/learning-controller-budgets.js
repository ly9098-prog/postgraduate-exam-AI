const fs = require('node:fs')
const path = require('node:path')
const { createRequire } = require('node:module')
const { Script } = require('node:vm')

const ROOT = path.resolve(__dirname, '../../..')
const MINI_ROOT = path.join(ROOT, 'miniprogram')
const ts = createRequire(path.join(ROOT, 'admin-frontend/package.json'))('typescript')

const DIRECTORIES = Object.freeze([
  'pages/pomodoro/utils',
  'subpackages/productivity/pomodoro-stats',
  'subpackages/study/practice/utils',
  'subpackages/study/review-today/utils',
  'subpackages/exam/utils',
  'subpackages/study/practice-result/utils',
  'subpackages/study/wrong-detail/utils',
])
// Same directories, but every JavaScript module is governed, not only the
// `*controller.js` files. Page entries keep their own legacy ceilings from
// scripts/architecture/page-budgets.js and are excluded here.
const MODULE_DIRECTORIES = DIRECTORIES
const PAGE_ENTRIES = Object.freeze([
  'subpackages/productivity/pomodoro-stats/index.js',
])
const FUNCTION_BUDGET = 50
const MODULE_BUDGET = 300

function inspectSource(source, relativePath) {
  const file = ts.createSourceFile(
    relativePath, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS,
  )
  const lines = source.trimEnd().split('\n').length
  const errors = []
  const functions = []
  try {
    new Script(source, { filename: relativePath })
  } catch (error) {
    errors.push(`${relativePath}: invalid JavaScript: ${error.message}`)
  }
  if (lines > MODULE_BUDGET) {
    errors.push(`${relativePath}: module has ${lines} lines, limit ${MODULE_BUDGET}`)
  }
  for (const diagnostic of file.parseDiagnostics) {
    errors.push(`${relativePath}: ${ts.flattenDiagnosticMessageText(diagnostic.messageText, ' ')}`)
  }
  function walk(node) {
    if (ts.isFunctionLike(node) && node.body) {
      const start = file.getLineAndCharacterOfPosition(node.getStart(file)).line + 1
      const end = file.getLineAndCharacterOfPosition(node.end).line + 1
      const length = end - start + 1
      functions.push({ start, lines: length })
      if (length > FUNCTION_BUDGET) {
        errors.push(`${relativePath}:${start}: function has ${length} lines, limit ${FUNCTION_BUDGET}`)
      }
    }
    ts.forEachChild(node, walk)
  }
  walk(file)
  return { path: relativePath, lines, functions, errors }
}

function collectFiles(directory, miniRoot, keep) {
  const files = []
  for (const entry of fs.readdirSync(directory, { withFileTypes: true }).sort((a, b) =>
    a.name.localeCompare(b.name))) {
    const filename = path.join(directory, entry.name)
    if (entry.isDirectory()) {
      files.push(...collectFiles(filename, miniRoot, keep))
    } else if (entry.isFile()) {
      const relative = path.relative(miniRoot, filename).split(path.sep).join('/')
      if (keep(relative)) files.push(relative)
    }
  }
  return files
}

function collectControllers(directory, miniRoot) {
  return collectFiles(directory, miniRoot, relative => relative.endsWith('controller.js'))
}

function collectModules(directory, miniRoot) {
  return collectFiles(
    directory,
    miniRoot,
    relative => relative.endsWith('.js') && !PAGE_ENTRIES.includes(relative),
  )
}

function scanControllers(miniRoot = MINI_ROOT) {
  return scanDirectories(DIRECTORIES, collectControllers, miniRoot)
}

function scanModules(miniRoot = MINI_ROOT) {
  return scanDirectories(MODULE_DIRECTORIES, collectModules, miniRoot)
}

function scanDirectories(directories, collect, miniRoot) {
  const modules = []
  const errors = []
  const scanned = []
  for (const relativePath of directories) {
    const directory = path.join(miniRoot, relativePath)
    if (!fs.existsSync(directory) || !fs.statSync(directory).isDirectory()) {
      errors.push(`${relativePath}: required controller directory is missing or is not a directory`)
      continue
    }
    const files = collect(directory, miniRoot)
    scanned.push({ path: relativePath, controllers: files.length })
    if (!files.length) errors.push(`${relativePath}: controller directory is empty`)
    for (const filename of files) {
      const source = fs.readFileSync(path.join(miniRoot, filename), 'utf8')
      const result = inspectSource(source, filename)
      modules.push(result)
      errors.push(...result.errors)
    }
  }
  return { directories: scanned, modules, errors }
}

function main() {
  const controllers = scanControllers()
  const modules = scanModules()
  const errors = [...controllers.errors, ...modules.errors]
  if (errors.length) {
    console.error(errors.join('\n'))
    process.exitCode = 1
    return
  }
  const controllerFunctions = controllers.modules
    .reduce((sum, module) => sum + module.functions.length, 0)
  const moduleFunctions = modules.modules
    .reduce((sum, module) => sum + module.functions.length, 0)
  console.log(`Learning controller budgets passed: ${controllers.directories.length} directories, ` +
    `${controllers.modules.length} controllers, ${controllerFunctions} functions; ` +
    `function limit ${FUNCTION_BUDGET}, module limit ${MODULE_BUDGET}`)
  console.log(`Learning module budgets passed: ${modules.directories.length} directories, ` +
    `${modules.modules.length} modules, ${moduleFunctions} functions; ` +
    `${PAGE_ENTRIES.length} page entry excluded for the page budget gate`)
}

module.exports = {
  DIRECTORIES,
  MODULE_DIRECTORIES,
  PAGE_ENTRIES,
  FUNCTION_BUDGET,
  MODULE_BUDGET,
  inspectSource,
  scanControllers,
  scanModules,
}

if (require.main === module) main()
