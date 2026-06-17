#!/usr/bin/env node
/**
 * Verify that latex-symbols.ts (source of truth) and latex-symbols.js (mirror)
 * have identical key sets.
 *
 * Usage: node scripts/check-latex-symbols-sync.js
 */
const fs = require('fs')
const path = require('path')

const TS_FILE = path.resolve(__dirname, '../admin-frontend/src/lib/latex-symbols.ts')
const JS_FILE = path.resolve(__dirname, '../miniprogram/utils/latex-symbols.js')

// Extract keys from TS source via regex
function parseKeysFromSource(source, objName) {
  // Match keys inside the object assigned to objName
  const start = source.indexOf(objName + ': Record') >= 0
    ? source.indexOf(objName + ': Record')
    : source.indexOf(objName + ' = {')
  if (start < 0) throw new Error('Cannot find ' + objName + ' in source')
  const open = source.indexOf('{', start) + 1
  const keys = []
  const re = /^\s+([A-Za-z_][A-Za-z0-9_]*)\s*:/gm
  let m
  while ((m = re.exec(source.slice(open))) !== null) {
    keys.push(m[1])
  }
  return [...new Set(keys)].sort()
}

function parseArrayFromSource(source, arrName) {
  const re = new RegExp(arrName + "\\s*=\\s*\\[([^\\]]+)\\]", '')
  const m = re.exec(source)
  if (!m) throw new Error('Cannot find ' + arrName)
  return m[1].split(',').map(s => s.trim().replace(/['"]/g, '')).filter(Boolean).sort()
}

const tsSource = fs.readFileSync(TS_FILE, 'utf-8')
const tsKeys = parseKeysFromSource(tsSource, 'LATEX_SYMBOLS')
const tsFns = parseArrayFromSource(tsSource, 'LATEX_FUNCTION_NAMES')

const jsMod = require(JS_FILE)
const jsKeys = Object.keys(jsMod.LATEX_SYMBOLS).sort()
const jsFns = [...jsMod.LATEX_FUNCTION_NAMES].sort()

let exitCode = 0
const onlyInTs = tsKeys.filter(k => !jsKeys.includes(k))
const onlyInJs = jsKeys.filter(k => !tsKeys.includes(k))
if (onlyInTs.length) { console.error('In TS but not JS:', onlyInTs.join(', ')); exitCode = 1 }
if (onlyInJs.length) { console.error('In JS but not TS:', onlyInJs.join(', ')); exitCode = 1 }

const fnsOnlyTs = tsFns.filter(k => !jsFns.includes(k))
const fnsOnlyJs = jsFns.filter(k => !tsFns.includes(k))
if (fnsOnlyTs.length) { console.error('Fns in TS but not JS:', fnsOnlyTs.join(', ')); exitCode = 1 }
if (fnsOnlyJs.length) { console.error('Fns in JS but not TS:', fnsOnlyJs.join(', ')); exitCode = 1 }

if (exitCode === 0) console.log('OK: ' + tsKeys.length + ' symbols + ' + tsFns.length + ' fns in sync')
process.exit(exitCode)
