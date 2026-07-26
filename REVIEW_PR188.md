# Reviewing PR #188 in neovim — step-by-step plan

Branch: `tidy-module-organization` (47 commits ahead of `main`, tip `8b6a849`).
PR: <https://github.com/tobocop2/lilbee/pull/188>

This plan is tailored to your dotfiles — leader is `,`, you have Telescope,
LSP (pyright + ruff), nvim-tree, treesitter, gitsigns, mini.comment, conform.
Companion file: `REVIEW_PR188_COMMITS.txt` in this directory has the
commit-by-commit breakdown with stream labels.

You can delete both files after review (they're untracked).

## One-time setup (60s)

```bash
cd ~/projects/lilbee
git checkout tidy-module-organization
nvim
```

Once inside nvim, open both review files in splits so you can flip to them
fast:

- `:tabnew REVIEW_PR188.md`        — this plan
- `:vsp REVIEW_PR188_COMMITS.txt`  — the commit cheat sheet
- back to your code tab with `gt` (next tab)

## Your toolkit for this review

Pulled from your dotfiles. `<leader>` is `,`. The big ones:

| Goal | Keys |
|---|---|
| Find file by name (tests deprioritized!) | `,ff` |
| Find file including hidden/ignored | `,fa` |
| Live grep across the repo | `,fw` |
| Search current word under cursor | `,sw` |
| Fuzzy-find inside the current buffer | `,fz` |
| Open buffer list | `,fb` (or `,,`) |
| Resume the last picker | `,sr` |
| Browse all keymaps (when you forget) | `,fk` |
| Reveal current file in nvim-tree | `<C-f>` |
| Focus tree | `<C-t>` |
| Move between splits / tmux panes | `<C-h/j/k/l>` |
| Next / prev buffer | `<Tab>` / `<S-Tab>` |
| Close current buffer | `,x` |

LSP (pyright + ruff are auto-configured; treat these as your primary
navigation tools for this review):

| Goal | Keys |
|---|---|
| Goto definition | `gd` |
| Find all references | `gr` |
| Goto implementation | `gi` |
| Goto type definition | `gy` |
| Hover docs (signature + docstring) | `K` |
| Diagnostics next / prev | `]d` / `[d` |
| Diagnostics in buffer (Telescope) | `,sd` |
| Workspace diagnostics list | `,dq` |

Git browsing (you don't have fugitive, so we use Telescope's git pickers):

| Goal | Keys / command |
|---|---|
| Browse all commits in this branch | `:Telescope git_commits` |
| Commits touching the current file | `:Telescope git_bcommits` |
| `git status` view | `:Telescope git_status` |
| Show one commit's diff | `:!git show <sha> \| less` (in a terminal split: `:term`) |
| Blame current line | `:!git blame -L .,. -- %` (or just look at the gitsigns column) |

Misc:

- `Esc` clears search highlight (you mapped it).
- `<leader>/` toggles comment via mini.comment (good for marking lines you've
  read with `# REVIEW: read`).
- gitsigns shows `+ ~ _` in the sign column for hunks vs the previous commit
  (NOT vs main). To see what this PR changed in a file: `:!git diff origin/main -- %`.
- todo-comments highlights `TODO`, `NOTE`, `FIX`, `HACK`. None of those should
  exist in this PR's diff (the No-Back-Compat-Scaffolding rule rejects them);
  if you find one, that's a finding.

---

## Step 1 — Read the rules first (10 min)

The whole refactor obeys two documents that themselves got tightened. Read
them so the rest makes sense.

```
:e AGENTS.md
```

Search for "No Back-Compat Scaffolding" with `/No Back-Compat<CR>`. That's
the new section that drove most of the re-export deletions.

```
:e pyproject.toml
```

`/tool.ruff.lint<CR>` — see the new lint rules (`C90, N, RET, TID,
PLR0911, PLR0912, PLR0915, PLR2004`) and the `[tool.ruff.lint.mccabe]
max-complexity = 10`. These are the gates every later commit had to pass.

```
:e scripts/check_style_rules.py
```

Custom checks ruff can't express: em dashes, divider comments, stale
`<old>.py` references in docstrings, back-compat phrasing.

```
:e Makefile
```

`/^lint:<CR>` — note `make lint` runs ruff *and* the style script.

**What to take away:** every later file's shape was constrained by these.
Once you see the gates, the small choices (why something was renamed, why
a `# noqa` exists) stop being arbitrary.

---

## Step 2 — Trace the entry point (15 min)

The question: "what happens when I run `lilbee`?"

| Order | Open with | What to learn |
|---|---|---|
| 1 | `:e pyproject.toml` then `/scripts<CR>` | Look at `lilbee = "lilbee.runtime.launcher:main"`. That's the binary entry |
| 2 | `,ff runtime/launcher` | Then read `main()`. It sets up Typer and dispatches |
| 3 | `,ff cli/__init__` | The Typer app instance + how `model_app` sub-typer is attached. Note the comment about import order |
| 4 | `,ff cli/commands/__init__` | The 6-file command split. Comment explains why ordering matters (`--help` text) |
| 5 | `,ff cli/commands/meta` | Read `status_cmd` end to end. Use `gd` on `gather_status` to jump straight into the new `app/` layer |

**Tactic:** when you `gd` from `from lilbee.app.status import gather_status`, you
land in `src/lilbee/app/status.py`. That single jump is the architectural
transition this PR is about — `cli/` calling into `app/`, not the other way.

---

## Step 3 — The two architectural shifts (40 min)

These are the *why* of the PR. Everything else is consequence.

### Shift A — the `app/` shared use-case layer

CLI, HTTP, MCP, and TUI used to all reach into `cli/helpers.py` and
`cli/model.py` for surface-agnostic logic. Now `app/` owns it.

| Order | File | Concept |
|---|---|---|
| 1 | `,ff app/__init__` | **Intentionally empty.** That's the AGENTS.md "no facade re-exports" rule in action |
| 2 | `,ff app/status` | Simplest case. `gather_status()` returns `StatusResult` (bare Pydantic — no Rich) |
| 3 | `,ff cli/helpers` then `/render_status_result<CR>` | The Rich adapter over `StatusResult`. Note the layer split: `app/` has the data, `cli/` has the rendering |
| 4 | `,ff app/models` | The biggest use-case file. `list_models_data`, `pull_model_data`, etc. The shape that all four surfaces consume |
| 5 | `,ff app/reset` `,ff app/ingest` `,ff app/version` `,ff app/search` | Same pattern, smaller |
| 6 | `:cex system('grep -rn "from lilbee.app" src/lilbee/') | cope` (or just `,fw from lilbee.app<CR>`) | See the four surfaces calling into `app/`. Confirms the dependency direction is one-way |

After this step you understand half the PR.

### Shift B — `Services` consolidation

| Order | File | Concept |
|---|---|---|
| 1 | `,ff core/services` | The frozen `Services` dataclass. 11 fields. Note the field list: `provider, store, embedder, reranker, concepts, clusterer, searcher, registry, hf_client, model_manager, ingest_lock_registry` |
| 2 | Same file | `get_services()` — function-local imports inside it are the canonical example of "CLI-startup" import discipline |
| 3 | `,ff catalog/hf_client` | `HfClient` class — used to be free `_fetch_hf_models` + module-level `_hf_cache` dict. Cache moved into the class |
| 4 | `,ff runtime/ingest_lock` | `IngestLockRegistry` class — used to be 5 free functions in `server/handlers/ingest.py`. Note it lives in `runtime/`, NOT `server/` (cross-cutting review caught the layer inversion) |
| 5 | What's *not* there | `:!find src -name 'holder.py'` returns nothing. `modelhub/model_manager/holder.py` got deleted. There used to be a parallel `_ManagerHolder` singleton; now it's just `services.model_manager` |
| 6 | `:!git show 1487591 -- src/lilbee/modelhub/model_manager/holder.py` | See it being deleted in the F2+F3 bundle commit |

After this you understand the other half.

---

## Step 4 — One full god-module decomposition (25 min)

Pick `catalog/` — cleanest example. Walk through it; every other
decomposition (`server/handlers/`, `wiki/`, `cli/commands/`,
`providers/llama_cpp/`, etc.) follows the same pattern.

| Order | Action | Concept |
|---|---|---|
| 1 | `:!git log --oneline -- src/lilbee/catalog/ \| head` | See decomposition history |
| 2 | `,ff catalog/__init__` | Public re-exports only. No underscores leaked through |
| 3 | `,ff catalog/models` | Pure dataclasses. `HfPage`, `HfGgufMeta` — note the unprefixed names (NIT cleanup commit `769ba72`) |
| 4 | `,ff catalog/featured` | Hardcoded curated set; loads `featured_models.toml` |
| 5 | `,ff catalog/hf_client` | The `HfClient` class you saw in Step 3 |
| 6 | `,ff catalog/download_progress` | **The locked TUI progress chain** — `_CallbackProgressBar`, `_ProgressTracker`, `make_download_callback`. Treat as immutable contract; `tests/test_download_progress.py` is the regression gate |
| 7 | `,ff catalog/query` | `get_catalog`, `find_catalog_entry`. Notice the function-local `from lilbee.core.services import get_services` — circular avoidance (look at the comment) |
| 8 | `,ff catalog/download` | `download_model`, the actual HF download |
| 9 | `,ff catalog/formatting` then `,ff catalog/families` | Display name + grouping helpers |
| 10 | `,ff tests/test_catalog` | See how mock targets moved from old monolith path to submodule paths |

**Tactic:** treat each file as "what's the one thing this module owns?" If you
can summarize each file in one sentence, the split was right.

---

## Step 5 — Skim the other decompositions (20 min, optional depth)

You don't need to deep-read these. Just `,ff <package>/__init__` for each
and skim. Pick whichever interests you most for a deeper read.

| Package | Was | Files now |
|---|---|---|
| `server/handlers/` | `server/handlers.py` (1158 lines) | `sse, rag, models, ingest, config, documents, crawl` |
| `wiki/` | `wiki/gen.py` (1804 lines) | `generation, page, synthesis, citations, quality, persistence, batch, cache` |
| `providers/llama_cpp/` | `llama_cpp_provider.py` (741) | `provider, batching, log_dispatch, gguf_meta` |
| `providers/worker/` | `worker_process.py` (451; class was `WorkerProcess`) | `protocol, worker, manager` (class renamed `WorkerManager`) |
| `crawler/` (was `crawler/api.py`) | one big file | `runner, events, discovery` |
| `retrieval/clustering_embedding/` | one big file | `types, helpers, clusterer` |
| `data/store/` | `store.py` (955) | `types, schema, ranking, lance_helpers, core` |
| `data/ingest/` | `ingest.py` (968) | `types, extract, discovery, code, pipeline` |
| `retrieval/query/` | `query.py` (783) | `tokenize, formatting, dedup, expansion, searcher` |
| `core/config/` | `config.py` (1049) | `enums, validators, defaults, parsing, model` |

Useful question to ask each one: "do the file names match what each one
*does*?" If yes, the split was right.

---

## Step 6 — Read one rule-driven cleanup commit (15 min)

The single best commit for "see why each rule mattered" is **F9**:

```
:term
git show f42fdf0 | less
```

(or just `:!git show f42fdf0 > /tmp/f9.diff` then `:e /tmp/f9.diff`)

You'll see in one diff:

- The new ruff rules getting added
- ~50 source-tree fixes for `C901` / `PLR2004` / `N818` / etc.
- 3 exceptions renamed (`CrawlerBackendMissing → CrawlerBackendError`, etc.)
- 9 functions split for cyclomatic complexity (`extract_pdf_vision`,
  `crawl_and_save`, `download_model`, etc.)

That single commit has the most diverse "yeah, the lint forced this"
examples in one place.

For commits-as-stories navigation: `:Telescope git_commits` shows the
whole branch. Hit `<CR>` on any one to see its diff in the preview.
`<C-x>` opens it in a split.

---

## Step 7 — Tests + corner cases (15 min)

| File | Concept |
|---|---|
| `,ff tests/conftest` | The new autouse `_reset_services_after_test` fixture — singleton hygiene between tests. `/reset_services<CR>` to find it fast |
| `,ff tests/integration/test_crawl_integration` | The CI-revealed bug from commit `70f0418`: import was missed in F6 because integration tests are excluded from `make test` (see `pyproject.toml` `addopts = "--ignore=tests/integration"`) |
| `,ff runtime/_splash_runner` then `/_pipe_closed_posix<CR>` | Two `# pragma: no cover  POSIX-only` / `Windows-only` annotations — the platform-asymmetry coverage trick. Mirror pair |
| `,ff tests/test_download_progress` | The canonical TUI progress regression test. If it stays green, the locked progress chain is intact |

---

## Step 8 — Refactoring or moving code with CodeCompanion (during review)

If you spot something during review that you want to refactor or move,
your `,ac` / `,ao` / `,ae` / `,am` / `,aa` bindings give you three
escalating tools. Pick by what you're doing.

**First: don't commit straight to `tidy-module-organization`.** That branch
is in CI cleanup. Use a scratch branch:

```
:!git switch -c review/<topic>
```

Then choose a mode:

### Mode A — Inline edit on a selection (fastest, in-file refactors)

Visual-select the code (`V` for line-wise, `v` for char), then run an
`Ex` command with a natural-language prompt. The result replaces the
selection in place.

```vim
:'<,'>CodeCompanion split this function into a parser and a renderer
:'<,'>CodeCompanion extract the for-loop into a helper named _build_table_rows
:'<,'>CodeCompanion rename argument `data` to `model_record` in this function
```

No chat panel opens. The model produces the edit, CodeCompanion applies
it. Good for: extract method, rename within scope, simplify a block.
**Bad for: anything that touches another file.**

### Mode B — Chat panel (cross-file moves; needs broader context)

Open with `,ac` (your `:CodeCompanionChat Toggle` binding — talks to
Claude Sonnet 4.6 by default). For a cheap-experiment chat against
local Ollama instead, use `,ao`.

Inside the chat buffer, **slash commands** load context:

| Slash | What it does |
|---|---|
| `/buffer` | inject current buffer (you also have `,am` as a shortcut) |
| `/file` | filename completion → inject another file's contents |
| `/symbols` | list workspace symbols (LSP-driven) |
| `/lsp` | LSP info on the symbol under your original cursor |
| `/now` | timestamp |
| `/terminal` | last terminal output |

**Typical "move this function across files" flow:**

1. In the source file, visual-select the function. Press `,ae` — that's
   your `:CodeCompanionChat Add` binding. The chat opens with the
   selection embedded.
2. In the chat, type `/file<Tab>` and pick the destination file. Its
   full contents land in the prompt as context.
3. Write the move instruction. Be specific about importers:

   ```
   Move `gather_status` from `cli/helpers.py` into `app/status.py`. Keep
   the signature. Add the imports it needs (`cfg`, `Path`, etc.) at the
   top of `app/status.py`. Update every importer in `src/`, `tests/`,
   `docs/` — grep for `from lilbee.cli.helpers import gather_status`.
   ```

4. Send. The model returns a plan plus per-file diffs. To apply each
   diff: position cursor inside its code block and press `ga` (the
   "accept code" action, default in chat buffers). It writes to disk.

Claude Sonnet 4.6 supports multi-file edits in one turn — you'll see
each file's diff and accept individually.

### Mode C — Actions palette (curated workflows)

`,aa` opens `:CodeCompanionActions` — a picker over built-in prompt
templates. The ones useful for review:

- **Refactor code** — pre-fills a refactor-flavored prompt with your
  selection.
- **Code workflow** — the multi-step "explain → refactor → test"
  sequence.
- **Generate tests** — if you're walking through a moved function and
  want pytest coverage for it on the new path.

### Two caveats worth knowing

1. **The model only sees what you give it.** For a cross-file move,
   CodeCompanion will not auto-grep the codebase for callers. Either
   include all relevant files via `/file` slash commands, or paste the
   grep output yourself:
   ```
   :!grep -rn "gather_status" src/ tests/ > /tmp/callers.txt
   ```
   and then feed `/file /tmp/callers.txt` into the chat.

2. **For tiny review-stage ideas, don't refactor at all.** Drop a
   `# REVIEW: move this to app/` comment in the file (mark with `,/` for
   mini.comment), commit nothing, and use those comments as your
   follow-up todo list once `tidy-module-organization` merges. This is
   especially apt for the "I'd structure this differently but it works"
   kind of finding.

### Smoke-testing whatever you produce

Whichever mode you used:

```
:!uv run make check
```

If green, decide: cherry-pick into `tidy-module-organization`? Save for
a follow-up PR after it merges? File as a bd issue (`:!bd create
--type=task --priority=2 --title="..."`)? The PR's "no follow-up PRs"
posture is intentional — only cherry-pick if the change is small and
unambiguously fits the PR's scope.

---

## Step 9 — The merge with main (5 min)

```
:!git show 3f7a2b4 | less
```

Three real conflicts resolved in one commit:

1. README catalog ASCII art — kept main's monospace-safe glyphs but
   dropped `[GGUF]` tags per the F-stream framing rule.
2. `chat.py` imports — kept the new package paths
   (`lilbee.app.version.get_version`, `lilbee.core.settings`) and dropped
   stale main-side imports.
3. `test_tui_navigation.py` comment — colon over em dash (style-check
   rejects em dashes).

---

## Time estimates

- Skim (Steps 1, 2, 3, 9): **~70 min** — gives you the architecture
- Reasonable depth (add Steps 4, 6, 7): **~2 h** — gives you "I could maintain this"
- Full read (everything including Step 5): **~3 h** — gives you "I know the whole codebase"

Step 8 (CodeCompanion) is a *tool* you reach for during any of the above
when you spot something worth refactoring or moving. Not a review step
itself; doesn't add time to the review unless you act on a finding.

The single biggest payoff per minute is **Step 3** (the two architectural
shifts). That's the conceptual core. Everything else is execution of those
two ideas.

---

## Track your progress

Bottom of any file you've finished, drop a `# REVIEWED yyyy-mm-dd` comment
(via `,/` if mini.comment is loaded for that buffer, otherwise just paste).
Or use a checklist file:

```
:e REVIEW_PR188_PROGRESS.md
```

(scratch file, also untracked) and tick off the steps. Whichever you prefer.

When you're done, `rm REVIEW_PR188.md REVIEW_PR188_COMMITS.txt
REVIEW_PR188_PROGRESS.md` cleans up the review aids.
