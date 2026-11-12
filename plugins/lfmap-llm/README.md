# lfmap-llm

Plugin `llm`: three operations that send text to the model the owner routed each task to (`[models]` in `config.toml`, see `docs/specs/model-client.md`).

| Operation | Input | Output |
| --- | --- | --- |
| `summarise` | `text`, `max_words = 150`, `language = "same"`, `data = "normal"` | `summary`, `model`, `truncated` |
| `extract` | `text`, `schema` (field name to `{type, description}`), `data` | `fields`, `missing`, `model` |
| `classify` | `text`, `labels` (2 to 20), `data` | `label`, `model` |

```powershell
uv run lfmap llm summarise --text "..." --max-words 80       # CLI
uv run lfmap serve mcp --plugins llm                          # MCP tools llm_summarise, llm_extract, llm_classify
```

In a flow: `call = "llm.summarise"` with `input = { text = "${steps.convert.output.markdown}" }`.

- The plugin names a task (`summarise`, `extract`, `classify`), never a URL. Routes and endpoints exist only in the owner's `config.toml`.
- A task routed to a local endpoint is T0 and runs unattended; a cloud route is T3 (a person approves it at a terminal, or a `[approval.destinations]` entry covers it) and each cloud call writes a `model_call` line to `audit.jsonl`. `data = "secret"` never goes to a cloud endpoint.
- The input text is placed after a fixed delimiter and the system message says it is data, never instructions. Model output is still untrusted: `extract` keeps only schema keys of the declared type (the rest go to `missing`), `classify` returns only one of `labels`, and anything else is `backend_unavailable` with `reason: bad_response`.
- `summarise` cuts input over 100 000 characters at a paragraph boundary and sets `truncated = true`; `extract` and `classify` refuse longer input.
- Reads and writes no files.
