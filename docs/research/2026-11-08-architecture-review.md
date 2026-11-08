# Architecture review before Phase 2b: commercial value lens

- Date: 2026-11-08. Role: Architect / Reviewer. Requested by Hùng (project thread "Rà soát kiến trúc lfmap trước Phase 2").
- Question: are the chosen technical solutions sound for a product that **delivers value to a user and can be sold**, not only one that runs? This is not a re-litigation of the ADRs. Accepted core values stay: local-first, Core + Adapters, solo-maintainable, fewest dependencies, Windows-first, licence rules.
- Sources read: `/mnt/project-files/lfmap-docs/` 01–06 (priority 03 ADR > 02 > 01 > 05 > 04 > 06), the ADR-022 amendment draft and A3 result (2026-11-07), `ARCHITECTURE.md`, `README.md`, `docs/specs/` (chat-ui, rest, flows), open issues, the last 50 commits on `main` (0ce5f2e).
- Every proposal that touches an Accepted ADR, the Blueprint or the Roadmap is marked **[needs Hùng]**. Nothing in this file changes an ADR.

## 1. Verdict in one paragraph

The **core is sound and better engineered than most products of its size**: one Tool class with generated adapters, a tier-based approval gate that is consistent across CLI, MCP, jobs, events and flows, embedded storage with no background service, and a licence gate in CI. None of that should change. The risk is elsewhere: since Phase 1 closed, almost all effort went into **platform plumbing and into the AI development pipeline**, while the product still has **no capability a user would pay for beyond Phase 1** (convert + search). Phase 2 as written needs an LLM step that does not exist in the product, a UI stack that is the heaviest piece of the whole plan, and an install story that does not exist yet. The recommendations below re-sequence Phase 2 around one end-to-end user workflow, add the one missing capability (a small `llm` plugin), and stop or cap work that does not move a user outcome.

## 2. Keep as is (no action)

| Area | Why it holds up commercially |
| --- | --- |
| Core + generated adapters (ADR-001/002/014) | One plugin gets SDK, CLI and MCP for free; this is the main reason a solo maintainer can ship several products. |
| Tiers T0–T3, grants with expiry, audit, approvals queue (ADR-016/017/018/020) | Matches what buyers of "AI on my documents" ask first: what can it do without me, and is it logged. Strong selling point. |
| Embedded storage SQLite + LanceDB (ADR-013) | Zero services to install; the right default for a desktop product. |
| No agent framework (ADR-024), in-house EventBus (ADR-021/006) | Measured, cheap, reversible behind a Protocol. Done; do not reopen. |
| Licence gate, SBOM, provenance | Lowers due-diligence cost for any future buyer or partner. |
| MCP first (ADR-003) | Claude Desktop/Code is today the cheapest usable front end; it already proves Phase 1 value. |

## 3. Findings

Severity: **H** = would cause waste or block a sellable product if not handled in Phase 2; **M** = should be decided in Phase 2; **L** = note.

### F1 (H). The Phase 2 exit workflow needs a capability the product does not have

- Evidence: Roadmap Phase 2 exit: "email with attachment → convert → ingest → **summarise** → wait for approval". The product plugins are `echo`, `markitdown`, `powershell`, `knowledge`; the only model call in product code is embeddings (`lfmap_knowledge/embed.py`). Flows can only call operations. No plugin generates text. `email` (Phase 2) does not exist yet either. The chat spec (`docs/specs/chat-ui.md` §2) plans its own model loop in `lfmap-core/chat.py`, and RT-08 (#167) plans an OpenAI-compatible client for the embedder: three places are heading towards three model clients.
- Risk: Flows and EventBus are finished but have nothing valuable to orchestrate; the Agent Router (Roadmap Phase 2) has nothing to route.
- Options:
  - A. A small plugin `llm` (one OpenAI-compatible client, stdlib `urllib`, loopback by default): operations `summarise`, `extract` (JSON by schema), `classify`; `cloud_ai` and `[approval.destinations]` decide whether a cloud endpoint is allowed (T3 otherwise). Chat (`chat.py`) and the embedder reuse its client. The "Agent Router" becomes the endpoint choice inside this plugin (Blueprint §4.4 table as config), not a separate module.
  - B. Put the client in `lfmap-core` and let plugins call it through `ctx` (no plugin, but a model dependency in core and no tier per call).
  - C. Keep the summarise step outside the product (Claude via MCP). Cheapest, but then the exit workflow is not a product feature.
- **Recommendation: A.** It follows Core + Adapters, gives tiers and audit per call for free, and is about one small plugin. No ADR conflict; the Roadmap line "Agent Router" would be re-worded **[needs Hùng]**.

### F2 (H). Effort since Phase 1 went mostly to plumbing and the dev pipeline, not to user outcomes

- Evidence: in the last 50 commits on `main` (2026-10-24 to 2026-11-07), changed-file counts are about 880 under `spikes/` (framework spike and Leading bench), 103 under `docs/handoff`, 122 in `lfmap-core`, 70 in `lfmap-knowledge`, 44 in `markitdown`. No new user-facing plugin since Phase 1. Open work still includes speed research for local Leading (#181 plan B, #183) after the A3 result "lose" and the ADR-022 amendment (Sonnet as Leading, #184).
- Assessment: the local Leading/Working agents are a tool to **build** LFMAP, not part of what a user buys. The framework spike was worth it (it removed a dependency for good). Further Leading speed work (capy-flash on WSL2, MoE streaming) has no product payoff in Phase 2, and A3 shows the misses are capability misses, not speed.
- Options: A. Continue both tracks as now. B. Cap dev-pipeline work at about 20 % of the weekly budget, park plan B and #183 until a named trigger, keep only the cheap shadow runs in GPU night slots. C. Stop all local Leading work until Phase 3.
- **Recommendation: B.** No ADR conflict (ADR-022 is Proposed, #184 already moves Leading to Sonnet). Hùng's 2026-11-06 rule "no own inference engine until LFMAP is complete" points the same way.

### F3 (H). No defined user and job-to-be-done; the sellable assets are the vertical tools

- Evidence: Blueprint §1 targets "solopreneur / vibe-coder" and "every plugin is a product", but no document names a buyer, a price point or the first paid workflow. The three things that already create value are MarkitdownTool (released 2.4.0 with installer and GUI), Phase 1 "ask my documents with citations", and isomp (ISO 9001/14001/45001 records, a real niche with paying organisations). ADR-019 keeps isomp as a case-study "outside the scope and exit criteria of every phase".
- Risk: a horizontal automation platform is the hardest thing for one person to sell (it competes with n8n, Zapier, Power Automate and Copilot). A vertical product on top of LFMAP is much easier to explain and price.
- Options:
  - A. Platform first (current): finish Phase 2/3 as written, find users later.
  - B. Vertical first: LFMAP stays the engine; the Phase 2 exit workflow is chosen from a vertical (for example "ISO records inbox": email with attachment → convert → ingest → summarise/classify against the ISO record list → proposal to file it, using ghost data). isomp becomes the first commercial pilot through `lfmap-isomp`.
  - C. Two-track: keep the generic exit workflow, and add a short product note (persona, top 3 workflows, what is free and what is paid) before Tauri work starts.
- **Recommendation: B, or C if Hùng prefers to keep isomp separate for now.** B amends **ADR-019 (1)** ("case-study only, outside every phase") **[needs Hùng]**. The data rule of ADR-019 (5) (ghost data only over MCP) stays.

### F4 (H). There is no install path for anyone but the developer

- Evidence: the README still says "Status: Phase 0" and starts with `uv sync` in a git checkout; `Invoke-LfmapJob.ps1` needs `uv.exe` and a repo path; ADR-023's runtime root is a git clone fast-forwarded hourly; the chat spec §10 (2) leaves Python sidecar packaging open ("PyInstaller was rejected for lfmap-core so far"). MarkitdownTool already has a working NSIS + PyInstaller pipeline.
- Risk: packaging decides the UI stack, the update model and the runtime-root rule; leaving it to CU-2 means Tauri work starts on an unknown base.
- Options: A. Installer that ships an embedded Python + pinned wheel set into a versioned folder (`%LOCALAPPDATA%\Programs\LFMAP\<version>`), which also serves as the "runtime root" of ADR-023 on a customer machine. B. PyInstaller onedir sidecar (proven in MarkitdownTool, slower start, harder plugin install). C. Developer-only until Phase 3.
- **Recommendation: A, as a short spike before CU-2** (one day, Cloud + one Windows run). No ADR conflict; ADR-023 needs only a note that a customer's runtime root is the installed version folder.

### F5 (M). The UI stack is the heaviest item in the plan

- Evidence: `chat-ui.md`: Tauri 2 (Rust toolchain) + React + TypeScript + Vite + npm supply chain + Python sidecar + REST (FastAPI, a new dependency). Approvals in the UI are deferred to Phase 3 (decision 2026-11-06), so v1 is read-only.
- Assessment: the decision is defensible for a desktop product, but it adds two languages and two package ecosystems for one maintainer before there is a workflow to show.
- Options: A. Tauri as specified (CU-1..CU-4). B. **Web-first, shell later**: the same React UI built as static files served by `lfmap serve rest` on loopback and opened in the default browser or WebView2; Tauri wraps the same build later only as a shell and installer. Keeps the REST rules (token, Host/Origin checks); the token is delivered to the page by a one-time loopback launch URL and an HttpOnly, SameSite=Strict cookie. C. No own UI in Phase 2: Claude Desktop over MCP plus a generated read-only HTML status page.
- **Recommendation: B.** Same code for the UI, Rust/Tauri postponed until packaging (F4) is settled. It changes the order of Blueprint §10 / Roadmap Phase 2 ("Tauri Workspace"), not an ADR **[needs Hùng]**. Needs `/security-review` on the cookie/launch-URL design before code.

### F6 (M). Too many automation concepts for a user

- Evidence: a user meets job, flow, event, subscription, proposal, grant, tier, channel, `max_tier` in two files (`jobs.toml`, `flows.toml`) and `[events] max_tier` in a third (`config.toml`). Jobs with `via = "event"` and flows with schedule triggers overlap.
- Options: A. Keep all. B. Present one user concept, **Flow** (a job is a one-step scheduled flow), in docs and UI now; keep `jobs.toml` working, decide in Phase 3 whether to fold it into `flows.toml`. C. Merge the files now.
- **Recommendation: B.** Documentation and UI only, reversible, no ADR change (ADR-018 stays the mechanism).

### F7 (M). Answer quality is the product, but it is not measured continuously

- Evidence: `packages/lfmap-knowledge/bench/iso-vi` has 9 questions over 30 synthetic Vietnamese ISO documents, run by hand. CI runs no retrieval-quality check.
- Options: A. Keep manual. B. Grow the bench to about 50 questions (Vietnamese and English, scanned PDF included) and run it weekly on DIEP-ANH (needs Ollama) with recall and precision tracked in a CSV; fail the week when recall drops. C. Add a cloud judge (costs quota).
- **Recommendation: B.** This is the number to put in front of a buyer. No ADR conflict.

### F8 (M). Two code bases for document conversion

- Evidence: MarkitdownTool (standalone, MIT, GUI, Office COM under ADR-011) and `plugins/lfmap-markitdown` (ported text-quality checks, OCR, Docling) solve the same problem; fixes must be made twice.
- Options: A. Keep both independent. B. Make `lfmap-markitdown` the conversion library and MarkitdownTool its GUI/installer shell over time (MarkitdownTool's Office-COM path stays GUI-only). C. Freeze MarkitdownTool at 2.x, bug fixes only.
- **Recommendation: C now, B when F4 lands** (the installer work is shared). MarkitdownTool is MIT and lfmap is Apache-2.0, so code may move into lfmap; moving lfmap code into MarkitdownTool needs the Apache notice. No ADR conflict.

### F9 (L). Approval only at a terminal will not work for a non-developer buyer

- Evidence: ADR-017/018/023: approve, grant and add-folder need a real console and a typed code; UI approvals are Phase 3 (decision 2026-11-06). ADR-023's separate Windows account protects the developer machine from coding agents; it is not a customer requirement.
- Recommendation: keep for Phase 2 (the owner is the only user). Add to the Phase 3 entry criteria: "a non-developer can approve a proposal safely" (OS-level confirmation from the shell, per chat-ui.md §6 B), and state in docs that the agent account is a development-machine rule, not a product requirement. No ADR change now.

### F10 (L). Project hygiene that costs tokens

- Several issues look finished but are open (#161, #162, #163, #165 match PRs #169, #171, #172); #156 is a past plan. The README is two phases out of date. The handoff + spec + frozen tests + cards chain is right for qwen/AG cards but heavy for small Claude tasks.
- Recommendation: close or update those issues at the next triage, refresh the README as the product page (it is what a user reads first), and allow a one-paragraph handoff for Claude-only tasks under about 100 lines.

## 4. Proposed Phase 2b order

| # | Work | Env | Why first |
| --- | --- | --- | --- |
| 1 | Product note: persona, top 3 workflows, free/paid line; pick the exit workflow (F3) | Cloud, Hùng decides | Everything below is sized by it |
| 2 | `llm` plugin (F1), shared model client | Cloud | Unblocks summarise, chat and the router |
| 3 | `email` plugin, IMAP first (Hùng 2026-10-24 Q2), read-only + attachments to a declared root | Cloud + DIEP-ANH smoke | Exit workflow input |
| 4 | Exit workflow as one `flows.toml`, end to end on ghost data | DIEP-ANH | Phase 2 exit criterion |
| 5 | Packaging spike (F4) | Cloud + DIEP-ANH | Decides the UI shell |
| 6 | REST + web-first UI v1 read-only (F5) | Cloud | Something to demo |
| 7 | Retrieval bench weekly (F7) | DIEP-ANH, GPU night slot | Quality number |

`ocr` (PaddleOCR), `file`, `organizer` and entities follow after item 4, in the order the chosen workflow needs them. This keeps Roadmap Phase 2 content, changes only its order, and removes nothing.

## 5. Decisions for Hùng

1. F3: Phase 2 exit workflow from a vertical (isomp pilot, amends ADR-019 (1)), or generic plus a product note?
2. F1: accept a small `llm` plugin and treat the Agent Router as its endpoint choice (Roadmap wording change)?
3. F5: web-first UI served by the REST adapter, Tauri later as shell (Roadmap/Blueprint order change)?
4. F2: cap dev-pipeline work at about 20 % of the weekly budget and park Leading speed plan B and #183?
5. F4: packaging spike (embedded Python installer) before any UI code?

F6–F10 are reversible and can be done without a decision; they go to the backlog as issues after Hùng reads this.

## 6. Not covered

Security review of the code (done per PR with `/security-review`), pricing and market research (needs Hùng's input on target buyers), Phase 3 marketplace and Team Edition.
