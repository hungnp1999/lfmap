# Core acceptance scenarios: template (#191)

Purpose: the owner describes real business workflows; Claude turns each into a `flows.toml` over real plugins, runs it on DIEP-ANH with synthetic data, and keeps it as a regression suite that every core change must pass (architecture review C2, decision 2 of 2026-11-08).

**How to fill in.** Copy the block "Scenario template" below to the end of this file under the heading `## S<n>: <short name>`. Write in Vietnamese or English, one line per field is enough. Skip a field with `?` if unsure; Claude asks back. Aim for 15 minutes per scenario. Describe the process as you do it today, not as you think LFMAP can do it. Never paste real names, numbers or documents: say what *kind* of data it is.

Two or three scenarios are enough to start. Prefer the ones you repeat most often or that cost the most time.

## Scenario template

```
## S<n>: <short name>

- Why it matters: <what it costs you today: time per week, errors, delays>
- Frequency: <daily | weekly | per event | rare>
- Trigger: <what starts it: a schedule, a new email, a file appears, you ask>
- Input: <what comes in: kind of file or message, rough size, language, where it sits today>
- Steps today: <numbered, in your words, including tools you use now (n8n, Office, email...)>
  1.
  2.
  3.
- Expected output: <what you want at the end: a file, a summary, a reply draft, a table; where it goes>
- Your approval: <which step must wait for you to say yes: sending, deleting, paying, moving files... or "none">
- Data class: <scratch | normal | private | secret> (see ADR-025 draft; `?` if unsure)
- Leaves the machine?: <no | yes: what and to whom>
- Success check: <how you would know the result is right: a number, a field, a sample you can compare>
- Failure to avoid: <the worst thing that could go wrong>
- Plugins you expect: <markitdown, knowledge, email, ... or `?`>
- Test data available?: <you can provide synthetic samples | Claude generates | needs ghost data>
```

## Worked example (synthetic)

## S0: Weekly summary of new documents

- Why it matters: reading five new reports on Monday takes about an hour.
- Frequency: weekly.
- Trigger: Monday 08:00 schedule.
- Input: PDF and Word files dropped into one inbox folder during the week, Vietnamese, 1 to 30 pages each.
- Steps today:
  1. Open each file and skim.
  2. Write a few lines per file in a note.
  3. Save the note next to the files.
- Expected output: one Markdown note with a short summary per file, saved in the declared output folder.
- Your approval: saving the note (T1 write is fine); nothing else.
- Data class: normal.
- Leaves the machine?: no (local model only).
- Success check: every input file has exactly one summary line, and the summary names the right file.
- Failure to avoid: a file silently skipped, or a summary attached to the wrong file.
- Plugins you expect: `markitdown`, `llm` (summarise), later `file`.
- Test data available?: Claude generates five synthetic reports.

Sketch of the flow Claude would write: schedule trigger, then `markitdown.convert` per file, then `llm.summarise`, then a write step above `max_tier` that pauses for approval.

## What Claude does with a filled scenario

1. Reads it and asks at most three clarifying questions.
2. Writes `flows.toml` plus synthetic inputs and a pass/fail check, as a regression case under `docs/specs/flows-tests/` or the plugin tests.
3. Lists gaps found in the core (a missing plugin operation, an approval that cannot be expressed) as issues, before building anything.
4. Runs it on DIEP-ANH and reports.
