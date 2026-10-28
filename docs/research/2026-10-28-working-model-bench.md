# Working model bench W0: qwen3-coder:30b vs qwen2.5-coder:14b

- Date: 2026-10-28 · Author: Claude (Managing Agent) · Requested by: Hùng
- Status: **plan, waiting for approval**. Nothing runs on DIEP-ANH until Hùng types the sentence in §9.
- Question: which local model should be the main Working Agent of the qwen loop (Roadmap 1.7, ADR-004 B6 note: S cards with strict tests only)?
- Inputs: B0/B0b (`2026-10-23-b0-benchmark.md`: `qwen3-coder:30b` ≈ 50 tok/s with RAM spill, 67–72 % on GPU, "try as Working"), the K4–K7 batch of 2026-10-21 (`qwen2.5-coder:14b`, 37–41 tok/s, peak 12.4–12.5 GB), the L1b experience store (`docs/handoff/2026-10-24-experience-store-l1b.md`) and card TC-V1.
- No ADR changes: the bench only chooses the model behind an unchanged loop. ADR-022 (Leading tier) is not touched; one model stays resident at a time.

## 1. Candidates

| Model | Ollama tag | Size | Fits 16 GB? | Licence (04 register) |
| --- | --- | --- | --- | --- |
| Qwen2.5-Coder 14B (dense) | `qwen2.5-coder:14b` | 9.0 GB | yes, 12.3–12.5 GB peak at `num_ctx` 16384 | Apache-2.0, Internal, approved 2026-10-19 |
| Qwen3-Coder 30B-A3B (MoE, ~3B active) | `qwen3-coder:30b` | 18.6 GB | no, 67–72 % on GPU, rest in system RAM | Apache-2.0, Internal, approved 2026-10-23 |

Both are already in `D:\AI\models\ollama` (pulled for B0). No download, no new dependency, no licence work. Step 0 checks `ollama list`; if `qwen3-coder:30b` is missing, the run stops and asks (a download is outside the approval).

## 2. Cards

Seven S cards for the main comparison plus one larger card. All have frozen tests in the prompt and a fixed `base_ref`.

| Card | Target | Prompt | Group | Why |
| --- | --- | --- | --- | --- |
| TC-K4 | `lfmap_knowledge/extract.py` | 7.7 KB | seen | 14b history: green round 2, 3 Claude fixes |
| TC-K5 | `lfmap_knowledge/chunker.py` | 7.5 KB | seen, hard | 14b never green; Claude rewrote it |
| TC-K6 | `lfmap_knowledge/fts.py` | 6.8 KB | seen | green after a card fix, 0 Claude fixes |
| TC-K7 | `lfmap_knowledge/embed.py` | 8.4 KB | seen | green round 3, 2 Claude fixes, security checks |
| TC-V1 | `lfmap_core/versions.py` | 5.6 KB | unseen | 38 tests with traps (`fullmatch`, `re.ASCII`, `repr`) |
| TC-N1 | new (prep P1) | ≤ 6 KB | unseen | fresh card, no lesson written from it |
| TC-N2 | new (prep P1) | ≤ 6 KB | unseen | fresh card, no lesson written from it |
| TC-K2 | `lfmap_knowledge/store.py` | 8.7 KB | large | for option B (§8): does the bigger model help on bigger cards? |

- K-cards use the copies in `/mnt/project-files/qwen-loop/runs/2026-10-21/cards/` (K6 with the fixed prompt) and the branches `origin/feature/knowledge-k4-k7` and `origin/scratch/k2-rerun`; TC-V1 uses `origin/claude/project-thread-5g13hp`. All three branches exist.
- Why an "unseen" group: the 11 L1b lessons were written from the K1–K7 reviews, so with the store on, K-cards measure partly "can the model follow its own corrections". The unseen cards measure the real gain. The store already leaves out a card's own example when it retrieves examples (`experience.py`, `example.id != card_id`).
- TC-N1/N2 (prep P1): two small pure-Python modules from the Phase 2 backlog, no I/O or security logic, 20–40 frozen tests, reference implementation green in Cloud and kept out of the repository until the bench is reviewed.

## 3. Runs

| Block | Model | Store | Cards | Repeats | Card runs |
| --- | --- | --- | --- | --- | --- |
| A1 | `qwen2.5-coder:14b` | off (`--no-experience`) | 7 S cards | 3 | 21 |
| A2 | `qwen2.5-coder:14b` | on (frozen snapshot) | 7 S cards | 3 | 21 |
| B1 | `qwen3-coder:30b` | off | 7 S cards | 3 | 21 |
| B2 | `qwen3-coder:30b` | on (frozen snapshot) | 7 S cards | 3 | 21 |
| C | both | on | TC-K2 | 3 per model | 6 |
| | | | | **total** | **90** |

Fixed settings for every run, recorded at the start (`ollama --version`, environment, `ollama ps`):

- Same `qwen_loop.py` (L1b version in `D:\Development\lfmap-tools\qwen-loop`), `max_rounds = 3`, `num_ctx` 16384, temperature 0.2 (script default; Qwen suggests 0.7 for qwen3-coder, but one setting for both keeps the comparison fair), same Ollama settings as B0c and TC-V1 (`OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`).
- **Frozen store**: every store-on run gets a fresh copy of the store snapshot (`--experience <run folder>\store`). Each store-on run counts as a batch and retires lessons after 3 batches (`experience.start_batch`), so running 42 batches against the live store would retire every lesson and change the prompts mid-bench. The live `experience\` folder is never touched by the bench.
- Order: all blocks of one model, then the other (one model resident, no reload between cards). Inside a block the card order rotates per repeat. Before the first card of each model: `ollama stop` both models, so the first call measures a cold load; three extra cold loads per model at the end give the load-time figure.
- TC-V1 runs of the L1b thread (14b, 3 + 3, same Ollama settings) are a sanity check for block A: if A's TC-V1 numbers are far from them, the setup changed and the bench stops. They are not reused as data because the store will have moved by then (lessons added after the TC-V1 review).

## 4. Metrics

Per card run (from `summary.csv`, the run logs and the wrapper):

| Metric | Source | Notes |
| --- | --- | --- |
| First-round green | `first_round_green` | **primary metric**: tests + ruff green on the first answer |
| Green within 3 rounds | `status` | |
| Fix rounds to green | `rounds` | mean over green runs |
| Answer outside the card | log | edits to files outside `targets`, invented imports or modules; counted, any one is a red flag |
| Claude hand fixes | blind review, `claude_fixes` | see below |
| Speed | `tok_s` | answer tokens / eval time |
| Wall time per card | `wall_s` | what actually matters for a batch; includes prompt processing, which is the slow part with RAM spill |
| Peak VRAM | `peak_vram_mb` (nvidia-smi, 1 s) | for 30b it sits near the card limit, so also: |
| GPU/CPU split, system RAM | wrapper: `ollama ps` after each card, committed bytes | detects spill growth and RAM pressure |
| Load time | `load_s` on the cold calls | plus bge-m3 reloads in store-on blocks (bge-m3 must fit next to the Working model or it swaps for every retrieval) |

Claude hand fixes: for each model and S card, the first green run of block A2/B2 (up to 14 diffs, plus K2) goes to one blind review. Claude sees the diffs as X/Y with model names hidden, counts the edits needed before merge with the usual review checklist (logic, error handling, docstrings, scope) and only then unblinds. Reviewing all 90 diffs would cost more Claude tokens than the decision is worth. A card with no green run counts as "rewrite" (as K5 on 2026-10-21).

Honest limit: 21 runs per block. A 15-point difference is about 3 runs, so small gaps are noise. The thresholds below ask for clear gaps and treat the rest as a tie.

## 5. Decision rule (written before the run)

`qwen3-coder:30b` becomes the main Working model only if **all** hold, comparing B2 with A2 (store on, the configuration we will actually use):

1. First-round green rate on the 7 S cards at least **15 points** higher, **or** green-within-3 at least 15 points higher with first-round green not lower; and on the unseen cards (V1, N1, N2) not lower.
2. Claude hand fixes per card (mean) not higher; no more "rewrite" cards.
3. Answers outside the card: not more than 14b.
4. Wall time per card at most **1.5 ×** the 14b figure, and the whole 7-card batch under 30 minutes.
5. Stable: no crash or timeout, no Windows memory pressure warning, bge-m3 retrieval works without reloads that add more than 10 s per card.

Outcomes:

- **All five hold** → option A: switch the default model in `qwen_loop.py` (`DEFAULT_MODEL`), keep 14b installed as fallback.
- **30b better only on TC-K2 / K5 (harder cards)** → option B (§8): escalation route.
- **Gap below the thresholds** → tie: keep 14b (lighter, leaves VRAM free, known failure modes); spend effort on the L1b store instead.
- **Store gain** (A2 vs A1, B2 vs B1) is reported separately: it is the first measurement of L1b on more than one card and feeds the L1b review whatever the model decision.

## 6. GPU time and queue

| Item | Estimate |
| --- | --- |
| Block A (14b, 42 runs + K2) | 45 runs × ≈ 90 s (K4–K7 on 21/10: 47–216 s) ≈ 70 min |
| Block B (30b, 42 runs + K2) | 45 runs × ≈ 120 s (faster answers, slower prompt processing with spill) ≈ 90 min |
| Cold loads, worktrees, bge-m3 | ≈ 15 min |
| **Total** | **≈ 3 h GPU, up to 3.5 h**; can be split into two sessions (one per model) |

Queue on DIEP-ANH (serial, never overlapping): B0c → TC-V1 (3 + 3) → D2c embed 1k → **W0**. The wrapper checks `ollama ps` before starting and stops if another model than the expected one is loaded. Hùng can stay away from the PC; a power cut only loses the current card (each card run writes its row when done, the wrapper skips finished rows on restart).

## 7. Preparation (Cloud, before the run)

| Step | What | Environment |
| --- | --- | --- |
| P1 | Write TC-N1 and TC-N2: card.toml, prompt.md with tests verbatim, frozen tests on a bench branch, reference implementation green in Cloud | Cloud |
| P2 | `Run-WorkingBench.ps1` in `D:\Development\lfmap-tools\qwen-bench`: loops model × store × card × repeat, copies the store snapshot per run, `ollama stop` for cold loads, logs `ollama ps` and RAM after each card, resumes from `bench.csv`; `aggregate.py` builds the §4 tables. Tested in Cloud against a fake Ollama | Cloud, copied to DIEP-ANH with folder tools |
| P3 | Snapshot the store after the TC-V1 review into `qwen-bench\store-snapshot\` (hash recorded in this file) | DIEP-ANH folder tools |
| P4 | After the run: copy `out\` and `bench.csv` to `/mnt/project-files/qwen-loop/runs/2026-10-28-W0/`, blind review, results section in this file, decision card for Hùng | Cloud |

## 8. Options

| Option | What | For | Against |
| --- | --- | --- | --- |
| **A. Switch** | 30b becomes the default Working model | one model, maybe fewer Claude fixes | 18.6 GB spill: RAM pressure, slower prompts, crowds bge-m3 and the Leading model rotation |
| **B. Escalate** (recommended if 30b wins only on hard cards) | 14b runs first; a card still red after 3 rounds gets 2 more rounds on 30b with the last error, then goes to Claude. One extra `--model` pass in the wrapper, no loop change | the cheap model handles easy cards, the big one only the hard ones; one model per phase (all 14b rounds, then all 30b rounds) | two models to keep current; the second pass adds time to bad batches |
| **C. Keep 14b + L1b** | no switch, invest in lessons and examples | lightest, VRAM free, no new behaviour to learn | if 30b is clearly better we leave quality on the table |
| D. Size routing | 30b for cards whose prompt is above about 6K tokens, 14b below | simple rule | B0/B5 data say hardness is not prompt size (K5 is small and hard); B covers it better |

Recommendation: run W0 as planned and apply the rule in §5. Before data, the most likely outcome is B or C: the B0 runs showed 30b fast but not careful, and its spill makes it a poor permanent resident.

## 9. Approval sentence (Hùng types it in the Remote Control thread on DIEP-ANH)

> Tôi duyệt chạy bench W0 trên DIEP-ANH theo docs/research/2026-10-28-working-model-bench.md: dùng qwen2.5-coder:14b và qwen3-coder:30b đã có trong D:\AI\models\ollama (không tải model mới, không đổi cấu hình Ollama), chạy Run-WorkingBench.ps1 trong D:\Development\lfmap-tools\qwen-bench với worktree trong D:\Development\lfmap, ghi kết quả vào D:\Development\lfmap-tools\qwen-bench\out, chỉ chạy khi B0c, TC-V1 và D2c đã xong, hết hạn sau 48h.

Everything it covers is inside the grant for `D:\Development`; it is a typed sentence because the device classifier only accepts approvals written by Hùng in that thread. 48 hours instead of the default 24 because the bench waits for three earlier GPU jobs.

## 10. Project document updates (outside this repository)

- 05 Roadmap, row 1.7: after the decision, note the chosen Working model and the W0 result.
- 03 ADR-004 note: only if option A or B is chosen (the Working model changes or gains a second step); B6 scope (S cards only) stays.
- 04 License Register: no change (both rows exist).
