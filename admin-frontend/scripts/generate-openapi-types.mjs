#!/usr/bin/env node
/** Generate TypeScript declarations from a FastAPI OpenAPI JSON document. */
import { mkdir } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const input = path.resolve(process.argv[2] ?? path.join(root, "..", ".contract", "openapi.json"));
const output = path.resolve(process.argv[3] ?? path.join(root, ".contract", "openapi.ts"));
await mkdir(path.dirname(output), { recursive: true });

const command = process.platform === "win32" ? "npx.cmd" : "npx";
const args = [
  "--yes",
  "--package=openapi-typescript@7.8.0",
  "openapi-typescript",
  input,
  "--output",
  output,
];
const result = spawnSync(command, args, { stdio: "inherit", cwd: root });
if (result.error) throw result.error;
process.exit(result.status ?? 1);
