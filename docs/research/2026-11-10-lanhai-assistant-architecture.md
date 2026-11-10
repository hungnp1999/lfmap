# Lan Hài as a JARVIS-style assistant: architecture sketch and solution choices

- Date: 2026-11-10. Role: Architect. Requested by Hùng (project thread "Phác thảo kiến trúc Lan Hài kiểu Jarvis").
- Epic: #157 (JARVIS roadmap after Phase 3, as LFMAP plugins). Related: #199 (passkey), #194 (web-first UI), #189 (ModelClient), #197 (data classes), #196 (backup).
- Status: **sketch for discussion**. Docs only, no code, no ADR changed, no issue scheduled. Everything that would touch an ADR, the Blueprint or the Roadmap is marked **[needs Hùng]**. Nothing here adds work to Phase 2.
- Sources: `/mnt/project-files/lfmap-docs/` 01–05 (Blueprint v0.3 §15, ADR-001..025, Roadmap), `ARCHITECTURE.md`, `docs/specs/` (model-client, chat-ui, flows, events), `docs/research/2026-11-08-architecture-review.md`.
- Limits of this file: licences and model facts in section 6 come from memory, not from a check of the current upstream files. Each is marked "verify"; none may be used before a License Register row exists. Latency and memory numbers are estimates until a spike measures them on pc-01.

## 1. Summary

1. **Lan is not a new system.** Lan is a set of plugins plus one conversation loop on the core that already exists. The assistant gets no path to a tool other than `run_operation`, so tiers, data classes, grants, audit and the approvals queue apply to it exactly as they apply to a flow.
2. **The model proposes, the core decides.** Whatever the model produces (a tool call, a flow draft, a memory fact) is data that the gate checks. A T2/T3 action from a conversation becomes a proposal, never an in-conversation "yes".
3. **Six building blocks**: senses (text, voice, events), brain (conversation loop, model routing), memory (documents, personal facts, history), hands (plugins), guard (gate, data classes, security plugin), surfaces (web UI, voice out, notifications, phone).
4. **Phase 2 already builds most of the skeleton** (ModelClient, Flows, EventBus, data classes, TOTP, backup, read-only chat UI). This sketch asks for **no new Phase 2 item**, only three reservations to keep in mind when the Phase 2 specs that are already planned get written (section 5).
5. **Order after Phase 3**: text assistant with tool proposals, then personal memory, then voice (push-to-talk), then proactivity, then phone, then IoT. Each stage is usable on its own.
6. **Honest ceiling on pc-01** (RTX 5060 Ti 16 GB, GPU jobs serial): a turn-based voice assistant in Vietnamese is realistic; full-duplex, interruptible speech with large-model reasoning fully local is not, on this hardware. Reasoning quality comes from the models (epic #157, "Out of scope"); the architecture keeps the door open to a stronger local machine or a gated cloud route without change.

## 2. What "JARVIS-equivalent" means here

Capability levels, so progress can be stated without hype. The epic estimated 15–20 % after Phases 1–3; the levels below show where the rest is.

| Level | The owner can | Needs | Earliest |
| --- | --- | --- | --- |
| L0 | Ask questions over own documents, with citations (MCP today) | knowledge, markitdown | done (Phase 1) |
| L1 | Chat with Lan in a window; Lan reads, searches, summarises; sees pending approvals | chat UI v1 read-only, `llm`, ModelClient | Phase 2 (planned) |
| L2 | Ask Lan to *do* things: Lan calls T0/T1 tools itself and files proposals for T2/T3; Lan drafts a flow from a sentence | conversation loop with tool calling, channel `chat`, approvals from the UI | Phase 3 |
| L3 | Lan remembers the owner (preferences, people, ongoing matters) across conversations, and can forget on request | plugin `memory` | after Phase 3 |
| L4 | Speak to Lan and hear the answer (push-to-talk, Vietnamese and English) | plugin `voice` | after Phase 3 |
| L5 | Lan speaks first: morning briefing, "an email needs you", reminders, under an interruption budget | plugin `briefing` on Flows + EventBus, notification surface | after Phase 3 |
| L6 | Same Lan from the phone; approvals with a passkey | PWA + private network, #199 | after Phase 3 |
| L7 | Lan controls devices at home | plugin `home` (bridge) | future, depends on hardware |
| L8 | Lan defends itself: incident detection and encrypted retreat to cloud | security S4 (Roadmap Phase 3) | Phase 3 |

## 3. Architecture

```mermaid
flowchart TB
  subgraph surfaces [Surfaces]
    WEB[Web UI on loopback, later PWA on phone]
    MIC[Microphone, push-to-talk]
    SPK[Speaker]
    NOTE[Notifications inbox]
  end
  subgraph senses [Senses: plugins]
    VOICE[voice: STT and TTS as external programs]
    EMAIL[email, file, calendar]
    SCHED[Task Scheduler]
  end
  subgraph brain [Brain: lfmap-core]
    CONV[conversation loop, channel chat]
    ROUTER[ModelRouter behind ctx.models]
    FLOWS[Flows runner]
    BUS[(EventBus events.db)]
  end
  subgraph guard [Guard: lfmap-core]
    GATE[Gate T0-T3 + data classes + TOTP or passkey]
    AUD[(audit.jsonl, approvals queue, grants)]
  end
  subgraph memory [Memory: plugins]
    KN[knowledge: documents]
    MEM[memory: personal facts]
    HIST[(chat.db history)]
  end
  subgraph hands [Hands: plugins]
    TOOLS[markitdown, llm, powershell, organizer, email send, home]
  end
  subgraph models [Models: outside the product]
    LOCAL[Local runtime on loopback]
    CLOUD[Cloud endpoint, T3 gated]
  end
  WEB --> CONV
  MIC --> VOICE --> CONV
  CONV --> SPK
  EMAIL --> BUS
  SCHED --> FLOWS
  BUS --> FLOWS
  FLOWS --> NOTE
  CONV --> ROUTER
  FLOWS --> GATE
  CONV -->|tool call = run_operation| GATE
  ROUTER --> LOCAL
  ROUTER -->|via gate| CLOUD
  GATE --> TOOLS
  GATE --> KN
  GATE --> MEM
  GATE --> AUD
  CONV --> HIST
```

### 3.1 The six blocks

| Block | What it is | Where it lives | New or existing |
| --- | --- | --- | --- |
| Brain: conversation loop | Prompt assembly, model call, tool-call round trips, citations, stop. One loop for text and voice | `lfmap-core` (`chat.py` of `chat-ui.md` §2), Python stdlib + pydantic | planned (Phase 2 read-only, Phase 3 with tools) |
| Brain: model routing | Task to endpoint, data-class rule, cloud only through T3 | `lfmap-core` `models*.py` | exists (#189) |
| Brain: automation | Flows runner, EventBus, schedules | `lfmap-core` | exists |
| Guard | Gate, data classes, TOTP, grants, audit, approvals queue, backup | `lfmap-core` | exists or planned in Phase 2 |
| Senses | `voice` (speech in), `email`, `file`, `calendar` publish events or feed the loop | plugins | `email`, `file` Phase 2; rest later |
| Memory | `knowledge` (documents), `memory` (personal facts), conversation history | plugins + `chat.db` | knowledge exists; `memory` new |
| Hands | Every plugin operation | plugins | grows per need |
| Surfaces | Web UI, notification inbox, voice out, phone | static UI served by `lfmap serve rest`; `voice` | UI planned; rest new |

### 3.2 Rules that make it safe (proposed invariants)

These are the heart of the design. They restate existing invariants for the new channels, they do not weaken any.

1. **One door.** The conversation loop calls tools only through `run_operation` on channel `chat` (decided like `rest`, `chat-ui.md` §4). Voice is the same loop with speech at both ends, so it uses channel `chat` too. Proactive work is a flow, on channel `flow`. No new privilege path, no new channel rules to audit.
2. **A conversation never approves.** T2/T3 from a conversation becomes a proposal that shows the resolved input. Approval happens outside the model's reach: TTY with TOTP today (ADR-025), the approvals screen with a passkey later (#199). A spoken "yes" is never an approval, because a recording or another person in the room can say it.
3. **Untrusted text does not get hands.** Email bodies, web pages and document content are untrusted input. The dangerous combination is private data + untrusted content + a way to send out. Proposed rule: once a conversation or run has read untrusted content, the proposals it files are marked `tainted` and shown so; a tainted context can never use a time-limited grant for an external send (always a fresh T3 decision). This needs a provenance flag on tool results, which is the same mechanism as the class label that `model-client.md` §4 point 5 already requires before any cloud route is enabled.
4. **The class travels with the data.** Whatever enters the model context carries its data class (ADR-025); the context's class is the highest one in it; a `secret` context never goes to a cloud route (existing rule), and a memory fact inherits the class of its source.
5. **Local first, cloud by named route.** Lan's default brain is a local model. A cloud model is used only when the owner wrote the route, the data class allows it and T3 passes; there is no automatic fallback (existing invariant). Speech audio and personal memory never leave the machine.
6. **Lan speaks first only through the inbox.** Proactivity means a flow ends in a `notify` step that writes to a local inbox with a priority. Only the top priority may interrupt (sound or speech), within a daily budget the owner sets. Lan never starts a T2+ action on its own initiative; it files a proposal and says so.
7. **Everything Lan knows about the owner is inspectable and deletable.** Personal memory is stored as readable records with source and date; `forget` removes the record and its index rows; backup covers it (#196).
8. **Models stay outside the product.** No own inference engine (owner decision 2026-11-06). Speech and language models run in an external runtime or program, reached over loopback or as a subprocess on the allow-list pattern of `powershell` (ADR-020), the way Tesseract and Ollama are reached today.

### 3.3 Two flows, end to end

**"Lan, tóm tắt mail của anh Bình sáng nay rồi soạn trả lời" (voice, L4 + L2).** Push-to-talk records to a temp file in the plugin's `data_dir`; `voice.transcribe` (T0, local program) returns text; the loop asks the local model; the model calls `email.search` (T0, class `private`) and `llm.summarise` (local route); email content marks the context tainted; the model calls `email.draft` (T1, writes a draft in the mailbox's draft folder or a local file); Lan answers in speech with `voice.speak`. Sending is a separate T3 proposal that shows recipient and body; the owner approves on the approvals screen.

**Morning briefing (L5).** Task Scheduler starts flow `briefing` at 07:00: steps `calendar.today`, `email.unread_summary`, `approvals.pending`, `knowledge.changed_since`, then `llm.summarise` on the local route, then `notify` (T1) into the inbox. When the owner opens the UI or says "Lan, có gì mới", the inbox is read out. Nothing runs above T1, so nothing waits for approval.

## 4. Component designs (sketch level)

### 4.1 Conversation loop (core)

- Built on `ModelClient`. Its v1 has no streaming and no tool calling (`model-client.md` non-goals), so the loop needs a **ModelClient v2**: streaming and tool calling for OpenAI-compatible endpoints. This is the one real core extension in this sketch, and it is already implied by `chat-ui.md`; it belongs with the chat UI work, not earlier.
- Tools offered to the model are generated from the plugin manifests, as the MCP adapter does today, filtered by an owner-set allow-list per persona (`[assistant] tools = [...]` in `config.toml`). Fewer tools means better local-model accuracy and a smaller attack surface.
- Planning: for a multi-step request the model does not improvise a long chain of calls. It writes a **flow draft** (TOML, validated by `check_flow`) that the owner sees and starts. This reuses the Flows runner, its ceiling and its durable pause, and avoids a second orchestrator (ADR-024). Short requests (one to three T0/T1 calls) run directly in the loop with a hard step limit.
- Size target: the loop stays a small module like `flows_run.py` (a few hundred lines); a framework is reconsidered only by the named capabilities of ADR-024 note (iv).

### 4.2 Plugin `memory` (personal long-term memory)

Three kinds of memory, three stores, all local:

| Kind | Content | Store | Written by |
| --- | --- | --- | --- |
| Episodic | conversations | `chat.db` (planned in `chat-ui.md`) | the loop |
| Semantic | facts about the owner, people, ongoing matters, preferences | plugin `memory`: one SQLite table (subject, statement, source, class, created, last used, expires) | proposal from the model, accepted by the owner |
| Procedural | "how I like things done" | flows and the assistant's instruction file | the owner |

- Options for semantic memory: (A) Markdown notes in a declared folder that `knowledge` indexes; (B) own SQLite table in the plugin with FTS5, reusing `knowledge`'s chunk and embed functions through the SDK; (C) a third-party memory library.
- **Recommendation: B.** Facts are short records with a life cycle (confirm, update, expire, forget), which a table handles and loose notes do not; no dependency; C adds a dependency for what is one table and two queries. An export to Markdown keeps it readable.
- Write policy **[needs Hùng]**: (1) every fact needs a click; (2) facts of class `normal` and below are saved automatically and listed in a weekly review, `private` and above need a click. Recommendation: (2), because (1) trains the owner to click without reading, the same failure ADR-025 was written against.
- Retrieval: before each turn the loop asks `memory.recall` (T0) for the few facts that match, within a token budget; the facts' classes join the context class (rule 4).
- Not stored: credentials, health and identity documents of other people, anything from a `secret` root unless the owner writes the fact by hand.

### 4.3 Plugin `voice`

- Mode options: (A) push-to-talk (hotkey or button), turn-based; (B) wake word "Lan ơi", always listening; (C) full-duplex speech with interruption.
- **Recommendation: A first, B later as an option, C not on current hardware.** A has no always-on microphone, no wake-word model to license and no false triggers; it also makes "who spoke" a non-issue. B needs a small always-running process, which breaks today's "no background service" shape and therefore needs its own ADR **[needs Hùng]** when its turn comes.
- Pipeline: record (Windows audio API) → voice activity detection → speech-to-text → conversation loop → text-to-speech → play. Each model stage is an external program or loopback runtime (rule 8); the plugin holds only glue and the audio file handling in its `data_dir`. Audio files are deleted after transcription unless the owner turns on keeping them.
- Operations: `voice.transcribe(path) -> text` (T0), `voice.speak(text) -> path` (T0, writes own `data_dir`), `voice.listen()` (interactive, CLI/UI only, no MCP form). The first two are useful alone: dictation, reading a summary aloud, transcribing a meeting recording into `knowledge`.
- Budget on pc-01 (estimates, to measure in a spike): speech-to-text on CPU or a small share of the GPU; a 7–14B chat model on the GPU; text-to-speech on CPU. Target: first sound within about 3 seconds after the owner stops speaking, for short answers. GPU jobs are serial on pc-01, so voice and a reindex or a shadow run cannot share the GPU: the plugin must check a GPU lock and say "busy" instead of queueing silently.

### 4.4 Proactivity (`briefing`, `notify`, context)

- Mechanism: nothing new. Event or schedule triggers start flows; the flow's last step is `notify`. A small core operation or plugin `notify` writes inbox records (SQLite, own `data_dir`): text, priority, source run, expiry.
- Context signals, in the order of value against privacy cost: calendar (high value, low cost), unread mail and pending approvals (already there), files changed in declared roots (already there), active window title (low value, medium cost), screen content and location (**recommend not doing**: high privacy cost, heavy models, little use on a desktop).
- Calendar options: (A) read an `.ics` file or folder that the owner's calendar client exports or syncs; (B) CalDAV over the network; (C) Outlook through COM. Recommendation: A first (stdlib parser, no network, no secret), C when the owner uses Outlook on pc-01 (pywin32 is already in the License Register for MarkitdownTool); B needs credentials and a network rule, so later.

### 4.5 Multi-device

- Options: (A) the same web UI as a PWA, reached from the phone over a private network (WireGuard or a mesh VPN), no public port; (B) a chat-app bot (Telegram, Zalo) as a bridge; (C) an own cloud relay.
- **Recommendation: A.** One UI code base, nothing of the conversation leaves the owner's devices, and the passkey of #199 fits a browser. B sends every message through a third party (an external send on each turn, so T3 by the current rules) and C is a service to run. A needs the REST adapter to accept a non-loopback bind on the VPN interface only, which changes the invariant "no network beyond loopback": own ADR and `/security-review` **[needs Hùng]**.
- Notifications to the phone when the UI is closed: start with a content-free ping through a channel the owner already approved (for example an email "Lan: 1 việc chờ duyệt", no details), decided as an `[approval.destinations]` entry. Web Push is a later option; it involves the browser vendor's push service.
- Identity: the `principal` field (#192) is already there; add `device` to audit lines when the phone arrives.

### 4.6 Security plugin (S4) and IoT

- S4 stays as planned in the Roadmap (Phase 3): read-only Windows Security signals, and on an incident an encrypted, versioned snapshot pushed to the owner's cloud folder with the key kept off the machine. It builds on #196 snapshots and on the sync-folder approach of Blueprint §15.7 (no cloud drive API). Assistant-specific addition: on an incident Lan drops to **safe mode** (conversation loop offers T0 tools only, flows above T0 pause, cloud routes off) until the owner clears it at a TTY with TOTP.
- IoT (`home`): do not speak device protocols in-house. Bridge to one hub through its public local API (Home Assistant is the obvious candidate, used unmodified as an Internal component per ADR-021 (4)), with every device action declared as an operation with a tier: reading a sensor T0, lights T1, locks, doors, heating and anything that can harm T3. Decide only when the hardware exists.

## 5. Phase placement

"P2" = already in Roadmap Phase 2 (no change). "P3" = Roadmap Phase 3. "After" = after Phase 3, as #157 says.

| Part | Phase | Note |
| --- | --- | --- |
| ModelClient v1, `llm` plugin | P2 (done, #189) | |
| Data classes, TOTP (ADR-025) | P2 (#197) | rule 4 builds on it |
| Flows, EventBus, jobs as flows | P2 (done) | carrier for proactivity |
| `email`, `file`, `organizer`, `ocr` | P2 | Lan's first real hands |
| Backup snapshots S2, doctor S3 | P2 (#196, #198) | |
| REST + web UI v1 read-only, channel `chat` | P2 (#194) | L1 |
| `principal` in audit, proposals, grants | P2 (#192) | multi-device later adds `device` |
| ModelClient v2: streaming, tool calling | P3 (with chat that acts) | implied by `chat-ui.md`; not needed for read-only v1 if answers are not streamed |
| Conversation loop with tool calls, flow drafts, persona tool allow-list | P3 | L2 |
| Approvals from the UI with passkey | P3 (#199) | precondition for L2 being pleasant |
| Provenance flag (`tainted`) and class label on tool results | P3, before L2 and before any cloud route | same mechanism as `model-client.md` §4 point 5 |
| Security S4 + assistant safe mode | P3 | L8 |
| `notify` inbox | P3 or After | small; needed by L5 |
| Plugin `memory` | After | L3 |
| Plugin `voice` (push-to-talk) | After | L4 |
| `briefing`, `calendar` | After | L5 |
| PWA on phone over private network | After | L6; ADR on non-loopback bind |
| Wake word, always-on listener | After, optional | ADR on a background process |
| `home` (IoT) | Future | hardware-dependent |

**Reservations for Phase 2 specs (no new work, only "do not close the door"):**

1. Channel `chat` is defined once and voice reuses it; do not create per-surface channels.
2. The class label on step outputs and `knowledge` content (already a condition in `model-client.md`) should be designed as a general label on tool results, so the `tainted` flag can join it later without a second mechanism.
3. The UI's approvals view shows proposals only; no approve button reachable by the model's output (already in `chat-ui.md` §4). Keep it that way when #199 adds approval from the UI.

**Roadmap wording [needs Hùng]:** Phase 3 today is "Productization" (registry, marketplace, sync, Team Edition) and Blueprint §15.1 moves commercial topics to Phase 3 discussion. L2 (Lan acts) serves the owner's own use directly and is the base for every later level, so it competes with marketplace work for Phase 3 time. This belongs in the Phase 3 planning thread; this file only flags it.

## 6. Solution choices

Order per ADR-021: build in-house, then derive from permissive code, then adopt. "Verify" = licence and facts must be checked against the exact version before a License Register row is written; nothing below is approved by this file.

| Need | Options | Recommendation | Why |
| --- | --- | --- | --- |
| Conversation loop, planning | in-house on ModelClient; agent framework | **In-house** | ADR-024; the gate integration is the hard part and no framework provides it |
| Local chat model for Lan | models already on pc-01 through the loopback runtime; a model chosen by a Vietnamese tool-calling bench | **Bench first**: 20–30 Vietnamese requests with tool calls, scored like the Working bench; rows in the model licence matrix | tool-calling accuracy in Vietnamese on 16 GB is the real unknown; it decides how much L2 can do locally |
| Speech-to-text | (a) whisper.cpp as an external program (MIT, verify), multilingual Whisper weights (MIT, verify) or a Vietnamese fine-tune such as PhoWhisper (licence verify); (b) faster-whisper as a Python dependency (MIT, verify; pulls CTranslate2); (c) sherpa-onnx (Apache-2.0, verify) with a Vietnamese model; (d) Windows built-in recognition (Vietnamese offline support: verify, believed missing) | **(a)**, compare (c) in the spike | external program on the Tesseract pattern, no Python dependency, no own engine; Vietnamese accuracy of the weights must be measured on the owner's own voice |
| Text-to-speech | (a) Windows built-in voices through WinRT/SAPI (Vietnamese voice "An": verify it is installable offline on pc-01); (b) Piper (the original MIT repo is archived, its successor is GPL-3.0 and both use an espeak-ng phonemiser under GPL-3.0: verify; **avoid** unless used strictly as a separate program after a licence decision); (c) sherpa-onnx TTS with a Vietnamese voice (verify model licence); (d) newer neural Vietnamese voices (several have non-commercial weights: verify each) | **(a) first**, (c) as the quality upgrade | zero dependency and zero model licence risk; quality is plain but understandable; swap later behind `voice.speak` |
| Voice activity detection | energy threshold in-house; Silero VAD (MIT, verify) | **In-house threshold** for push-to-talk | with push-to-talk the button already marks start and end |
| Wake word (later) | openWakeWord (code Apache-2.0, pretrained models non-commercial: verify); Porcupine (proprietary); sherpa-onnx keyword spotting (Apache-2.0, verify) | decide when the stage comes | model licences are the trap here |
| Personal memory | own SQLite table + FTS5 + existing embedder; third-party memory layers | **In-house** | one table; reuse `knowledge` functions |
| Calendar | `.ics` reader on stdlib; Outlook COM (pywin32, already registered); CalDAV | **`.ics` first** | no network, no secret |
| Notifications | own inbox table + UI badge; Windows toast (WinRT, verify how to call without a new dependency); phone ping by approved destination | **Inbox first**, toast second | inbox is needed anyway |
| Phone access | PWA + WireGuard (verify licences of the Windows client) or a mesh VPN service (third-party coordination server); chat-app bot | **PWA + private network** | no third party sees content |
| Approval from phone | TOTP (P2), WebAuthn passkey (#199) | as planned | |
| IoT | bridge to a hub's local API; own protocol code | **Bridge** | protocols are a maintenance sink for one person |
| Incident retreat | own snapshot + encryption with stdlib-available primitives or a vetted library (verify: Python stdlib has no authenticated cipher; this likely needs `cryptography`, Apache-2.0/BSD, verify, or Windows CNG through `ctypes`) | decide in the S4 spec | the cipher must not be home-made |

Dependency count if the recommendations hold: **zero new Python runtime dependencies** for L2–L5; two external programs (speech-to-text binary and its weights) plus Windows components. The cipher for S4 is the one place where adopting a library is probably right.

## 7. Risks

| Risk | Why it matters | Control |
| --- | --- | --- |
| Prompt injection through email, documents, web | an assistant with tools turns text into actions | rules 1–3; T3 always a fresh human decision in a tainted context; tool allow-list per persona |
| Approval fatigue | too many proposals and the owner clicks through | data classes (ADR-025), flow drafts instead of many single calls, weekly memory review instead of per-fact clicks |
| Local model too weak for tool calling in Vietnamese | L2 feels unreliable | bench before building; flow drafts are checked by `check_flow`; cloud route for non-sensitive reasoning if the owner opens it |
| GPU contention on one card | voice stalls behind reindex or a shadow run | GPU lock, small chat model for voice turns, speech models on CPU |
| Always-on microphone | privacy of everyone in the room | push-to-talk first; wake word only by ADR |
| Personal memory is a high-value target | one file describes the owner | class `private` minimum, never cloud, covered by backup encryption in S4, `forget` |
| Scope growth for one maintainer | eight levels, one person | each level is one or two plugins, usable alone, started only when the previous one is in daily use; no level starts before Phase 2 exit |
| Voice model licences | several good Vietnamese voices are non-commercial | Windows voice first; licence matrix row per model before use |

## 8. Decisions for Hùng (none blocks Phase 2)

1. **Principle:** accept rules 1–8 of section 3.2 as the frame for all Lan work (they become invariants in `ARCHITECTURE.md` when the first code lands)?
2. **Voice mode:** push-to-talk first, wake word later by its own ADR (recommended), or wake word from the start?
3. **Memory write policy:** automatic for `normal` and below with a weekly review, click for `private` and above (recommended), or a click for every fact?
4. **Lan's brain:** local model by default, cloud only by a named route for non-sensitive contexts (recommended, follows today's invariant), or local only?
5. **Phase 3 content:** should "Lan acts" (L2: conversation loop with tools, approvals from the UI) enter Phase 3 next to productization? To settle in the Phase 3 planning thread.

## 9. Follow-up work this sketch suggests (not scheduled)

- Spike S-voice (pc-01, about half a day, GPU night slot not needed): Windows Vietnamese voice offline, one speech-to-text program with two weight sets on 20 sentences of the owner's voice, end-to-end latency. Output: numbers for section 4.3 and License Register rows.
- Bench B-tools: Vietnamese tool-calling set for local chat models (reuses the bench harness).
- ADR drafts when their stage starts: conversation channel and provenance flag (L2); non-loopback bind for the phone (L6); background listener (wake word); personal memory rules (L3).
- Sub-issues of #157 are opened one at a time when a level is picked up (epic rule), not now.

## 10. Not covered

Phase 3 plan and productization (separate thread), ecosystem projects after lfmap (separate thread), threat model of Flows and ModelClient (separate thread), prices, branding and trademark (parked until Phase 2 ends).
