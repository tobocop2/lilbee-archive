# PR #188 QA — resume note

A compacted session can pick up here. Everything below is verifiable
from on-disk artifacts; no chat memory needed.

## Where things stand (as of 2026-04-27)

- **Branch:** `tidy-module-organization`, tip `8481fc3`, pushed to origin (53 commits ahead of `main`).
- **PR #188:** open at <https://github.com/tobocop2/lilbee/pull/188>.
- **Last activity:** 4 QA findings filed and all 4 fixed in this session. Crawler + LiteLLM extras now installed in the venv.

## What's done

| Phase | Status | Notes |
|---|---|---|
| 0 Pre-flight | DONE | `/tmp/qa-pr188-{data,models,captures,hf}` dirs in place |
| 1 Static gates | PASS | `make check` green, 100% coverage, integration suite green |
| 2 Public API | PASS | Lilbee facade, Services container shape (HfClient/ModelManager/IngestLockRegistry/RoutingProvider/Store) |
| 3 Model pulls | PASS | Qwen/Qwen3-0.6B-GGUF (Q8_0), nomic-ai/nomic-embed-text-v1.5-GGUF (Q4_K_M) |
| 4 PDF ingest | PASS | `~/Downloads/cv-manual.pdf` (Ford manual), 362 chunks |
| 5a HTTP read-only | PASS | 17 routes covered |
| 5b HTTP write/SSE | PASS | sync/add/ask{,/stream}/chat{,/stream}/documents/remove/models/pull all `event: done` |
| 6 MCP | PASS | 25 tools listed; 8 representative calls return content |
| 7 TUI | PASS* | 5 screens render; chat input now refocuses on resume (bb-6mup fix) — but the actual chat-text-input flow was deferred; re-test after compaction |
| 9 Wiki build | PASS | concept + draft pages with frontmatter + faithfulness; lint reports 2 expected content warnings |
| 11 Edge cases + concurrency | PASS | bad pull → 404 + exit 1; empty search rejected; `event: already_ingesting` fires on concurrent same-source `/api/add` |
| 12 Reset | PASS | data dir cleared, init recreates fresh state |

## What's left (continue here)

| Phase | Remaining | Notes |
|---|---|---|
| 7 TUI chat-text-flow | not yet exercised | bb-6mup fix should let `i → type → Enter` work after `[/]` navigation; verify via tmux send-keys |
| 8 Crawler runtime | not yet exercised | crawl4ai is now installed (0.8.6); test `lilbee add https://example.com` and `/api/crawl` SSE for `event: crawl_page` + `event: done` |
| 10 Provider switching | partial | Ollama detection already verified (4 remote models showed up at `localhost:11434`). LiteLLM not yet exercised end-to-end (needs an API key the user trusts to expose to the run; skip or use a free tier) |
| Wiki MCP tools | partial | wiki_status/list/drafts_list verified. wiki_build/synthesize/prune/update/read/citations not yet tool-called via MCP (they ran via CLI) |
| TUI install wizard with no models | not exercised | requires fresh `LILBEE_MODELS_DIR` AND missing model files; the current run had models pre-pulled |

## Findings filed (all closed)

| bd | P | Status | Commit | What |
|---|---|---|---|---|
| bb-0jg8 | 1 | CLOSED | `2c052c0` | cfg default chat_model + featured.toml + 4 test files → Q8_0 (only file in Qwen/Qwen3-0.6B-GGUF) |
| bb-6yqt | 2 | CLOSED | `8481fc3` | `/setup/crawler/status` now reports `package_installed` + `chromium_installed` separately |
| bb-vd5b | 3 | CLOSED | `8481fc3` | error text "lilbee models install" → "lilbee model pull" |
| bb-6mup | 3 | CLOSED | `8481fc3` | TUI chat input refocuses on `on_show` (was AUTO_FOCUS-only) |

Pre-existing not filed: `tests/test_tui_e2e.py::TestChatSlashCommands::test_cmd_status` xdist flake.

## Critical environment to verify on resume

```bash
# at /Users/tobias/projects/lilbee
git log --oneline -1                    # → 8481fc3 ...
git status -s                           # only untracked: README_REVISED.md, REVIEW_PR188*.md, debug-sigill.sh
ls /tmp/qa-pr188-data/.lilbee/          # config.toml, data/, documents/
ls /tmp/qa-pr188-models/manifests/ 2>/dev/null || ls ~/Library/Application\ Support/lilbee/models/manifests/  # Qwen + nomic manifests
ls /tmp/qa-pr188-captures/SUMMARY.md    # report from previous run
uv run python -c "import crawl4ai, litellm; print('crawl4ai', crawl4ai.__version__.__version__); print('litellm', __import__('importlib.metadata').metadata.version('litellm'))"
ls ~/Downloads/cv-manual.pdf            # test fixture (Ford vehicle manual, 362 chunks when ingested)
bd list --status=open --json | jq -r '.[] | select(.title|test("QA"))'   # nothing left
```

## Resume commands (copy-paste from here)

### Phase 8: crawler runtime end-to-end

```bash
# Fresh data dir
rm -rf /tmp/qa-pr188-data /tmp/qa-pr188-captures/crawl-resume
mkdir -p /tmp/qa-pr188-data /tmp/qa-pr188-captures/crawl-resume
cd /tmp/qa-pr188-data && uv --project /Users/tobias/projects/lilbee run lilbee init

# CLI crawl
cd /tmp/qa-pr188-data && LILBEE_MODELS_DIR=/tmp/qa-pr188-models uv --project /Users/tobias/projects/lilbee run lilbee add https://example.com 2>&1 | tee /tmp/qa-pr188-captures/crawl-resume/cli-add.txt

# Verify .md saved
ls /tmp/qa-pr188-data/.lilbee/documents/_web/

# Search the crawled content
cd /tmp/qa-pr188-data && LILBEE_MODELS_DIR=/tmp/qa-pr188-models uv --project /Users/tobias/projects/lilbee run lilbee search "Example Domain" | tee /tmp/qa-pr188-captures/crawl-resume/cli-search.txt

# HTTP /api/crawl (boot server first)
cd /tmp/qa-pr188-data && LILBEE_MODELS_DIR=/tmp/qa-pr188-models uv --project /Users/tobias/projects/lilbee run lilbee serve --port 8765 &
until curl -fsS http://127.0.0.1:8765/api/health > /dev/null 2>&1; do sleep 2; done
TOKEN=$(python -c "import json; print(json.load(open('/tmp/qa-pr188-data/.lilbee/data/server.json'))['token'])")
curl -N --max-time 30 -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"url":"https://example.com"}' http://127.0.0.1:8765/api/crawl | tee /tmp/qa-pr188-captures/crawl-resume/http-crawl.txt
pkill -f "lilbee serve --port 8765"
```

Pass criteria for Phase 8:
- `lilbee add https://example.com` produces an .md under `documents/_web/`.
- `lilbee search "Example Domain"` returns ≥1 hit from that .md.
- `/api/crawl` SSE: `event: crawl_start`, ≥1 `event: crawl_page`, `event: done`.

### Phase 7 chat-text-flow (re-test after bb-6mup fix)

```bash
tmux new-session -d -s qa-tui-resume -x 200 -y 50
tmux send-keys -t qa-tui-resume "cd /tmp/qa-pr188-data && LILBEE_MODELS_DIR=/tmp/qa-pr188-models uv --project /Users/tobias/projects/lilbee run lilbee" Enter
sleep 6
tmux send-keys -t qa-tui-resume "]"; sleep 2; tmux send-keys -t qa-tui-resume "["    # navigate Catalog and back to Chat
sleep 2
tmux send-keys -t qa-tui-resume "i"; sleep 1
tmux send-keys -t qa-tui-resume -l "Tell me about engine oil"
sleep 1
tmux send-keys -t qa-tui-resume Enter
# wait for streaming response, capture frames
sleep 25
tmux capture-pane -t qa-tui-resume -p > /tmp/qa-pr188-captures/tui-chat-resume.txt
tmux send-keys -t qa-tui-resume "C-c"
tmux kill-session -t qa-tui-resume
```

Pass criteria: capture contains response text relevant to "engine oil" (the cv-manual has many such chunks); no traceback.

### Phase 10 LiteLLM (only if you want — needs API key)

LiteLLM is installed but exercising it needs a key. Skip unless the user
wants to test a specific provider; ollama detection already verified.

### Wiki MCP tool calls

```bash
# Same MCP driver pattern from /tmp/mcp-driver.py (still on disk).
# Add wiki_build, wiki_synthesize, wiki_prune, wiki_update, wiki_read,
# wiki_citations to the calls list. Make sure wiki = true is in
# /tmp/qa-pr188-data/.lilbee/config.toml first.
```

## Key files (for any agent picking this up)

- `/Users/tobias/projects/lilbee/REVIEW_PR188.md` — code-walk plan
- `/Users/tobias/projects/lilbee/REVIEW_PR188_QA.md` — full QA matrix plan
- `/Users/tobias/projects/lilbee/REVIEW_PR188_COMMITS.txt` — 30+ commit cheat sheet
- `/Users/tobias/projects/lilbee/REVIEW_PR188_QA_RESUME.md` — **this file**
- `/tmp/qa-pr188-captures/SUMMARY.md` — last run's report
- `/tmp/qa-pr188-captures/{static,cli,http,mcp,tui,errors,wiki,reset}/` — capture trail

## Hard rules to carry forward

- All fixes land on `tidy-module-organization` (no follow-up PRs).
- File new findings as bd issues; don't fix inline unless they block QA progression.
- Don't `git add -A` — it pulls in `README_REVISED.md` / `debug-sigill.sh` / the review files. Stage explicit paths.
- `make check` must stay green at 100% coverage on every commit.
- Static gates already exercised; no need to rerun unless QA is interrupted by a code change.

## Quick verifier before resuming

```bash
cd /Users/tobias/projects/lilbee
git log --oneline -3
ls /tmp/qa-pr188-captures/SUMMARY.md
uv run lilbee --help > /dev/null && echo OK
```

If all three pass, you can keep going from any of the "What's left" sections above without re-running anything done.
