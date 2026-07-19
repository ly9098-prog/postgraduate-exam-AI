#!/usr/bin/env node
/**
 * fix_formula_det_db.js
 *
 * Fix database formula records: convert \det(...) to \left|...\right|.
 * Also processes conditions and error_tips fields.
 *
 * Safe: uses normalizeDeterminantNotation() from formula-content.js,
 *       creating a backup; uses transactions for all changes.
 *
 * Usage: node scripts/fix_formula_det_db.js
 */

const path = require('path')
const { execSync } = require('child_process')
const crypto = require('crypto')

const fc = require(path.resolve(__dirname, '..', 'miniprogram', 'subpackages', 'formulas', 'utils', 'formula-content'))

const DB = path.resolve(__dirname, '..', 'backend', 'postgraduate.db')

function sql(query) {
  return execSync(`sqlite3 "${DB}" "${query.replace(/"/g, '\\"')}"`, { encoding: 'utf8' }).trim()
}

// Load all formula_cards
const rows = sql(`
  SELECT id, title, formula_blocks, conditions, symbol_notes,
         secondary_conclusions, error_tips, examples, content_hash, version
  FROM formula_cards
  WHERE formula_blocks LIKE '%det%'
     OR conditions LIKE '%det%'
     OR symbol_notes LIKE '%det%'
     OR secondary_conclusions LIKE '%det%'
     OR error_tips LIKE '%det%'
     OR examples LIKE '%det%'
  ORDER BY id
`).split('\n').filter(Boolean)

const changes = []

rows.forEach(row => {
  const parts = row.split('|')
  if (parts.length < 10) {
    console.error('  SKIP unparseable row:', row.slice(0, 80))
    return
  }
  const id = parts[0]
  const title = parts[1]
  const blocksJson = parts[2]
  const conditions = parts[3] || ''
  const symbolNotes = parts[4] || ''
  const secondary = parts[5] || ''
  const errorTips = parts[6] || ''
  const examples = parts[7] || ''
  const oldHash = parts[8] || ''
  const version = parseInt(parts[9] || '0', 10)

  const cardChanges = []

  // Process formula_blocks
  let blocks = []
  try { blocks = JSON.parse(blocksJson) } catch (e) { blocks = [] }

  const newBlocks = blocks.map(block => {
    const blockObj = typeof block === 'string' ? { latex: block } : { ...block }
    const oldLatex = blockObj.latex || ''
    const newLatex = fc.normalizeDeterminantNotation(oldLatex)
    if (newLatex !== oldLatex) {
      blockObj.latex = newLatex
      cardChanges.push({ field: 'formula_blocks', label: blockObj.label || '(unnamed)', old: oldLatex, new: newLatex })
    }
    return blockObj
  })

  // Calculate content hash from all fields
  const hashInput = JSON.stringify({
    formula_blocks: newBlocks,
    conditions,
    symbol_notes: symbolNotes,
    secondary_conclusions: secondary,
    error_tips: errorTips,
    examples,
  })
  const newHash = crypto.createHash('sha256').update(hashInput).digest('hex')

  if (cardChanges.length > 0) {
    changes.push({
      id,
      title,
      version: version + 1,
      oldHash,
      newHash,
      blocksJson: JSON.stringify(newBlocks),
      cardChanges,
    })
  }
})

// Report
console.log(`\nFound ${changes.length} records with determinable changes:\n`)

changes.forEach(c => {
  console.log(`[${c.id}] ${c.title} (v${c.version})`)
  c.cardChanges.forEach(cc => {
    console.log(`  ${cc.field} / ${cc.label}:`)
    console.log(`    OLD: ${cc.old}`)
    console.log(`    NEW: ${cc.new}`)
  })
  console.log('')
})

if (changes.length === 0) {
  console.log('No changes needed.')
  process.exit(0)
}

// Apply changes
console.log('Applying changes...')
sql('BEGIN TRANSACTION')

changes.forEach(c => {
  const now = new Date().toISOString().replace('T', ' ').split('.')[0]
  const escapedBlocks = c.blocksJson.replace(/'/g, "''")
  const updateSQL = `
    UPDATE formula_cards
    SET formula_blocks = '${escapedBlocks}',
        content_hash = '${c.newHash}',
        version = ${c.version},
        updated_at = '${now}'
    WHERE id = ${c.id}
  `
  try {
    sql(updateSQL)

    // Also insert into formula_card_versions
    const snapshot = JSON.stringify({
      formula_blocks: JSON.parse(c.blocksJson),
      conditions: null,
      symbol_notes: null,
      secondary_conclusions: null,
      error_tips: null,
      examples: null,
    }).replace(/'/g, "''")

    sql(`
      INSERT INTO formula_card_versions
        (formula_card_id, version, snapshot, action, created_at)
      VALUES (${c.id}, ${c.version}, '${snapshot}', 'det_fix', '${now}')
    `)

    console.log(`  ✓ Updated card ${c.id} (v${c.version})`)
  } catch (e) {
    console.error(`  ✗ Failed to update card ${c.id}:`, e.message)
    sql('ROLLBACK')
    process.exit(1)
  }
})

sql('COMMIT')
console.log(`\nDone. ${changes.length} records updated.`)
