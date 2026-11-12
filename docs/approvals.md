# Approvals and grants

LFMAP asks before an operation does something you may not want (ADR-009, ADR-017, ADR-018). What is asked depends on the call's **tier**, the **channel** it arrives on, and any **grant** you made earlier. Approval only decides whether a person is asked; it never widens the folders a plugin may read or write (`[plugins.*.permissions]`).

## Tiers and channels

| Tier | Meaning | Default `[approval]` action |
|---|---|---|
| T0 | no side effects (a plugin's own data and temp folders count as none) | always runs |
| T1 | creates new files in a declared write folder | `audit`: runs, written to `audit.jsonl` |
| T2 | overwrites, renames or deletes | `ask` |
| T3 | sends data out, uses paid APIs, touches secrets or runs external commands | `ask`; can never be set to `allow` or `audit` |

A plugin operation starts at the tier of its manifest `side_effects` (`none` is T0, `local_write` T1, `external` T3). What happens to a call that needs a person:

| Channel | T1 / T2 | T3 |
|---|---|---|
| `cli` (`lfmap <plugin> <op>`) | asks at an interactive terminal; `--yes` / `-y` approves T1 and T2 | asks at an interactive terminal (`--yes` does not cover it) |
| `mcp` (`lfmap serve mcp`) | `--approve <plugin>.<op>`, a client that supports elicitation, or a grant | refused unless a grant or a preapproved destination covers it; elicitation does not |
| `job` (scheduled) | queued as a proposal, or runs under `max_tier` (below) | queued as a proposal |
| `event` (event adapter) | same as `job`, capped by `[events] max_tier` | queued as a proposal |

Without a person to ask (no terminal), the call is refused with `permission_denied`; the error's `hint` says what would allow it. The policy in `config.toml` can change the defaults per tier and per operation:

```toml
[approval]
T1 = "audit"                     # allow | audit | ask | deny
T2 = "ask"
operations = { "organizer.apply" = "deny" }   # "<plugin>.<operation>" overrides the tier action

[approval.destinations."api.example.com"]     # preapprove one T3 destination
data = "normal"                  # normal | private; secret data never leaves
expires = 2026-12-31             # at most 90 days from today
```

`deny` always wins. `allow` and `audit` for T3 are treated as `ask`. A preapproved destination only helps operations that report a destination; it does not cover jobs or events.

## Per-call tiers (`min_tier`, powershell)

A manifest operation may declare `min_tier`, a tier below its base tier. Core then asks the plugin for each call's tier and clamps it between `min_tier` and the base tier; if the plugin cannot say, the base tier applies. The `powershell` plugin uses this: `run` is `external` (T3) with `min_tier = "T1"`, and every allow-listed script has `tier = "T1" | "T2" | "T3"`, **default T3**. Lower it only for read-only scripts. Details: [docs/specs/powershell.md](specs/powershell.md).

## Time-limited grants

A grant covers one operation up to a tier for a limited time, on the `cli` and `mcp` channels. Jobs and events ignore grants. Only a person at an interactive terminal can create or remove one; no MCP tool and no operation can.

```powershell
uv run lfmap approvals grant powershell.run --tier T3 --for 2h
uv run lfmap approvals list
uv run lfmap approvals revoke powershell.run
```

- `--tier` is `T1`, `T2` or `T3` (default `T2`); a grant covers that tier and below.
- `--for` is a whole number plus `m`, `h` or `d` (`30m`, `1h`, `7d`; default `1h`). T3 grants last at most 24 h, T1 and T2 at most 7 d.
- Granting again for the same operation replaces the earlier grant. `revoke` removes every grant for the operation.
- `list` shows grants including expired ones (an expired grant counts as none).
- `grant` and `revoke` accept only a known `<plugin>.<operation>`.

`lfmap serve mcp --approve <plugin>.<op>` (repeatable) is the lighter alternative for one MCP session: it pre-approves up to T2 for 8 hours from server start and refuses T3 operations at start-up.

## The owner code: authenticator app or typed code

With an authenticator enrolled (`lfmap auth enroll`), every command below asks for the 6-digit code from the app instead of the typed code:

```text
To grant powershell.run up to T3 for 2h, enter the code from your authenticator app:
Code:
```

Each code works once, the current and the previous 30-second step are accepted, and five wrong codes lock the check for 5 minutes (an `auth locked` line goes to the audit log). Without an enrolment the typed code below works exactly as before. An unreadable `auth.json` refuses the command (`permission_denied`, fix with `lfmap auth reset`); it is never treated as "not enrolled".

```text
lfmap auth enroll   # Windows only: prints the otpauth URI and the secret once, stores them (DPAPI) after one code verifies;
                    # replacing an enrolment asks the current app code
lfmap auth status   # enrolled or not, since when, locked or not; never the secret
lfmap auth reset    # lost phone: typed code, removes auth.json, audited; the typed code is used again
```

`auth.json` lives in `%LOCALAPPDATA%\lfmap\`, is encrypted for the current Windows user and is left out of `lfmap backup`: enrol again after a restore on a new machine. TOTP stops what can type into your console but cannot read your profile; a process running as you can still read it (ADR-023: agents run as a separate account).

## The typed confirmation code

`approvals grant`, `approvals revoke` and `config add-folder` print a random 6-character code (letters and digits without `0`, `O`, `1`, `I`) and run only when you type it back:

```text
To grant powershell.run up to T3 for 2h, type this code: K7MQ4X
Code:
```

A wrong code, an empty answer or end of input cancels the command with `permission_denied`, changes nothing and writes a `deny` line to the audit log. For `grant` the tier and duration are checked before the code is asked. The code exists because a yes/no prompt can be answered by a script or an agent that drives the terminal; making the person read a fresh value makes a blind answer fail.

"Interactive terminal" means a person at a console. On Windows stdin must be a real console (`GetConsoleMode` succeeds; `<NUL` does not count) and the console must have a visible window, so hidden consoles of agent shells are refused; elsewhere stdin must be a TTY. This stops scripts and accidents, not an agent of the same Windows user that drives a visible console (#108); a separate Windows user for agents is a pending ADR.

## Data classes: `[data.classes]`

You can say how much a folder matters, once, in `config.toml` (ADR-025, [docs/specs/data-classes.md](specs/data-classes.md)):

```toml
[data.classes]
'D:\Tmp'                 = "scratch"
'D:\Work'                = "normal"
'D:\Work\Contracts'      = "secret"
```

Classes are `scratch < normal < private < secret`. Once the table has an entry, a path in no entry is `private`; a folder counts as the highest class at or below it. **Without the table nothing changes.** An invalid table makes gated calls fail until you fix it. A class only changes whether you are asked and what is audited; it never lets a plugin read or write a folder it could not before.

| Path class | Read | Create a file | Overwrite, rename, delete |
|---|---|---|---|
| `scratch` | as before | as before (T1) | T1 (audited, not asked) when the plugin names the paths and everything the call wrote is `scratch` too; otherwise T2 |
| `normal`, `private` | as before | as before | as before (T2) |
| `secret` | T1, always audited (once per call per entry, even with `T1 = "allow"`) | T2: asked at a terminal; on `mcp` elicitation, `--approve` or a grant; a proposal on `job`, `event`, `flow` | T2 |

T3 is never lowered by a class. A scheduled job that reads a `secret` folder (for example `knowledge.reindex`) needs `max_tier = 1`, or each run queues a proposal. Lines about a classified path carry two more fields: `data_class` and `action_tier` (the tier before the class was applied; `tier` is the tier decided on):

```json
{"tier": "T1", "action_tier": "T2", "data_class": "scratch", "decision": "allow", "reason": "overwrite", "target": "D:\\Tmp\\out"}
```

### Changing the table: `lfmap data`

```text
data classes [--json]       # the table as loaded: resolved path, class; marks folders that do not exist
data explain PATH [--json]  # class_of, the entry that decided, class_under; reads only config.toml
data classify PATH CLASS    # add or change one entry; interactive terminal only
data unclassify PATH        # remove one entry; interactive terminal only
```

`classify` and `unclassify` edit only the one line inside `[data.classes]` (the table is created when absent), keep your comments and other tables as they are, and check that the result still loads before replacing the file. They print the effect first, for example `D:\Tmp: private -> scratch (lower). Overwrites here will be audited instead of asked.`

**The lowering rule.** The command compares the class of the path before and after the edit (a path in no entry counts as `private`). If the class goes **down** (`secret` to anything lower, `private` to `normal`, removing an entry that was more protective than what is left), the owner code is required: the authenticator code once enrolled, else the typed code, and nothing is written before it is accepted. If the class stays or goes **up**, a yes/no confirmation is enough. Removing the last entry turns the feature off, and the command says so. A path with a single quote cannot be written as a TOML literal key: the command refuses and you edit `config.toml` by hand. Every change is audited with `reason` `data classify <old> -> <new>` or `data unclassify <old> -> <new>` and `target` the path; a refusal (no terminal, wrong code, answer no) is audited as a `deny`.

`lfmap jobs doctor` has two matching checks: `data_classes` (lists every `scratch` entry; warns about missing folders, a `scratch` entry that contains or lies inside a `[paths] knowledge` root, and the old `[plugins.knowledge.settings.sensitivity]`) and `auth` (warns when no authenticator is enrolled or when `auth.json` can be changed by another account).

## The job approval queue

A job (or an event call) never asks anyone. A call it may not run becomes a **proposal** and the job exits 1 with `permission_denied`, `Queued for approval`, and the proposal id in the error details. Proposals live in `%LOCALAPPDATA%\lfmap\approvals\` and are only moved, never deleted. The full flow is in [docs/jobs.md](jobs.md#approving-queued-calls).

```powershell
uv run lfmap approvals pending            # proposals waiting; expired ones move to approvals\expired
uv run lfmap approvals approve <id>       # shows the proposal, asks, runs it once
uv run lfmap approvals reject <id>        # moves it to approvals\rejected
```

- `approve` asks `Run <plugin>.<op> now with this input?` (a yes/no prompt) for T1 and T2 proposals; a proposal whose recorded tier is T3 asks the owner code instead (authenticator code when enrolled, else the typed code). It moves the proposal to `approvals\done` before running, and runs it with the channel `cli`. Calls up to the proposal's recorded tier run and are audited; a higher tier, or a `deny` in the policy, goes through the normal CLI approval again.
- A proposal expires after 7 days (`[jobs] approval_ttl_days` in `config.toml`, whole number 1 to 30).
- An identical pending call reuses its proposal.
- Proposal text is escaped before it is printed, and a proposal file is validated on every read.

## `max_tier` for jobs and events

`max_tier` is a ceiling for calls that run without a person: `0` (default) runs only T0, `1` also runs T1 (audited). The policy can only tighten it. Anything else is queued, or refused if the policy says `deny`.

| Setting | Where |
|---|---|
| `max_tier` | per job in `%LOCALAPPDATA%\lfmap\jobs.toml` ([docs/jobs.md](jobs.md)) |
| `[events] max_tier` | in `config.toml`, for the event adapter ([docs/events.md](events.md#events-max_tier-and-the-approval-queue)) |

With `via = "event"` both apply and the lower one wins. Either way the proposal is queued under the job's id; a request that names no job is queued under `events`.

## Commands

`grant`, `revoke`, `approve` and `reject` refuse to run outside an interactive terminal (`list` and `pending` do not check). Based on `uv run lfmap approvals <cmd> --help`:

```text
approvals grant PLUGIN.OPERATION   # approve up to TIER for a limited time; interactive, typed code
  --tier TEXT                      # highest tier covered: T1, T2 or T3 (default T2)
  --for TEXT                       # 30m, 1h, 7d; T3 at most 24h, others 7d (default 1h)
approvals revoke PLUGIN.OPERATION  # remove every grant for the operation; interactive, typed code
approvals list [--json]            # show grants, including expired ones
approvals pending [--json]         # job proposals waiting; expired ones move to approvals\expired
approvals approve ID [--json]      # show a proposal and, once confirmed, run it one time; interactive
approvals reject ID                # move a proposal to approvals\rejected; interactive
auth enroll | status | reset       # authenticator for the owner code; enroll and reset are interactive
data classes | explain PATH        # read-only view of [data.classes]
data classify PATH CLASS           # interactive; the owner code when the class is lowered
data unclassify PATH               # interactive; the owner code when the class is lowered
```

## Where things live

| What | Where |
|---|---|
| Grants | `%LOCALAPPDATA%\lfmap\grants.json` |
| Authenticator | `%LOCALAPPDATA%\lfmap\auth.json` (DPAPI-encrypted secret; not backed up) |
| Proposals | `%LOCALAPPDATA%\lfmap\approvals\{pending,done,rejected,expired}\<id>.json` |
| Audit log | `%LOCALAPPDATA%\lfmap\audit.jsonl`; `uv run lfmap audit tail -n 20 [--json]` |

The audit log holds time, principal, channel, plugin, operation, tier, decision (`allow`, `deny`, `queue`, `grant`, `revoke`, `approve`, `reject`), reason and target; never document content or output.

`principal` says who acted. It is always `owner` today and is also stored in every grant and proposal; a record written before the field existed means `owner`. New code must not assume a single user: adding users later only adds values.

## Troubleshooting

| You see | Cause and fix |
|---|---|
| `permission_denied: ... needs approval (T2, ...)` | nobody could be asked. Use the `hint` in the error: run in a terminal, pass `--yes`, start the server with `--approve`, or make a grant |
| `... only works in an interactive terminal` | the command ran from a script, a redirect or a hidden console. Open a real console window and run it yourself |
| `... cancelled: the confirmation code did not match` | wrong or missing code. Run the command again; the code changes every time |
| `Queued for approval` | a job or event call needs a person. `approvals pending`, then `approve <id>` or `reject <id>` |
| `No pending proposal with this id (expired or already handled?)` | the proposal expired or was handled; check `approvals\expired` and `approvals\done` |
| `Operations with external side effects cannot be pre-approved` | `--approve` never covers T3; use a grant or a preapproved destination |
| `A T3 grant lasts at most ...` / `Duration must look like 30m, 1h or 7d` | fix `--for` |
| `[approval] in config.toml is invalid` | check the keys above; a destination may expire at most 90 days from today |
