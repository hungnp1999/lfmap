# lfmap-web

Plugin `web`: one operation, `fetch`, reads one public page over HTTPS and returns its text. All network code, the allow-list and the limits live in `lfmap-core` (`docs/specs/web-plugin.md`); the plugin only calls `ctx.web.fetch`.

| Input | Output |
| --- | --- |
| `url` (https), `max_bytes` (optional, only lowers the cap), `save = false` | `url_final`, `status`, `content_type`, `text`, `bytes`, `truncated`, `fetched_at`, `saved_path` |

```powershell
uv run lfmap web fetch --url https://example.org/        # CLI
uv run lfmap serve mcp --plugins web                      # MCP tool web_fetch
```

In a flow: `call = "web.fetch"` with `input = { url = "https://example.org/list" }`, then `${steps.fetch.output.text}` in the next step.

## Hosts and limits (owner's `config.toml`)

```toml
[web]
allowed_hosts = ["example.org"]   # exact host names; no table means no host is reachable
rate_limit_per_host = 12          # requests per minute per host
max_bytes = 2097152
timeout_s = 20
max_redirects = 3
max_calls_per_run = 100
```

- No `http`, no IP literals, no userinfo, redirects are re-checked against the list, addresses must be globally routable.
- Tier: T0 on every channel (no approval), except a URL whose query is longer than 200 characters, which is T3 and so never runs unattended.
- `save = true` writes a copy to `<plugin data folder>/pages/<UTC time>-<host>-<sha256 first 8>.<ext>`. The copy is the page text as returned, encoded as UTF-8 (the plugin only receives decoded text). The name never contains the URL path or query. Nothing is deleted automatically.
- Page text is data: it is returned verbatim and never parsed, followed or obeyed. Converting HTML is a separate step.
- Check a site's terms of service and `robots.txt` before listing it; the rate limit is a ceiling, not permission.
