# Handoff addendum: start card for DC-2 (#234)

Issue: [#234](https://github.com/hungnp1999/lfmap/issues/234). Parent handoff: [2026-11-10-adr-025-data-classes.md](2026-11-10-adr-025-data-classes.md) (section DC-2). Spec: [docs/specs/data-classes.md](../specs/data-classes.md). Umbrella: #197.

## State on main (2026-11-11)

- DC-1 is merged (PR #243): `data_classes.py` with `adjust`, `ClassMap`, `load_class_map`.
- DC-3 is merged (PR #248): `totp.py`, `auth.py`, `cli.py` changes. DC-2 does not touch `cli.py`, but both edit `ARCHITECTURE.md` and `docs/approvals.md`: merge `origin/main` before push.
- Executor: Claude Code, Cloud, **Opus** (owner agreed 2026-11-10, the task touches the approval gate). One PR, draft, `Refs #197` and `Closes #234`.

## Review notes carried over from DC-1

1. `data_classes.py` imports the private `_is_remote` from `permissions.py`. DC-2 edits `permissions.py`: keep that name, or rename it in both files in the same PR (run `grep -rn _is_remote packages plugins`).
2. `test_adjust_table` in `test_data_classes.py` derives its expectations with logic close to `adjust` itself. DC-2 does not edit DC-1 tests, but if you extend the table logic, do not copy it into `test_data_guard.py`: hand-write expected tiers.
3. `data_classes.py` must stay a leaf (no import of `approval.py`); `data_guard.py` may import it, not the other way round.

## Start prompt (paste into a new Claude Code Cloud session, model Opus, repo lfmap)

```
Task DC-2 of lfmap #197 / issue #234 (ADR-025: the class guard in the approval gate). Read docs/handoff/2026-11-10-adr-025-data-classes.md (section DC-2), docs/handoff/2026-11-11-dc2-start-card.md and docs/specs/data-classes.md (sections 5, 6, 10, 11, 12). DC-1 (data_classes.py) and DC-3 are already on main. Branch from up-to-date main; merge origin/main again before push.

File scope: packages/lfmap-core/src/lfmap_core/data_guard.py (new, at most 120 code lines), permissions.py, tool.py, runtime.py, approval.py, approvals.py, plugins/lfmap-markitdown/src/lfmap_markitdown/tool.py (only add paths=[output_dir] to the existing require_approval call), new packages/lfmap-core/tests/test_data_guard.py, ARCHITECTURE.md, docs/approvals.md, changelog.d/197-data-guard.added.md. Do not touch cli.py, mcp_adapter.py, flows_run.py or any adapter. If you need a file outside this list or the guard exceeds 120 lines, stop and report.

Write the frozen tests first with exactly these names: test_no_table_no_change, test_secret_read_audited_once, test_secret_write_asks, test_scratch_overwrite_is_t1, test_scratch_not_lowered_when_mixed, test_overwrite_without_paths_unchanged, test_external_never_lowered, test_adjust_error_keeps_secret_floor, test_junction_into_scratch_classified_by_target, test_context_for_shares_guard. Hand-write expected tiers; do not re-derive them with the logic under test. Existing suites test_approval.py, test_approvals.py, test_call_tier.py, test_permissions.py, test_explicit_read.py, test_models_router.py, test_plugin_compat.py and test_data_classes.py pass unedited: without [data.classes] nothing changes, byte for byte in audit lines.

Rules: raising for secret happens in a PermissionManager hook and never depends on the plugin; lowering for scratch only through require_approval(paths=...), only when every declared path and every path written in this call is scratch; T3 is never lowered; a secret decision line is always audited; any exception from adjust keeps the action tier (and T1 read / T2 write for secret); classify only paths core resolved itself (string remote check, then realpath, then an inline startswith guard on the same variable); keep _is_remote consistent between permissions.py and data_classes.py; data_classes.py stays a leaf.

Run uv run pytest and uv run ruff check . and uv run ruff format --check . (7 test_jobs_doctor failures on Linux are pre-existing). Update ARCHITECTURE.md (module map and the invariants of spec section 10). Commit trailers: Dev-Environment: cloud and Claude-Session (the cloud hook may not add Dev-Environment: add it by hand). Draft PR from the template with "Refs #197" and "Closes #234", and list the Plugin Contract wording of spec section 12 under "Cập nhật tài liệu dự án". Then run /security-review on the diff and answer every finding in the PR. Do not merge; report the PR link.
```

## Review checklist for the thread (after the PR)

- Only files in the scope list changed; `data_guard.py` code lines at most 120.
- All 10 frozen tests exist with those names; old suites unedited and green; CodeQL green.
- Audit lines unchanged without `[data.classes]` (look for the byte-identical test).
- `secret` is raised in the hook, not by the plugin; `adjust` failure path covered.
- `ARCHITECTURE.md` carries the spec section 10 invariants; `/security-review` findings answered.
- Verdict: Approve / Approve with changes / Reject. Merge squash only when the PR is not draft.
