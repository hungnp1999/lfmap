# Module Spec: data classes in the approval gate and TOTP for self-granting commands (ADR-025)

- Package: `lfmap-core` (flat modules next to `approval.py` and `permissions.py`); small changes in `lfmap-knowledge` and `plugins/lfmap-markitdown`
- Decision: ADR-025, Accepted 2026-11-10 (four classes `scratch | normal | private | secret`, unclassified = `private`, `secret` reads are T1). It amends ADR-017 (1) and adds a layer to ADR-023. ADR-016, ADR-018 and ADR-020 are unchanged.
- Issue: #197 (S1 of the security core, epic #157). Must land before the `organizer` spec.
- Related: [`docs/specs/model-client.md`](model-client.md) section 4 rule 5 and decision 3 (a class label must travel with data before any cloud route is enabled); [`docs/approvals.md`](../approvals.md) (user documentation of tiers, grants and the typed code)
- Handoff and task list: [`docs/handoff/2026-11-10-adr-025-data-classes.md`](../handoff/2026-11-10-adr-025-data-classes.md)
- Status: **draft for the owner's handoff gate.** No code in this PR.

## 1. Purpose

Today the gate sets a tier from the kind of action only. Overwriting a scratch draft asks exactly like overwriting a signed contract, and reading a folder of identity documents leaves no trace. ADR-025 lets the owner say how much each folder matters, once, in `config.toml`, and has the gate use it:

- less friction where nothing is at stake (`scratch`: an overwrite is audited, not asked);
- more protection where it matters (`secret`: every read is audited, every write asks);
- one source for the class of a path, shared by the gate, `knowledge` and the model router;
- a second factor from the owner's phone (TOTP) for commands that widen rights.

Non-goals: per-file labels, content inspection, encryption at rest, classes for non-file data (mail, clipboard), a UI, passkeys (#199, Phase 3), incident retreat (S4, Phase 3), enabling any cloud model route.

## 2. What the ADR leaves open, and how this spec closes it

Reading the code against the ADR shows five gaps. Each is closed here; the first two change the shape of the work and are the ones the owner should read.

| # | Gap | Resolution in this spec |
| --- | --- | --- |
| G1 | The ADR says "one call in `approval.py`", but the gate never sees a path. Adapters call `gate(call_tier(...), "side_effects")` before the operation runs; paths only appear inside the plugin, at `ctx.permissions.require_read/require_write`. | Classes are applied where core already sees every caller-supplied path: a hook in `PermissionManager` (raises for `secret`) and a `paths=` argument on `ctx.require_approval` (lowering for `scratch`). Section 5. |
| G2 | `ModelRouter` takes the data class from the caller (`data="normal"` by default). The class the owner set on a folder does not reach it, which is why cloud routes are refused today (`allow_cloud_unlabelled`). | Each call carries a **call label**: the highest class of any path the call read. The router uses `max(declared, call label)`. Section 8. Flow steps and the removal of `allow_cloud_unlabelled` are a follow-up (section 8.4). |
| G3 | Two vocabularies: gate and router use `normal | private | secret` (`DataLevel`), the ADR adds `scratch`. | `scratch` is an approval convenience, not a confidentiality level. For egress it counts as `normal`. `DataLevel` stays three values, derived by `egress_level()`. |
| G4 | A plugin may be handed a folder (`markitdown.export --output-dir`) and then touch files below it that core never checks one by one. | A path is classified by the highest class **at or below** it (`class_under`), so a `secret` entry nested in a `normal` folder makes the whole folder call `secret`. |
| G5 | DPAPI protects the TOTP secret from other Windows accounts, not from a process running as the owner. | Stated plainly in section 9.6: the OS account stays the boundary (ADR-023); TOTP defeats blind or scripted answers from anything that cannot read the owner's profile. |

## 3. Modules

| Module | Content | Task |
| --- | --- | --- |
| `data_classes.py` (new, leaf module) | `DataClass`, `ClassMap`, `load_class_map`, `adjust`, `egress_level`, `highest`. Pure except for `realpath` on declared entries at load. Imports nothing from `approval.py`. | DC-1 |
| `data_guard.py` (new) | `ClassGuard`: per-call object that receives path events from `PermissionManager`, asks the approver with the adjusted tier, keeps the call label. At most 120 code lines. | DC-2 |
| `permissions.py` | optional `on_path(access, resolved)` callback, called after a path passed the root check (and for typed reads) | DC-2 |
| `tool.py` | `ctx.require_approval(..., paths=...)`, `ctx.data_label`, `ctx.mark_data(path)` | DC-2 |
| `approval.py`, `approvals.py` | approvers accept `data_class` and `action_tier` and write them to the audit line; two new `AUDIT_FIELDS` | DC-2 |
| `runtime.py` | builds the `ClassGuard` in `build_tool`, shares it in `context_for` | DC-2 |
| `totp.py` (new) | RFC 6238 code generation and verification, pure, standard library | DC-3 |
| `auth.py` (new) | enrolment file `auth.json`, DPAPI wrapper, replay and lockout state | DC-3 |
| `cli.py` | `lfmap auth enroll|status|reset`; `_require_code` asks for TOTP when enrolled; T3 proposals ask for the code; `lfmap data classes|explain|classify|unclassify` | DC-3, DC-4 |
| `config.py` | line editor for `[data.classes]` (same technique as `add_folder`) | DC-4 |
| `jobs_doctor.py` | checks `data_classes` and `auth` | DC-4 |
| `lfmap-knowledge` | root class from the shared map; marks the call label on `search` and `get_context` | DC-5 |
| `models_router.py` | effective data class = `max(declared, call label)` | DC-5 |

No new dependency. `ARCHITECTURE.md` gets the new modules and invariants of section 10 in the DC-2 and DC-3 PRs.

## 4. `[data.classes]` in `config.toml`

```toml
[data.classes]
'D:\Tmp'                 = "scratch"
'D:\Work'                = "normal"
'D:\Work\Contracts'      = "secret"
'C:\Users\Admin\Scans'   = "secret"
```

Rules, all checked when the table is loaded (`load_class_map(config)`):

1. Keys are absolute local paths; TOML literal strings (single quotes) keep backslashes readable. Values are one of the four class names.
2. A key that is a UNC, `\\?\`, `\\.\` or `//` path is refused **before any file-system call** (string check, same helper as `permissions._is_remote`). Each remaining key is resolved with `os.path.realpath`; a result that is remote is refused. A key that does not exist yet is allowed (the folder may be created later).
3. A key inside the application folder (`%LOCALAPPDATA%\lfmap`) is refused: plugin `data_dir` and `temp_dir` stay outside the class model (ADR-016).
4. Two keys that resolve to the same path are an error (no silent winner).
5. Any violation is `ToolError("invalid_input", "[data.classes] in config.toml is invalid", ...)`, as for `[approval]`. Gated calls then fail until the owner fixes the file; nothing falls back to a looser reading.
6. **No table, no feature.** When `[data.classes]` is absent or empty, no guard is built, no label is kept and every code path behaves as before this spec (the ADR's reversibility promise). A table with at least one entry turns the model on, and from then on every path in no entry is `private`.

Order of classes: `scratch < normal < private < secret`. `highest()` uses this order.

### 4.1 Looking a path up

Input is always a path that core has already resolved (`realpath`), compared case-insensitively on Windows (`os.path.normcase`), with the inline `startswith` plus separator test used in `PermissionManager._require`.

- `class_of(path)` returns the class of the **most specific entry at or above** the path (longest matching entry), and that entry; `private` and no entry when none matches.
- `class_under(path)` returns the highest of `class_of(path)` and every entry **strictly below** the path. This is the value the guard uses (gap G4). For a file it equals `class_of`.

Example with the table above: `D:\Work\notes.md` is `normal`; `D:\Work\Contracts\a.pdf` is `secret`; the folder `D:\Work` as a whole is `secret` (it contains a `secret` entry); `D:\Other\x.txt` is `private`.

### 4.2 Who may change it

- The file is the owner's (`config.toml` in the owner's profile, ADR-023 ACL). No operation and no MCP tool writes it.
- By hand: any edit, as today for `[paths]` and `[approval]`.
- `lfmap data classify <path> <class>` and `lfmap data unclassify <path>` (section 7) run only at an interactive terminal. If the change **lowers** the class of the path (compare `class_of(path)` before and after), the command also requires the owner code (TOTP when enrolled, else the typed random code). Raising needs a yes/no confirmation only.
- `organizer` (later spec) proposes classes into the approvals queue; approving such a proposal runs the same code path as `data classify`.

## 5. Tier adjustment

### 5.1 The pure function

`adjust(action_tier, access, data_class) -> tier`, with `access` in `read | write`:

| Class | Read | Write |
| --- | --- | --- |
| `scratch` | unchanged | T2 becomes T1; T0, T1, T3 unchanged |
| `normal` | unchanged | unchanged |
| `private` | unchanged | unchanged |
| `secret` | at least T1 | at least T2 |

Invariants (each has a frozen test, section 11):

- T3 in is T3 out, for every class and access.
- The result is never below `action_tier - 1` and never above T3.
- A write is never below T1.
- An unknown class or tier raises `ValueError`; the caller (`ClassGuard`) catches any exception from `adjust` and uses the action tier (ADR risk table: "on error use the action tier"), and for a `secret` path uses the raised tier computed by a literal fallback (`T1` read, `T2` write) so that an error can never drop a `secret` protection.

The ADR-020 clamp is untouched: `runtime.call_tier` still computes the pre-call tier between `min_tier` and the declared tier, and the pre-call `gate(tier, "side_effects")` runs as today, before any path is known.

### 5.2 Where the action tier comes from

Core sees three kinds of path events during a call. Each has a fixed action tier:

| Event | Seen at | Action tier |
| --- | --- | --- |
| read | `require_read` succeeded, or a typed read outside the roots (`_typed_read`) | T0 |
| create | `require_write` succeeded | T1 |
| destructive | `ctx.require_approval(reason, detail, paths=[...])` with a reason other than `"external"` | T2 |

`"external"` approvals (T3) never involve the guard's tier logic; they only use the call label (section 8).

### 5.3 `ClassGuard` behaviour

One guard per operation call, built by `runtime.build_tool` when the class map is not empty and an approver is attached (plain SDK use has no approver and stays the owner's own code). `context_for` shares the parent's guard, so an in-process call to another plugin is covered by the same label and memo.

On a **read** event for resolved path `p`:

1. `c = class_under(p)`; raise the call label to `c`.
2. If `c` is `secret`: call the approver with tier T1, reason `secret_read`, target `p`, `data_class="secret"`, `action_tier="T0"`. Once per call per matching entry (memo), so indexing a `secret` folder writes one line, not one per file.

On a **create** event for `p`:

1. `c = class_under(p)`; remember `p` in the call's write set. The call label is not raised by writes.
2. If `c` is `secret`: call the approver with tier T2, reason `secret_write`, target `p`, `data_class="secret"`, `action_tier="T1"`. Once per call per entry. The approver decides exactly as for any T2 (ask at a TTY, elicitation or `--approve` on `mcp`, proposal on `job`/`event`/`flow`), and a refusal raises `permission_denied` out of `require_write`, so the plugin never receives the path.

On a **destructive** approval with `paths`:

1. The guard resolves each declared path itself (string remote check, then `realpath`; no root check, this is classification only) and takes `c = highest(class_under(q) for q in declared paths + the call's write set)`.
2. `tier = adjust("T2", "write", c)`: T1 when everything is `scratch`, else T2.
3. The approver is called with that tier, the plugin's reason and detail, `data_class=c`, `action_tier="T2"`.
4. Without `paths` (every plugin written before this spec) nothing changes: T2, no class recorded. Lowering is opt-in and needs the plugin to say what it is about to overwrite; raising never depends on the plugin.

A plugin is in-process Python and already trusted not to lie (it could skip `require_approval` altogether). The adversary in this model is the caller (an agent choosing inputs), and a caller cannot influence classification: classes come from the owner's file and from paths core resolved.

### 5.4 Channels (no new rules)

The adjusted tier goes through the existing `decide` / `job_decision` logic. Consequences worth stating:

| Case | `cli` | `mcp` | `job`, `event`, `flow` |
| --- | --- | --- | --- |
| read in `secret` (T1) | runs, audited | runs, audited | runs when the ceiling `max_tier >= 1`, else becomes a proposal |
| create in `secret` (T2) | asks | elicitation, `--approve` or grant | proposal |
| overwrite in `scratch` (T1) | runs, audited | runs, audited | runs when `max_tier >= 1`, else proposal |
| overwrite elsewhere (T2) | as today | as today | as today |

- A scheduled `knowledge.reindex` over a `secret` root therefore needs `max_tier = 1` on that job, or it queues a proposal on each run. The DC-5 notes and `jobs doctor` say so.
- A `secret` line is written even when the owner set `[approval] T1 = "allow"`: for `data_class == "secret"` the approvers always write the audit line.
- `deny` in the policy still wins. Permission roots never widen: a class never makes a path readable or writable.

## 6. Audit

Two fields are added to `AUDIT_FIELDS`: `data_class` (one of the four names) and `action_tier` (the tier before adjustment). `tier` keeps its meaning: the tier the decision was made on. They are written on every decision line that involved a classified path; lines without a path (the pre-call `side_effects` line, grants) are unchanged. The existing `data` field of `model_call` lines keeps the egress level (`normal | private | secret`).

```json
{"time": "...", "principal": "owner", "channel": "mcp", "plugin": "markitdown", "operation": "export",
 "tier": "T1", "action_tier": "T2", "data_class": "scratch", "decision": "allow",
 "reason": "overwrite", "target": "D:\\Tmp\\out"}
```

New decision lines for the commands of sections 7 and 9: `reason` is `data classify <old> -> <new>`, `data unclassify <old> -> <new>`, `auth enroll`, `auth reset`, `auth locked`; `target` is the path for the `data` commands. No secret, code or `otpauth` URI is ever written.

## 7. Commands

```text
lfmap data classes [--json]          # the table as loaded: resolved path, class; warns on missing folders
lfmap data explain PATH [--json]     # class_of, the entry that decided, class_under; read-only
lfmap data classify PATH CLASS       # add or change one entry; interactive; owner code when lowering
lfmap data unclassify PATH           # remove one entry; interactive; owner code when lowering
```

- `explain` resolves `PATH` after the string remote check and does not need the path to be inside any plugin root; it reads nothing but the config.
- `classify` and `unclassify` edit only the one line inside `[data.classes]` (create the table when absent), keep comments, write through a temp file and `os.replace`, like `config.add_folder`. A path that contains a single quote cannot be a TOML literal key: the command refuses and tells the owner to edit by hand.
- Both print the effect before asking: `D:\Tmp: private -> scratch (lower). Overwrites here will be audited instead of asked.`
- After `unclassify` removes the last entry the table is empty and the feature is off (rule 6 of section 4); the command says so.

`lfmap jobs doctor` gains two checks:

| Check | OK | Warning |
| --- | --- | --- |
| `data_classes` | table valid; lists every `scratch` entry so a mistake is visible | entry folder missing; a `scratch` entry that contains or lies inside a `[paths] knowledge` root; old `[plugins.knowledge.settings.sensitivity]` still present |
| `auth` | TOTP enrolled, date | not enrolled (the typed code is in use); `auth.json` writable by another account (reuses `other_writers`) |

## 8. The call label and the model router

### 8.1 Label

`ClassGuard.label` is the highest class of every path the call has **read** so far (`None` when it read none). `ctx.data_label` exposes it read-only. `ctx.mark_data(path)` lets a plugin raise it for content that came from a path without a file read in this call (an index, a cache); it classifies the path with `class_under` and can only raise the label. There is no way to lower it.

### 8.2 `ModelRouter`

`_call` computes `effective = max(egress_level(declared data), egress_level(label))` when a guard exists, and uses `effective` everywhere it uses `data` today: the `secret` refusal for cloud endpoints, the `destination=..., data=...` argument of the T3 approval, and the `data` field of both `model_call` lines. Nothing else changes: `embed` stays local, `cloud_ai` and `network` are still required, the T3 gate is still asked, local endpoints accept any class and write no line.

So `llm.summarise` in a flow step or CLI call that read a file under a `secret` entry can no longer reach a cloud endpoint by declaring `data = "normal"`, and a call that read an unclassified file counts as `private`, which a destination approved for `normal` does not cover.

### 8.3 `knowledge`

- The class of a root is `class_under(root)` from the shared map; the catalog column `roots.sensitivity` stores `egress_level(class)` so its `CHECK` constraint and the `mcp`/`rest` hiding rule need no migration. A root that contains a `secret` entry is hidden as a whole on `mcp` and `rest`; the documentation tells the owner to make such a folder its own root if the rest should stay visible.
- Old key: when `[data.classes]` is absent, `[plugins.knowledge.settings.sensitivity]` is read exactly as today (one release). When both exist the shared map wins and `jobs doctor` warns. Note the changed default: with the shared map an unlisted root is `private`, not `normal`. Nothing in `knowledge` distinguishes the two today.
- `search` and `get_context` call `ctx.mark_data(root)` for the root of every hit they return, so text that leaves `knowledge` inside the same call (an in-process `context_for` caller) carries the label.

### 8.4 What still blocks cloud routes (follow-up, not in this handoff)

The label lives for one operation call. Two hops lose it:

1. **Flow steps.** Step B receives step A's output through `${steps.A...}` in a new call. Design direction: `FlowRun` stores each finished step's label; a step whose input references earlier steps starts its guard with `floor = highest(labels of the referenced steps)`. This touches `flows_run.py`, which has a line cap, so it gets its own card (DC-6) after DC-5.
2. **An agent in the middle.** On `mcp` an agent can read text with one tool and pass it to `llm` as plain input. Core cannot follow text through an agent. The existing controls stay the answer: `secret` roots are hidden on `mcp`, and a cloud call on `mcp` passes only with a preapproved destination. Residual risk: `private` text declared `normal` by an agent, to a destination approved for `normal` only.

`[models] allow_cloud_unlabelled` therefore stays, default off. Removing it is an owner decision after DC-6, with this residual risk on the table.

## 9. TOTP for self-granting commands

### 9.1 Scope

`_require_code` in `cli.py` becomes the single "owner code" prompt. When TOTP is enrolled it asks for the 6-digit code from the authenticator app; when not, it asks for the typed random code as today. It is used by every command that uses the typed code now (`approvals grant`, `approvals revoke`, `config add-folder`, `backup restore`) and by three new places: lowering a data class, `approvals approve` of a proposal whose recorded tier is T3, and `auth enroll` when replacing an existing enrolment. T1/T2 proposals and `flows.resume` keep the yes/no prompt. The interactive-terminal check comes first in every case and is unchanged.

The prompt shows the exact action before asking, as today: `To grant powershell.run up to T3 for 2h, enter the code from your authenticator app:`.

### 9.2 `totp.py` (pure)

- RFC 6238 with HMAC-SHA-1, 30-second step, 6 digits; RFC 4226 dynamic truncation; `hmac`, `hashlib`, `struct`, `base64`, `secrets` only.
- `new_secret()`: 20 random bytes. `provisioning_uri(secret, account="owner", issuer="LFMAP")`: `otpauth://totp/LFMAP:owner?secret=<base32>&issuer=LFMAP&algorithm=SHA1&digits=6&period=30`.
- `verify(secret, code, now, last_step) -> step | None`: accepts the current step and the one before it (clock skew and typing time), compares with `hmac.compare_digest`, and refuses any step `<= last_step` (each code works once). Input must be exactly six ASCII digits after stripping spaces.

### 9.3 `auth.py` and `auth.json`

`%LOCALAPPDATA%\lfmap\auth.json` (owner profile; agents cannot read it, ADR-023):

```json
{"version": 1, "secret": "<base64 of the DPAPI blob>", "enrolled_at": "...", "last_step": 0,
 "failures": 0, "locked_until": null}
```

- The secret is encrypted with Windows DPAPI for the current user (`CryptProtectData` / `CryptUnprotectData` from `crypt32` through `ctypes`, flag `CRYPTPROTECT_UI_FORBIDDEN`). The protector is injected (`Protector` Protocol) so tests run on Linux with a fake; on a non-Windows system `auth enroll` refuses (`backend_unavailable`) and the typed code remains.
- `check(code)`: refuse while locked; verify; on success write `last_step` and reset `failures` **before** returning (temp file and `os.replace`), so a crash cannot allow a replay; on failure increment `failures`, and at 5 set `locked_until = now + 5 min` and write an `auth locked` audit line.
- An unreadable or invalid `auth.json` is **not** "not enrolled": it fails closed (`permission_denied`, hint `lfmap auth reset`). Only a missing file means not enrolled.
- `auth.json` is excluded from `lfmap backup` (a DPAPI blob is useless on another account or machine); after a restore on a new machine the owner enrols again.

### 9.4 Commands

```text
lfmap auth enroll      # interactive; prints the otpauth URI and the base32 secret once; asks for one code to confirm
lfmap auth status      # enrolled or not, date, locked or not; never the secret
lfmap auth reset       # interactive; typed random code; removes auth.json; audited
```

- `enroll` stores nothing until the first code verifies. v1 prints text for manual entry in the app (32 base32 characters); a QR code needs an encoder we do not have and no dependency is added for it (noted as a possible in-house follow-up).
- Replacing an enrolment requires the current TOTP code. A lost phone goes through `reset`.
- `reset` is the documented fallback of the ADR: it needs a person at a visible console and the typed code, after which commands use the typed code until the next `enroll`.

### 9.5 Tests need no phone

`totp.verify` takes `now` as an argument; the RFC 6238 Appendix B vectors (secret `12345678901234567890`, last six digits of the published SHA-1 values: 59 s `287082`, 1111111109 s `081804`, 1111111111 s `050471`, 1234567890 s `005924`, 2000000000 s `279037`, 20000000000 s `353130`) are the frozen reference.

### 9.6 What TOTP does and does not add

- It **does** stop anything that can type into the owner's console but cannot read the owner's profile, and it removes the weakness that the typed code is printed on the same screen it is typed into. It also prepares remote approval surfaces (Chat UI, Phase 3), where the code proves the phone is present.
- It **does not** stop a process running as the owner: such a process can read `auth.json`, call DPAPI and compute codes, exactly as it can edit `grants.json` today. The boundary remains the separate Windows account for agents (ADR-023).
- `auth reset` needs only a visible console and the typed code, so the reset path is as strong as today's typed code, not stronger. Mitigation: the audit line, and `jobs doctor` showing the enrolment date. A cool-down after reset was considered and left out (not in the ADR; adds state for little gain while the OS account is the boundary).

## 10. Invariants (for `ARCHITECTURE.md` when the code lands)

- Classes come only from `[data.classes]` in the owner's `config.toml`; no operation, MCP tool, flow or plugin sets or lowers a class. An unlisted path is `private` once the table has an entry.
- A class changes whether a person is asked and what is audited. It never widens a permission root.
- Core classifies paths it resolved itself (`realpath`, inline `startswith` guard). A plugin can raise the call label, never lower it.
- `secret`: every read is audited at T1 or above, every write is asked at T2 or above, and its content never goes to a cloud endpoint. A failure in the adjustment code cannot remove these.
- T3 is never lowered by a class. `scratch` lowers only a destructive T2 to T1, only when every path the call declared and wrote is `scratch`.
- The TOTP secret is stored DPAPI-encrypted in the owner's profile, never logged, never backed up; each code is accepted once; five wrong codes lock for five minutes.

## 11. Frozen tests (names fixed; written first in each task)

| Test | Asserts | Task |
| --- | --- | --- |
| `test_adjust_table` | all 32 rows (4 classes x 4 tiers x read/write) of section 5.1 | DC-1 |
| `test_adjust_never_lowers_t3`, `test_adjust_clamp` | T3 stays T3; result in [action - 1, T3]; write never below T1 | DC-1 |
| `test_class_of_most_specific`, `test_class_default_private`, `test_class_under_takes_nested_highest` | section 4.1, including case-insensitive match and the `D:\Work` example | DC-1 |
| `test_class_map_refuses_remote_before_io` | UNC, `\\?\`, `\\.\`, `//` keys are refused and `os.path.realpath` is not called for them | DC-1 |
| `test_class_map_invalid` | relative key, unknown class, key inside the app folder, duplicate after resolving: `invalid_input` | DC-1 |
| `test_no_table_no_change` | without `[data.classes]` no guard is built and the audit lines of an export are byte-identical to today's | DC-2 |
| `test_secret_read_audited_once` | T0 operation reading two files under one `secret` entry: one `secret_read` line, `tier` T1, `action_tier` T0, also with `[approval] T1 = "allow"` | DC-2 |
| `test_secret_write_asks` | create under `secret`: asked on `cli`; `permission_denied` on `mcp` without elicitation; proposal on `job`; the plugin never gets the path when refused | DC-2 |
| `test_scratch_overwrite_is_t1` | `require_approval("overwrite", paths=[scratch])`: no question, line with `tier` T1, `action_tier` T2 | DC-2 |
| `test_scratch_not_lowered_when_mixed` | declared `scratch` path plus an earlier write to a `normal` path, or a `scratch` folder containing a `normal` entry: T2 | DC-2 |
| `test_overwrite_without_paths_unchanged` | old call form stays T2 with no class fields | DC-2 |
| `test_external_never_lowered` | `require_approval("external", ...)` is T3 for every class | DC-2 |
| `test_adjust_error_keeps_secret_floor` | `adjust` patched to raise: `secret` read still T1, write still T2; other classes use the action tier | DC-2 |
| `test_junction_into_scratch_classified_by_target` | a link inside a `scratch` entry that resolves into a `secret` entry is `secret` (Windows junction or POSIX symlink) | DC-2 |
| `test_context_for_shares_guard` | a read by an in-process callee raises the caller's label | DC-2 |
| `test_totp_rfc6238_vectors` | the six vectors of section 9.5 | DC-3 |
| `test_totp_single_use`, `test_totp_window` | same code twice is refused; previous step accepted, two steps back and next step refused | DC-3 |
| `test_auth_lockout`, `test_auth_corrupt_fails_closed`, `test_auth_never_logged` | 5 failures lock for 5 minutes; invalid file is not "not enrolled"; neither secret nor URI appears in `audit.jsonl` or captured output after `enroll` except the one enrolment print | DC-3 |
| `test_require_code_uses_totp_when_enrolled`, `test_t3_proposal_needs_code` | typed code path unchanged when not enrolled; T3 proposal approval asks the owner code, T2 does not | DC-3 |
| `test_classify_lowering_needs_code`, `test_classify_keeps_comments`, `test_unclassify_last_entry_turns_off` | section 7 | DC-4 |
| `test_router_uses_call_label` | declared `normal` + label `secret`: cloud refused, nothing sent; label `private`: destination approved for `normal` does not cover; local route unaffected | DC-5 |
| `test_knowledge_root_class_from_shared_map`, `test_knowledge_legacy_sensitivity_fallback`, `test_knowledge_marks_label` | section 8.3 | DC-5 |

The existing suites `test_approval.py`, `test_approvals.py`, `test_call_tier.py`, `test_permissions.py`, `test_explicit_read.py`, `test_models_router.py` and the frozen plugin fixture of Plugin Contract v0.1.1 (`test_plugin_compat.py`) must pass unedited in DC-2: the change is additive for plugins that pass no `paths`.

## 12. Plugin Contract impact (v0.2, additive)

- `ctx.require_approval(reason, detail="", *, destination="", data="normal", paths=())`: a plugin that overwrites, renames or deletes should pass the paths it is about to change. Omitting them keeps T2.
- `ctx.data_label` (read) and `ctx.mark_data(path)` (raise only).
- A plugin never reads `[data.classes]` itself and never decides a tier from a class.
- `markitdown.export` passes `paths=[output_dir]` in DC-2; it is the only current caller of `require_approval("overwrite")`.

The contract text lives outside the repo; the wording goes in the DC-2 PR body under "Cập nhật tài liệu dự án".

## 13. Risks

| Risk | Control | Residual |
| --- | --- | --- |
| The hook is skipped by a path that does not go through `PermissionManager` | Existing invariant (every caller-supplied path goes through it) plus `test_junction_...`; `/security-review` on DC-2 | Low |
| Owner marks a real folder `scratch` | Only T2 to T1, still audited; `jobs doctor` lists `scratch` entries; lowering needs the owner code | Low to medium |
| Prompt fatigue returns through `secret` writes | Asked once per call per entry, not per file | Low |
| Scheduled jobs over `secret` roots start queueing | Documented; `jobs doctor` hint; `max_tier = 1` | Low, visible |
| `class_under` makes a big folder `secret` because of one nested entry | Intended (fail closed); `data explain` shows why | Low, usability |
| Label lost across flow steps or through an agent | Cloud routes stay off (`allow_cloud_unlabelled`), DC-6 | Tracked |
| TOTP gives a false sense of security against owner-account malware | Section 9.6 states the limit; ADR-023 boundary unchanged | Accepted |
| Lockout or lost phone blocks the owner | `auth reset` at a console; 5-minute lock only | Low |

## 14. Decisions taken in this spec (reversible; the owner may overrule at the handoff gate)

| # | Decision | Rejected option |
| --- | --- | --- |
| 1 | Apply classes at `PermissionManager` and `require_approval(paths=)` (G1) | Pass paths to the pre-call gate from the adapter: adapters do not know which input fields are paths, and plugin-specific code in adapters is forbidden |
| 2 | `scratch` counts as `normal` for egress (G3) | Treat `scratch` as `private` for egress: safer, but breaks the single order that `organizer` needs ("same class or upwards") |
| 3 | A folder takes the highest class at or below it (G4) | Classify by the folder's own entry only: a nested `secret` folder would be writable at T1 through its parent |
| 4 | Invalid `[data.classes]` stops gated calls | Treat everything as `private` and continue: hides a typo that the owner believes is protecting a folder |
| 5 | TOTP replaces the typed code everywhere the typed code is used, once enrolled | Only the four commands named in the ADR: two prompt styles to remember, and `backup restore` can replace `config.toml` |
| 6 | Enrolment shows text, no QR, in v1 | Add a QR dependency or write an encoder now |
| 7 | Lowering by `scratch` is opt-in per plugin call (`paths=`) | Infer from the write set alone: a plugin that never declares paths would get lowered approvals for overwrites core cannot see |

## 15. Task breakdown

Detailed cards, order and prompts are in the handoff. Summary: DC-1 pure module; DC-2 guard, audit and `markitdown.export`; DC-3 TOTP; DC-4 `lfmap data` commands and doctor; DC-5 `knowledge` and `ModelRouter`; DC-6 (later) flow-step labels; DC-7 owner set-up on pc-01.
