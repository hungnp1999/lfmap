# Phase 3 outline: items, entry criteria, dependencies on Phase 2, cost and risk

- Date: 2026-11-14. Role: Planner / Architect. Issue #262 (item K7 of the 11/11 report).
- Question: what is in Phase 3, what must be true before each item starts, what does each item need from Phase 2, what does it cost and risk, and what leaves Phase 2 if Phase 2 grows.
- Outline only. No code, no ADR, no Roadmap line and no owner decision is changed by this file. The Roadmap lives outside the repo; proposed changes are listed in section 8 for the owner. Anything that touches an ADR, the Blueprint or the Roadmap is marked **[needs Hùng]**.
- Sources: `/mnt/project-files/lfmap-docs/` 01, 03, 05 (Blueprint v0.3 §15, ADR-001..026, Roadmap), `ARCHITECTURE.md`, `docs/specs/` (acceptance-scenarios, chat-ui, data-classes), `docs/research/` 2026-11-08 architecture review, 2026-11-10 Lan Hài sketch, 2026-11-13 threat model, 2026-11-15 ModelClient review, open issues on 2026-11-13 (47 open; milestone "Phase 3" holds #157, #183, #199).
- Limits: sizes are relative estimates, not forecasts (S = one card such as DC-2; M = a short series such as MC-1..MC-5; L = a handoff series such as Flows or knowledge K4..K14; XL = a product of its own). No licence, price, legal or vendor-policy fact was checked for this file; each is marked "verify". What other people's machines can run was not measured.

## 1. Verdict

1. **The Roadmap's Phase 3 is two different phases under one title.** "Productization" (registry, marketplace, sync, Team Edition, packaging) serves other people. "Lan acts" (L2, added 2026-11-10), approvals from the UI with a passkey and security S4 serve the owner. The owner's stated frame (2026-11-08: own needs first, commercial use unlikely soon, solid core) points at the second group; the title and four of the five Roadmap lines point at the first.
2. **Phase 3 has no exit criteria and no entry criteria of its own.** Every earlier phase has an exit line. Without one, Phase 3 cannot end, and the Roadmap rule "do not start a phase before the previous one meets its exit criteria" has nothing to check Phase 3 items against.
3. **Three Roadmap items have no user today**: Marketplace, Cloud Sync and Team Edition. Each needs something that does not exist (third-party plugin authors, a second machine with a need, a team and a legal entity). They should wait for a named signal, not for a date.
4. **Several real Phase 3 items are not on the Roadmap list**: class and provenance labels on tool results (DC-6 #237, G10 #317), ModelClient with the `claude -p` endpoint (ADR-026), approvals from the UI and the passkey (#199, `chat-ui.md` §6), security S4 (only in the Phase 2 bullet as a forward note), and scenario S4 "meeting minutes" (deferred from Phase 2 on 2026-11-13).
5. **Phase 2 is already larger than its exit line needs.** The exit line needs one end-to-end workflow; the list holds about fifteen items, and the reviews of 13/11 added 25 issues (#296 to #321). Section 6 names five things that can leave Phase 2 without touching the exit criteria or the three acceptance scenarios.
6. **Recommended shape [needs Hùng]:** Phase 3a "Lan acts" (owner value, hardest security work), Phase 3b "Shareable product" (release, installer, registry, packaging), and a signal-driven list for marketplace, live sync and Team Edition. A thin slice of 3b (first tagged release, installer) comes first because it also closes threat-model gap G2.

Scope warning: sections 4.1 and 4.2 list 17 items. Counted in the units above, 3a alone is about the size of Phases 0 to 2 together. The entry criteria below exist so that each item starts only when its evidence is in, and so that several of them may never start.

## 2. What Phase 3 inherits from Phase 2

State on 2026-11-13, from the Roadmap list and the open issues.

| Phase 2 item | State | Phase 3 use |
| --- | --- | --- |
| EventBus, Flows, jobs into Flows | built; JF-1..JF-5 (#231, #239..#242) open | runner for plans that Lan drafts; carrier for proactivity later |
| `ModelClient`, `llm` | merged (#189); findings #296..#306 open; no real-model smoke yet (#301) | intake and local execution of L2 |
| Data classes, TOTP (ADR-025) | DC-1..DC-4 merged; DC-5 #236, DC-6 #237 open; not yet set up on pc-01 (DC-7 #238) | "the class decides where work runs" (Lan rule 5) |
| Backup S2, doctor S3 | merged (#196, #198) | base of S4 retreat |
| Acceptance scenarios S1, S3 (reduced), S2 (trimmed) | chosen 2026-11-13; S1 flow not built | proof that the core carries real work |
| `web` plugin | WEB-1..WEB-4 merged | first hands with network egress |
| `email`, `file`, `organizer`, `ocr` | not started | Lan's hands; S1 needs `email` and `file` |
| REST adapter + web UI v1 read-only (#194) | spec only | surface for L2 and for approvals |
| `principal` (#192), CLA (#200) | done | precondition for other users |
| Installer spike (#201) | not started | precondition for sharing |
| Threat model gaps G1..G14 (#308..#321) | open; 2 high | several are preconditions below |
| Plugin Contract | v0.2 merged; v0.3 planned with JF-4 (#241) | public API that a registry freezes |
| Releases | none: no tag, `lfmap-core` 0.2.0, `CHANGELOG.md` only `[Unreleased]` | every 3b item needs versions |

## 3. Entry criteria for Phase 3 as a whole (proposed) **[needs Hùng]**

The Phase 2 exit line ("one workflow end to end, hands off except approval") can be met by one good run. Phase 3 builds a model-driven caller and other people's installs on top, so it needs the core to be stable in use, not only demonstrated.

| # | Criterion | Evidence | Why |
| --- | --- | --- | --- |
| E1 | Phase 2 exit met, and S1 has run on its schedule on pc-01 for 14 days with no manual repair | `audit.jsonl`, flow run files | A demo proves the path; two weeks prove retention, interrupted runs and restarts (JF-3) |
| E2 | S3 (reduced) passed with a local model on `private` data | acceptance record | The only Phase 2 test of the class rule plus a local model; without it Lan rule 5 is untested |
| E3 | Threat-model gaps G1 (#308) and G2 (#309) closed; owner checks #322 done | issues closed | Both are ways round the approval boundary; a chat loop multiplies the callers that can reach them |
| E4 | `[data.classes]` holds the owner's real map and TOTP is enrolled (DC-7 #238), in use for 14 days | `lfmap doctor`, audit lines with class | Routing by class is only as good as the map |
| E5 | Plugin Contract at the version that JF-4 produces, with the frozen old-plugin fixture passing | CI | L2 and the registry both generate from manifests |
| E6 | First tagged release of the workspace; `CHANGELOG.md` has a released section | tag, release notes | Versions are the unit of install, update, compatibility and rollback |
| E7 | Phase-end document set `docs/phase2/` and the architecture diagram redrawn against `ARCHITECTURE.md` | merged PR | Standing rule for every phase |
| E8 | Approval counts per week by tier and by channel are available from `audit.jsonl` | a report or `doctor` view | Items A6 and A7 are justified only by measured approval load |

E3, E4 and E8 gate Track A; E5 and E6 gate Track B; E1, E2 and E7 gate both.

## 4. Phase 3 items

Columns: **Entry** = what must be true before the first card; **Needs from Phase 2** = the Phase 2 result it builds on; **Size** as defined above; **Main risk**.

### 4.1 Track A: Lan acts (owner value)

| # | Item | Entry | Needs from Phase 2 | Size | Main risk |
| --- | --- | --- | --- | --- | --- |
| A0 | One label on every tool result: data class (DC-6 #237) and provenance of untrusted content (G10 #317) | DC-5 merged; JF-3 done so step outputs have their final shape | data classes, Flows step outputs, `web` (first untrusted source) | M | Changes the Plugin Contract result shape (`gate:po`); if class and provenance become two mechanisms the cost doubles |
| A1 | ADR set, in this order: (a) channel `chat` and the provenance flag; (b) cloud intake: class of the owner's request text, pre-check patterns, standing destination for the cloud endpoint, daily call cap | #297 decided (one T3 gate or two for a cloud call); #310 decided (T3 asks the owner code) | ADR-025, ADR-026, ModelRouter | S each, `gate:po`, `/security-review` | (b) makes "the request leaves the machine" the default; a wrong pre-check pattern leaks by design |
| A2 | Local-model bench in Vietnamese: extract, summarise, answer over given text, simple tool calls (Lan sketch B-tools), scored like the Working bench | S3 (reduced) result in hand; GPU night slots free | bench harness, `llm`, #301 smoke | S to M, `res:gpu` | Result below threshold: the `private` half of L2 is hollow on 16 GB. That is a finding, not a failure: see stop rule S1 |
| A3 | ModelClient: `claude -p` endpoint (subprocess, all tools off, JSON out, call cap, fail closed) | G9 (#316, minimal environment for child processes) merged; #296, #298, #299, #300 fixed; vendor policy for `claude -p` re-read on that day (ADR-026 revisit clause, verify) | ModelClient, egress log | M, `/security-review` | Shares the Pro quota with development (ADR-026): using Lan slows building Lan; policy can change |
| A4 | L2 step 1, "plan then run": chat request, pre-check, intake returns a flow draft, `check_flow`, class recomputed per step, owner starts it, Flows runs it, T2/T3 pause as today | A0, A1, A3 done; web UI v1 read-only in daily use; A2 result known | Flows, approvals queue, chat UI v1, REST adapter | L | Prompt injection through fetched or mailed text; drafts that pass `check_flow` but do the wrong thing |
| A5 | L2 step 2, direct tool calls in the loop for short requests (ModelClient tool calling and streaming, persona tool allow-list, hard step limit) | A4 used for 2 weeks and the log shows short requests where a flow draft is clumsy; A2 shows the local model can call tools | A4 | M to L | A second execution path beside Flows; local tool calling in Vietnamese unproven |
| A6 | Approvals from the UI (`chat-ui.md` §6 option B) with the phone passkey | #199 spike answered its three unknowns; E8 shows more than a handful of approvals per week; ADR accepted | TOTP in use, approvals queue, REST | M to L, `gate:po` | New human channel. The hard part is not the signature but the screen: what the owner reads must be drawn by core code from the proposal file, never from model output |
| A7 | Plan-level approval: one approval for all resolved T2/T3 steps of a plan (amends "a flow never pre-approves", ADR-017/018) | A4 in daily use for 4 weeks and E8 shows plans that pause three times or more as the normal case | A4, A0 (tainted contexts are excluded) | M, `gate:po` | The largest loosening of the gate proposed so far. Build only on measured fatigue |
| A8 | Security S4: read-only incident signals, encrypted versioned retreat snapshot to the owner's cloud folder, Lan safe mode | Restore drill of #196 passed on pc-01; G5, G6, G7 (#312..#314) merged; cipher chosen with a License Register row (verify); spike shows which Windows Security signals are readable without admin | backup S2, doctor S3 | L, `gate:po` | Home-made crypto; a false alarm is itself an external send; where the key lives; detection quality unknown |
| A9 | Plugin `speech`, transcription only (`transcribe(path) -> text`), for scenario S4 reduced: a recording dropped in a declared folder | Spike S-voice of the Lan sketch done (accuracy on the owner's voice, licences of program and weights verified); GPU lock exists | `file`, `email`, `llm`, per-run data class | M, `res:gpu` | Model licences; GPU contention; the Lan sketch places voice after Phase 3, so this pulls one operation forward **[needs Hùng]** |

Notes:

- **A4 before A5 is a design proposal of this file.** The Lan sketch (§4.1) asks for "ModelClient v2: streaming and tool calling" as the one core extension. Intake through `claude -p` with all tools off can only return text or JSON, which is exactly a flow draft. So the first usable L2 needs no native tool calling: the cloud plans, Flows executes, and `llm` steps do the local reading. Tool calling becomes a later step with its own evidence. To verify when A3 is built: that `claude -p` returns schema-valid JSON reliably enough for `check_flow`.
- **A6 and A7 are comfort items.** L2 works with approvals at a terminal with TOTP. Both add attack surface to save the owner's time, so both carry a measured entry criterion (E8).
- **Not in Phase 3** (unchanged from the Lan sketch): personal memory (L3), push-to-talk conversation (L4), briefing and proactivity (L5), phone (L6), IoT (L7).

### 4.2 Track B: shareable product

| # | Item | Entry | Needs from Phase 2 | Size | Main risk |
| --- | --- | --- | --- | --- | --- |
| B1 | Release discipline: version policy for core and plugins, first tag, release notes, SBOM per release | E6 is this item's first output; nothing else | changelog fragments, licence gate, SBOM | S | Low. Without it every item below has no unit |
| B2 | Windows installer and update path (#201): embedded Python and a pinned wheel set in a versioned folder; update replaces "pull `main` hourly" | #201 spike done; G2 (#309) decided; minimum hardware profile written (what works with no GPU, with no Ollama) | ADR-023 runtime root, `lfmap doctor` | M | Code-signing certificate is a paid item (verify; owner approval); the local model, not Python, is the real install barrier for non-developers |
| B3 | Plugin Registry: owner allow-list of plugins (G8 #315), install, update and remove a plugin from a wheel with licence, `min_core_version` and hash checks | G8 merged; E5; one out-of-tree plugin loaded from a wheel on a clean install | manifest, `versions.py`, licence script | M, `/security-review` | A plugin is code that runs as the owner: the registry is a supply-chain door. No remote index in this item |
| B4 | Out-of-tree proof: `lfmap-isomp` (ADR-019, backlog today) as the registry's acceptance test, on ghost data | B3 usable; ADR-019 (6) condition met | Plugin Contract, tiers for apply and rollback | M | Scope creep into isomp itself; keep to the thin wrapper ADR-019 defines |
| B5 | Early users (family): Vietnamese quick start, one owner per install, no telemetry, a way to report a problem | B1, B2 done; the owner has used his own install daily for 4 weeks; CLA and `principal` in place (done) | everything above | S to M, then ongoing | Support time of one maintainer; their data on their machines is their own, so no remote help that reads it |
| B6 | Plugins as standalone products (PyPI, README, price list if any) | Name and trademark check done (parked until Phase 2 ends); copyright evidence set refreshed; decision whether the repo or only wheels go public; package names free on PyPI (verify) | B1, B3 | S per plugin | Publishing is irreversible (`gate:po`); a public package invites support requests and name squatting |

### 4.3 On signal only (proposed to leave Phase 3) **[needs Hùng]**

| Item | Start signal | Why not before | Size |
| --- | --- | --- | --- |
| Plugin or agent Marketplace | Three plugins exist that were written by people other than the owner, and a legal entity exists | A marketplace is a running service with accounts, payment and intermediary-platform duties (verify with a lawyer); it contradicts "few background services". A signed static index file on the project site covers discovery until then | XL |
| Cloud Sync (live, two-way) | The owner runs LFMAP on a second declared machine and names what must be the same on both | Undefined today: nothing says what is synced. "Move or restore to another machine" already follows from backup S2 and the S4 snapshot at no extra design | L |
| Team Edition (accounts, Qdrant or PostgreSQL server, NATS) | A named team of two or more real users who must share one knowledge base, and a legal entity (ADR-026 (5): other people's data needs commercial API terms) | Three servers and an account system for a product with one user; the largest breach of solo-maintainable on the Roadmap | XL |

## 5. Order

Options:

- **O1. Roadmap as titled:** registry, marketplace, sync, Team Edition, packaging, then Lan. Builds for users who do not exist; the owner's own use waits longest.
- **O2. Lan first, product later:** all of Track A, then Track B. Matches the owner's frame, but leaves G2 (code from `main` runs as the owner within the hour) on the hourly updater for the whole of 3a, and Lan gets built on an unversioned core.
- **O3. Thin product slice, then Lan, then product (recommended):**

| Stage | Items | Ends when |
| --- | --- | --- |
| 3.0 | B1 release discipline, B2 installer and update path | pc-01 itself runs from an installed, versioned build |
| 3a-1 | A0 labels, A1 ADRs, A2 bench, A3 `claude -p` endpoint | a cloud call with a class label and a call cap passes `/security-review` |
| 3a-2 | A4 plan then run; A9 `speech` and scenario S4 reduced in parallel when GPU slots allow | exit 3a (section 8, R4) |
| 3a-3 | A8 S4 retreat; A5, A6, A7 each only if its entry criterion is met | each stands alone |
| 3b | B3 registry, B4 isomp proof, B5 early users, B6 packaging | exit 3b (section 8, R4) |

Why O3: B1 and B2 are small, close a high threat-model gap and give every later item a version to refer to. After them the order follows the owner's value. B5 (family) can move before 3a-2 if the owner wants early users sooner; its entry criteria do not depend on Lan.

Stop rules (decide now, so that a weak result is not argued away later) **[needs Hùng]**:

- **S1.** If the A2 bench shows no local model on pc-01 reaches the agreed threshold on Vietnamese `private`-class tasks, L2 ships for `normal` data only and the `private` half waits for hardware or a new model. No silent fallback to cloud.
- **S2.** If `claude -p` stops being allowed for this use, or the call cap is hit on most days for two weeks, A4 pauses and ADR-026 (5) is reopened (paid API: owner approval).
- **S3.** If the #199 spike fails any of its three unknowns, A6 is dropped, approvals stay at the terminal with TOTP, and the UI stays read-only.
- **S4.** No Track A item above A4 starts while more than three `security-review` issues of P1 or P2 are open.

## 6. What leaves Phase 2 if it grows

Test used: does the item serve the Phase 2 exit line, one of the three acceptance scenarios, or a Phase 3 entry criterion? If not, it can leave. Listed in the order to cut.

| Order | Item on the Phase 2 list | Goes to | Why it can leave |
| --- | --- | --- | --- |
| 1 | "n8n internal integration over REST" | Removed **[needs Hùng]** | No n8n is installed and no n8n flow exists (owner, 13/11); the goal is to automate manual work with Flows. The line describes a transition that never started |
| 2 | Plugin `ocr` (PaddleOCR) | Backlog, pulled by a scenario | None of S1, S2, S3 needs it; `markitdown` already does OCR through Tesseract; PaddleOCR is a heavy dependency (licence and size: verify) |
| 3 | Entities in the graph with a human review step (ADR-012) | After 3a | No scenario uses it; it is a second approval queue to design |
| 4 | Web UI parts beyond chat read-only and the approvals list (plugin list page, agent console) | 3a-2, with the loop that needs them | L1 needs one window; the other pages have no user yet |
| 5 | `organizer` | Start of Phase 3 as its own item, only if 1 to 4 are not enough | Large (plan, approve, apply, undo journal) and outside all three scenarios. It has real owner value, so it is last on this list |

Must not move (each is an exit criterion, a scenario dependency or an entry criterion of section 3): S1, S3 and S2 with `email` and `file`; the recipient-list rule (G2 of #218); JF-1..JF-4; DC-5 and DC-7; threat-model G1, G2, G3, G5, G6, G8, G9; ModelClient #296 and #301; REST adapter and chat UI v1 read-only; installer spike #201 (may slide to stage 3.0, where it is the first card).

Already moved by earlier decisions: Tauri shell (after the core is stable), scenario S4 (Phase 3), DC-6 (first cloud route), approvals from the UI (Phase 3).

## 7. Risks across items

| Risk | Where it bites | Control |
| --- | --- | --- |
| One maintainer, 17 items | everywhere | entry criteria per item; three items start only on a signal; A5, A6, A7 only on measured need; one item in progress per track |
| Quota: Lan at run time and Lan's development share one Pro plan (ADR-026) | A3, A4 | daily call cap in `[models]`; stop rule S2; measure calls per request in the first week |
| The gate is loosened three times in one phase (standing cloud destination, UI approval, plan-level approval) | A1, A6, A7 | one ADR each, in that order, each after the previous one has been used; `/security-review`; threat model redone after A4 (its own section 12 trigger) |
| Local model too weak for `private` work | A2, A4 | bench before build; stop rule S1 |
| Other people's machines cannot run the local parts | B2, B5 | hardware profile is an entry criterion of B2; say plainly what works without a GPU |
| Publishing cannot be undone | B6, any public index | `gate:po`; copyright evidence and name check first |
| Legal duties appear with other people's data or money (verify with a lawyer) | B5 at scale, section 4.3 | no accounts, no payment, no third-party content before a legal entity; one owner per install |
| A second product planned by the owner depends on B3 and B2 | 3b | treat it as one more out-of-tree plugin; its needs are requirements for B3, not lfmap items |
| Phase 3 never ends | whole phase | exit criteria per stage (R4) |

## 8. Proposed Roadmap changes **[needs Hùng]**

The Roadmap (`05_Roadmap.md`) is kept outside the repo; nothing was edited.

| # | Change | Reason |
| --- | --- | --- |
| R1 | Split Phase 3 into **3a "Lan acts"** and **3b "Shareable product"**, with stage 3.0 (release, installer) first | section 1 points 1 and 6 |
| R2 | Move Marketplace, live Cloud Sync and Team Edition (with Qdrant, PostgreSQL, NATS) to a list "On signal", each with its start signal | section 4.3 |
| R3 | Add to Phase 3 the items that exist only in other documents: labels on tool results (#237, #317), `claude -p` endpoint (ADR-026), approvals from the UI with passkey (#199), security S4 as its own line, scenario S4 reduced with `speech` transcription, `lfmap-isomp` as the registry proof (from Backlog) | section 1 point 4 |
| R4 | Add exit criteria. **3a:** in the chat window the owner asks in Vietnamese for a task over mixed-class data; Lan returns a plan; the `private` steps run on the local model and the egress log shows no `private` content sent to a cloud route; every T2/T3 step is approved outside the model's reach; a drill with an instruction planted in a fetched page and in a mail produces no unapproved send. Scenario S4 reduced passes. **3b:** a person other than the owner installs the product on a clean Windows machine with no developer tool, installs one out-of-tree plugin from a wheel, updates once and restores from a backup | section 1 point 2 |
| R5 | Add the Phase 3 entry criteria E1 to E8 after the Phase 2 exit line | section 3 |
| R6 | Phase 2 list: remove the n8n line; mark `ocr`, graph entities and the extra UI pages "if a scenario needs it"; note `organizer` as the last candidate to move | section 6 |
| R7 | Wording: "NATS only when several machines (Phase 3)" becomes "(Team Edition, on signal)"; the "Lan acts" line drops "order against Registry/Marketplace settled in the Phase 3 plan" once R1 is decided | follows R1, R2 |

## 9. Decisions for Hùng

1. R1: split Phase 3 into 3a and 3b with stage 3.0 first (order O3)?
2. R2: Marketplace, live Cloud Sync and Team Edition wait for their signals?
3. R4 and R5: accept the exit and entry criteria, or change the numbers (14 days, 4 weeks)?
4. Section 6: accept the cut order for Phase 2, and remove the n8n line now?
5. A9: pull `speech` transcription into Phase 3 for scenario S4, or keep all voice work after Phase 3 (then S4 waits too)?
6. Stop rules S1 to S4: accept as written?

Items 1 to 4 change the Roadmap. Nothing here blocks Phase 2 work.

## 10. Follow-up

- #326: the six decisions above (`gate:po`, `needs-decision`).
- #327: approval counts per week by tier and channel from `audit.jsonl` (criterion E8). Small, Phase 2b, feeds A6 and A7.
- Not opened: issues for A0 to A9 and B1 to B6. Per the epic rule of #157 each is opened when it is picked up, and several depend on decisions 1 to 5. Existing issues already cover A0 (#237, #317), A6 (#199) and B2 (#201).

## 11. Not covered

Designs of the items (each gets a spec or ADR at its start), prices, branding and trademark (parked until Phase 2 ends), the owner's separate commercial project, levels L3 to L7 of the Lan sketch, a calendar: the Roadmap counts by results, not dates.
