# Architecture review before Phase 2b: is the core solid enough to carry what comes next?

- Date: 2026-11-08. Role: Architect / Reviewer. Requested by Hùng (project thread "Rà soát kiến trúc lfmap trước Phase 2").
- Revision 2 (same day). Hùng set the frame: LFMAP serves **his own needs first**; commercialisation is unlikely in the near term; this phase deliberately invests most resources in a **solid core**, because a feature shell on a weak core collapses or costs far more to maintain later (his ERP experience). Revision 1 judged by sellability; this revision judges by core strength and keeps commercial points only where they cost nothing now.
- Question: will the core carry Phase 2–3 and the JARVIS epic (#157) without rework, and is effort going to the core or to things that are neither core nor use?
- Accepted core values stay: local-first, Core + Adapters, solo-maintainable, fewest dependencies, Windows-first, licence rules. No ADR is changed by this file; anything that touches an ADR, the Blueprint or the Roadmap is marked **[needs Hùng]**.
- Sources: `/mnt/project-files/lfmap-docs/` 01–06 (priority 03 ADR > 02 > 01 > 05 > 04 > 06), ADR-022 amendment draft and A3 result (2026-11-07), `ARCHITECTURE.md`, `docs/specs/` (chat-ui, rest, flows), `docs/research/2026-11-06-flows-fl4-smoke.md`, open issues, the last 50 commits on `main` (0ce5f2e).

## 1. Verdict

The core-first strategy is right, and what exists is well built: one Tool class with generated adapters, one approval gate shared by CLI, MCP, jobs, events and flows, embedded storage with no service, licence and provenance gates in CI, about 1,000 tests. The gaps are not "too few features" but **core pieces that are still missing or not yet proven under load**:

1. Model access (local/cloud LLM calls) is not a core capability yet, although almost everything in Phase 2–3 and JARVIS depends on it.
2. EventBus and Flows have only been exercised with the `echo` plugin; no real workload has tested them.
3. Three overlapping automation mechanisms (jobs, events, flows) are about to get plugins built on all three.
4. The Plugin Contract, the core's public interface, is behind the code.

Fixing these is core work, in line with Hùng's strategy, and cheaper now than after `email`, `ocr`, `organizer` and the UI are built on top.

## 2. Keep as is (no action)

| Area | Why it is a sound core choice |
| --- | --- |
| Core + generated adapters (ADR-001/002/014) | One plugin gets SDK, CLI and MCP; the main reason one person can maintain many plugins. |
| Tiers T0–T3, grants with expiry, audit, approvals queue (ADR-016/017/018/020/023) | One gate for every channel; new channels (`flow`, later `chat`) reuse it. |
| Embedded storage SQLite + LanceDB (ADR-013) | Zero services; VectorStore interface leaves Team Edition open. |
| No agent framework (ADR-024), in-house EventBus behind a Protocol (ADR-021/006) | Measured, reversible; NATS can replace the SQLite bus without touching plugins. |
| Licence gate, SBOM, provenance | Keeps the door to later commercial use open at no extra cost. |

## 3. Findings

Severity: **H** = core gap that later plugins would build around (rework risk); **M** = should be settled during Phase 2; **L** = note.

### C1 (H). Model access is not a core capability

- Evidence: the only model call in product code is embeddings (`lfmap_knowledge/embed.py`). Phase 2 exit needs "summarise"; the chat spec (`docs/specs/chat-ui.md` §2) plans its own model loop in `lfmap-core/chat.py`; RT-08 (#167) plans an OpenAI-compatible client for the embedder; the Agent Router (Roadmap Phase 2, Blueprint §4.4) has no spec. Three clients are heading in three directions, and the local/cloud decision is a **security boundary** (egress, `cloud_ai`, `[approval.destinations]`, T3), like the Permission Manager.
- Options:
  - A. A `ModelClient` Protocol in `lfmap-core` (like `EventBus`): one OpenAI-compatible implementation (stdlib `urllib`, loopback by default), routing policy from `config.toml` (Blueprint §4.4 table as data), every cloud call through the gate and `egress_log`. Reached by plugins through `ctx`, so tiers and audit apply per call. A thin `llm` plugin (`summarise`, `extract`, `classify`) exposes it to Flows, CLI and MCP. The Agent Router is this policy, not a separate module.
  - B. Only an `llm` plugin with its own client; other plugins call it through the SDK (`context_for`).
  - C. Leave it to each plugin.
- **Recommendation: A.** It is the same pattern as EventBus and the Permission Manager, keeps one place for the egress rule, and prevents three divergent clients. Roadmap wording for "Agent Router" changes **[needs Hùng]**; no ADR conflict (fits ADR-018 (4), ADR-024).

### C2 (H). EventBus and Flows are proven only with `echo`

- Evidence: EB-4 and FL-4 smokes used `echo` with `[adapters] events = true` set only for the run and reverted (`2026-11-06-flows-fl4-smoke.md` line 12). No shipped plugin has `events = true`. Issue #178 (one subscription per flow) was found only by design review, not by use.
- Why it matters for a solid core: a core is proven by the workloads it carries. In ERP terms, the core is designed and accepted against reference processes; without them, defects show up only when the first real plugin lands, and by then several plugins depend on the defect.
- Options: A. Continue plugin by plugin and fix the core as problems appear. B. Pick 2–3 **reference workflows** from Hùng's own needs (RT-07 #166 is the inventory of his n8n flows) and make them core acceptance tests: real plugins (`markitdown`, `knowledge`, later `llm`), real `flows.toml`, run on DIEP-ANH, kept as a regression suite. C. A synthetic load test only (many events, fake plugins).
- **Recommendation: B, with C as a cheap add-on.** It loads the core with Hùng's real use, not features for sale. No ADR conflict.

### C3 (M). Three overlapping automation mechanisms

- Evidence: `jobs.toml` jobs (`via = "call"` or `"event"`), EventBus subscriptions with `[events] max_tier`, and `flows.toml` flows (manual, schedule, event) each have their own ceiling, proposal path and CLI. A scheduled one-step flow and a job do the same thing through different code.
- Risk: every new plugin and the UI must support all three; bugs get fixed three times.
- Options: A. Keep all three. B. Make **Flow the single orchestration concept**: a job becomes a one-step scheduled flow inside the core (one runner, one proposal type), `jobs.toml` stays readable and is translated on load; EventBus stays the transport underneath. C. Merge only in docs and UI.
- **Recommendation: B, planned now and done before `email`.** Reversible behind the existing CLI; ADR-018 keeps its mechanism (Task Scheduler + approvals queue), but its wording "a job is one CLI command" changes **[needs Hùng]**.

### C4 (M). The Plugin Contract is behind the code

- Evidence: `02_Plugin_Contract.md` is v0.1.1 with a change note of 2026-10-22 (ADR-020). It does not describe `ctx.events` and its publishing rules, the `event` and `flow` channels, idempotent handlers, `data_dir` rules beyond ADR-016, or how flows reference operation outputs. `min_core_version` is enforced (`versions.py`), but nothing tests that a plugin built against an older contract still loads.
- Options: A. Update the contract when the next plugin needs it. B. Contract v0.2 now, plus a compatibility test: a frozen "old" plugin fixture that must keep loading and running across core changes. C. Generate the contract text from code.
- **Recommendation: B.** The contract is the core's public API; for a long-lived core it must lead the code, not follow it. No ADR conflict.

### C5 (M). Effort on the AI dev pipeline is neither core nor use

- Evidence: of the last 50 commits (2026-10-24 to 2026-11-07), changed-file counts are about 880 under `spikes/` (framework spike, Leading bench), 122 in `lfmap-core`. The framework spike paid off (it settled ADR-024). Leading speed research continues (#181 plan B, #183) after the A3 result "lose", and #184 moves Leading to Sonnet.
- Assessment: the local Leading/Working agents are tools for building LFMAP, not part of its core. Further speed work has no core payoff in Phase 2, and A3 shows the misses are capability misses, not speed.
- Options: A. Continue as now. B. Cap dev-pipeline work at about 20 % of the weekly budget; park plan B and #183 until a named trigger; keep cheap shadow runs in GPU night slots. C. Stop until Phase 3.
- **Recommendation: B.** Matches Hùng's 2026-11-06 rule (no own inference engine until LFMAP is complete). No ADR conflict.

### C6 (M). Retrieval quality has no regression gate

- Evidence: `packages/lfmap-knowledge/bench/iso-vi` has 9 questions over 30 synthetic Vietnamese documents, run by hand; CI checks no retrieval quality. Any change to chunking, folding, fusion or the embedder can silently lower answer quality.
- **Recommendation:** grow it to about 50 questions (Vietnamese and English, a scanned PDF included) and run it weekly on DIEP-ANH in a GPU night slot, tracking recall and precision in a CSV; a drop fails the week. No ADR conflict.

### C7 (M). UI stack weight for one maintainer

- Evidence: `chat-ui.md`: Tauri 2 (Rust) + React/TypeScript/Vite (npm) + Python sidecar + REST (FastAPI). v1 is read-only (decision 2026-11-06).
- Options: A. Tauri as specified. B. **Web-first, shell later:** the same React UI as static files served by `lfmap serve rest` on loopback and opened in the browser or WebView2; Tauri wraps the same build later. C. No own UI in Phase 2 (Claude Desktop over MCP).
- **Recommendation: B.** Same UI code, one fewer toolchain (Rust) to maintain until the core is settled. Changes the order in Blueprint §10 / Roadmap Phase 2 **[needs Hùng]**; the token-to-page design needs `/security-review` before code.

### C8 (L). Two code bases for document conversion

MarkitdownTool (standalone, GUI, Office COM under ADR-011) and `plugins/lfmap-markitdown` solve the same problem, so fixes are made twice. Recommendation: keep MarkitdownTool at 2.x for bug fixes; let `lfmap-markitdown` be where conversion grows. MarkitdownTool is MIT, so its code may move into lfmap (Apache-2.0) with its notice.

### C9 (L). Kept open for later commercial use, no work now

From revision 1, deferred by Hùng's frame: install path for non-developers (embedded-Python installer), approvals outside a terminal (Phase 3 with the security core), a defined buyer and vertical product (ADR-019 unchanged). The current choices (Apache-2.0, licence gate, SBOM, Protocol boundaries, versioned installs possible as ADR-023 runtime root) keep these open at no cost.

### C10 (L). Hygiene

Issues #161, #162, #163, #165 look done (PRs #169, #171, #172) but are open; #156 is a past plan. The README still says "Phase 0". Close or update at the next triage.

## 4. Proposed Phase 2b order (core first)

| # | Work | Env | Why in this place |
| --- | --- | --- | --- |
| 1 | Plugin Contract v0.2 + compatibility fixture (C4) | Cloud | Fixes the public API before more plugins |
| 2 | Jobs folded into Flows, one runner (C3) | Cloud + DIEP-ANH smoke | Fewer code paths before new plugins |
| 3 | `ModelClient` in core + thin `llm` plugin (C1) | Cloud, `/security-review` | Core capability every later item needs |
| 4 | Reference workflows from RT-07 (#166) as core acceptance suite (C2) | DIEP-ANH | First real load on EventBus/Flows |
| 5 | `email` (IMAP first), then `ocr` / `file` / `organizer` as the workflows need | Cloud + DIEP-ANH | Built on a settled core |
| 6 | Retrieval regression bench weekly (C6) | DIEP-ANH, night slot | Guards knowledge quality |
| 7 | REST + UI v1 read-only (C7) | Cloud | After the core shape is stable |

This keeps all Roadmap Phase 2 content and changes only the order.

## 5. Decisions for Hùng

1. C1: model access as a core Protocol (`ModelClient`) with a thin `llm` plugin, Agent Router = its routing policy (Roadmap wording)?
2. C2: use 2–3 of your own workflows (from the n8n inventory, #166) as the core acceptance suite?
3. C3: fold jobs into Flows as one orchestration concept (ADR-018 wording)?
4. C5: cap dev-pipeline work at about 20 % of the weekly budget and park Leading speed plan B and #183?
5. C7 (can wait until item 7): web-first UI, Tauri later as a shell?

C4, C6, C8, C10 are reversible core or hygiene work and can be scheduled without a decision.

## 6. Not covered

Code-level security review (per PR with `/security-review`), Phase 3 marketplace and Team Edition, pricing.
