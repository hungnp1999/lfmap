# Module Spec: EventBus (in-house, in-process + SQLite)

- Package: `lfmap-core` (flat modules next to `jobs.py`)
- Roadmap: Phase 2a item 2a.3 "EventBus tự xây"; research plan RT-03 (spec, Protocol, contract tests) and RT-12 (durable SQLite queue) in [`docs/research/2026-10-23-commercial-replacements.md`](../research/2026-10-23-commercial-replacements.md)
- Decisions: ADR-006 as amended by ADR-021 (in-house EventBus: Protocol + in-process + SQLite queue with outbox, ack, redelivery and several processes on one machine; NATS only for several machines), ADR-014 (topic `<plugin>.<operation>.requested`), ADR-017/018 (tiers, non-interactive calls go to the approvals queue), Plugin Contract §5 (Events adapter: receive `.requested`, emit `.completed` / `.failed`)
- Handoff and task list: [`docs/handoff/2026-10-29-eventbus.md`](../handoff/2026-10-29-eventbus.md)
- Frozen tests: [`docs/specs/events-tests/`](events-tests/) (outside `testpaths`; each task copies its files into `packages/lfmap-core/tests/` unchanged)

## 1. Purpose

Let plugins, jobs and (later) LFMAP Flows react to each other without calling each other directly, on one Windows machine, with no background service. Plugins only see the `EventBus` Protocol, so a NATS implementation can be added in Phase 3 without touching plugins.

Non-goals for Phase 2a: Flows definitions (RT-09, next handoff), a daemon or Windows service, events between machines, replay of history, exactly-once delivery, a UI.

## 2. Modules

| Module | Content | Task |
| --- | --- | --- |
| `topics.py` | `validate_topic`, `validate_pattern`, `topic_matches` (grammar below) | TC-N1 (tests from bench W0, commit `790748b`) |
| `events_retry.py` | `PERMANENT_CODES`, `backoff_seconds`, `after_failure`, `describe_error` | TC-E1 |
| `events_payload.py` | `MAX_PAYLOAD_BYTES`, `encode_payload`, `decode_payload` | TC-E2 |
| `events_names.py` | `PHASES`, `operation_topic`, `parse_operation_topic`, `plugin_may_publish` | TC-E3 |
| `events.py` | `Event`, `DeadLetter`, `Handler`, `EventBus` Protocol, `InProcessBus`, shared checks | EB-1 |
| `events_sqlite.py` | `SqliteBus` (+ `prune`) | EB-1 |
| `events_adapter.py` | `PluginEvents` (the plugin's view), `open_bus()`, event adapter for `events = true` plugins | EB-2 |
| `cli.py` | `lfmap events status|dead|retry|prune|run`; `lfmap jobs run` drains after the job | EB-3 |

Standard library and pydantic only. No new dependency (`sqlite3` is stdlib).

## 3. Model

### Topics and patterns (`topics.py`)

- A topic is 1 to 8 tokens joined by single dots, at most 200 characters; a token is one or more of ASCII `a-z 0-9 _ -`.
- A pattern follows the same rules, but a token may be exactly `*` (one token) or, as the last token only, `>` (one or more tokens). `jobs.>` does not match `jobs`.
- Matching compares token lists, never string prefixes.

### Event

```python
class Event(BaseModel):  # frozen, extra="forbid"
    id: str  # uuid4().hex, 32 lowercase hex
    topic: str  # a valid topic, never a pattern
    source: str  # "core" or a plugin id ([a-z][a-z0-9-]{0,63})
    payload: dict[str, Any]  # the JSON round trip of what was published
    created_at: AwareDatetime  # UTC, from the bus clock
    correlation_id: str  # id of the first event of a chain
    causation_id: str | None = None  # id of the event that caused this one
    attempt: int = 1  # delivery attempt, set per delivery


class DeadLetter(BaseModel):
    event: Event
    subscription: str
    attempts: int
    error: str  # events_retry.describe_error, one line, <= 500 chars
```

- Payload: a JSON object with string keys at every depth, no NaN/Infinity, at most 65,536 UTF-8 bytes once encoded compact and key-sorted (`events_payload`). Events carry references (paths, ids, counts), not document content. The stored form is JSON text; never pickle.
- `publish(..., causation=parent)` sets `causation_id = parent.id` and `correlation_id = parent.correlation_id`; without a parent `correlation_id = id`.

### Protocol

```python
Handler = Callable[[Event], None]


@runtime_checkable
class EventBus(Protocol):
    def publish(
        self, topic: str, payload: dict[str, Any] | None = None, *, source: str, causation: Event | None = None
    ) -> Event: ...
    def subscribe(self, name: str, pattern: str, handler: Handler) -> None: ...
    def unsubscribe(self, name: str) -> None: ...
    def drain(self, *, max_events: int = 1000) -> int: ...
    def dead_letters(self, subscription: str | None = None) -> list[DeadLetter]: ...
    def retry(self, event_id: str, subscription: str) -> None: ...
    def close(self) -> None: ...
```

Constructors: `InProcessBus(*, clock=time.time, max_attempts=5)`, `SqliteBus(path, *, clock=time.time, max_attempts=5, lease_seconds=60.0)`. `clock` returns seconds since the epoch; tests pass a fake clock.

## 4. Semantics (the contract, `test_events_contract.py`)

1. **Validation.** Bad topic, pattern, source, payload, subscription name (`[a-z][a-z0-9_-]{0,63}`) or `max_events` (int >= 1) raise `ToolError("invalid_input")`. A refused publish stores and delivers nothing.
2. **Publish never runs handlers.** It records one delivery per subscription whose pattern matches at publish time. Subscriptions created later never see older events (no replay).
3. **`drain` runs handlers** for subscriptions that have a handler in this bus instance, oldest event first, until nothing is ready now or `max_events` handler calls were made, and returns the number of calls. Events published by a handler during a drain are delivered in the same drain.
4. **At-least-once.** A delivery is done only after its handler returns. Handlers must be idempotent; `event.id` is stable across redeliveries.
5. **Ordering.** First deliveries of one subscription follow publish order. A delivery waiting for a retry does not block later events (no head-of-line blocking), so order is not kept after a failure.
6. **Failure.** Any exception from a handler is caught (never escapes `drain`). `after_failure` decides: `ToolError` with code `invalid_input`, `permission_denied` or `not_found` is dead at once; otherwise retry after `backoff_seconds(attempt)` = 2, 4, 8 … capped at 300 s, until `max_attempts` (default 5), then dead.
7. **Dead letters** stay until `retry(event_id, subscription)` (back to ready, attempt count reset) or `unsubscribe`. Unknown dead letter: `not_found`.
8. **Subscriptions are named.** Subscribing again with the same name and pattern replaces the handler; with another pattern it raises `invalid_input` (no silent rerouting). `unsubscribe` drops the subscription and its pending deliveries; unknown name: `not_found`.
9. **Closed bus**: `publish` and `drain` raise `ToolError("backend_unavailable")`; `close` is idempotent.

## 5. SqliteBus specifics (`test_events_sqlite.py`)

- File `%LOCALAPPDATA%\lfmap\events.db` (`open_bus()` in EB-2; the class takes any path). WAL journal, `foreign_keys=ON`, connection timeout 30 s, `PRAGMA user_version = 1`; later schema changes bump `user_version` with an ordered migration list.
- Schema (version 1):

```sql
events(seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE, topic, source, payload TEXT /* JSON */,
       created_at REAL, correlation_id, causation_id)
subscriptions(name TEXT PRIMARY KEY, pattern, created_at REAL)
deliveries(event_seq REFERENCES events(seq) ON DELETE CASCADE, subscription,
           state CHECK (state IN ('ready','leased','done','dead')), attempts, available_at REAL,
           lease_until REAL, lease_token TEXT, last_error TEXT, PRIMARY KEY (event_seq, subscription))
```

- **Outbox.** The `events` row and its `deliveries` rows are written in one `BEGIN IMMEDIATE` transaction, so a published event is never lost after `publish` returns. There is no atomicity with a plugin's own database (catalog.db and events.db are separate files); a plugin publishes after its own commit and accepts at-least-once.
- **Subscriptions are durable.** They live in the database, so events queue while no process has a handler; any process that subscribes with the same name and pattern takes over.
- **Leases.** Claiming a delivery is one `BEGIN IMMEDIATE` transaction: pick the oldest delivery of a local subscription that is `ready` and available, or `leased` with an expired lease; mark it `leased` with `lease_until = now + lease_seconds`, a new random `lease_token` and `attempts + 1`. No transaction is open while a handler runs. Ack and failure updates match on `lease_token`, so a late ack after the lease expired and another process took the delivery is ignored.
- **Several processes** drain the same subscription without duplicates while leases hold (test with two `subprocess` workers on Windows CI).
- `prune(*, older_than: float) -> int` deletes events older than `older_than` seconds whose deliveries are all `done` (or that had none); dead letters and pending work stay. Default retention used by the CLI: 7 days.

## 6. Plugins and the event adapter (EB-2)

- **Opt-in.** A plugin publishes or receives events only when its manifest has `[adapters] events = true`; otherwise `ctx.events` raises `permission_denied`.
- **Publishing.** Plugins use `ctx.events.publish(topic, payload)`; `source` is set to the plugin id. `plugin_may_publish` allows only `<plugin-id>.<…>` topics with at least two tokens and never the operation topics `<plugin>.<op>.requested|completed|failed`, which belong to core.
- **Requests.** Only core (`source="core"`: the event adapter, `lfmap jobs run`, later Flows) publishes `<plugin>.<operation>.requested`, payload `{"input": {...}}`. The adapter keeps one durable subscription per events-enabled plugin, named `adapter-<plugin-id>`, pattern `<plugin-id>.*.requested`.
- **Calls run like jobs.** The adapter runs the operation with `channel="event"` (new `Channel` value). Nobody watches it, so it never asks: `decide` treats `event` like `job`, and the approver applies `job_decision` with `max_tier` from `[events] max_tier` in config.toml (0 or 1, default 0). A call above it becomes a proposal in the approvals queue (`job = "events"`), approved later at a TTY with `lfmap approvals approve`. Every call above T0 is audited as today.
- **Results.** Success publishes `<plugin>.<operation>.completed` with `{"request_id": <event id>, "output": <model_dump(mode="json")>}`; when the output does not fit the payload limit it sends `{"request_id": ..., "output": null, "output_too_large": true}`. A `ToolError` publishes `.failed` with `{"request_id": ..., "error": error.to_dict()}` and returns normally, so permanent business errors are not retried; other exceptions go through the retry policy. Both use `causation=request`.
- Adapters stay generic: no plugin-specific code in `events_adapter.py`.

## 7. CLI and draining (EB-3)

There is no daemon (ADR-006: no background service in Phase 2). Handlers run only when a process drains:

- `lfmap jobs run <id>` drains the bus after the job's operation (bounded by `--max-events`, default 1000).
- `lfmap events run [--until-idle] [--max-seconds 60]` attaches the adapter subscriptions and drains; it can itself be a scheduled job (every few minutes) when lower latency is needed.
- `lfmap events status` (counts by subscription and state), `lfmap events dead [--subscription s]`, `lfmap events retry <event-id> <subscription>`, `lfmap events prune [--days 7]`.
- No MCP or REST form for these commands in 2a. `retry` and `prune` run only at an interactive terminal, like `approvals`.

## 8. Permissions, data and security

- `events.db` lives in the user's app folder, written by core only; no caller-supplied path reaches `SqliteBus`. Payloads are local data; no network.
- Event payloads must not carry document text or secrets (reference by path or id). Audit records stay as today and never include payloads.
- A plugin cannot trigger another plugin's operation: `.requested` is core-only and the event channel is capped at `[events] max_tier` (default T0).
- SQLite text built with f-strings in the reference only interpolates placeholder lists and fixed column names; values always go through parameters.

## 9. Dependencies and licences

None new. `sqlite3` (stdlib, SQLite public domain), pydantic (MIT, already used). Semantics (ack, lease, redelivery, dead letters) follow the public documentation of NATS JetStream (Apache-2.0); no code is copied. Add a `docs/PROVENANCE.md` row with EB-1: "in-house, behaviour referenced from JetStream docs".

## 10. Risks and open points

- At-least-once means duplicate handler calls after a crash or an expired lease; handlers must be idempotent (document in the plugin guide, EB-3).
- `drain` only runs when something drains: latency is "next job or `events run`". Acceptable for the 2a Exit workflow; revisit with Flows.
- SQLite on network drives is not supported (WAL needs a local disk); `%LOCALAPPDATA%` is local.
- A proposal approved later with `lfmap approvals approve` runs the call at the CLI and does not publish `.completed`; Flows (RT-09) decides how an approved step resumes a chain.
- Slow handlers longer than `lease_seconds` (60 s) can run twice; long operations should be started by events but tracked as jobs.

## 11. Definition of Done

- Frozen tests in `docs/specs/events-tests/` copied unchanged into `packages/lfmap-core/tests/` and green on Windows CI, including the two-process test.
- `ruff check`, `ruff format --check`, licence check green; CodeQL clean.
- EB-2 and EB-3: `/security-review` run and answered (they touch adapters and approval).
- `ARCHITECTURE.md` (module map, a "Event" main flow, invariants), `CHANGELOG.md`, `docs/PROVENANCE.md` updated in the PR that adds the code.
- Windows smoke (EB-4): two PowerShell windows draining one subscription; `jobs run` → `.requested` → markitdown `.completed`.
