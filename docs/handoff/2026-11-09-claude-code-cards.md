# Claude Code (Cloud) start prompts, plan #208 (09/11–11/11)

Cloud sessions cannot read `/mnt/project-files`; everything a card needs is in this repo or in its issue. Where a card names a project file, the owner pastes the needed part.

Environment for all cards: Cloud (project default env, SessionStart hook runs `uv sync`), repo `hungnp1999/lfmap`, Sonnet. Branch from up-to-date `main`. Docs-only PRs skip `/security-review`. Every commit keeps the `Dev-Environment` and `Claude-Session` trailers. Open the PR as non-draft with `Closes #N`, update `CHANGELOG.md` `[Unreleased]`.

## Status

| Card | Task | Status | Start when |
| --- | --- | --- | --- |
| A | #189 ModelClient spec | READY | now |
| B | #164 Planner 2a.2 checklist item | READY | now (small) |
| C | #190 jobs into Flows, code | BLOCKED | PR #210 merged and its 3 open questions (13.7) answered |
| D | #192 Plugin Contract v0.2 + fixture | BLOCKED (partly) | after #210 merged; model-access section after Card A merged |
| E | #191 scenario template | READY | Wed 11/11 morning (Hùng fills in 11:00–12:00) |

Not Claude Code Cloud: #207 (Local QW, needs run script + preflight comment by Mon noon: not yet posted), gates #197/#200/#196, #201 and the rest are Backlog.

## Card A: #189 ModelClient Module Spec (docs only)

- File scope: new `docs/specs/model-client.md`; one line in `CHANGELOG.md`. No code.
- Inputs: issue #189, `docs/research/2026-11-08-architecture-review.md` (C1, K2), Blueprint §4.4 in the Blueprint (project file, not in the repo: ask the owner to paste section 4.4 if you need it), `docs/specs/knowledge.md` (embed), ADR-022/ADR-024 in ADR text (project file; the repo has only notes in docs/).
- Spec must cover: `ModelClient` Protocol (chat, embed); one OpenAI-compatible stdlib implementation, loopback default; routing policy local/cloud as `config.toml` data; cloud endpoint through the gate (`cloud_ai`, `[approval.destinations]`, T3 otherwise) and `egress_log`; access via `ctx`; thin `llm` plugin (`summarise`, `extract`, `classify`); migration of `knowledge` embeddings only after identical vectors on the iso-vi bench; frozen test list written first; open questions for Hùng. Fold RT-08 (#167).
- Frozen tests (in the spec, to implement later): Protocol conformance with a fake server; loopback refusal of non-loopback host without approval; egress_log line per cloud call; routing by config.
- Blockers: none. Opus only if Hùng allows.

Prompt:
```
Read CLAUDE.md, ARCHITECTURE.md and issue #189. Write docs/specs/model-client.md (Module Spec, English) following the scope and frozen-test list in docs/handoff/2026-11-09-claude-code-cards.md (Card A). Docs only, no code. List open questions for the owner at the end. Add one CHANGELOG line and open a PR with "Refs #189" (the issue stays open for the code). Stop after the PR.
```

## Card B: #164 Planner 2a.2 checklist item (docs only)

- File scope: the K7 card and the Planner 2a.2 checklist under `docs/` (find with grep "K7", "2a.2"); fallback per issue: add to `docs/handoff/2026-11-05-f7-deterministic-checks.md` follow-up or the #155 handoff.
- Change: add the `count` seed class checklist item and the K7 card note (decision 3 of F7, Hùng 05/11).
- Done: PR merged. Blockers: none.

Prompt:
```
Read CLAUDE.md and issue #164. Find the K7 card and the Planner 2a.2 checklist in docs/. Add the checklist item and the card note for the "count" seed class (F7 decision 3; see docs/handoff/2026-11-05-f7-deterministic-checks.md). If Planner 2a.2 has no checklist, add the item to the nearest handoff and say so in the PR. Docs only. Open a PR with "Closes #164".
```

## Card C: #190 fold jobs into Flows (code), start only after PR #210 is merged

- File scope: new `packages/lfmap-core/.../jobs_flow.py` (translation, outside the 230-line cap of `flows_run.py`), small edits in jobs/flows CLI, `docs/specs/flows.md`, `docs/jobs.md`, `ARCHITECTURE.md`, `CHANGELOG.md`, tests per section 13.6 of the spec.
- Frozen tests: write first, from `docs/specs/flows.md` §13.6 (translation table, T0–T3 tiers, pause/resume, legacy proposals approvable for one release, golden test for `jobs register --dry-run`, exit codes).
- Blockers: Hùng's review of PR #210 and answers to 13.7 (run file strategy, audit channel, transition timing). Then DIEP-ANH smoke (res: Local) after merge.
- `/security-review` before merge (touches approvals and subprocess paths).

Prompt:
```
Read CLAUDE.md, ARCHITECTURE.md, issue #190 and section 13 of docs/specs/flows.md (the owner's answers to 13.7 are in the PR #210 discussion). Write the tests of 13.6 first, then implement jobs_flow.py and the runner/CLI changes. flows_run.py must stay <= 230 lines. Keep jobs.toml, task names, the lfmap jobs CLI and tier rules unchanged. Run uv run pytest, ruff check and format. Run /security-review and answer findings. Open a PR with "Closes #190".
```

## Card D: #192 remainder, Plugin Contract v0.2 and compatibility fixture

- #192 was closed by PR #209 (principal only). Reopen or open a follow-up issue for: contract text and the frozen "old plugin" fixture.
- File scope: `02_Plugin_Contract.md` (project files, outside repo: Hùng approves) plus a repo copy/note under `docs/`; fixture in `packages/lfmap-core/tests/` with a frozen plugin that must keep loading (`min_core_version` already enforced in `versions.py`).
- Content: `ctx.events` and publishing rules, `event` / `flow` channels, idempotent handlers, flow references to operation outputs, `principal` (done in #209), jobs→Flows (after #210), model access (after Card A).
- Blockers: #210 merged; Card A merged for the model section. Suggest two PRs if needed: fixture + events/flows text first.

Prompt:
```
Read CLAUDE.md, ARCHITECTURE.md, /mnt/project-files/lfmap-docs/02_Plugin_Contract.md (v0.1.1), PR #209, docs/specs/events.md, docs/specs/flows.md (incl. §13) and docs/specs/model-client.md if merged. Write Plugin Contract v0.2 to match the current code (not aspirational) and add a frozen old-plugin fixture test in lfmap-core that must keep loading and running. Tests first. Docs for the contract go in the PR as a diff for the owner to copy to the project file. Run uv run pytest and ruff. Open a PR with "Refs #192".
```

## Card E: #191 scenario template (docs only, Wed 11/11)

- File scope: new `docs/specs/acceptance-scenarios.md` (template + 1 filled example using `markitdown`, `knowledge` on ghost data; fields: trigger, input, expected output, approval step, plugins used, data class).
- Hùng fills 2–3 real scenarios Wed 11:00–12:00; flows/regression suite is a later card.
- Blockers: none for the template; RT-07 (#166) n8n export not needed.

Prompt:
```
Read CLAUDE.md, issue #191 and docs/research/2026-11-08-architecture-review.md (C2). Write docs/specs/acceptance-scenarios.md: a fill-in scenario template (trigger, input, expected output, approval step, plugins, data class, success check) with one worked example on synthetic data, short enough for the owner to fill in 15 minutes each. Docs only. Open a PR with "Refs #191".
```
