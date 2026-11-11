# Handoff addendum: start card for DC-4 (#235)

Issue: [#235](https://github.com/hungnp1999/lfmap/issues/235). Parent handoff: [2026-11-10-adr-025-data-classes.md](2026-11-10-adr-025-data-classes.md) (section DC-4). Spec: [docs/specs/data-classes.md](../specs/data-classes.md) (sections 4, 4.2, 6, 7). Umbrella: #197. Card format follows [2026-11-11-dc2-start-card.md](2026-11-11-dc2-start-card.md).

## State on main (2026-11-11)

- DC-1 (#243), DC-3 (#248) and DC-2 (#256) are merged, so the blockers of #235 are gone (remove the `blocked` label when the PR opens).
- Available to reuse: `data_classes.load_class_map`, `ClassMap.lookup/class_of/class_under`, `cli._require_code` (TOTP once enrolled, else typed code; refuses without a terminal), `cli._interactive`, `config.add_folder` (one-line TOML editor, temp file + `os.replace`), `jobs_doctor.other_writers`, `auth.enrolled`.
- Executor: Claude Code, Cloud, **Sonnet** (the issue says so). One PR, draft, `Refs #197` and `Closes #235`.

## Scope (from the issue)

May change or create: `cli.py` (`data` command group), `config.py` (a one-line editor for `[data.classes]`), `jobs_doctor.py` (two checks), additions to `test_cli_config.py` and `test_jobs_doctor.py`, `docs/approvals.md`, one changelog fragment. Also `ARCHITECTURE.md` if the module map changes (it should not).

Must not touch: `approval.py`, `permissions.py`, `data_classes.py` behaviour, adapters, plugins.

## Decisions for the executor (reversible, taken here so the session does not stall)

1. `config.py` gets two small functions next to `add_folder`, e.g. `set_data_class(path, cls)` and `remove_data_class(path)`, sharing the line-editing helpers already in the file. They edit only the one line inside `[data.classes]`, create the table when absent, keep comments and other tables byte for byte, and return the previous class (or `None`).
2. "Lowering" is decided by comparing `class_of(path)` **before and after** using the order `scratch < normal < private < secret`. A path with no entry counts as `private` before (spec 4.1). Raising or equal: yes/no confirmation only. Lowering: `_require_code` (no extra yes/no on top).
3. The file after the edit must still load with `load_class_map`; validate the new text first (write to temp file, load, then `os.replace`). On an invalid result nothing is written. A key containing a single quote is refused with the hand-edit message of spec 7.
4. `explain` and `classes` never touch the file system beyond reading the config (and the string remote check before any `realpath`, like `load_class_map`).
5. Audit: `classify` and `unclassify` write one decision line each with `reason` `data classify <old> -> <new>` / `data unclassify <old> -> <new>` and `target` = the path; refusals (no terminal, wrong code) also write a line, as `add-folder` does. Reuse the existing audit helper used by `add-folder`; do not add audit fields.
6. Doctor: add `_check_data_classes` and `_check_auth` to `run_checks`. Existing tests count the checks, so update them rather than special-casing. Keep warnings as `Check(name, None, detail, fix)` like the others. Missing config or no table: `data_classes` OK with "no table (class model off)".

## Start prompt (paste into a new Claude Code Cloud session, model Sonnet, repo lfmap)

```
Task DC-4 of lfmap #197 / issue #235 (ADR-025: `lfmap data` commands and two doctor checks). Read docs/handoff/2026-11-11-dc4-start-card.md, docs/handoff/2026-11-10-adr-025-data-classes.md (section DC-4) and docs/specs/data-classes.md (sections 4, 4.2, 6, 7). DC-1, DC-2 and DC-3 are on main. Branch from up-to-date main; merge origin/main again before push.

File scope: cli.py (new `data` command group: classes, explain, classify, unclassify), config.py (one-line editor for [data.classes]), jobs_doctor.py (checks data_classes and auth), additions to tests/test_cli_config.py and tests/test_jobs_doctor.py, docs/approvals.md, changelog.d/197-data-commands.added.md. Do not touch approval.py, permissions.py, data_classes.py, adapters or plugins. If you need another file, stop and report.

Write the frozen tests first with exactly these names: test_classify_lowering_needs_code, test_classify_keeps_comments, test_unclassify_last_entry_turns_off. Hand-write expected values. test_classify_lowering_needs_code: lowering asks the owner code through _require_code (no code, no change to the file), raising only asks yes/no. test_classify_keeps_comments: comments and other tables are byte-identical after classify; table created when absent. test_unclassify_last_entry_turns_off: removing the last entry leaves an empty table and the command says the feature is off; load_class_map then returns a falsy map. Add small extra tests for explain, classes, refusal of a single-quote path, refusal of UNC/device keys before any I/O, no-terminal refusal, and the two doctor checks (OK and warning rows of spec section 7).

Rules: classify/unclassify run only at an interactive terminal; lowering is decided by comparing class_of before and after; validate the edited text with load_class_map before os.replace and write nothing on failure; edit only the one line, keep comments; remote-path string check before any realpath; no secret, code or otpauth URI in any output or audit line; audit reason strings exactly as in spec section 6. Existing tests that count doctor checks must be updated, nothing else edited in old tests.

Run uv run pytest and uv run ruff check . and uv run ruff format --check . (7 test_jobs_doctor failures on Linux are pre-existing; compare against that baseline). Update docs/approvals.md (commands and the lowering rule). Commit trailers: Dev-Environment: cloud and Claude-Session (the cloud hook may not add Dev-Environment: add it by hand). Draft PR from the template with "Refs #197" and "Closes #235". Then run /security-review on the diff (the command writes config.toml) and answer every finding in the PR. Do not merge; report the PR link.
```

## Review checklist for the thread (after the PR)

- Only files in the scope list changed; `data_classes.py`, `approval.py`, `permissions.py` untouched.
- The 3 frozen tests exist with those names; old suites green except the 7 known Linux failures; CodeQL green.
- Lowering (including removing a more-protective entry and `secret` to anything lower) needs the owner code; raising does not; no write happens before the code is accepted.
- The edited file is validated before `os.replace`; comments preserved; atomic write.
- Doctor wording matches spec section 7; no secret or URI in output or audit.
- `/security-review` findings answered. Verdict: Approve / Approve with changes / Reject. Merge squash only when not draft.
