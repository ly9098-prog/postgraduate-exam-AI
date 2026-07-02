#!/usr/bin/env node
/**
 * Test that LaTeX symbols are in sync between the source-of-truth
 * (admin-frontend TypeScript) and the miniprogram JavaScript mirror.
 */
const path = require('path')
const { checkLatexSymbolsSync } = require('../scripts/check-latex-symbols-sync')

function main() {
  const result = checkLatexSymbolsSync()
  if (!result.ok) {
    console.error(result.message || 'LaTeX symbols are not synchronized')
    process.exit(1)
  }
  console.log(result.message || 'LaTeX symbols sync check passed')
}

main()
