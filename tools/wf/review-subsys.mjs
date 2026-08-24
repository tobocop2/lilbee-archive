// Single-pass parallel code review over file batches, ported from the Claude wf script.
// Usage: node review-subsys.mjs [--known <titles-file>] <paths...>   (default: src/lilbee/retrieval)
import { readdirSync, statSync } from "node:fs"
import { join } from "node:path"
import { batches, createRunner } from "./lib.mjs"

export const meta = {
  name: "subsys-review",
  description: "Token-conservative single-pass review of a subsystem, one parallel batch per file group",
}

const FINDINGS = {
  type: "object", required: ["findings"],
  properties: {
    findings: {
      type: "array",
      items: {
        type: "object", required: ["title", "file", "severity", "category", "confidence", "description", "evidence"],
        properties: {
          title: { type: "string" }, file: { type: "string" }, line: { type: "integer" },
          severity: { enum: ["blocker", "important", "minor"] },
          category: { type: "string" },
          confidence: { enum: ["verified", "suspected"] },
          description: { type: "string" }, evidence: { type: "string" },
        },
      },
    },
  },
}

const SEVERITY_RANK = { blocker: 0, important: 1, minor: 2 }
const BATCH_SIZE = 6

function collect(paths) {
  const files = []
  for (const p of paths) {
    if (statSync(p).isDirectory()) {
      for (const entry of readdirSync(p, { recursive: true })) {
        if (entry.endsWith(".py")) files.push(join(p, entry))
      }
    } else {
      files.push(p)
    }
  }
  return files.sort()
}

function parseArgs(argv) {
  const paths = []
  let known
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === "--known") known = argv[++i]
    else paths.push(argv[i])
  }
  return { paths: paths.length ? paths : ["src/lilbee/retrieval"], known }
}

const { paths, known } = parseArgs(process.argv.slice(2))
const tree = process.cwd()
const files = collect(paths)
const runner = await createRunner({ config: { permission: { edit: "deny" } } })

try {
  const groups = batches(files, BATCH_SIZE)
  console.error(`reviewing ${files.length} files in ${groups.length} batches`)
  const results = await runner.parallel(groups.map((group, i) => () =>
    runner.agent(`You are doing a single-pass, high-rigor code review of part of the lilbee codebase.
Tree under review: ${tree}. Read files from that directory directly. READ-ONLY: never edit, commit, or push (edits are denied at the tool level).
YOUR FILES (review every line of each): ${JSON.stringify(group)}
You may read any other file in the tree for context (callers, callees, tests, AGENTS.md at ${tree}/AGENTS.md), but report findings ONLY in your assigned files.
Apply ALL of these lenses in one pass per file: (1) correctness bugs and edge cases (empty inputs, unicode, huge corpora, concurrency, error paths swallowed); (2) code smells per AGENTS.md and low-complexity/DRY/Pythonic standards; (3) wheel-reinvention: mechanisms a dependency already owns (check ${tree}/.venv or installed libs: lancedb, pydantic, httpx, filelock); (4) misuse of dependency APIs; (5) comment/docstring drift vs actual behavior; (6) test-truth: find each file's tests and flag tests whose name promises what the body does not exercise, and risky paths with no test; (7) performance traps on large corpora.
${known ? `KNOWN FINDINGS (do NOT re-report these or close variants; the list is at ${known} - read it first).` : ""}
Self-verify before reporting: re-derive each finding from the code, check whether a caller or sibling handles it, and label confidence "verified" (you confirmed the defect end to end, including that no caller handles it) or "suspected" (plausible but you could not fully confirm). Report every distinct finding, no cap; severity: blocker = wrong results or data loss on a default path; important = real defect or missed-handling a reviewer would demand fixed; minor = polish. Evidence must cite file:line and quote the relevant code. Budget: stop at ~10 minutes and return what you have.`,
      { schema: FINDINGS, title: `review:batch${i}:${group[0].split("/").pop()}` })
      .then((r) => r?.findings ?? [])
      .catch((err) => {
        console.error(`batch ${i} failed: ${err.message}`)
        return []
      })
  ))
  const flat = results.flat().sort((a, b) => SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity])
  console.error(`${flat.length} findings from ${groups.length} batches`)
  console.log(JSON.stringify(flat, null, 2))
} finally {
  runner.close()
}
