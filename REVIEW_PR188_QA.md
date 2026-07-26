# Lilbee: Full-surface QA matrix for PR #188 (fresh-install scenario)

## Context

PR #188 (`tidy-module-organization`, tip `8b6a849`) refactored every layer
of lilbee: top-level package layout, god-module decompositions, singleton
consolidation into `Services`, lazy-import discipline, lint tightening, the
new `lilbee/app/` shared use-case layer. Every code path a user touches —
CLI, HTTP, MCP, TUI — got moved or restructured.

CI is green for static gates and unit/integration tests, but those exercise
mocks. We need a **fresh-install end-to-end QA pass** that proves the four
public surfaces actually work against real models, real PDFs, and real
HTTP/MCP traffic. Treat the codebase as if it just landed — no models
installed, no config on disk, no data dir.

The user's hardware is single-GPU/single-CPU. Heavy work (chat completion,
sync/embedding, wiki build, model download) cannot run in parallel. Light
work (HTTP read-only routes, static checks, env capture) can.

Drive everything with **tmux send-keys + capture-pane** so each step's
output is recorded and reviewable. capture-pane is the OCR for terminals.

## Bug triage policy (read before starting)

This QA pass is **discovery-only**. The goal is to surface bugs across the
full surface, not to fix them mid-run.

| Finding type | What to do |
|---|---|
| Bug found mid-step | `bd create --type=bug --priority=2 --title="..." --description="<step number, capture path, observed vs expected, surface affected>"`. Continue to the next step. |
| Bug **blocks** the next QA step (e.g. server won't boot, model download crashes the run) | Triage minimally: file the bd, then either (a) work around to keep QA going (e.g. skip the failing phase and mark `BLOCKED` in SUMMARY) or (b) apply the smallest possible inline fix to unblock — **and only the smallest**. Do not start refactoring during QA. |
| Pre-existing flake (xdist TUI, LLM non-determinism, etc.) | Don't file. Note in SUMMARY. |
| Test or coverage failure | File. Don't fix during QA. |
| Performance regression (sub-second → multi-second) | File with timing data attached. |
| UX wart that isn't a bug | File at P3 ("polish"). Don't get distracted. |

**At the end of the QA pass:** collect every bd issue filed during the
run, group by surface and severity, and bring the list back to the user.
Round 2 — fix sweep — is a **separate planning session** driven from that
list. Do not start fixing until the user has reviewed the full set and
decided priorities.

The captures dir is the evidence trail. Every bd description must point
at its capture path so the bug can be reproduced from the on-disk
artifact.

## Test fixtures and environment (frozen)

| Setting | Value |
|---|---|
| Fresh data dir | `/tmp/qa-pr188-data/` |
| Fresh models dir override | `LILBEE_MODELS_DIR=/tmp/qa-pr188-models/` |
| Fresh config (in data dir) | `/tmp/qa-pr188-data/config.toml` |
| Captures dir | `/tmp/qa-pr188-captures/` |
| HuggingFace cache override | `HF_HOME=/tmp/qa-pr188-hf/` |
| Test PDF | `~/Downloads/cv-manual.pdf` (verified present) |
| Test crawl URL | `https://example.com` (small, stable, public) |
| Chat model | `Qwen/Qwen3-0.6B-GGUF/Qwen3-0.6B-Q4_K_M.gguf` |
| Embed model | `nomic-ai/nomic-embed-text-v1.5-GGUF/nomic-embed-text-v1.5.Q4_K_M.gguf` |
| Optional: LiteLLM / Ollama for provider switch | user-supplied if available |

Pre-flight: `rm -rf /tmp/qa-pr188-*`, then `mkdir -p /tmp/qa-pr188-{data,models,captures,hf}`.
Install lilbee with the right extras: `uv sync --all-extras` from the repo
(this installs litellm, crawl4ai, kreuzberg, and the dev deps in one shot).

## tmux window topology

One session, multiple windows. Window naming `qa-<purpose>`. Per
`feedback_never_kill_user_tmux.md` we only kill sessions we created.

| Window | Purpose | Owns | Concurrent with |
|---|---|---|---|
| `qa-static` | Static gates + env capture | nothing | everything |
| `qa-cli` | CLI surface (sequential) | model + disk + chat | `qa-http-readonly` only |
| `qa-http-server` | HTTP server process | port 8765 | (background) |
| `qa-http-readonly` | curl read-only routes | nothing heavy | `qa-cli` ingest steps |
| `qa-http-heavy` | curl SSE streams (sync, ask, chat) | model + disk + chat | runs alone |
| `qa-mcp` | MCP stdio harness | model + disk + chat | runs alone |
| `qa-tui` | TUI screens | model + disk + chat + terminal | runs alone |

Rule: only one window at a time may use the chat or embedding model. Read-
only HTTP routes never touch the model and can run anytime the server is up.

## Phase plan

Phases run top-to-bottom. Within a phase, the window listed for each step
is the one to drive.

### Phase 0 — Pre-flight (5 min)

- Confirm `cv-manual.pdf` is at `~/Downloads/cv-manual.pdf` (`ls ~/Downloads/cv-manual.pdf`).
- Branch is `tidy-module-organization`, working tree clean.
- `rm -rf /tmp/qa-pr188-*` then `mkdir -p /tmp/qa-pr188-{data,models,captures,hf}`.
- `mkdir -p /tmp/qa-pr188-captures/{static,env,cli,http,mcp,tui,crawl,wiki,provider,reset,errors}`.
- `tmux new-session -d -s qa-pr188`. Then `tmux new-window -t qa-pr188 -n qa-static`,
  same for the other window names above.
- Capture environment: in `qa-static`,
  ```
  uv run python -c "import sys; print(sys.version)" \
    > /tmp/qa-pr188-captures/env/python.txt
  uv run pip list | grep -E "kreuzberg|llama-cpp|litellm|crawl4ai|textual|lancedb" \
    > /tmp/qa-pr188-captures/env/key-deps.txt
  uname -a > /tmp/qa-pr188-captures/env/uname.txt
  ```

### Phase 1 — Static gates (parallel with Phase 2 Pre-fetch) (10 min)

Driven from `qa-static`. Runs concurrently with Phase 2's environment
priming because nothing here touches models or data.

| Step | Send-keys | Capture | Pass criteria |
|---|---|---|---|
| Format | `make format` | `static/format.txt` | exit 0, no diff |
| Lint | `make lint` | `static/lint.txt` | exit 0 (ruff clean + style script clean) |
| Format-check | `make format-check` | `static/format-check.txt` | exit 0 |
| Typecheck | `make typecheck` | `static/typecheck.txt` | exit 0 |
| Unit suite | `make test` | `static/unit-tests.txt` | 4779+ passed, **100.00% coverage** |
| Integration suite | `make test-integration` | `static/integration-tests.txt` | exit 0 |
| Importer audit | `grep -rln "from lilbee\." src/ tests/ docs/` | `static/importers.txt` | no stale paths (`lilbee.config`, `lilbee.store`, `lilbee.crawler.api`, `lilbee.providers.llama_cpp_provider`, `lilbee.providers.worker_process`, `lilbee.modelhub.model_manager.holder`) |
| Absence assertion | `uv run python -c "<importlib block from REVIEW_PR188.md>"` | `static/absence.txt` | every old top-level path raises `ModuleNotFoundError` |
| Startup time | `time uv run lilbee --help` | `static/startup-time.txt` | total wall < 1.0s |

### Phase 2 — Public Python API + fresh-install CLI (15 min, sequential, owns `qa-cli`)

| Step | Window | Send-keys | Capture | Pass |
|---|---|---|---|---|
| 01 Lilbee facade | `qa-static` | `uv run python -c "from lilbee import Lilbee; print(Lilbee.__module__)"` | `cli/01-lilbee-facade.txt` | prints `lilbee.api` |
| 02 Runtime entry | `qa-static` | `uv run python -c "from lilbee.runtime.launcher import main; print(main.__module__)"` | `cli/02-runtime-entry.txt` | prints `lilbee.runtime.launcher` |
| 03 Use-case layer | `qa-static` | `uv run python -c "from lilbee.app.status import gather_status; from lilbee.app.models import pull_model_data; from lilbee.app.version import get_version; from lilbee.app.reset import perform_reset; from lilbee.app.ingest import copy_files, temporary_ocr_config; from lilbee.app.search import clean_result; print('app: ok')"` | `cli/03-app-layer.txt` | prints `app: ok` |
| 04 Services container | `qa-static` | `LILBEE_DATA_DIR=/tmp/qa-pr188-data uv run python -c "from lilbee.core.services import get_services; svc = get_services(); print(type(svc.hf_client).__name__, type(svc.model_manager).__name__, type(svc.ingest_lock_registry).__name__, type(svc.provider).__name__, type(svc.store).__name__)"` | `cli/04-services.txt` | prints `HfClient ModelManager IngestLockRegistry RoutingProvider Store` |
| 05 Help (baseline) | `qa-cli` | `uv run lilbee --help` | `cli/05-help.txt` | shows top-level command list |
| 06 Version | `qa-cli` | `uv run lilbee --version` | `cli/06-version.txt` | semver matches `pyproject.toml` |
| 07 Init | `qa-cli` | `LILBEE_DATA_DIR=/tmp/qa-pr188-data uv run lilbee init` | `cli/07-init.txt` | creates `/tmp/qa-pr188-data/{config.toml,documents,...}` |
| 08 Status fresh | `qa-cli` | `LILBEE_DATA_DIR=/tmp/qa-pr188-data uv run lilbee status` | `cli/08-status-fresh.txt` | shows zero documents, default config |
| 09 Token list | `qa-cli` | `LILBEE_DATA_DIR=/tmp/qa-pr188-data uv run lilbee token` | `cli/09-token.txt` | no token by default |
| 10 Models list (empty) | `qa-cli` | `LILBEE_MODELS_DIR=/tmp/qa-pr188-models uv run lilbee models list` | `cli/10-models-list-empty.txt` | empty list, no error |

### Phase 3 — Model pulls (15 min, sequential, owns network) (`qa-cli`)

The two model downloads are bandwidth-heavy. Run sequentially.

| Step | Send-keys (in `qa-cli`) | Capture | Pass |
|---|---|---|---|
| 11 Catalog browse chat | `LILBEE_MODELS_DIR=/tmp/qa-pr188-models uv run lilbee models browse --task chat` | `cli/11-catalog-chat.txt` | shows Qwen3-0.6B in featured set |
| 12 Pull Qwen 0.6B (Rich progress) | `LILBEE_MODELS_DIR=/tmp/qa-pr188-models HF_HOME=/tmp/qa-pr188-hf uv run lilbee models pull Qwen/Qwen3-0.6B-GGUF` | `cli/12-pull-qwen.txt` (multi-frame: capture-pane every 3s while running) | percent strictly increases, finishes ≤120s, file lands at `/tmp/qa-pr188-models/.../*.gguf` |
| 13 Pull nomic embed (Rich progress) | `LILBEE_MODELS_DIR=/tmp/qa-pr188-models HF_HOME=/tmp/qa-pr188-hf uv run lilbee models pull nomic-ai/nomic-embed-text-v1.5-GGUF` | `cli/13-pull-nomic.txt` (multi-frame) | same — percent monotonic, finishes |
| 14 Models list (populated) | `LILBEE_MODELS_DIR=/tmp/qa-pr188-models uv run lilbee models list` | `cli/14-models-list.txt` | shows both refs |
| 15 Models show Qwen | `LILBEE_MODELS_DIR=/tmp/qa-pr188-models uv run lilbee models show Qwen/Qwen3-0.6B-GGUF/Qwen3-0.6B-Q4_K_M.gguf` | `cli/15-models-show.txt` | manifest details: hf_repo, file size, sha |
| 16 Status w/ models | `LILBEE_DATA_DIR=/tmp/qa-pr188-data LILBEE_MODELS_DIR=/tmp/qa-pr188-models uv run lilbee status` | `cli/16-status-with-models.txt` | chat + embed model refs populated |

For step 12/13 the multi-frame capture is the locked TUI-style regression.
While the pull runs, `tmux capture-pane -t qa-pr188:qa-cli -p > .../frame-N.txt`
every 3s. Compare frames: each percent line should be > previous frame's
(real-time-progress regression check).

### Phase 4 — Document ingest (20 min, sequential, owns `qa-cli`)

`cv-manual.pdf` is the test fixture. Verify the kreuzberg PDF extractor + chunker
+ embedder + LanceDB write pipeline works end-to-end.

| Step | Send-keys | Capture | Pass |
|---|---|---|---|
| 17 Add PDF | `LILBEE_DATA_DIR=/tmp/qa-pr188-data LILBEE_MODELS_DIR=/tmp/qa-pr188-models uv run lilbee add ~/Downloads/cv-manual.pdf` | `cli/17-add-pdf.txt` (multi-frame; capture every 5s while running) | progress: page count, OCR if scanned, chunks count visible; exit 0 |
| 18 Status after add | `... lilbee status` | `cli/18-status-after-add.txt` | shows cv-manual.pdf with chunk count > 0 |
| 19 Chunks of file | `... lilbee chunks --source cv-manual.pdf` | `cli/19-chunks.txt` | non-empty list, each chunk has page_start/page_end |
| 20 Search keyword | `... lilbee search "<keyword from CV>"` (e.g. "education", "experience") | `cli/20-search.txt` | returns ≥1 result with citation |
| 21 Ask question | `... lilbee ask "What programming languages does the candidate know?"` | `cli/21-ask.txt` | answer streams, contains terms from PDF, citations attached |
| 22 Topics overview | `... lilbee topics` | `cli/22-topics.txt` | non-error topics list (may be empty if concept graph not built — note for review) |
| 23 Rebuild | `... lilbee rebuild` | `cli/23-rebuild.txt` (multi-frame) | drops + re-ingests cv-manual.pdf; chunk count matches step 18 |
| 24 Remove file | `... lilbee remove cv-manual.pdf` | `cli/24-remove.txt` | exit 0; chunks dropped |
| 25 Sync (no-op after remove) | `... lilbee sync` | `cli/25-sync-empty.txt` | exit 0, 0 added, 0 updated |

After step 25, re-add the PDF (`lilbee add ~/Downloads/cv-manual.pdf`) so
the rest of the matrix has data to query against. Capture as
`cli/25b-readd.txt`.

### Phase 5 — HTTP server matrix (30 min total, mixed parallelism)

Boot the server once in `qa-http-server` and keep it running through Phase
5–6. Read-only routes (`qa-http-readonly`) run concurrently with Phase 6's
heavy CLI work. SSE streams in `qa-http-heavy` run alone.

#### Phase 5a — Server boot + auth + read-only routes (10 min, can overlap with Phase 4 tail)

| Step | Window | Send-keys / curl | Capture | Pass |
|---|---|---|---|---|
| 26 Boot server | `qa-http-server` | `LILBEE_DATA_DIR=/tmp/qa-pr188-data LILBEE_MODELS_DIR=/tmp/qa-pr188-models uv run lilbee serve --port 8765` | leave running, capture-pane `http/26-server-boot.txt` | server "ready" line visible |
| 27 Health | `qa-http-readonly` | `curl -fsS http://127.0.0.1:8765/api/health` | `http/27-health.json` | 200, JSON with `status: ok` |
| 28 Version | `qa-http-readonly` | (extracted from /api/health body or status) | `http/28-version.txt` | semver |
| 29 Auth: 401 without token | `qa-http-readonly` | `curl -s -o /dev/null -w "%{http_code}" -X POST -d '{}' http://127.0.0.1:8765/api/sync` | `http/29-auth-401.txt` | `401` |
| 30 Read auth token | `qa-http-readonly` | `python -c "import json; print(json.load(open('/tmp/qa-pr188-data/server.json'))['token'])"` | `http/30-token.txt` | non-empty token |
| 31 Status | `qa-http-readonly` | `curl -fsS -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8765/api/status` | `http/31-status.json` | 200 |
| 32 Config GET | `qa-http-readonly` | `curl -fsS -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8765/api/config` | `http/32-config.json` | 200, all knobs visible |
| 33 Config defaults | `qa-http-readonly` | `curl -fsS -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8765/api/config/defaults` | `http/33-config-defaults.json` | 200 |
| 34 Config PATCH | `qa-http-readonly` | `curl -fsS -X PATCH -H "Authorization: Bearer $TOKEN" -d '{"max_distance": 0.85}' http://127.0.0.1:8765/api/config` | `http/34-config-patch.json` | 200, value reflected on next GET |
| 35 Models list | `qa-http-readonly` | `curl -fsS -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8765/api/models` | `http/35-models.json` | 200, lists Qwen + nomic |
| 36 Models installed | `qa-http-readonly` | `curl -fsS -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8765/api/models/installed` | `http/36-models-installed.json` | 200, two manifests |
| 37 Models external | `qa-http-readonly` | `curl -fsS -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8765/api/models/external` | `http/37-models-external.json` | 200 (empty if no Ollama; not an error) |
| 38 Models catalog | `qa-http-readonly` | `curl -fsS -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8765/api/models/catalog?task=chat&limit=5"` | `http/38-models-catalog.json` | 200, ≤5 entries, `installed:true` for Qwen |
| 39 Models show | `qa-http-readonly` | `curl -fsS -X POST -H "Authorization: Bearer $TOKEN" -d '{"model":"Qwen/Qwen3-0.6B-GGUF/Qwen3-0.6B-Q4_K_M.gguf"}' http://127.0.0.1:8765/api/models/show` | `http/39-models-show.json` | 200, manifest details |
| 40 Documents list | `qa-http-readonly` | `curl -fsS -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8765/api/documents` | `http/40-documents.json` | 200, lists cv-manual.pdf |
| 41 Source content | `qa-http-readonly` | `curl -fsS -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8765/api/source?source=cv-manual.pdf"` | `http/41-source.txt` | 200 |
| 42 Search GET | `qa-http-readonly` | `curl -fsS -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8765/api/search?q=experience"` | `http/42-search.json` | 200, hits |
| 43 Setup crawler status | `qa-http-readonly` | `curl -fsS -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8765/setup/crawler/status` | `http/43-crawler-status.json` | 200 |
| 44 Crawler 503 fallback | `qa-http-readonly` (only if crawl4ai not installed) | `curl -s -o /dev/null -w "%{http_code}" -X POST -H "Authorization: Bearer $TOKEN" -d '{"urls":["https://example.com"]}' http://127.0.0.1:8765/api/crawl` | `http/44-crawl-503.txt` | 503 with `MissingDependency`-style detail (acceptable if crawl4ai not installed) |

#### Phase 5b — SSE streams + write routes (15 min, sequential, owns model)

| Step | Window | Send-keys / curl | Capture | Pass |
|---|---|---|---|---|
| 45 Set chat model | `qa-http-heavy` | `curl -fsS -X PUT -H "Authorization: Bearer $TOKEN" -d '{"model":"Qwen/Qwen3-0.6B-GGUF/Qwen3-0.6B-Q4_K_M.gguf"}' http://127.0.0.1:8765/api/models/chat` | `http/45-set-chat.json` | 200 |
| 46 Set embedding model | `qa-http-heavy` | `curl -fsS -X PUT -H "Authorization: Bearer $TOKEN" -d '{"model":"nomic-ai/nomic-embed-text-v1.5-GGUF/nomic-embed-text-v1.5.Q4_K_M.gguf"}' http://127.0.0.1:8765/api/models/embedding` | `http/46-set-embed.json` | 200 |
| 47 /api/sync stream | `qa-http-heavy` | `curl -N --max-time 60 -X POST -H "Authorization: Bearer $TOKEN" -d '{}' http://127.0.0.1:8765/api/sync` | `http/47-sync-stream.txt` | event-stream, ends with `event: done` (or `already_ingesting`) |
| 48 /api/add stream | `qa-http-heavy` | `curl -N --max-time 90 -X POST -H "Authorization: Bearer $TOKEN" -d "{\"paths\":[\"$HOME/Downloads/cv-manual.pdf\"]}" http://127.0.0.1:8765/api/add` | `http/48-add-stream.txt` | event-stream, `event: done` (or already_ingesting if Phase 4 left it indexed) |
| 49 /api/ask non-stream | `qa-http-heavy` | `curl -fsS --max-time 60 -X POST -H "Authorization: Bearer $TOKEN" -d '{"query":"What languages does the candidate know?"}' http://127.0.0.1:8765/api/ask` | `http/49-ask.json` | 200, answer + citations |
| 50 /api/ask/stream SSE | `qa-http-heavy` | `curl -N --max-time 60 -X POST -H "Authorization: Bearer $TOKEN" -d '{"query":"Summarize the candidate's education"}' http://127.0.0.1:8765/api/ask/stream` | `http/50-ask-stream.txt` | event-stream, `token` events, ends with `done` |
| 51 /api/chat non-stream | `qa-http-heavy` | `curl -fsS --max-time 60 -X POST -H "Authorization: Bearer $TOKEN" -d '{"messages":[{"role":"user","content":"Hello"}]}' http://127.0.0.1:8765/api/chat` | `http/51-chat.json` | 200 |
| 52 /api/chat/stream SSE | `qa-http-heavy` | `curl -N --max-time 60 -X POST -H "Authorization: Bearer $TOKEN" -d '{"messages":[{"role":"user","content":"Tell me a haiku about CVs"}]}' http://127.0.0.1:8765/api/chat/stream` | `http/52-chat-stream.txt` | event-stream |
| 53 /api/crawl SSE | `qa-http-heavy` (skip if crawl4ai not installed; covered separately in Phase 7) | `curl -N --max-time 30 -X POST -H "Authorization: Bearer $TOKEN" -d '{"urls":["https://example.com"]}' http://127.0.0.1:8765/api/crawl` | `http/53-crawl-stream.txt` | event-stream, `crawl_page` event for example.com, `done` |
| 54 Models pull SSE (small redundant pull) | `qa-http-heavy` | `curl -N --max-time 60 -X POST -H "Authorization: Bearer $TOKEN" -d '{"hf_repo":"Qwen/Qwen3-0.6B-GGUF","gguf_filename":"Qwen3-0.6B-Q4_K_M.gguf"}' http://127.0.0.1:8765/api/models/pull` | `http/54-models-pull-stream.txt` | event-stream; since model already installed, `is_cache_hit:true` event observed; ends with `done` |
| 55 Documents remove | `qa-http-heavy` | `curl -fsS -X POST -H "Authorization: Bearer $TOKEN" -d '{"sources":["cv-manual.pdf"]}' http://127.0.0.1:8765/api/documents/remove` | `http/55-doc-remove.json` | 200; subsequent `/api/documents` shows it gone |
| 56 Re-add for downstream phases | `qa-http-heavy` | `curl -N --max-time 120 -X POST -H "Authorization: Bearer $TOKEN" -d "{\"paths\":[\"$HOME/Downloads/cv-manual.pdf\"]}" http://127.0.0.1:8765/api/add` | `http/56-readd.txt` | `event: done` |
| 57 Models delete (skip — needed for later phases) | — | — | — | only verify endpoint shape; don't actually delete |

After Phase 5b, leave the server running for `qa-http-heavy` cleanup later.

### Phase 6 — MCP matrix (15 min, sequential, owns model+chat)

Drive `lilbee mcp` (stdio) with a small Python harness or `mcp` CLI client.
Boot once, send the JSON-RPC sequence, capture replies.

| Step | Window | Action | Capture | Pass |
|---|---|---|---|---|
| 58 Boot + initialize | `qa-mcp` | `printf '%s\n' '<initialize>' '<notifications/initialized>' '<tools/list>' \| LILBEE_DATA_DIR=/tmp/qa-pr188-data LILBEE_MODELS_DIR=/tmp/qa-pr188-models uv run lilbee mcp 2>/dev/null` | `mcp/58-tools-list.jsonl` | 25 tools listed, names match the source set |
| 59 status | `qa-mcp` | tools/call name=status | `mcp/59-status.json` | content array with status text |
| 60 init | `qa-mcp` | tools/call name=init | `mcp/60-init.json` | success |
| 61 list_documents | `qa-mcp` | tools/call name=list_documents | `mcp/61-list-documents.json` | shows cv-manual.pdf |
| 62 search | `qa-mcp` | tools/call name=search arguments={"query":"experience"} | `mcp/62-search.json` | hits |
| 63 ask | `qa-mcp` | tools/call name=ask arguments={"query":"summarize the CV"} | `mcp/63-ask.json` | text answer |
| 64 add (no-op already-ingested) | `qa-mcp` | tools/call name=add arguments={"paths":["~/Downloads/cv-manual.pdf"]} | `mcp/64-add.json` | success or already_ingesting |
| 65 sync | `qa-mcp` | tools/call name=sync | `mcp/65-sync.json` | summary |
| 66 model_list | `qa-mcp` | tools/call name=model_list | `mcp/66-model-list.json` | lists installed |
| 67 model_show | `qa-mcp` | tools/call name=model_show arguments={"model":"Qwen/Qwen3-0.6B-GGUF/Qwen3-0.6B-Q4_K_M.gguf"} | `mcp/67-model-show.json` | manifest |
| 68 model_pull (cache hit) | `qa-mcp` | tools/call name=model_pull arguments={"hf_repo":"Qwen/Qwen3-0.6B-GGUF","gguf_filename":"Qwen3-0.6B-Q4_K_M.gguf"} | `mcp/68-model-pull.json` | already-installed shortcut |
| 69 wiki_status | `qa-mcp` | tools/call name=wiki_status | `mcp/69-wiki-status.json` | enabled/disabled state |
| 70 wiki_build | `qa-mcp` | tools/call name=wiki_build (only if a chat+embed are wired) | `mcp/70-wiki-build.json` | summary or graceful no-op |
| 71 wiki_list | `qa-mcp` | tools/call name=wiki_list | `mcp/71-wiki-list.json` | pages list (may be empty, not an error) |
| 72 wiki_read | `qa-mcp` | tools/call name=wiki_read arguments={"slug":"<one-from-list>"} (skip if list empty) | `mcp/72-wiki-read.json` | content |
| 73 wiki_lint | `qa-mcp` | tools/call name=wiki_lint | `mcp/73-wiki-lint.json` | lint report |
| 74 wiki_citations | `qa-mcp` | tools/call name=wiki_citations arguments={"wiki_source":"<slug>"} (skip if empty) | `mcp/74-wiki-citations.json` | citation list |
| 75 wiki_drafts_list | `qa-mcp` | tools/call name=wiki_drafts_list | `mcp/75-wiki-drafts.json` | drafts list (may be empty) |
| 76 wiki_drafts_diff | `qa-mcp` | (skip if empty) | `mcp/76-wiki-drafts-diff.json` | diff |
| 77 wiki_synthesize | `qa-mcp` | tools/call name=wiki_synthesize | `mcp/77-wiki-synthesize.json` | success |
| 78 wiki_update | `qa-mcp` | tools/call name=wiki_update | `mcp/78-wiki-update.json` | success |
| 79 wiki_prune | `qa-mcp` | tools/call name=wiki_prune | `mcp/79-wiki-prune.json` | summary |
| 80 model_rm (skip — needed) | — | — | — | endpoint shape verified by call; don't actually remove |
| 81 reset | `qa-mcp` | tools/call name=reset arguments={"confirm":false} | `mcp/81-reset.json` | requires confirm=true; without it, returns guard error (not 500) |
| 82 crawl | `qa-mcp` | tools/call name=crawl arguments={"urls":["https://example.com"]} (skip if crawl4ai not installed) | `mcp/82-crawl.json` | task_id returned |
| 83 crawl_status | `qa-mcp` | tools/call name=crawl_status arguments={"task_id":"<from 82>"} | `mcp/83-crawl-status.json` | running / done state |
| 84 remove | `qa-mcp` | (skip — keep cv-manual.pdf for later) | — | endpoint shape only |
| 85 Shutdown | `qa-mcp` | EOF | — | clean exit, no traceback in stderr |

### Phase 7 — TUI matrix (45 min, sequential, owns terminal+model+chat)

The biggest matrix. Each step: tmux send-keys, sleep 2-3s, capture-pane.
Per `feedback_pilot_press_tests.md` we drive via real key events
(`tmux send-keys`), not direct action calls.

Setup once:

```
tmux send-keys -t qa-pr188:qa-tui "cd $(pwd) && LILBEE_DATA_DIR=/tmp/qa-pr188-data LILBEE_MODELS_DIR=/tmp/qa-pr188-models uv run lilbee" Enter
```

Wait ~5s for splash + main view, then proceed.

| Step | Keys | Capture | Pass |
|---|---|---|---|
| 86 Launch | (none) | `tui/86-launch.txt` | splash → setup wizard appears (since this is fresh) OR main view if models pre-existed |
| 87 Wizard setup-screen render | (none after splash) | `tui/87-wizard.txt` | featured chat models grid visible, recommended highlighted |
| 88 Pick chat | navigate (`Down`/`Right`) to Qwen3-0.6B, `Enter` | `tui/88-install-frame{1,2,3}.txt` (capture every 5s) | percent strictly increases across frames; no tqdm leak; install completes |
| 89 Pick embed | navigate to embed grid, pick nomic, `Enter` | `tui/89-embed-install-frame{1,2,3}.txt` | (already cached from CLI pull → expect "already downloaded" cache-hit; instant) |
| 90 Wizard done | `Escape` | `tui/90-after-wizard.txt` | main chat view; airline shows model in chat, embed pill |
| 91 Chat screen render | (none) | `tui/91-chat.txt` | chat input + welcome message |
| 92 Send a question | `i` (insert mode), type "What is the candidate's email?", `Enter` | `tui/92-chat-stream-{1,2}.txt` | response streams, capture early + late frame |
| 93 Vim normal mode | `Escape` | `tui/93-normal-mode.txt` | mode indicator changes; navigation keys (j/k) now scroll instead of typing |
| 94 Slash command list | `/` then `?` (or whatever opens command palette) | `tui/94-slash.txt` | dropdown of slash commands |
| 95 /status slash | `i`, type `/status`, `Enter` | `tui/95-slash-status.txt` | status info renders inline in chat |
| 96 /add slash | `i`, type `/add ~/Downloads/cv-manual.pdf` | `tui/96-slash-add.txt` | already_ingesting OR re-ingest flow visible |
| 97 /clear slash | `i`, type `/clear`, `Enter` | `tui/97-slash-clear.txt` | chat history cleared |
| 98 Switch to Catalog | `Escape`, `c` (or whatever the binding is — see `cli/tui/app.py` BINDINGS) | `tui/98-catalog.txt` | catalog grid view rendered |
| 99 Catalog filter | `/`, type `qwen`, `Enter` | `tui/99-catalog-filter.txt` | filtered list |
| 100 Catalog list view | `v` (toggle view) | `tui/100-catalog-list.txt` | list view |
| 101 Catalog model card | `Down`, `Enter` (or focus a card) | `tui/101-catalog-card.txt` | detail card |
| 102 Switch to Status | `Escape`, `s` | `tui/102-status.txt` | status screen with model pills + documents table |
| 103 Status j/k nav | `j`, `j`, `k` | `tui/103-status-nav.txt` | cursor moves in docs table |
| 104 Status g/G | `g`, then `G` | `tui/104-status-g-G.txt` | cursor jumps to top, then bottom |
| 105 Switch to Settings | `Escape`, then settings binding | `tui/105-settings.txt` | settings panel; cfg fields visible |
| 106 Settings edit | tab to a field (e.g. `max_distance`), modify, save (`Ctrl+S` or whatever) | `tui/106-settings-edit.txt` | value persists; reflected in `cfg` |
| 107 Theme cycle | `Ctrl+T` (or `t`) | `tui/107-theme.txt` | colors change |
| 108 Switch to Wiki | `Escape`, wiki binding | `tui/108-wiki.txt` | wiki entry list (may be empty if not built) |
| 109 Wiki drafts | (depends on bindings) | `tui/109-wiki-drafts.txt` | drafts screen |
| 110 Switch to Tasks | task center binding | `tui/110-tasks.txt` | task center; should show recent ingest task |
| 111 Help overlay | `?` | `tui/111-help.txt` | help modal |
| 112 Help dismiss | `Escape` | `tui/112-help-dismissed.txt` | back to previous screen |
| 113 Quit gracefully | `Escape`, then `q` | (none — session ends) | `lilbee` exits, returns to shell prompt |

Tear-down: `tmux kill-session -t qa-pr188` only at the very end. (The
`-t qa-pr188:qa-tui` *window* closes when `lilbee` quits.)

### Phase 8 — Crawler path (10 min, sequential, owns network + model)

Skip entirely if `crawl4ai` is not installed (the relevant routes return
503 which is the documented graceful failure). If installed:

| Step | Window | Send-keys | Capture | Pass |
|---|---|---|---|---|
| 114 Install Playwright | `qa-cli` | `uv run lilbee setup-crawler` (or `lilbee setup crawler`) | `crawl/114-setup.txt` | Chromium installs (first run only) |
| 115 Add URL | `qa-cli` | `LILBEE_DATA_DIR=/tmp/qa-pr188-data uv run lilbee add https://example.com` | `crawl/115-add-url.txt` | crawl + save .md under documents/_web/ |
| 116 Verify saved file | `qa-cli` | `ls /tmp/qa-pr188-data/documents/_web/` | `crawl/116-saved.txt` | one .md file present |
| 117 Status with crawl source | `qa-cli` | `lilbee status` | `crawl/117-status.txt` | shows crawled source |
| 118 Search crawled content | `qa-cli` | `lilbee search "Example Domain"` | `crawl/118-search.txt` | hit from crawled markdown |
| 119 HTTP /api/crawl SSE | `qa-http-heavy` | (already covered in step 53) | (existing capture) | event-stream |
| 120 MCP crawl | `qa-mcp` | (already covered in steps 82–83) | (existing) | task_id returned |

### Phase 9 — Wiki build (15 min, sequential, owns chat+embed)

| Step | Window | Send-keys | Capture | Pass |
|---|---|---|---|---|
| 121 Wiki status | `qa-cli` | `lilbee wiki status` | `wiki/121-status.txt` | wiki-disabled state by default; enable with cfg if needed |
| 122 Enable wiki | `qa-cli` | `LILBEE_WIKI_ENABLED=1` env var or set in config | — | cfg reflects |
| 123 Wiki build | `qa-cli` | `lilbee wiki build` | `wiki/123-build.txt` (multi-frame, ~minutes) | builds pages from cv-manual.pdf chunks; chat model exercised heavily |
| 124 Wiki status post-build | `qa-cli` | `lilbee wiki status` | `wiki/124-status-built.txt` | page count > 0 |
| 125 Wiki list | `qa-cli` | `lilbee wiki list` | `wiki/125-list.txt` | entries listed |
| 126 Wiki read | `qa-cli` | `lilbee wiki read <slug>` | `wiki/126-read.txt` | page content with citations |
| 127 Wiki lint | `qa-cli` | `lilbee wiki lint` | `wiki/127-lint.txt` | lint report |
| 128 Wiki synthesize | `qa-cli` | `lilbee wiki synthesize` | `wiki/128-synthesize.txt` | synthesis pages built |
| 129 Wiki prune | `qa-cli` | `lilbee wiki prune` | `wiki/129-prune.txt` | dry-run output (or actual prune) |
| 130 Wiki update | `qa-cli` | `lilbee wiki update` | `wiki/130-update.txt` | summary |

### Phase 10 — Provider switching (10 min, sequential — only if user has API keys)

Skip silently if no LiteLLM-compatible API key is available. If the user
has e.g. an OpenAI key:

| Step | Window | Send-keys | Capture | Pass |
|---|---|---|---|---|
| 131 LiteLLM ask | `qa-cli` | `LILBEE_LLM_PROVIDER=openai LILBEE_LLM_API_KEY=$OPENAI_KEY lilbee ask "Hello"` | `provider/131-litellm.txt` | answer routed via litellm; `services.provider` is `RoutingProvider` selecting `LiteLlmProvider` |
| 132 Ollama detect | `qa-cli` (only if Ollama is running locally) | `lilbee models list --source ollama` | `provider/132-ollama-list.txt` | external models if any |
| 133 Provider via PUT | `qa-http-heavy` | `curl -X PATCH ... '{"llm_provider":"litellm"}'` | `provider/133-provider-switch.json` | 200 |
| 134 Switch back | `qa-http-heavy` | switch back to `auto` / `llama-cpp` | `provider/134-provider-back.json` | 200 |

### Phase 11 — Edge cases / cancellation (10 min, sequential)

| Step | Window | Action | Capture | Pass |
|---|---|---|---|---|
| 135 Invalid model ref | `qa-cli` | `lilbee models pull org/does-not-exist-zzz` | `errors/135-bad-pull.txt` | proper error, no traceback, exit ≠ 0 |
| 136 Bad search query (empty) | `qa-cli` | `lilbee search ""` | `errors/136-empty-search.txt` | usage error, exit ≠ 0 |
| 137 Cancel mid-sync (Ctrl+C) | `qa-cli` | start `lilbee sync`, send `C-c` after 1s | `errors/137-cancel-sync.txt` | graceful shutdown, no orphaned files |
| 138 Concurrent /api/add | `qa-http-heavy` two requests in quick succession (use `&` to background curl) | two SSE streams in parallel | `errors/138-concurrent-add-{a,b}.txt` | second emits `already_ingesting` event |
| 139 Reset without confirm | `qa-cli` | `lilbee reset` (no `--yes`) | `errors/139-reset-no-confirm.txt` | prompts for confirmation; abort on `n` |
| 140 401 on /api/sync | `qa-http-readonly` | `curl -X POST -d '{}' http://127.0.0.1:8765/api/sync` (no auth) | `errors/140-no-auth.txt` | 401 |

### Phase 12 — Reset + re-init smoke (5 min, sequential)

| Step | Window | Send-keys | Capture | Pass |
|---|---|---|---|---|
| 141 Stop server | `qa-http-server` | `C-c` | `reset/141-server-stop.txt` | clean shutdown, server.json removed |
| 142 Reset confirm | `qa-cli` | `lilbee reset --yes` | `reset/142-reset.txt` | data dir cleared (cfg, lancedb, documents) |
| 143 Verify clean | `qa-cli` | `ls /tmp/qa-pr188-data/` | `reset/143-clean.txt` | empty (or just config remnant) |
| 144 Re-init | `qa-cli` | `lilbee init` | `reset/144-reinit.txt` | fresh state |
| 145 Status after reset | `qa-cli` | `lilbee status` | `reset/145-status-fresh.txt` | zero documents, default cfg |

### Phase 13 — Cleanup + summary report (5 min)

```
tmux kill-session -t qa-pr188
```

Generate `SUMMARY.md` in `/tmp/qa-pr188-captures/`. The summary records:

- Phase-by-phase pass/fail count.
- Total duration.
- Frame-deltas for the locked progress regression checks (steps 12, 13, 17, 23, 88).
- Any non-200 HTTP responses that weren't documented as expected (e.g. 401
  for unauthenticated, 503 for missing crawl4ai).
- Any tracebacks discovered in any capture (`grep -rn "Traceback" /tmp/qa-pr188-captures/`).

Optional: tar the captures dir: `tar czf /tmp/qa-pr188-captures.tgz -C /tmp qa-pr188-captures/`.

### Phase 14 — Triage handoff + round-2 planning kickoff (5 min)

The QA pass terminates here. **No fixes have been applied yet** beyond
inline blocker workarounds noted in Phase 13's SUMMARY.

Capture the run window so we can list every bd issue created during it:

```bash
QA_RUN_START="<ISO timestamp captured at Phase 0>"
bd list --created-after="$QA_RUN_START" --json \
  | jq -r '.[] | "[\(.priority)] \(.id) \(.title)"' \
  > /tmp/qa-pr188-captures/bd-findings.txt

bd list --created-after="$QA_RUN_START" --json \
  | jq '[.[] | {id, priority, type, title, surface: (.description | capture("(?<s>cli|http|mcp|tui|crawl|wiki|provider|reset|errors)")|.s) }] | group_by(.surface) | map({surface: .[0].surface, count: length, items: .})' \
  > /tmp/qa-pr188-captures/bd-by-surface.json
```

Append to `SUMMARY.md`:

- Total bd issues filed.
- Breakdown by surface (CLI / HTTP / MCP / TUI / crawler / wiki /
  provider / reset / edge cases).
- Breakdown by priority (P0 blocker / P1 / P2 / P3).
- Top 5 highest-priority items with one-line summaries.
- Pointer to the captures tarball.

**Then notify the user.** Hand off the issues list and `SUMMARY.md`.
Wait for the user to:

1. Review the findings.
2. Decide which to fix in this PR vs defer to a follow-up.
3. Set priorities (some P3 polish items may stay open indefinitely).

Do NOT start a fix sweep until that decision is made. Round 2 is its
own planning session — it gets its own plan file (overwriting this
one once QA closes).

Notification template (text to send back):

```
QA matrix complete. <N> bd issues filed, <X> P1, <Y> P2, <Z> P3.
Captures at /tmp/qa-pr188-captures/, summary at
/tmp/qa-pr188-captures/SUMMARY.md.

Surfaces with findings: <list>
Surfaces clean: <list>

Top items needing your call:
  1. <bd-id> [P1] <title> (capture: <path>)
  2. <bd-id> [P1] <title> (capture: <path>)
  3. <bd-id> [P2] <title> (capture: <path>)

Review the list and tell me which to fix on this PR vs defer.
Round-2 fix-sweep planning waits on your call.
```

## Pass criteria (full-sweep gate)

The matrix passes if:

1. Phase 1 static gates all green (lint, format, typecheck, tests, integration).
2. Public Python API imports + `Services` shape correct (Phase 2).
3. Both model pulls finish; progress percent strictly increases across captured frames (Phase 3).
4. PDF ingest produces ≥1 chunk; `lilbee ask` returns text containing PDF terms with citations (Phase 4).
5. All 29 HTTP routes reachable, return expected status codes; no 500s; no Pydantic validation leaks; SSE streams emit `done` (Phase 5).
6. MCP boots, lists 25 tools, every `tools/call` returns content (Phase 6).
7. TUI: setup wizard installs both models; chat streams a real answer; every screen renders without traceback in the capture; locked progress chain works (Phase 7).
8. Crawler path produces a saved `.md` and searchable content if `crawl4ai` installed; otherwise 503 fallback observed (Phase 8).
9. Wiki build produces ≥1 page with citations; lint passes (Phase 9).
10. Provider switch: LiteLLM/Ollama route resolved correctly if keys/Ollama present; otherwise skipped (Phase 10).
11. Edge cases all return graceful errors, no tracebacks (Phase 11).
12. Reset + re-init returns to a clean state (Phase 12).

A finding is a non-pass observation. File each as a beads issue
(`bd create --type=bug --priority=2`) with the captured file path attached
unless it's a pre-existing flake (e.g. macOS xdist TUI flakiness, the LLM
non-determinism that fired in `test_chat_returns_real_answer`).

## Hard rules (carried from user memory)

- Drive tmux **directly** with send-keys + capture-pane; no shell-script
  orchestration (`feedback_qa_send_keys_directly.md`).
- Never kill an unrelated tmux session — only `qa-pr188` and its windows
  (`feedback_never_kill_user_tmux.md`).
- File QA findings as bd issues; don't fix inline unless they're blockers
  for the matrix to continue (`feedback_qa_file_bugs_not_fix.md`).
- This QA matrix runs in a dedicated worktree path or against a fresh
  data dir at `/tmp/qa-pr188-data` — do NOT pollute the user's
  `~/Library/Application Support/lilbee/` config
  (`feedback_qa_in_worktree.md`).

## Critical files this matrix exercises

The whole tree, but the high-leverage code paths to keep in mind while
reading captures:

- `src/lilbee/runtime/launcher.py:main` — every CLI invocation goes through here.
- `src/lilbee/cli/commands/{meta,ingest_sync,search_chat,wiki,servers,setup}.py` — the 6-file Typer split.
- `src/lilbee/cli/model.py` — the `models` sub-typer.
- `src/lilbee/server/routes/{general,documents,search,models,crawl,setup}.py` — the 29 HTTP routes.
- `src/lilbee/server/handlers/{sse,rag,models,ingest,config,documents,crawl}.py` — the handler split.
- `src/lilbee/mcp.py` — the 25 MCP tools.
- `src/lilbee/cli/tui/screens/{setup,chat,catalog,status,settings,wiki,wiki_drafts,task_center}.py` — every TUI screen.
- `src/lilbee/app/{status,models,reset,ingest,version,search}.py` — the use-case layer that all four surfaces share.
- `src/lilbee/core/services.py` — the singleton container.
- `src/lilbee/catalog/download_progress.py` — the **locked TUI progress chain**.
- `src/lilbee/runtime/ingest_lock.py` — concurrent-add concurrency primitive.

## Verification — what to run after the matrix completes

```
grep -rn "Traceback" /tmp/qa-pr188-captures/   # should be empty
grep -rn "Error 500" /tmp/qa-pr188-captures/   # should be empty
grep -rn "ImportError\|ModuleNotFoundError" /tmp/qa-pr188-captures/  # should be empty
ls /tmp/qa-pr188-captures/SUMMARY.md           # exists
```

If all four checks pass, the matrix is green.

## Done definition

- All 14 phases run to completion (skipping documented optional phases).
- Captures dir contains every file the table calls out.
- `SUMMARY.md` records pass/fail per phase plus the frame-delta proofs for
  the progress regression check.
- Every finding filed as a bd issue with capture path attached. Round-2
  fix sweep is **not** part of this pass.
- The matrix is reproducible: someone else with the same fixture
  (`~/Downloads/cv-manual.pdf`) and a fresh data dir gets the same outcome.
- Branch state unchanged: this is a discovery-only QA pass. No commits
  to `tidy-module-organization` from QA execution **except** minimal
  inline blocker workarounds documented in `SUMMARY.md`.
- User has been notified per the Phase 14 template, with the bd list,
  surface breakdown, and top items needing their call.

## Notes for the QA executor (whoever runs this)

- Total wall-clock estimate: **2.5–3 hours** for the full matrix on a
  single GPU/CPU host. Phases 3, 7, 9 are the slowest (model pulls + LLM
  inference + wiki build).
- Phase 1 static + Phase 2 public-API can start before model pulls, so
  the first 15 minutes have parallelism. After that it's mostly
  sequential because the chat model is single-tenant.
- Save the captures dir as the audit trail. Don't run the matrix in a way
  that makes captures ephemeral.
- If a phase fails midway, the next phase often depends on its state
  (e.g. wiki build needs models pulled and PDF ingested). Don't skip
  forward without first triaging the failure.
- **You are a discovery agent, not a fixer.** When a step uncovers a bug,
  your reflex is `bd create`, not `Edit`. The exception is a blocker
  that prevents subsequent phases — and even then, the smallest possible
  inline workaround that gets QA going again. Refactors, polish,
  multi-step fixes wait for the user's round-2 review.
- Capture the QA run start time at Phase 0 so Phase 14 can filter bd
  issues by `--created-after`. `date -u +%Y-%m-%dT%H:%M:%SZ > /tmp/qa-pr188-captures/run-start.txt`.
