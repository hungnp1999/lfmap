# Design: core extension points before the freeze (Phase 3a, item A10)

- Date: 2026-11-14. Role: Architect. Issue #334. Item A10 of `docs/research/2026-11-14-phase3-outline.md` section 12.2 point 2.
- Status: **direction accepted by the owner on 2026-11-14 14:40Z** (all seven decisions of section 8 and the ADR amendments of section 6; recorded in section 10). Design only: no code and no invariant is changed by this file. The ADR texts are in `docs/research/2026-11-14-adr-027-029-drafts.md`. Building each point is separate 3a work with its own card.
- Question: which hooks must the core offer before it is frozen, so that the later plugins (memory, voice, proactivity, phone, devices: levels L3 to L7 of `docs/research/2026-11-10-lanhai-assistant-architecture.md`) need no change to the core's architecture.
- Owner frame (2026-11-14): after the 3a exit, for about 4 years, no change request alters the basic architecture of the core. Fixes, additive functions and configuration continue as normal. Surprises are handled as exceptions raised to the owner, but the freeze is upheld in every design and planning decision.
- Sources: `/mnt/project-files/lfmap-docs/` 02 (Plugin Contract v0.2) and 03 (ADR-001..026), `ARCHITECTURE.md`, `docs/specs/` (model-client, chat-ui, rest, flows, events, data-classes), the Lan sketch, the threat model of 2026-11-13, `lfmap-core` at `147d2dd`.
- Sibling documents, so nothing is designed twice:
  - #331 (architecture baseline) owns the **spec of the label on tool results** and the **ADR for channel `chat`**. Section 4.8 here only lists what that label must be able to do.
  - `docs/research/2026-11-14-lan-core-architecture.md` (in progress, another thread) owns the **inside of the Lan engine**: session kernel, context ledger, step executor, the shape of `ModelClient` v2 messages. This file owns the **seams a plugin or a surface touches**.
- Limits: facts about Windows, browsers and Python behaviour that were not run are marked "verify". Sizes use the units of the Phase 3 outline (S, M, L).

## 1. Verdict

1. **The five points the outline named are all needed.** Two of them are too narrow as named. A "GPU lock" should be a lease on a named serial resource (the board already has two: `res:gpu` and `res:office`). A "listener process rule" should be the rule for every long-running process, because the bus drainer that proactivity needs is the same kind of thing as a wake-word listener.
2. **Three more points were found.** Outbound connections to hosts the owner names, including hosts on the home network (a device hub; the `email` plugin of Phase 2 needs the public half already). The attach points of the conversation loop (how a surface such as voice or the phone, a memory recall, and a memory writer plug in). The label for data that has no path (owned by #331).
3. **Four points amend accepted text.** "No network beyond loopback", "no background service", "no daemon" and the scope of ADR-016 are all touched. None is contradicted in spirit, but each needs an ADR accepted by the owner before code. Three ADR drafts cover them (section 6).
4. **One thing is deliberately not an extension point: streaming operations.** A plugin operation stays one input, one output, for the whole freeze. Streaming exists in exactly two places: the model call and the conversation's event stream. This is the decision in this file that is hardest to reverse (section 4.1, decision D2).
5. **Design is frozen at 1.0; code is built on demand.** Only the parts that change shared shapes (contract types, audit fields, config models, the gate's view of who calls) must be code at the 3a exit. A non-loopback listener, for example, is built with the first plugin that needs it, as an additive function under an ADR that is already accepted. This keeps A10 at size M to L instead of XL (section 7).
6. **3a grows by about three cards beyond the outline's A10 estimate** (resource lease, inbox, long-running process host) plus three ADR drafts. Warned here as the project rule on scope asks.

## 2. The test: what counts as a change to the core's architecture

The owner's definition needs a form a reviewer can apply to a pull request. Proposed **[needs Hùng, D1]**: after the freeze a change is architectural, and therefore refused or raised as an exception, when it does one of these.

| # | Architectural change (not allowed after the freeze) | Why it is the architecture |
| --- | --- | --- |
| F1 | A new way for a caller to reach an operation other than `run_operation` behind the Gate | "One door" is what makes tiers, classes and audit hold |
| F2 | A new channel value, or a changed rule in `decide` / `job_decision` for an existing channel | Every channel is a column in the approval matrix that every plugin relies on |
| F3 | A new kind of long-running process, or a new way for processes to talk to each other | The process model decides what can run while nobody watches |
| F4 | A new rule about where a socket may listen or connect | The network posture is the egress boundary |
| F5 | A breaking change to the Plugin Contract (manifest keys, `ToolContext`, the shape of an operation, error codes) or to the formats of `config.toml`, `flows.toml` and the state files | Plugins and the owner's files are written against them |
| F6 | A new store written by more than one component, or a new arbitration between processes | Shared state is where one-maintainer systems rot |
| F7 | A change in who can approve, or where approval state lives | The human boundary |

Allowed at any time: fixes; new plugins, operations and event topics; new config tables whose absence keeps today's behaviour; new optional manifest keys (the manifest is strict, so each is a minor release of the core); new audit fields; a new endpoint protocol behind `ModelClient`; a new value in a list that an extension point declares open (resource names, listener names, named endpoints).

Each point in section 4 exists to turn a future F-change into an allowed addition. The channel list is proposed **closed at eight values** at 1.0: `sdk`, `cli`, `mcp`, `rest`, `job` (legacy audit lines only), `event`, `flow`, `chat`. A new surface maps onto one of them and is told apart by attributes of the caller (section 4.4), never by a ninth channel.

## 3. Demand: what the later plugins need and cannot get today

| Level | Plugin (sketch) | Needs from the core | Blocked today by | Point |
| --- | --- | --- | --- | --- |
| L2 | conversation loop (3a itself) | model calls that return tool calls; answers that arrive piece by piece | `ModelClient` v1 has neither (spec non-goals) | X1 |
| L3 | `memory` | recall before each turn; learn from finished turns; label a fact that has no path | the loop has no declared attach point; labels are path-based (ADR-025) | X2, X8 |
| L4 | `voice`, push-to-talk | be a surface of the same loop; run speech programs without colliding on the GPU; label audio and transcripts | no surface rule; GPU use is serial by habit only | X2, X6, X8 |
| L4 later | wake word | a process that listens all the time | "no background service" (`ARCHITECTURE.md` Shape, ADR-018 (1)) | X5 |
| L5 | `briefing`, `notify`, sensors | a place where Lan speaks first; reaction to an event within seconds, not at the next scheduled drain | no inbox; "no daemon" (events invariant) | X3, X5 |
| L6 | phone (PWA over a private network) | reach the REST adapter from another device; know which device asked | REST binds 127.0.0.1 only (`rest.md` R2); audit has `principal` but no device | X4 |
| L7 | `home` (bridge to a device hub) | connect out to a host on the home network; receive the hub's pushes | only loopback, cloud model routes and public pages in `[web]` are allowed | X7, X4, X5 |
| 3a | security S4 (A8) | tell the owner about an incident; stop every surface in safe mode | no inbox; no single list of what is running | X3, X5 |

## 4. The points

Each point: need, options, recommendation, contract, rules (candidate invariants), conflicts, and what 1.0 freezes. Signatures are contract sketches in the style of `model-client.md` section 3, not implementation.

### 4.1 X1: tool calling and streaming in model access

**Need.** L2 short requests (outline A5, required since 2026-11-14) and every later surface that should not wait in silence for a full answer.

**What this file fixes** (the message and turn types themselves are in the Lan core architecture document):

1. **Additive on `ctx.models`.** `chat(...)` gains optional `tools` and `tool_choice`; a second method `chat_stream(...)` returns an iterator of deltas that ends with the same `ChatResult` a plain `chat` would return. A plugin written against v1 keeps working unchanged (frozen-plugin fixture).
2. **A tool call is data.** `ModelClient` never executes anything. It returns tool calls with parsed arguments; the stream delivers a tool call only when it is complete, so no consumer ever handles half an argument object. Whoever receives a tool call can act on it only through `run_operation` (the loop) or `context_for` (a plugin, with the caller's rights and channel). F1 holds.
3. **Tool names** offered to a model are generated from manifests exactly as the MCP adapter does (`<plugin>_<operation>`, ADR-014). No second naming scheme.
4. **Capabilities per endpoint, no silent downgrade.** An endpoint states `tools` and `stream` support (config, with a default per protocol). A call that needs a capability the routed endpoint lacks fails with `backend_unavailable`, `reason: unsupported`. The `claude -p` endpoint of ADR-026 runs with all tools off, so it is `tools = false` by construction.
5. **Routing, class rule, T3 gate and egress lines are unchanged** and apply per call, streamed or not. The `sent` line is written before the request, the result line when the stream ends or breaks.
6. **Plugins do not implement `ModelClient`.** A new provider is a new protocol module in the core plus an endpoint entry in `[models]`. This keeps every byte that leaves through a model in one audited place.

**Decision D2: operations stay unary [needs Hùng].**

- Option A, streaming operations: `@operation(stream=True)` yields chunks through every adapter. Touches CLI, MCP, REST, Flows (step outputs are stored whole and referenced by later steps), events (payload limit) and the label (a label per chunk). It is the largest possible change to the contract and has no user in L3 to L7.
- Option B (recommended), unary operations: one Pydantic input, one Pydantic output, as today. Long work reports progress through an optional `ctx.progress(text, fraction)` that does nothing by default (addable at any time, so not part of A10). Text-to-speech is called per sentence by the surface; live partial transcripts, if ever wanted, are events with references.
- Cost of B: a later plugin that truly needs a streamed result (none known) would be an F5 exception. ADR-001 already recorded this limit ("adapter sinh tự động có giới hạn với streaming … xử lý bằng hook mở rộng khi cần"); B answers it with "the hook is progress, not chunks".

**Frozen at 1.0:** points 1 to 6 and D2. **Open:** multimodal message parts (shape in the engine document; adding a part kind is additive).

### 4.2 X2: attach points of the conversation loop

**Need.** The loop is core code (`chat.py`, `chat-ui.md` section 2). Voice, the phone, memory and proactivity are plugins or clients. Without declared attach points each of them would later need its own change inside the loop (F1 or F5).

Four attach points, and no others:

| Attach point | Who uses it | Contract |
| --- | --- | --- |
| **Entry** | every surface | One function, `converse(conversation, text, origin) -> stream of ChatEvent`. Reachable three ways: the REST route family (web UI, phone), a CLI command, and `ctx.conversation` for a plugin whose manifest sets `[adapters] surface = true` (voice). Not reachable over MCP (an outside agent driving Lan's own agent is a confused deputy) and not from inside a call that is already on channel `chat` (no re-entry) |
| **Event stream** | every surface | `ChatEvent` with a `kind`: `turn.started`, `text.delta`, `tool.call` (name, tier, input summary drawn by core), `tool.result` (status, error code, label), `proposal.filed` (id), `notice` (busy, call cap, safe mode), `turn.ended` (reason: `stop`, `step_limit`, `refused`, `cancelled`, `error`). New kinds may be added; a consumer must ignore kinds it does not know. Over HTTP the stream is server-sent events on the response of the `POST` (plain HTTP, one direction, no new dependency: verify with the FastAPI version in `uv.lock`). Cancel is closing the connection or a cancel call; the loop stops before the next model or tool call |
| **Context provider** | `knowledge` today, `memory` later | An operation with `side_effects = "none"` whose input and output match a fixed pair (`ContextQuery {text, budget_tokens}`, `ContextItems {items: [{text, source, label}]}`). The owner lists providers in `[assistant] context = ["knowledge.context", "memory.recall"]`; the loop calls each before a turn through `run_operation`, checks the schema at start, and enters every item in the context with its label. A provider gets no rights beyond its own manifest |
| **Session observer** | `memory` (learning), later analytics | Core publishes `chat.turn.ended {conversation, turn}` on the bus (references only, like `flows.run.<status>`). A plugin with `[permissions] sessions = "read"` may call `ctx.sessions.read(conversation, turn)`; what it reads raises its call label. Writing what it learned is an ordinary operation of that plugin, usually a flow step, with its ordinary tier |

**Rules.**

- Everything the loop does for a surface runs on channel `chat`. A surface is told apart by `origin` (section 4.4), not by a channel (F2).
- A surface never approves. Approval surfaces are a different seam, owned by outline item A6 and the engine document. If stop rule S3 drops A6, that seam must still be designed in 3a, or approving from a phone later would be an F7 change. **Flagged.**
- The tool list a model sees is the owner's `[assistant] tools` allow-list, filtered again by what the surface's origin may call.
- The text of a `tool.call` card and of a proposal is drawn by core from the real input, never from model output (`chat-ui.md` section 4, outline A6 risk).

**Frozen at 1.0:** the four attach points, the base event kinds, the two schemas. **Open:** more event kinds; more provider roles.

### 4.3 X3: notification inbox

**Need.** Lan rule 6 ("Lan speaks first only through the inbox"), L5, and core itself: a pending approval, a failed flow, a reached call cap, an S4 incident.

**Options.**

- A. Plugin `notify` owns a table in its `data_dir`. Core cannot write to it without depending on a plugin, so core's own notices would need a second path.
- B. Notifications are bus events with a durable subscription. Events carry references only, are delivered at least once and are pruned; an inbox item has text, a read state, an expiry and a dedup key. Wrong container.
- C (recommended). **Core module `inbox.py` with its own small SQLite file, and a thin built-in plugin `inbox`** (operations `post`, `list`, `mark`) in front of it. Core code posts directly; plugins post through `ctx.notify`; flows post with `call = "inbox.post"`; CLI, MCP and REST forms are generated like any plugin's. No adapter learns anything about the inbox.

**Contract.**

```python
ctx.notify(title: str, body: str = "", *, priority: Literal["info", "action", "urgent"] = "info",
           dedup_key: str | None = None, expires_hours: int | None = None, ref: str | None = None) -> str  # item id
```

- Needs `[adapters] notify = true`. Plain text only: title at most 120 characters, body at most 2000, shown escaped by the same rule as `approvals.visible`; no link is ever made clickable from an item, and an item can point at a proposal id but can never carry an approve action.
- Core stamps each item: time, source (plugin id or `core`), `principal`, run or flow id, the **call label** at post time (class and provenance), state (`new`, `read`, `dismissed`).
- `[inbox]` in `config.toml`: `per_source_per_day` (default 20), `urgent_per_day` (default 3, the interruption budget of Lan rule 6), `urgent_sources` (which plugins may post `urgent` at all; default only `core`), `keep_days` (default 14). Over a budget the item is dropped and one "N notices suppressed from <source>" item replaces them.
- After a post core publishes `inbox.item.posted {id, priority, source}` when `events.db` exists (reference only). A toast, a spoken alert or a content-free ping to the phone is then a plugin or a flow reacting to that event. The budget is enforced at post time in core, so it never depends on a surface.

**Rules.**

- **Tier: T0 within the budget [needs Hùng, D3].** The inbox is the core's own store, like `audit.jsonl`: posting neither changes the owner's documents nor sends anything out. If posting were T1, every briefing flow would need `max_tier = 1` only to say something. The scarce resource is the owner's attention, and a budget protects that better than a tier. This extends the reasoning of ADR-016 from a plugin's `data_dir` to one core store, so it needs an ADR line.
- An item posted from a context marked untrusted is shown as such. This is the control against planted text that tells the owner to approve something.
- `inbox.list` on an egress channel (`mcp`, remote `rest`) returns only items whose label the destination may receive (same rule as G1 #308); bodies of `private` items never go to a cloud route.
- A run started by an `inbox.*` event cannot post to the inbox (checked in `check_flow`, like the ban on `flows.*` triggers). No notification loops.
- Backup takes item metadata without bodies (same reasoning as G5 #312).

**Frozen at 1.0:** `ctx.notify`, the three priorities, the item fields, the event topic. **Open:** more delivery plugins, more `[inbox]` keys.

### 4.4 X4: listening beyond loopback, and a device identity

**Need.** L6 (phone), L7 (a hub that pushes), and the threat model's note that a non-loopback bind is "a new invariant: own ADR, device identity in audit lines".

**Options.**

- A (recommended). The REST adapter may bind one more address, under a strict rule, to devices the owner enrolled.
- B. Keep loopback and let a VPN tool forward to it. Every remote caller then looks like a local one and inherits the loopback token's trust. **Rejected**, and worth a warning in the docs: never proxy the loopback listener.
- C. A chat-app bot or an own cloud relay. An external send on every turn, or a service to run (Lan sketch section 4.6).

**Rule set for A (ADR draft N1, with section 4.7).**

1. **Config only.** A listener exists only as `[listen.<name>]` in the owner's `config.toml`: `address` (a literal IP; never `0.0.0.0` or `::`; must be private, unique-local or in the shared range 100.64.0.0/10 that mesh VPNs use, checked with `ipaddress`: verify the exact predicates), `port`, `surface` (`rest` at 1.0; the value list is open), `tls_cert`, `tls_key`. There is still no `--host` option. `lfmap serve rest --listen <name>` adds that listener to the loopback one.
2. **Fail closed.** The address must be assigned to an interface at start; otherwise the listener does not start and nothing falls back to another address. The interface going away stops it.
3. **TLS always** on a non-loopback listener. Browsers also require a secure context for passkeys (#199) and for an installable web app (verify), so this is needed regardless of the VPN's own encryption. How the owner gets a certificate is open (section 9).
4. **Devices are enrolled by the owner.** `lfmap devices enroll <name>` at a TTY with the owner code creates a random token shown once, stored hashed in `devices.json` in the owner's profile, with an expiry (default 90 days, like destinations), a data ceiling (`normal` or `private`, never `secret`) and a tier ceiling (0 or 1, default 0). `revoke` and `list` exist. The loopback token is not valid on a non-loopback listener and a device token is not valid on loopback. Five wrong tokens lock the listener for five minutes (the TOTP pattern). Device entries are not restored from a backup (same reasoning as G6 #313).
5. **A device is a destination.** Returning content to a device is egress: the label of what is returned is checked against the device's data ceiling, as for `[approval.destinations]` (ADR-017 (4)).
6. **A device never approves by its token.** Calls from a device: T0 runs, T1 runs when the device's ceiling is 1, anything above becomes a proposal. Approving from a device is A6 (passkey, own ADR).
7. **Who is calling becomes part of every decision.** The Gate receives an `origin` (`surface`, `device`, `remote: bool`) next to the channel, and `audit.jsonl` gains `device` and `surface`. Channel stays `rest` or `chat`. This struct and the two audit fields are the part that must be **code at 1.0**, because adding a parameter to the Gate later is F2/F5.
8. Host header must equal the configured address or name; `Origin` must be the listener's own; no CORS. Core never changes the Windows firewall; `lfmap doctor` lists listeners and warns about a public address or an expired device.
9. Safe mode (A8) stops every non-loopback listener.

**Conflicts.** `ARCHITECTURE.md` invariant "No network beyond loopback"; `rest.md` R2 ("Bind 127.0.0.1 only. No `--host` option"); `chat-ui.md` section 7; the ADR-009 note of 2026-11-11. All are amended by N1, none silently.

**Frozen at 1.0:** rules 1 to 9, `origin`, the audit fields. **Built on demand:** the TLS listener and `devices` commands, with the phone work.

### 4.5 X5: long-running processes

**Need.** Wake word (L4 later), reaction to events within seconds (L5), a file watcher, a held connection to a hub (L7). Today: "no background service" (`ARCHITECTURE.md` Shape; ADR-018 (1); ADR-006 consequence; project principle "ít dịch vụ nền"), and "No daemon: handlers run only while … drains".

**Options.**

- A. Each plugin starts what it likes. N unsupervised daemons, each a new F3.
- B. One core host process running plugin listeners as threads. One crash or leak takes all of them; a microphone listener and a bus drainer need different Windows sessions.
- C. An own supervisor that spawns one child per listener. Restart, backoff and logging become core code to maintain.
- D (recommended). **One process per listener, started and restarted by Windows Task Scheduler**, which ADR-018 already made the only scheduler. `lfmap jobs register` creates task `\LFMAP\listen-<plugin>-<name>` (trigger at logon or at start, "restart on failure": verify the available settings on pc-01), which runs `lfmap listeners run <plugin>.<name>` from `[runtime] root` (ADR-023). No supervisor code. The launcher is Windows-specific; the contract below is not.

**The process model, closed at three kinds (ADR draft N2).**

| Kind | Examples | Started by |
| --- | --- | --- |
| One-shot | a CLI call, a flow run, a scheduled task | the owner or Task Scheduler; exits when done |
| Server | `serve mcp`, `serve rest` | an MCP client, the UI shell or the owner; lives while its client does |
| Listener | bus drain, wake word, file watcher, hub connection | Task Scheduler, only when the owner enabled it |

Nothing else may outlive a call. A subprocess that an operation starts ends with the operation (and gets the minimal environment of G9 #316).

**Contract.**

```toml
[[listeners]]                 # plugin manifest
name = "wake"
session = "interactive"       # interactive (needs the logged-on desktop: microphone) | background
```

```python
class VoiceTool(Tool):
    @listener("wake")
    def wake(self, stop: StopSignal) -> None: ...  # a loop; must return within 10 s of stop
```

- **Off by default.** A listener runs only with `[listeners."<plugin>.<name>"] enabled = true` in the owner's `config.toml`. Installing a plugin never starts a process (supply chain, G8 #315).
- **A listener senses, it does not act.** Its context is an `event`-channel context: nobody is asked, calls are capped at `[events] max_tier`, and a call above the ceiling is refused (after JF-4 the only proposal kind is `flows.resume`; verify against the JF-4 result). What it may do: publish its own plugin's events (references only), post to the inbox, write its `data_dir`, lease a resource, use `ctx.models` / `ctx.net` as its manifest allows, and, with `surface = true`, start a conversation turn. Gated work happens in a flow that its event triggers. So a listener adds no path to an operation (F1) and no channel (F2).
- **Sensors are declared.** `[permissions] sensors = ["microphone"]` (open list). `lfmap listeners list` and the UI show what is listening; an always-on microphone is never silent in the interface.
- **Core's own listener `core.drain`** is the bus drain in a loop. It is the first user of the host and what makes event-triggered flows timely. Without it enabled, behaviour is exactly today's.
- One instance per listener (OS lock); a heartbeat file per listener for `doctor` and the UI; a maximum lifetime (default 24 h) after which the host exits and the scheduler starts it again; safe mode stops all listeners except `core.drain`.

**Conflicts.** The wording "no background service" and "No daemon" in `ARCHITECTURE.md`, ADR-018 (1) and the events spec. The principle survives as: **zero long-running processes by default; each one is named, enabled by the owner, supervised by the operating system, and listed.** Needs ADR N2 because the Lan sketch already said a background process "needs its own ADR".

**Frozen at 1.0:** the three kinds, the listener contract, off by default, `core.drain`. **Open:** listener names, sensor names.

### 4.6 X6: resource leases (the GPU lock, generalised)

**Need.** pc-01 has one GPU and jobs on it are serial by the owner's rule, kept today by hand and by board labels. A voice turn, a reindex, a bench of the agent account and a docling run must not collide, and a busy GPU must be said, not waited on in silence (Lan sketch section 4.4).

**Options.**

- A. Leave it to the model runtime's own queue. Covers only programs behind that runtime, and nothing can report "busy".
- B (recommended). **An advisory lease on a named resource, in core.** `gpu` is the first name; `office` (COM automation is also serial) and a sound device fit the same mechanism with no new design.
- C. A scheduler with priorities and preemption. A running model call cannot be preempted; this is a product of its own.

**Contract.**

```python
with ctx.resources.lease("gpu", purpose="transcribe", wait_seconds=None) as lease:
    ...
    if lease.should_yield():
        ...  # a background holder checks between units of work
```

- Resources are named by the owner: `[resources.gpu]` (exclusive; at 1.0 a resource has one holder). A plugin needs `[permissions] resources = ["gpu"]`.
- **Model calls take the lease themselves.** `[models.endpoints.<name>] resources = ["gpu"]` makes `ModelRouter` hold the lease around each call to that endpoint, so plugins that only use `ctx.models` never see it. A reindex embeds batch by batch and so releases between batches.
- **Busy is an answer.** No lease within the wait gives `backend_unavailable`, `reason: resource_busy`, with the holder's plugin, purpose and start time. No new error code. Default wait by channel: short on `cli`, `chat`, `rest`, `mcp` (seconds); long on `flow` and `event` (`[resources.gpu] unattended_wait_minutes`), so a night job queues behind another instead of failing.
- **Implementation choice: an operating-system file lock** (`msvcrt.locking` on Windows; verify that the lock is released when the holder dies) on one file per resource, with the holder's metadata written inside. No lease table, no heartbeat and no stale-lock clean-up to maintain. An in-process callee (`context_for`) shares its caller's lease.
- **Across accounts.** The agent account's benches use the same GPU but cannot reach the owner's profile (ADR-023). `[resources] lock_dir` may point to a folder both accounts can write, which the owner creates. The agent account can then hold the lock (availability only) and nothing else; holder metadata read from that file is treated as untrusted text (fixed character set, short).
- `should_yield()` lets an interactive waiter ask a background holder to stop at its next safe point. The method is in the 1.0 contract; its first implementation may always return `False`.

**Honest limits.** Advisory: a program outside LFMAP ignores it. It serialises use; it does not count VRAM, and a runtime that keeps a model loaded after the call still occupies memory. More than one resource per call is taken in name order.

**Conflicts.** None. **Frozen at 1.0:** `ctx.resources.lease`, `should_yield`, the busy error, the endpoint key. **Open:** resource names; counted resources.

### 4.7 X7: outbound connections to hosts the owner named

**Need.** Not on the outline's list. L7 must reach a hub on the home network. Today three purpose-built outbound rules exist (`[models]` cloud endpoints, `[web] allowed_hosts` for public pages, loopback), and the Phase 2 `email` plugin will need a fourth for its mail server. A hub on a private address is refused by all of them, and allowing it later would be F4.

**Recommendation: one rule for all outbound connections, written into the same ADR as X4 (N1), with the detailed spec written for `email` as the first user.**

1. A plugin connects only through a core connector, `ctx.net`, to an endpoint the owner named: `[net.endpoints.<name>]` with `host`, `port`, `tls`, `scope` (`public` or `private`), a data ceiling and an expiry. The plugin names the endpoint, never a host. It needs `[permissions] network = true` and `[adapters] net = true`.
2. The connector resolves the host, checks every address against the scope (`public`: globally routable only; `private`: private, unique-local or the shared VPN range only; loopback never through this door) and connects to the checked address, the pattern `web_http.py` already uses.
3. Each connection writes an audit line by endpoint name (no content), and what is sent is checked against the endpoint's data ceiling by label.
4. The tier is the operation's own (`side_effects = "external"`, lowered per call only by ADR-020: `min_tier` plus the owner's config). A device action that can harm stays T3.
5. `[models]` and `[web]` keep their own tables and rules; they are the same pattern and may later be expressed on the shared connector without a contract change.

**Residual risk, unchanged from today:** this binds honest plugins and makes review possible; in-process plugin code can open a socket itself (`ARCHITECTURE.md` already says this is not a sandbox). The control for a dishonest plugin is the owner's allow-list (G8 #315).

**Frozen at 1.0:** rules 1 to 4 including `scope = "private"`. **Built on demand:** the private scope, with the first device plugin.

### 4.8 X8: a label for data that has no path (requirements handed to #331)

#331 step 1 writes the spec. For the later plugins it must satisfy:

| # | Requirement | Who needs it |
| --- | --- | --- |
| R1 | A label (class and provenance) attaches to a value, not only to a path: a memory fact, a transcript, an inbox item, a chat message, a device state | X2, X3, L3, L4, L7 |
| R2 | A plugin can raise its call label by class with no path (today `ctx.mark_data(path)` only); never lower | `memory`, `voice` |
| R3 | A plugin declares in its manifest the lowest class of what it produces when no path is involved (for example `memory` and `voice` produce `private`); the owner may raise it in config; lowering stays a TTY action with the owner code (ADR-025 (3)) | all path-less producers |
| R4 | A derived value keeps at least the class of its sources (no downgrade by summary, Lan sketch section 4.2) | `llm`, `memory` |
| R5 | Provenance marks content that came from outside (page, mail, recording of other people, device-reported text); a spoken or typed request is never an approval, whatever its label | X2, X3 |
| R6 | The label is stored wherever the value is stored: step outputs, inbox items, conversation context, memory records | Flows, X3, engine |

## 5. Trace: do the later plugins fit without a core change?

A first pass of the freeze test of outline section 12.2 point 3. The one-page designs are still owed at the 3a exit; this table shows that nothing known falls outside the points.

| Plugin | Uses | Anything outside the points? |
| --- | --- | --- |
| `memory` (L3) | X2 context provider and session observer, X8, ordinary operations and proposals | No |
| `voice` push-to-talk (L4) | X2 surface, X1 stream (speak sentence by sentence), X6 `gpu`, X8; speech programs as subprocesses on the `powershell` pattern | No |
| Wake word (L4 later) | X5 listener with `sensors = ["microphone"]`, X2 surface, X6 | No. Interrupting Lan mid-answer uses the cancel of X2 |
| `briefing`, proactivity (L5) | Flows and schedule triggers (exist), X3, X5 `core.drain` for timely events | No |
| Phone (L6) | X4 listener and device, X2 entry and stream over REST, X3 through `inbox.list` | Reading and asking: no. **Approving from the phone needs the approval-surface seam (A6)** |
| Phone ping when the UI is closed | X3 event, a flow, X7 endpoint, content-free text | No |
| `home` (L7) | X7 private endpoint, X5 listener for a held connection or X4 with the hub enrolled as a device, ADR-020 tiers per action | No |
| Security S4 (A8, inside 3a) | X3 `urgent` from `core`, safe mode stopping X4 and X5 | Safe mode itself is A8's design; X4 and X5 only promise to obey it |

Known to fall outside, and accepted as outside the freeze test: more than one principal (family members with their own rights: Team Edition, on signal); more than one machine (NATS behind the `EventBus` Protocol, ADR-006); full-duplex speech (hardware, Lan sketch section 1 point 7).

## 6. Conflicts with accepted ADRs and documents

Nothing below is changed by this file. Each row needs the owner's decision before code.

| Accepted text | Touched by | Kind | Resolution proposed |
| --- | --- | --- | --- |
| `ARCHITECTURE.md`: "No network beyond loopback, except …"; `rest.md` R2; `chat-ui.md` section 7; ADR-009 note of 2026-11-11 | X4, X7 | Amends | **ADR draft N1 "Network posture"**: listen only through `[listen]` to enrolled devices; connect only through named endpoints with a scope. `gate:po`, `/security-review` |
| `ARCHITECTURE.md` Shape "no background service" and events invariant "No daemon"; ADR-018 (1) "không thêm dịch vụ nền"; ADR-006 consequence; project principle "ít dịch vụ nền" | X5 | Amends the wording, keeps the principle | **ADR draft N2 "Process model"**: three kinds, listeners off by default and supervised by Task Scheduler. `gate:po` |
| ADR-016 (own `data_dir` is not a side effect) and ADR-017 (1) tiers | X3 at T0 | Extends by analogy | **ADR draft N3 "Inbox"**, or one more note on ADR-016. `gate:po` |
| ADR-001 consequence (streaming handled "by an extension hook when needed") | D2 | Narrows | A note on ADR-001: operations are unary; progress, not chunks |
| `model-client.md` non-goals (streaming, tool calling) and decision 7 | X1 | Planned follow-up, no conflict | Spec revision with outline item A5 |
| ADR-017 (4) destinations | X4 rule 5 | Reuses | A device is treated as a destination; no change |
| ADR-020 | X7 rule 4 | Reuses | No change |
| ADR-023 | X5 (runs from `[runtime] root`), X6 (shared lock folder crosses the account boundary for availability only) | Consistent; one new shared folder | Stated in N2; the owner creates the folder |
| ADR-024 (no framework; named capabilities trigger a review) | X2, X5 | Consistent | None. No framework is proposed |
| ADR-025 (classes come from paths) | X8 | Extends | #331 step 1 |
| Flows invariant "a flow never pre-approves" | none | Not touched | Plan-level approval is outline item A7, not A10 |
| Plugin Contract (strict manifest) | new keys in section 7 | Additive | Contract 1.0 at the 3a exit |

No point contradicts an accepted ADR in a way that forces "change the ADR or change the requirement" beyond the amendments above. The two that deserve the owner's closest reading are N1 (it opens the first inbound port beyond the machine) and N2 (it ends "nothing runs unless something started it just now").

## 7. What Contract 1.0 gains, and what must be code at the 3a exit

| Point | Added to the contract | Code at 1.0 | May wait for its first user |
| --- | --- | --- | --- |
| X1 | `tools`, `tool_choice`, `chat_stream`; endpoint capabilities | Yes (A5 uses it) | |
| X2 | `[adapters] surface`, `ctx.conversation`, `ChatEvent`, context-provider schemas, `[permissions] sessions`, `ctx.sessions`, topic `chat.turn.ended` | Entry, event stream, context provider (first provider: `knowledge`) | `ctx.conversation` and `ctx.sessions` for plugins |
| X3 | `[adapters] notify`, `ctx.notify`, plugin `inbox`, `[inbox]`, topic `inbox.item.posted` | Yes (core's own notices) | delivery plugins |
| X4 | `[listen]`, `devices.json`, Gate `origin`, audit `device` and `surface` | `origin` and the audit fields | TLS listener, `devices` commands |
| X5 | `[[listeners]]`, `@listener`, `[listeners]`, `[permissions] sensors` | Host command and `core.drain` | plugin listeners |
| X6 | `[permissions] resources`, `ctx.resources`, `[resources]`, endpoint `resources` | Yes (small; useful in Phase 2 already) | |
| X7 | `[adapters] net`, `ctx.net`, `[net.endpoints]` | Public scope, with `email` | private scope |
| X8 | per #331 | per #331 | |

Proposed order: X8 design with #331 (Phase 2 exit). X6 first (S, no ADR, removes a manual rule today). N1, N2, N3 drafted and accepted early in 3a. X3 (S to M). X1 and X2 with outline items A4 and A5. X5 host and `core.drain` (M). X4 shapes (S). X7 with `email`. Total A10: three ADR drafts plus about five cards, size M to L as the outline estimated, provided "code on demand" is accepted.

## 8. Decisions for Hùng

1. **D1.** Accept the test of section 2 (F1 to F7, eight channels closed) as the working definition of "a change to the core's architecture"?
2. **D2.** Operations stay unary for the whole freeze: streaming only in the model call and the conversation event stream (section 4.1)? Hard to reverse.
3. **D3.** The inbox is a core store, posted at T0 inside a daily budget (section 4.3)?
4. **D4.** Network posture N1: listening beyond loopback only through `[listen]`, TLS and enrolled devices; connecting out only through named endpoints, including a `private` scope for the home network (sections 4.4, 4.7)?
5. **D5.** Process model N2: zero long-running processes by default; owner-enabled listeners, one process each, supervised by Task Scheduler (section 4.5)?
6. **D6.** A lease on named resources in place of a GPU-only lock, with an optional lock folder shared with the agent account (section 4.6)?
7. **D7.** "Design frozen at 1.0, code on demand" (section 7), and 3a grows by X2, X6 and X7?

Nothing here blocks Phase 2 work. D2 and D4 are the ones to read slowly.

## 9. Left open

- How the owner gets a TLS certificate for a non-loopback listener: a script around the Windows certificate tools, a small vetted library, or the VPN product's own feature. Decide with the phone work; the Python standard library cannot create one.
- Whether channel `event` survives JF-4 as the listener channel, or listeners need the JF-4 result restated (section 4.5).
- The approval-surface seam (A6) if stop rule S3 drops A6: design it in 3a anyway (section 4.2).
- Credentials for plugins (a hub token, a mail password): ADR-018 (5) points at Windows Credential Manager and `model-client.md` at an environment variable. One rule should be written with the `email` spec in Phase 2; it is not an A10 point because `email` forces it earlier.
- Counted or prioritised resources, and VRAM accounting (section 4.6).
- The threat model's own trigger list (section 12 there) asks for a redo before the REST adapter or the chat loop is merged; N1 and N2 should be in that redo.

## 10. Decisions recorded (Hùng, 2026-11-14 14:40Z)

The owner accepted the ADR amendments of section 6 and the proposals for all seven decisions of section 8 (D1 to D7), as written.

His frame for reading this file and the Lan core architecture document together: the project is shaping a **framework**. A risk that cannot be handled at the level of the framework is covered by another solution later. Example given: security risks that are hard to pin down while the Lan core is being designed are resolved in the security core, not by tightening the framework now.

What follows from it:

| Item | State |
| --- | --- |
| D1: test F1 to F7, eight channels closed | Accepted. Used in every 3a design review; goes into `ARCHITECTURE.md` with the first code that relies on it |
| D2: operations stay unary | Accepted. Note on ADR-001 |
| D3: inbox as a core store, T0 inside a budget | Accepted. ADR-029 |
| D4: network posture (listen through `[listen]`, TLS, enrolled devices; connect through named endpoints, scope `private` included) | Accepted. ADR-027. Code PRs still run `/security-review` |
| D5: process model (zero by default, owner-enabled listeners under Task Scheduler) | Accepted. ADR-028 |
| D6: resource leases, optional shared lock folder | Accepted. No ADR needed (no accepted text is amended). Backlog card: #339 |
| D7: design frozen at 1.0, code on demand; 3a grows by X2, X6, X7 | Accepted. Roadmap line for A10 to be widened by the coordinator |

Risks this file names but leaves to other work, in line with the owner's frame: in-process plugin code can open its own socket or start its own process (the rules bind honest plugins; the control is the plugin allow-list G8 #315 and the security core); an advisory lock is ignored by programs outside LFMAP; the points of section 9 stay open until their first user.

Accepting the direction is not accepting code: each point is built from its own card, and `ARCHITECTURE.md` changes only in the PR that lands the code.

ADR numbers: 027, 028 and 029 are taken by this file. ADR-030 is reserved for "labels and sinks" (the two sink rules of the Lan core architecture document, #333), written together with the label spec of #331.
