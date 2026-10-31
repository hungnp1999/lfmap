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

## The typed confirmation code

`approvals grant`, `approvals revoke` and `config add-folder` print a random 6-character code (letters and digits without `0`, `O`, `1`, `I`) and run only when you type it back:

```text
To grant powershell.run up to T3 for 2h, type this code: K7MQ4X
Code:
```

A wrong code, an empty answer or end of input cancels the command with `permission_denied`, changes nothing and writes a `deny` line to the audit log. For `grant` the tier and duration are checked before the code is asked. The code exists because a yes/no prompt can be answered by a script or an agent that drives the terminal; making the person read a fresh value makes a blind answer fail.

"Interactive terminal" means a person at a console. On Windows stdin must be a real console (`GetConsoleMode` succeeds; `<NUL` does not count) and the console must have a visible window, so hidden consoles of agent shells are refused; elsewhere stdin must be a TTY. This stops scripts and accidents, not an agent of the same Windows user that drives a visible console (#108); a separate Windows user for agents is a pending ADR.

## The job approval queue

A job (or an event call) never asks anyone. A call it may not run becomes a **proposal** and the job exits 1 with `permission_denied`, `Queued for approval`, and the proposal id in the error details. Proposals live in `%LOCALAPPDATA%\lfmap\approvals\` and are only moved, never deleted. The full flow is in [docs/jobs.md](jobs.md#approving-queued-calls).

```powershell
uv run lfmap approvals pending            # proposals waiting; expired ones move to approvals\expired
uv run lfmap approvals approve <id>       # shows the proposal, asks, runs it once
uv run lfmap approvals reject <id>        # moves it to approvals\rejected
```

- `approve` asks `Run <plugin>.<op> now with this input?` (a yes/no prompt, not the code), moves the proposal to `approvals\done` before running, and runs it with the channel `cli`. Calls up to the proposal's recorded tier run and are audited; a higher tier, or a `deny` in the policy, goes through the normal CLI approval again.
- A proposal expires after 7 days (`[jobs] approval_ttl_days` in `config.toml`, whole number 1 to 30).
- An identical pending call reuses its proposal.
- Proposal text is escaped before it is printed, and a proposal file is validated on every read.

## `max_tier` for jobs and events

`max_tier` is a ceiling for calls that run without a person: `0` (default) runs only T0, `1` also runs T1 (audited). The policy can only tighten it. Anything else is queued, or refused if the policy says `deny`.

| Setting | Where |
|---|---|
| `max_tier` | per job in `%LOCALAPPDATA%\lfmap\jobs.toml` ([docs/jobs.md](jobs.md)) |
| `[events] max_tier` | in `config.toml`, for the event adapter ([docs/events.md](events.md#events-max_tier-and-the-approval-queue)) |

With `via = "event"` both apply and the lower one wins. A call stopped by the event ceiling is queued under job `events`.

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
```

## Where things live

| What | Where |
|---|---|
| Grants | `%LOCALAPPDATA%\lfmap\grants.json` |
| Proposals | `%LOCALAPPDATA%\lfmap\approvals\{pending,done,rejected,expired}\<id>.json` |
| Audit log | `%LOCALAPPDATA%\lfmap\audit.jsonl`; `uv run lfmap audit tail -n 20 [--json]` |

The audit log holds time, channel, plugin, operation, tier, decision (`allow`, `deny`, `queue`, `grant`, `revoke`, `approve`, `reject`), reason and target; never document content or output.

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
