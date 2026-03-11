# lilbee

> This is an experimental tool and a work in progress. There will be issues with some formats and performance at scale is unknown at this time

[![PyPI](https://img.shields.io/pypi/v/lilbee)](https://pypi.org/project/lilbee/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/tobocop2/lilbee/actions/workflows/ci.yml/badge.svg)](https://github.com/tobocop2/lilbee/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/badge/coverage-100%25-brightgreen.svg)](https://tobocop2.github.io/lilbee/)
[![Platforms](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey.svg)]()
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Downloads](https://img.shields.io/pypi/dm/lilbee)](https://pypi.org/project/lilbee/)

> A local, offline knowledge base. Add documents and code, ask questions grounded in what's actually there.

---

- [Why lilbee](#why-lilbee)
- [Demos](#demos)
- [Install](#install)
- [Quick start](#quick-start)
- [Interactive chat](#interactive-chat)
- [Agent integration](#agent-integration)
- [Supported formats](#supported-formats)
- [Configuration](#configuration)
- [How it works](#how-it-works)

---

## Why lilbee

Index your documents and code into a local knowledge base, then ask questions grounded in what's actually there. Most tools like this only handle code. lilbee handles PDFs, Word docs, epics — and code too, with AST-aware chunking.

- **Documents and code alike** — add anything from a vehicle manual to an entire codebase
- **Fully offline** — runs on your machine with [Ollama] and LanceDB, no cloud APIs or Docker
- **Works with AI agents** — MCP server and JSON CLI so agents can search your knowledge base too

Add files (`lilbee add`), then ask questions or search. Once indexed, `search` works without Ollama — agents use their own LLM to reason over the retrieved chunks.

## Demos

### AI agent

[opencode] + [minimax-m2.5-free][opencode], single prompt, no follow-ups. Better results should be easily possible with iteration or [AGENTS.md](demos/godot-with-lilbee/AGENTS.md) refinements.

> [!CAUTION]
> minimax-m2.5-free is a cloud model — retrieved chunks are sent to an external API. Use a local model if your documents are private.

```
make a procedural level generator that places wall and floor tiles
and scatters collectibles using pathfinding. save it as level_generator.gd
```

In Godot 4.4, "places tiles" means [`TileMapLayer`][tml] — the engine's tile rendering class. "Using pathfinding" means [`AStarGrid2D`][asg2d] or [`NavigationServer2D`][ns2d] — the engine's built-in pathfinding. Without these, tiles don't render and pathfinding doesn't use the engine.

| | Uses TileMapLayer | Uses engine pathfinding |
|---|---|---|
| **With lilbee** | ✓ `TileMapLayer` | ✓ `AStarGrid2D` |
| **Without lilbee** | ✗ missing | ✗ `AStar2D` (manual, no grid) |

Full demos below — expand to see the recordings, generated code, and agent configs.

<details>
<summary><b>With lilbee</b> — all APIs correct (12/12) · <a href="demos/godot-with-lilbee/">source</a></summary>

![With lilbee MCP](demos/godot-with-lilbee.gif)

Uses `TileMapLayer.set_cell()` for tile rendering and `AStarGrid2D` for grid-based pathfinding — all 12 API calls verified against the Godot 4.4 class reference. Generated from a single prompt with no follow-ups.
</details>

<details>
<summary><b>Without lilbee</b> — compiles but doesn't place tiles (failed) · <a href="demos/godot-without-lilbee/">source</a></summary>

![Without lilbee](demos/godot-without-lilbee.gif)

Same model, no source indexed. No [`TileMapLayer`][tml] — level is a `Dictionary` in memory with no rendering. Uses `AStar2D` instead of engine pathfinding. Collectibles tracked in an array but never instantiated.
</details>

### Standalone

<details>
<summary><b>Interactive local offline chat</b></summary>

> [!NOTE]
> Entirely local on a 2021 M1 Pro with 32 GB RAM.

Model switching via tab completion, then a Q&A grounded in an indexed PDF.

![Interactive local offline chat](demos/chat.gif)

</details>

<details>
<summary><b>Code index and search</b></summary>

![Code search](demos/code-search.gif)

Add a codebase and search with natural language. Tree-sitter provides AST-aware chunking.
</details>

<details>
<summary><b>JSON output</b></summary>

![JSON output](demos/json.gif)

Structured JSON output for agents and scripts.
</details>

## Install

### Prerequisites

- Python 3.11+
- [Ollama] — the embedding model (`nomic-embed-text`) is auto-pulled on first sync. If no chat model is installed, lilbee prompts you to pick and download one.
- **Optional** (for image OCR): `brew install tesseract` / `apt install tesseract-ocr`

> **First-time download:** If you're new to Ollama, expect the first run to take a while — models are large files that need to be downloaded once. For example, `qwen3:8b` is ~5 GB and the embedding model `nomic-embed-text` is ~274 MB. After the initial download, models are cached locally and load in seconds. You can check what you have installed with `ollama list`.

### Install

```bash
pip install lilbee        # or: uv tool install lilbee
```

### Development (run from source)

```bash
git clone https://github.com/tobocop2/lilbee && cd lilbee
uv sync
uv run lilbee
```

## Quick start

```bash
# Check version
lilbee --version

# Chat with a local LLM (requires Ollama)
lilbee

# Add documents to your knowledge base
lilbee add ~/Documents/manual.pdf ~/notes/

# Ask questions — answers come from your documents via a local LLM
lilbee ask "What is the recommended oil change interval?"

# Search documents — returns raw chunks, no LLM needed at query time
lilbee search "oil change interval"

# Remove a document from the knowledge base
lilbee remove manual.pdf

# Use a different chat model
lilbee ask "Explain this" --model qwen3

# Check what's indexed
lilbee status
```


## Interactive chat

Running `lilbee` or `lilbee chat` enters an interactive REPL with conversation history, streaming responses, and slash commands:

| Command | Description |
|---------|-------------|
| `/status` | Show indexed documents and config |
| `/add [path]` | Add a file or directory (tab-completes paths) |
| `/model [name]` | Switch chat model — no args opens an interactive picker; with a name, switches directly (tab-completes installed models) |
| `/version` | Show lilbee version |
| `/reset` | Delete all documents and data (asks for confirmation) |
| `/help` | Show available commands |
| `/quit` | Exit chat |

Slash commands and paths tab-complete. A spinner shows while waiting for the first token from the LLM.

## Agent integration

lilbee can serve as a local retrieval backend for AI coding agents via MCP or JSON CLI. See [docs/agent-integration.md](docs/agent-integration.md) for setup and usage.

## Supported formats

| Format | Extensions | Requires |
|--------|-----------|----------|
| PDF | `.pdf` | — |
| Office | `.docx`, `.xlsx`, `.pptx` | — |
| eBook | `.epub` | — |
| Images (OCR) | `.png`, `.jpg`, `.jpeg`, `.tiff`, `.bmp`, `.webp` | [Tesseract](https://github.com/tesseract-ocr/tesseract) |
| Data | `.csv`, `.tsv` | — |
| Text | `.md`, `.txt`, `.html`, `.rst` | — |
| Code | `.py`, `.js`, `.ts`, `.go`, `.rs`, `.java` and [150+ more](https://github.com/Goldziher/tree-sitter-language-pack) via tree-sitter (AST-aware chunking) | — |

## Configuration

All settings are configurable via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `LILBEE_DATA` | *(platform default)* | Data directory path |
| `LILBEE_CHAT_MODEL` | `qwen3:8b` | Ollama chat model |
| `LILBEE_EMBEDDING_MODEL` | `nomic-embed-text` | Embedding model |
| `LILBEE_EMBEDDING_DIM` | `768` | Embedding dimensions |
| `LILBEE_CHUNK_SIZE` | `512` | Tokens per chunk |
| `LILBEE_CHUNK_OVERLAP` | `100` | Overlap tokens between chunks |
| `LILBEE_MAX_EMBED_CHARS` | `2000` | Max characters per chunk for embedding |
| `LILBEE_TOP_K` | `10` | Number of retrieval results |
| `LILBEE_SYSTEM_PROMPT` | *(built-in)* | Custom system prompt for RAG answers |

CLI also accepts `--model` / `-m`, `--data-dir` / `-d`, and `--version` / `-V` flags.

## How it works

Documents are hashed and synced automatically — add, change, or delete files and lilbee keeps the index current. [Kreuzberg] extracts text from PDFs, Office docs, images (OCR), etc. [tree-sitter] chunks code by AST. Chunks are embedded via [Ollama] and stored in [LanceDB]. Queries embed the question, find the closest chunks by vector similarity, and pass them as context to the LLM.

### Data location

| Platform | Path |
|----------|------|
| macOS | `~/Library/Application Support/lilbee/` |
| Linux | `~/.local/share/lilbee/` |
| Windows | `%LOCALAPPDATA%/lilbee/` |

Override with `LILBEE_DATA=/path` or `--data-dir`.

## License

MIT

[Ollama]: https://ollama.com
[opencode]: https://opencode.ai
[Kreuzberg]: https://github.com/Goldziher/kreuzberg
[tree-sitter]: https://tree-sitter.github.io/tree-sitter/
[LanceDB]: https://lancedb.com
[tml]: https://github.com/godotengine/godot/blob/4.4-stable/doc/classes/TileMapLayer.xml
[asg2d]: https://github.com/godotengine/godot/blob/4.4-stable/doc/classes/AStarGrid2D.xml
[nr2d]: https://github.com/godotengine/godot/blob/4.4-stable/doc/classes/NavigationRegion2D.xml
[ns2d]: https://github.com/godotengine/godot/blob/4.4-stable/doc/classes/NavigationServer2D.xml
