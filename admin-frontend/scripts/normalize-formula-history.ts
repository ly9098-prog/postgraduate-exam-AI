/**
 * Formula history data normaliser.
 *
 * Reads existing formulas from the API, normalises conditions and errorTips
 * via normalizeFormulaText, and optionally writes changes back.
 *
 * Default mode: dry-run (only show diff, no writes).
 * Pass --apply to write changes (exports JSON backup first).
 *
 * Usage:
 *   npx tsx scripts/normalize-formula-history.ts                 # dry-run all
 *   npx tsx scripts/normalize-formula-history.ts --apply         # write all
 *   npx tsx scripts/normalize-formula-history.ts --id 42         # single formula
 *   npx tsx scripts/normalize-formula-history.ts --limit 10      # limit to 10
 *   npx tsx scripts/normalize-formula-history.ts --field conditions
 *   npx tsx scripts/normalize-formula-history.ts --apply --id 42 --field errorTips
 *
 * Auth: set AUTH_HEADER env var for custom auth (e.g. "Bearer <token>").
 * API  base: set API_BASE_URL (default http://localhost:8000/api/v1).
 */

import { normalizeFormulaText } from '../src/lib/formula-normalize';

/* ── Config ── */

const API_BASE = process.env.API_BASE_URL || 'http://localhost:8000/api/v1';
const AUTH_HEADER = process.env.AUTH_HEADER || '';
const HEADERS: Record<string, string> = { 'Content-Type': 'application/json' };
if (AUTH_HEADER) HEADERS['Authorization'] = AUTH_HEADER;

/* ── Types ── */

interface Formula {
  id: number;
  conditions?: string | null;
  error_tips?: string | null;
  [key: string]: unknown;
}

type Change = { id: number; field: string; before: string; after: string };

/* ── CLI arg helpers ── */

const args = process.argv.slice(2);
const has = (name: string) => args.includes(name);
const value = (name: string) => {
  const i = args.indexOf(name);
  return i >= 0 && i + 1 < args.length ? args[i + 1] : null;
};

const APPLY = has('--apply');
const ID_FILTER = value('--id');
const LIMIT = value('--limit') ? Math.max(1, Number(value('--limit'))) : Infinity;
const FIELD_FILTER = value('--field') as 'conditions' | 'errorTips' | null;

/* ── API helpers ── */

async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { headers: HEADERS });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`GET ${path} ${res.status}${text ? ': ' + text.slice(0, 200) : ''}`);
  }
  return res.json();
}

async function apiPut(path: string, body: Record<string, unknown>): Promise<void> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'PUT',
    headers: HEADERS,
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`PUT ${path} ${res.status}${text ? ': ' + text.slice(0, 200) : ''}`);
  }
}

/* ── Fetch ── */

async function fetchFormulas(): Promise<Formula[]> {
  if (ID_FILTER) {
    const data = await apiGet<Formula>(`/formulas/${ID_FILTER}`);
    return [data];
  }

  const all: Formula[] = [];
  let page = 1;

  while (all.length < LIMIT) {
    const data = await apiGet<{ items?: Formula[] } | Formula[]>(
      `/formulas?page=${page}&page_size=50`,
    );
    const items = Array.isArray(data) ? data : data.items ?? [];
    if (items.length === 0) break;
    all.push(...items);
    if (items.length < 50) break;
    page++;
  }

  return all.slice(0, LIMIT);
}

/* ── Main ── */

async function main() {
  console.log();
  console.log('  Formula history normaliser');
  console.log(`  Mode:       ${APPLY ? 'APPLY (will write changes)' : 'dry-run'}`);
  console.log(`  API base:   ${API_BASE}`);
  if (ID_FILTER) console.log(`  Filter:     id = ${ID_FILTER}`);
  if (FIELD_FILTER) console.log(`  Field:      ${FIELD_FILTER}`);
  if (LIMIT < Infinity) console.log(`  Limit:      ${LIMIT}`);
  console.log();

  // Fetch
  let formulas: Formula[];
  try {
    formulas = await fetchFormulas();
  } catch (err) {
    console.error('  FAILED to fetch formulas:', err);
    process.exit(1);
  }

  console.log(`  Found ${formulas.length} formula(s).\n`);

  // Diff
  const changes: Change[] = [];

  for (const f of formulas) {
    const check = (field: string, value: string | null | undefined) => {
      if (value == null) return;
      const normalized = normalizeFormulaText(value);
      if (normalized === value) return;
      changes.push({ id: f.id, field, before: value, after: normalized ?? '' });
    };

    if (!FIELD_FILTER || FIELD_FILTER === 'conditions') check('conditions', f.conditions);
    if (!FIELD_FILTER || FIELD_FILTER === 'errorTips') check('error_tips', f.error_tips);
  }

  // Report
  if (changes.length === 0) {
    console.log('  All formulas already normalised. ✓\n');
    return;
  }

  const changedIds = new Set(changes.map((c) => c.id)).size;
  console.log(`  ${changes.length} field(s) across ${changedIds} formula(s) need normalisation.\n`);

  for (const c of changes) {
    console.log(`  #${c.id} | ${c.field}`);
    console.log(`    before: ${JSON.stringify(c.before)}`);
    console.log(`    after:  ${JSON.stringify(c.after)}`);
    console.log();
  }

  if (!APPLY) {
    console.log('  Dry-run complete. Pass --apply to write changes.\n');
    return;
  }

  // Backup
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
  const backupPath = `formula-backup-${timestamp}.json`;
  const backupIds = Array.from(new Set(changes.map((c) => c.id)));
  const backupData = formulas.filter((f) => backupIds.includes(f.id));

  const { writeFileSync } = await import('fs');
  writeFileSync(backupPath, JSON.stringify(backupData, null, 2));
  console.log(`  Backup saved → ${backupPath}\n`);

  // Apply
  for (const c of changes) {
    try {
      await apiPut(`/formulas/${c.id}`, { [c.field]: c.after });
      console.log(`  OK  #${c.id} ${c.field}`);
    } catch (err) {
      console.error(`  FAIL #${c.id} ${c.field}:`, err);
    }
  }

  console.log(`\n  Done. ${changes.length} field(s) processed.\n`);
}

main().catch((err) => {
  console.error('\n  Fatal error:', err);
  process.exit(1);
});
