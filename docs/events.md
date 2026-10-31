# Event bus

The event bus lets plugins, jobs and (later) LFMAP Flows react to each other without calling each other
directly. It runs on one Windows machine with no background service (ADR-006, ADR-021). Handlers only run when
a process **drains** the bus: at the end of `lfmap jobs run` or when `lfmap events run` is called explicitly.
See [docs/specs/events.md](specs/events.md) for the full specification.

## Turning the bus on for a plugin

Add one line to the plugin manifest (`lfmap.toml`):

```toml
[adapters]
events = true
```

Without it `ctx.events` raises `permission_denied` and the plugin neither publishes nor receives events.
`lfmap jobs doctor` flags a job whose plugin has `events = false` but whose `via` is `"event"`.

## Publishing from a plugin

Inside a tool method use `ctx.events.publish`:

```python
ctx.events.publish("knowledge.indexed", {"path": str(path), "count": n})
```

Rules that the bus enforces:

- **Topic ownership.** A plugin may only publish topics that start with its own id (`knowledge.indexed` is
  allowed from the `knowledge` plugin; `echo.say` is not). Topics of the form
  `<plugin>.<operation>.requested|completed|failed` belong to core and are always refused.
- **Payload limit.** Payloads are JSON objects with string keys, at most 65 536 UTF-8 bytes once encoded
  compact and key-sorted. Carry references (paths, ids, counts), never document text or secrets.
- **Causation chain.** When the event adapter runs an operation in response to a `.requested` event and the
  plugin calls `ctx.events.publish` inside that operation, the new event's `causation_id` is set to the
  `.requested` event's id automatically. No extra argument is needed. Outside of an event-adapter call
  `causation_id` is not set by `ctx.events.publish`.

## Topics and patterns

A topic is 1–8 tokens joined by single dots; a token is one or more of `a-z 0-9 _ -`. Patterns follow the
same rules but a token may be `*` (matches exactly one token) or `>` (as the last token, matches one or more).
Matching compares token lists, not string prefixes: `jobs.>` does not match `jobs`.

Examples: `knowledge.*` matches `knowledge.indexed`; `echo.>.requested` is invalid (`>` must be the last
token); `echo.say.>` matches `echo.say.requested` and `echo.say.completed`.

## Handlers must be idempotent

The bus delivers **at least once**: if a process dies after the handler runs but before the ack is written, or
if a lease expires (60 s) while the handler is still running, the same event is delivered again. Every handler
must be idempotent: use `event.id` (a stable 32-character hex UUID) to detect and skip a duplicate.

Retries back off exponentially: 2 s, 4 s, 8 s … capped at 300 s, up to 5 attempts. After five failures, or
after a `ToolError` with code `invalid_input`, `permission_denied` or `not_found`, the delivery becomes a
**dead letter** (see Troubleshooting).

## `[events] max_tier` and the approval queue

Add to `config.toml` if you want event-triggered operations to run without a person:

```toml
[events]
max_tier = 0   # 0 = only T0 (read-only) runs; 1 = T1 (new files) also runs
```

The default is 0. The same tier table as jobs applies (see [docs/jobs.md](jobs.md#jobs-through-the-event-bus-via--event)). A call above the ceiling is
queued as a proposal under job `events` and can be approved later at a TTY with `lfmap approvals approve`. See [docs/approvals.md](approvals.md) for tiers, grants and the queue.

## Commands

```powershell
uv run lfmap events status [--json]
# Deliveries per subscription and state (ready / leased / done / dead).

uv run lfmap events dead [--subscription SUBSCRIPTION] [--json]
# List dead letters (events a handler gave up on). Filter by subscription name.

uv run lfmap events retry EVENT_ID SUBSCRIPTION
# Put one dead letter back in the queue (interactive terminal only).

uv run lfmap events prune [--days 7]
# Delete handled events older than --days; dead letters and pending work stay (interactive terminal only).

uv run lfmap events run [--until-idle] [--max-seconds 60]
# Attach the event adapter and drain queued events.
# --until-idle: stop when nothing is ready (useful for scheduled jobs).
# --max-seconds: wall-clock limit (default 60 s).
```

`retry` and `prune` require an interactive terminal, like `approvals approve`.

`lfmap jobs run <id>` also drains after the job (bounded by `--max-events`, default 1000). Use
`lfmap events run` when you need lower latency, for example as a scheduled job every few minutes.

## Where the data lives

`events.db` is a SQLite WAL file in the user's app folder (`%LOCALAPPDATA%\lfmap\events.db`). It is written
by core only; no caller-supplied path reaches it. The file contains three tables: `events`, `subscriptions`
and `deliveries`. Two processes can drain the same subscription at the same time: leases (60 s) prevent
duplicates.

Prune regularly to keep the file small:

```powershell
uv run lfmap events prune --days 7   # remove handled events older than 7 days
```

`prune` also drops `request-*` watcher subscriptions older than a day (left behind by a killed `lfmap jobs run`) with their deliveries.

Dead letters and pending deliveries of other subscriptions are never pruned automatically.

## Troubleshooting

**Dead letters.** A delivery becomes a dead letter after 5 failures or after a permanent error code. List them:

```powershell
uv run lfmap events dead
uv run lfmap events dead --subscription adapter-echo   # one subscription only
```

Fix the root cause (bad payload, missing file, plugin bug), then put the event back in the queue:

```powershell
uv run lfmap events retry <event-id> <subscription>
```

After `retry`, the next drain attempts delivery again from attempt 1.

**Queue not draining.** Remember: no daemon. Run `lfmap events run --until-idle` or add it as a scheduled job
(see `lfmap jobs register`) if you need lower latency than the next `jobs run`.

**Locked database.** `SqliteBus` uses a 30 s busy timeout. A lock error means another process held an
`IMMEDIATE` transaction for over 30 s, which should not happen in normal use. If it does, stop all LFMAP
processes and restart.
