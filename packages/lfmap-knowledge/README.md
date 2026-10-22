# lfmap-knowledge

LFMAP plugin that catalogs and indexes your local files once, so an agent can search them and get cited context without rescanning disks. Everything runs on this machine: text extraction through `lfmap-markitdown`, embeddings through a local Ollama, storage in SQLite and LanceDB. Roadmap Phase 1, items 1.4 and 1.5.

| Operation | What it does | Side effects |
| --- | --- | --- |
| `status` | Roots, file counts by status, chunk count, embedding model, Ollama reachable, indexer busy | none |
| `reindex` | Scan the roots; extract, chunk and embed only new or changed files | none (writes only its own index) |
| `search_files` | Find files by name text, root, extension, status or modification date | none |
| `get_file` | One file's catalog entry, chunk count and duplicates | none |
| `search` | Hybrid (keyword + vector) chunk search with path and heading of each hit | none |
| `get_context` | Chunks for a question packed into a token budget, each with a citation | none |
| `related` | Files linked from or to a file | none |

## Setup

1. Add the folders to index to your config (interactive terminal only, so an agent cannot widen them):

   ```powershell
   uv run lfmap config add-folder D:\Docs --as knowledge
   ```

2. Optional settings in `%LOCALAPPDATA%\lfmap\config.toml`:

   ```toml
   [plugins.knowledge.settings]
   ollama_url = "http://127.0.0.1:11434"   # loopback only: 127.0.0.1, ::1 or localhost
   embed_model = "bge-m3"

   [plugins.knowledge.settings.sensitivity]   # default "normal"
   'D:\Contracts' = "private"
   'D:\HR' = "secret"
   ```

   - `normal` and `private`: returned on every channel. `secret`: only on `cli` and `sdk`, never over MCP.
   - Over MCP, roots that are secret or no longer in the config are hidden.

3. Pull the embedding model once: `ollama pull bge-m3`. Without Ollama, `reindex` still catalogs and extracts, skips embedding and says why in `embed_skipped_reason`; `search` falls back to keyword mode.

The index lives in `%LOCALAPPDATA%\lfmap\knowledge\` (`catalog.db`, `vectors\`, `cache\md\`, `indexer.lock`). `vectors\` can be rebuilt from `catalog.db` and the cache by running `reindex` again.

## Examples

CLI:

```powershell
uv run lfmap knowledge reindex --json        # first run extracts and embeds; later runs only stat unchanged files
uv run lfmap knowledge status --json
uv run lfmap knowledge search --query "hợp đồng bảo trì" --limit 5
uv run lfmap knowledge get_context --question "Điều khoản thanh toán là gì?" --token-budget 2000
```

SDK:

```python
from lfmap_core.registry import Registry
from lfmap_core.runtime import run_operation

registry = Registry()
registry.discover()
out = run_operation(registry.get("knowledge"), "get_context", {"question": "payment terms"})
for chunk in out.chunks:
    print(chunk.citation.path, chunk.citation.heading_path)
```

MCP (Claude Code):

```powershell
claude mcp add lfmap -- uv run --directory D:\Development\lfmap lfmap serve mcp --plugins knowledge
```

Then ask Claude about your documents; it calls `knowledge_search` or `knowledge_get_context` and cites path and heading.

## Reindex every hour

Add a job to `%LOCALAPPDATA%\lfmap\jobs.toml` (see `docs/jobs.md`), then run `uv run lfmap jobs register`. `reindex` is T0, so `max_tier = 0` is enough.

```toml
[[jobs]]
id = "knowledge-reindex"
plugin = "knowledge"
operation = "reindex"
input = {}
schedule = { every_minutes = 60 }
max_tier = 0
enabled = true
```

`register` rewrites every task in `\LFMAP\` and resets "Run whether user is logged on or not" on them; set it again afterwards if you use it.

## Limits

- Every result is marked `untrusted`: it is text from your files, to be treated as data, not instructions.
- Each `search` or `get_context` call that returns hits writes one row to `egress_log` in `catalog.db` (channel, operation, file and chunk ids, bytes).
- No network except the loopback Ollama URL.
- Legacy Office formats (`.doc`, `.rtf`, ...) and OCR follow `lfmap-markitdown`.
- Vietnamese keyword search without diacritics can match several accented words ("ma" matches "mà", "má", "mã"); vector search narrows it.
- One indexer at a time (`indexer.lock`); `status` shows `indexer_busy`.
