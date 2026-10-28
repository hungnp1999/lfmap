# Local model tiers: Leading Agent between Claude and the Working Agents

- Date: 2026-10-23 · Role: Research + Planner · Environment: Claude Code cloud session (Linux); nothing was run on the owner's PC.
- Inputs: Roadmap (Phase 1 accepted 2026-10-22, Phase 2 draft 2a/2b), ADR-004 and its B6 note, Blueprint §4.2–4.4, License Register, qwen-loop results (`docs/handoff/2026-10-21-qwen-loop.md`, K4–K7 batch, PR #26).
- Status: research only. The ADR draft at the end is **Proposed**; nothing changes until the owner accepts it.

## 1. Questions

1. When can local models take a real share of project work?
2. Can a larger local model (the owner named Qwen2.5 32B Q4_K_M) act as a **Leading Agent**: receive work packages from Claude (Managing Agent), split them into tasks for small local models (Working Agents), and check their output against standards Claude issues? The aim is to cut Claude token use and stop the cloud tier from being the bottleneck while the GPU idles.

Proposed tiers (the owner's company analogy):

| Tier | Who | Does | Does not |
| --- | --- | --- | --- |
| 1 Director | Owner | vision, goals, approvals | |
| 2 Managing | Claude (cloud) | architecture, work packages, acceptance tests, QA standard, final review, merge | write every S card, read every failing attempt |
| 3 Leading | large local model | split a package into S cards, brief Working Agents, run the gates, first-pass review report | accept or merge, touch security code, change tests |
| 4 Working | small local model | write one file/function per card | anything outside the card |

## 2. Where we are today

Local models already do part of the work: since 2026-10-21 the `qwen-loop` (pure Python, outside the product) runs S cards on `qwen2.5-coder:14b`. Measured on DIEP-ANH (RTX 5060 Ti 16 GB):

| Metric | Value |
| --- | --- |
| Speed | 37–41 tok/s, peak VRAM 12.4–12.5 GB at `num_ctx` 16384 |
| K4–K7 batch | green by tests 3/4; merged without a logic fix 1/4; K5 rewritten by Claude |
| Known failure modes | invents fixtures and modules, drops docstrings, fix rounds rarely converge without dictated edits |

So the Working tier exists and its ceiling is known: S cards with strict, pre-written tests. The missing piece is the Leading tier.

## 3. Answer 1: realistic timeline

Estimates, not commitments; they follow the Phase 2 draft (2a ≈ 27/10 → 20/11, 2b ≈ 20/11 → 21/12).

| When | What local models do | Gate to move on |
| --- | --- | --- |
| Now (Phase 1b, to ~30/10) | Working tier only: S cards with strict tests through `qwen-loop`; embeddings | none, already running |
| ~24–29/10 | **B0 benchmark** on DIEP-ANH (needs owner approval, §8) | data on speed, VRAM, review catch rate |
| 2a.1 spike (~27/10 → ~5/11) | Leading tier **in shadow mode**: it splits and pre-reviews, Claude still does the full review and compares | catch rate ≥ 80 % on seeded bugs, ≤ 1 hallucinated finding per 10 reviews, cards Claude would accept ≥ 70 % |
| rest of 2a (~5/11 → 20/11) | Leading tier **as filter**: Claude reads only packages the Leading Agent marked ready, plus its report; docs/docstrings/test drafts go local | token saving measured ≥ 25 % on comparable batches |
| 2b (from ~20/11) | Leading tier routine for S and simple M cards; Agent Router picks the tier | quality does not regress over two batches |

Earliest real share beyond today's S cards: **about the second week of November 2026**, if B0 and the shadow run pass. Security code, permission code and tests themselves stay with Claude throughout (B6).

## 4. Candidate Leading models for 16 GB

Sizes are Ollama Q4 downloads; VRAM needs a further 1–3 GB for KV cache depending on `num_ctx`. Speeds are third-party figures on other 16 GB cards and must be re-measured on DIEP-ANH. Licences were read on 2026-10-23 from model cards and vendor posts; re-check the exact tag with `ollama show --license` before use.

| Model (Ollama tag, unverified until B0) | Type | Q4 size | Fits 16 GB? | Reported speed | Licence | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `gpt-oss:20b` | MoE, ~3.6B active | ~14 GB | yes, 100 % GPU at moderate context | 140–190 tok/s (RTX 4080/5080) | Apache-2.0 (+ OpenAI usage policy) | reasoning model, native tool calling, 128K context; fastest candidate |
| `devstral-small-2:24b` | dense 24B, agentic coder | ~15 GB | tight; at 8K context it may not stay fully resident | lower than gpt-oss | Apache-2.0 (Devstral 2 123B is "modified MIT", not this one) | strongest pure coder that nearly fits |
| `qwen3-coder:30b` (30B-A3B) | MoE, ~3B active | ~18.6 GB | no, ~74 % GPU; MoE keeps offload tolerable | tens of tok/s, unmeasured here | Apache-2.0 | good tool calling; needs enough system RAM |
| `qwen2.5:32b` / `qwen2.5-coder:32b` (owner's candidate) | dense 32B | ~19–20 GB | no, partial CPU offload | single-digit to low-teens tok/s expected (dense + offload) | Apache-2.0 (the 3B and 72B sizes have other licences) | 2024 generation; slowest; not recommended as first choice |

Not fitting 16 GB and left out: Qwen3.6 27B (reported for 24 GB cards), gpt-oss 120B (≈ 12 tok/s with heavy offload).

Working-tier candidates to compare against the current `qwen2.5-coder:14b` (~9 GB) in the same benchmark: `qwen3:14b` (Apache-2.0, similar size). Smaller Working models (≤ 8B) are not worth it: today's 14B already needs strict tests.

**Recommendation:** benchmark `gpt-oss:20b` and `devstral-small-2:24b` as Leading candidates, `qwen3-coder:30b` as the "slightly too big" control, and keep `qwen2.5:32b` only as an optional fourth run, because a dense 32B with offload is the slowest option for a role that has to read many diffs.

All four are Apache-2.0, which the License Register treats as Ship-compatible; for this role they are **Internal** (development tooling, not shipped). Each one gets a row in the register's model table when it is first pulled.

## 5. VRAM and rotation with Ollama

The card cannot hold a Leading model (14–15 GB) and the Working model (9 GB) at once. Rotation is therefore by **phase, not by message**:

1. Leading phase: load Leading model, split the package into N cards (one call).
2. Working phase: unload Leading (`keep_alive: 0`), load Working model, run all N cards through `qwen-loop` with its gates (pytest, ruff).
3. Review phase: unload Working, load Leading, review all N results in one pass, write one report.

Ollama controls used: per-request `keep_alive` (0 unloads at once, -1 keeps resident; overrides `OLLAMA_KEEP_ALIVE`), `OLLAMA_MAX_LOADED_MODELS`, `num_ctx` per request. A model swap costs a cold load (24 s measured for the 14B on DIEP-ANH; expect 30–60 s for 15–19 GB). Three swaps per batch is under three minutes, so batching makes rotation cheap; swapping per card would not be.

`OLLAMA_NUM_PARALLEL=2` stays useful for the Working phase only; for a 14–15 GB Leading model set it to 1 so the KV cache fits.

## 6. How the Leading Agent receives work and standards

Everything stays files and plain Python (no agent framework, ADR-004). Claude writes one **work package** per feature into `lfmap-tools` (outside the product):

| File | Written by | Content |
| --- | --- | --- |
| `package.toml` | Claude | goal, files in scope, files forbidden (security, tests), max cards, size limits |
| `tests/` | Claude | acceptance tests, frozen: Leading and Working may not edit them |
| `standard.md` | Claude | QA checklist: the Review Checklist of the Prompt Playbook cut to items a script or a model can check, each with an id |
| `cards/*.toml` | Leading | S cards in the existing qwen-loop format |
| `report.json` | Leading | per card: verdict (`ready`/`rework`/`escalate`), findings with checklist id, file and line, evidence quote |

Rules the driver script enforces, so trust does not depend on the model:

- A card is `ready` only if the deterministic gates pass (frozen tests green, ruff clean, no file outside scope touched, test files unchanged by hash).
- Every finding must quote a line that exists in the diff; the script drops findings whose quote is not found and counts them as hallucinations.
- The Leading Agent can mark `rework` (send back once with its notes) or `escalate` (to Claude); it can never mark a package accepted. Claude reviews and merges.

## 7. Token savings: honest estimate

Claude's cost per S card today, roughly: card writing 3–5K output tokens, review of attempts 5–15K input tokens (more when attempts fail and need reading). With the Leading tier Claude writes one package (tests + standard) instead of N cards and reads one report plus the ready diffs instead of every attempt.

| Work | Claude today | With Leading tier | Saving |
| --- | --- | --- | --- |
| Splitting into cards | all | package only | 40–60 % of planning output |
| Reading failed attempts | all | escalations only | most of it |
| Final review of ready diffs | all | all (unchanged) | 0 |
| Security / M cards | Claude Code | Claude Code | 0 |

Net: **about 20–35 % of Claude tokens on batches of S cards**, near 0 on security and design work. The estimate is weak; the 2a.1 shadow run must measure it on real batches. The biggest saving still comes from cheap deterministic gates, which is why tests stay Claude's job.

## 8. Risks

| Risk | Effect | Mitigation |
| --- | --- | --- |
| Hallucinated reviews (findings on lines that do not exist, or "looks good" on wrong code) | false confidence, wasted rework | quote check in script; seeded-bug canary cards in every batch; Leading cannot accept |
| Leading model weaker than expected at splitting | cards Claude would not write; more escalations | shadow mode first; acceptance threshold in §3 |
| Model edits the tests to get green | silent quality loss | tests frozen by hash; any change = automatic `escalate` |
| VRAM pressure / offload makes review slow | batches take hours | batch rotation (§5); prefer MoE or ≤ 15 GB models |
| Scope creep into an agent framework | breaks ADR-004 before the 2a.1 spike | stays a script in `lfmap-tools`; the 2a.1 spike decides whether a framework replaces it |
| Licence drift of a model tag | weights under a different licence than the family | `ollama show --license` per tag, register row before use |
| Power cut on DIEP-ANH mid-batch | lost run | runs are idempotent per card (worktree per card), restart from the log |

## 9. Conflict with decided documents

- **ADR-004** (no agent framework in Phase 0–1): no conflict if the Leading tier stays plain Python outside the product, like `qwen-loop`.
- **ADR-004 note B6** ("qwen only gets S cards with strict tests; M cards and security go to Claude Code") and **Blueprint §4.4** ("Review chất lượng → Cloud"): **conflict** once a local model does any review or splits Claude's packages. Shadow mode (§3) does not conflict because Claude still reviews everything; the "filter" stage does. Hence the ADR draft below, to accept before the filter stage, not before the benchmark.

## 9a. Getting the Working tier better over time (decided 2026-10-23)

The owner asked how a small model can gain skill over time, the way a worker gains experience. Three levels were weighed; the owner decided (2026-10-23 09:36Z):

| Level | What | Decision |
| --- | --- | --- |
| 1 Experience store | no weight changes: a lessons file and accepted examples are retrieved into each prompt | **adopt now** |
| 2 Fine-tuning (LoRA/QLoRA on a 7–14B) | train on accepted solutions | **dropped**: too much effort and risk for a solo developer (hundreds of examples needed, redo on each new base model, Anthropic terms forbid using Claude output to build competing models) |
| 3 Swap to newer base models | re-run B0 on new releases | **not the main path**: depends on others; the owner prefers to build and customise his own setup. Model tags stay configurable so a swap remains cheap |

Level 1 design, plain Python in `qwen-loop` (`lfmap-tools`, outside the product):

- `lessons.toml`: one entry per recurring mistake (`id`, `rule`, `applies_to` glob or tag, `seen` count, `last_seen`, source run). Examples from the K-batches: do not define fixtures that `conftest.py` provides; keep existing docstrings; import what you use (`tomllib`); end the prompt with "NOW WRITE THE COMPLETE <module>.py". The driver adds matching rules to every card prompt, at most ~10 to keep prompts under ~4K tokens.
- `examples/`: each card that Claude accepted is saved with its card, final diff and the tests (accepted code only, written by the Working model and fixed by the owner or Claude in review).
- Retrieval: for a new card, the 1–2 most similar accepted examples are found by embedding the card text with the local `bge-m3` (through `lfmap-knowledge`, or a plain Ollama `/api/embed` call) and pasted as worked examples.
- Feedback: after every review, Claude (or the Leading Agent once trusted) adds or bumps lessons from the findings; a lesson that has not matched in 3 batches is retired so the list stays short.
- Skill metric: first-round green rate per batch (K4–K7 baseline: 0/4 green in round 1, 3/4 green by tests at the end), rounds per card, Claude fixes per card. Logged in `summary.csv`.

Nothing leaves the machine; no new dependency (TOML via `tomllib`, embeddings via the existing Ollama model).

## 10. Tasks

| # | Task | Environment | Done when | Needs owner |
| --- | --- | --- | --- | --- |
| L0 | B0 benchmark: pull 3 (opt. 4) models to `D:\AI\models\ollama`, measure tok/s, VRAM, swap time at `num_ctx` 8K/16K; review 10 diffs (6 from K4–K7 with known verdicts, 4 with seeded bugs); split one past package | Local (DIEP-ANH, GPU), driven by Claude through Remote Control | `bench.csv` + short report in `docs/research/` | done 2026-10-23: `docs/research/2026-10-23-b0-benchmark.md` (qwen3.8:27b 7/7 verdicts, chosen for shadow mode) |
| L1 | Extend `qwen-loop` with package/standard/report files and the quote check | Cloud (code) + Local (run) | unit tests green; dry run on a past package | no |
| L1b | Experience store (§9a): `lessons.toml`, `examples/`, retrieval of 1–2 similar accepted examples with `bge-m3`, first-round green metric; seed lessons from the K-batch reviews | Cloud (code, Claude Code session) + Local (run) | unit tests green; next qwen batch logs which lessons and examples each prompt carried | no |
| L2 | Shadow run inside the 2a.1 spike on a real batch | Local + Claude review | §3 thresholds measured | no |
| B0c | Same 15 cases with `qwen3.8:27b` at Q3_K_M, flash attention on and `OLLAMA_KV_CACHE_TYPE=q8_0` (§12.4) | Local (DIEP-ANH) | seeds caught, invented quotes, GPU share and time per review next to the Q4_K_M row | **yes**: download and environment change |
| L3 | Decide ADR-022 | owner | Accepted or Rejected | **yes** |

Sentence the owner writes himself in the Remote Control thread (the device classifier accepts only his own words there):

> Tôi duyệt chạy benchmark B0 trên DIEP-ANH: tải gpt-oss:20b, devstral-small-2:24b, qwen3-coder:30b (và qwen2.5:32b nếu còn chỗ) vào D:\AI\models\ollama, chạy script benchmark trong D:\Development\lfmap-tools\leading-bench, hết hạn sau 24h.

Removing the models afterwards (`ollama rm`) is blocked for Claude on that device; the owner does it if he wants the disk space back.

## 11. ADR draft

### ADR-022: Local Leading Agent tier between Claude and local Working Agents
- Status: Proposed (Claude, 2026-10-23; revised 2026-10-28 after the owner's hybrid notes, §12)
- Context: Claude's quota is the bottleneck while the local GPU idles. `qwen-loop` proved a local Working tier for S cards (K4–K7). The owner wants a larger local model to split Claude's work packages, brief Working models and pre-review their output. B6 and Blueprint §4.4 keep review in the cloud.
- Decision: Add a local Leading tier, plain Python in `lfmap-tools` (outside the product, no framework, ADR-004 unchanged). Claude issues work packages with frozen acceptance tests and a QA standard; the Leading model splits them into S cards, runs the Working loop and writes a review report. The Leading tier may mark cards `ready`, `rework` or `escalate`, never accept or merge. Claude still reviews every ready diff and merges; security, permission and test code stay with Claude. Rollout: benchmark B0 → shadow mode (2a.1) → filter mode once §3 thresholds are met. Models rotate by batch phase in Ollama (never per task); one model resident at a time; the Leading model runs with `num_ctx` of at least 8K (16K by default) and at the smallest quantisation that keeps the §3 thresholds on the bench (Q4_K_M today; Q3_K_M if B0c passes). Failed reviews feed the experience store as rules for the Working prompt (§9a). Orchestration stays plain Python; no n8n or LangChain (ADR-006/021). A second GPU node, when there is one, runs the Working tier over HTTP to an Ollama bound to its LAN address and firewalled to the first node; the Leading tier never stands in for Claude.
- Options considered: Qwen2.5 32B dense as Leading (too slow with offload on 16 GB); Leading tier with authority to accept (hallucinated reviews would reach `main`); no Leading tier (keeps Claude as the bottleneck); an agent framework now (ADR-004, decided by the 2a.1 spike); per-task rotation, Q2_K or a 1–2K context for the Leading model, and third-party context tools (CodeGraph, Claude-Mem, Archify, security-audit skills), see §12.
- Consequences: amends the ADR-004 B6 note and Blueprint §4.4 ("first-pass review may be local; final review is cloud"). New model rows in the License Register as Internal. If the 2a.1 spike picks a framework, the Leading tier moves onto it.

## 12. Review of the owner's hybrid notes (2026-10-28)

Before ADR-022 is decided, the owner shared three notes: a 3-tier hybrid design on one 16 GB GPU, the same design on several PCs over LAN, and a list of tools that cut Claude's context use. Each claim was checked against B0/B0b, ADR-004/006/021 and the License Register.

### 12.1 Single GPU

| Claim in the notes | Check | Keep? |
| --- | --- | --- |
| Never run two local models at once; unload with `keep_alive: 0` | Same as §5 (one model resident) | yes |
| Leader is `Qwen3.5-27B` | Real model (Feb 2026, Apache-2.0, dense, thinking by default). B0 used its successor `qwen3.8:27b` (Aug 2026, same size class) | use `qwen3.8:27b` |
| Leader at Q3_K_M or Q2_K, 10–13 GB | B0b ran Q4_K_M (17.7 GB, 67 % on GPU, 14 tok/s) and caught 7/8 seeds. Q3_K_M would likely fit the GPU and run faster; Q2_K loses clearly more quality on a 27B model. Untested on our cases | Q3_K_M only after a bench (B0c); Q2_K no |
| Leader `num_ctx` 1024–2048 | Too small: a review prompt (standard, card, diff, test log) is 9–17K characters, about 3–5K tokens, and thinking adds up to ~6K tokens. Ollama silently drops the start of a prompt that does not fit, so the Leader would review a truncated diff | no; keep 16K (8K minimum) |
| Worker with `OLLAMA_FLASH_ATTENTION=1`, `num_ctx` 8192 | Sound; flash attention also allows `OLLAMA_KV_CACHE_TYPE=q8_0`, which halves KV memory. It was approved on 2026-10-24 but not applied (device classifier). Check Ollama's log first: recent Ollama versions turn it on by default for several model families | yes, measured in B0c |
| Rotate Leader → Worker → Leader for every task | B0 measured 15–47 s cold load and 6–16 s warm (not 3–10 s), plus 2–9 min per Leader review. Per-task rotation spends much of the batch loading models | no; rotate per batch phase (split all, work all, review all), as §5 |
| On a fail, the Leader writes a "hard rule" injected into the Worker's prompt | Same idea as the experience store (§9a, `lessons.toml`) | yes, through L1b |
| Stateless Leader, JSON in and out | Same as §6; JSON-schema `format` gave empty answers with reasoning models (B0b), so JSON is asked for in the prompt | yes |
| Orchestrator in n8n or LangChain | ADR-004 (plain Python until the 2a.1 spike), ADR-006/021 (n8n replaced by in-house LFMAP Flows) | no; plain Python in `lfmap-tools` |
| Worker uses MCP tools to read and write files | A 14B model with file tools widens what a bad answer can do. Today the script gives the Worker the card, writes its answer into a scratch copy and runs frozen tests | not now; read-only tools later if a card needs them |
| Cloud API with prompt caching | Claude Code on the Pro plan already caches; an API key is a paid service | no change |

### 12.2 Several PCs

Leader on PC 1 and Worker on PC 2 removes the rotation cost and is the natural next step once a second GPU exists. Two changes to the notes:

- `OLLAMA_HOST=0.0.0.0` opens Ollama to the whole LAN without authentication. Bind to the PC's LAN address and allow port 11434 in the firewall only from PC 1 (or tunnel over SSH).
- "PC 1 takes over as Manager when the cloud is down" contradicts the rule that the Leading tier never accepts or merges. While the cloud is down, work queues.

Transport stays plain HTTP to Ollama; NATS only when ADR-021's multi-machine EventBus is needed. No hardware decision is needed now.

### 12.3 Context tools for Claude

| Tool | Licence / source | Overlap | Verdict |
| --- | --- | --- | --- |
| CodeGraph (tree-sitter graph in SQLite over MCP) | Several unrelated projects use the name; the matching ones are small MIT repositories | `lfmap-knowledge` already serves FTS + vector `get_context` with a token budget | no; a symbol and caller index could become an in-house `lfmap-knowledge` extension later (`tree-sitter`, MIT) |
| Claude-Mem | Licence unclear (sources say Apache-2.0, or AGPL-3.0 with a PolyForm Noncommercial part); hooks into every Claude Code session and stores transcripts | project memory | no |
| Milvus + AST chunking | Apache-2.0, a server to run | LanceDB in `lfmap-knowledge` | no |
| Repomix / AI-Digest | MIT | Claude Code reads files selectively | no |
| Archify (diagram skill) | MIT, Node.js, third-party skill | Claude draws diagrams as pages on request | optional, after reading the skill and adding a License Register row |
| CodeSee, CodeScene, Understand | commercial or SaaS; code leaves the machine | none | no |
| `shaxbozaka/security-audit` | not found | Claude Code `/security-review`, CodeQL on every PR | no |
| `agentnode-dev/skills-security-audit` | about 30 installs | same | no |

A skill or MCP server runs with Claude's permissions on the owner's machines, so third-party ones are the larger risk: install one only after reading its code, checking the licence and adding a License Register row. The notes' working rules (a short `ARCHITECTURE.md`, narrow tasks, never "read the whole project") are already how the repositories work (`CLAUDE.md`, handoffs).

### 12.4 Options

- **A. Keep ADR-022 as drafted** and take the compatible ideas: hard rules through L1b, stateless JSON, small cards, safe LAN binding for later. No new tools.
- **B. A plus bench B0c** (recommended): the same 15 cases with `qwen3.8:27b` at Q3_K_M, flash attention and q8_0 KV cache. Keep Q3_K_M if it catches at least 7/8 seeds with no invented quotes; it should fit the GPU and shorten the overnight batch. L1b and L2 start meanwhile on Q4_K_M.
- **C. Adopt the notes as written** (per-task rotation, Q2/Q3, 2K context, n8n or LangChain, the listed tools): not recommended; it conflicts with ADR-004/006/021, truncates review prompts and adds unreviewed third-party code.

## Sources

- [Best Coding LLM for 16GB VRAM (2026)](https://localaimaster.com/vram/best-coding-llm-16gb-vram)
- [Best Local LLMs for 16GB VRAM in 2026](https://www.runaihome.com/blog/best-local-llm-16gb-vram-2026/)
- [Comparing LLM performance on Ollama on a 16GB VRAM GPU](https://www.glukhov.org/post/2026/01/choosing-best-llm-for-ollama-on-16gb-vram-gpu/)
- [Best Ollama models 2026 by VRAM](https://www.morphllm.com/best-ollama-models)
- [Mistral: Devstral 2 and Vibe CLI](https://mistral.ai/news/devstral-2-vibe-cli/)
- [Devstral Small 2 24B (local model notes)](https://www.developersdigest.tech/local-models/devstral-small-2-24b)
- [Qwen3-Coder-30B-A3B GGUF](https://huggingface.co/atomicchat/qwen3-coder-30b-a3b-GGUF)
- [Qwen2.5-32B-Instruct](https://apxml.com/models/qwen2-5-32b)
- [Ollama FAQ (keep_alive, loaded models)](https://ollama.readthedocs.io/en/faq/)
- [Ollama model reloading and swapping](https://runaihome.com/blog/ollama-model-keeps-reloading-vram-fix-2026/)
- [Qwen3.5 27B (model listing)](https://apxml.com/models/qwen35-27b)
- [claude-mem on GitHub (licence notes)](https://horadecodar.com.br/claude-mem-github/)
- [claudekit: claude-mem](https://claudekit.io/en/tools/claude-mem/)
- [Archify agent skill](https://betterstack.com/community/guides/ai/archify-architecture/)
- [codegraph-rust](https://awesome.ecosyste.ms/projects/github.com%2Fsunerpy%2Fcodegraph-rust)
- [agentnode-dev skills-security-audit](https://www.skills.sh/agentnode-dev/skills-security-audit/skills-security-audit)
