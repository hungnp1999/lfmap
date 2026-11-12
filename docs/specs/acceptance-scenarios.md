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

## S1: Tender package search

Source: the owner's real workflow, recorded 2026-11-09 (the notes in brackets are the owner's answers to the follow-up questions). Public data only.

- Why it matters: 2 to 3 hours a week; by hand, tenders are missed and updates are late because they depend on one person's calendar.
- Frequency: daily.
- Trigger: a schedule (time of day to be set).
- Input: text on two public websites (baodauthau.vn and muasamcong.mof.gov.vn); Vietnamese, English and Russian. Only browser access today; no API or RSS known (to be checked).
- Steps today:
  1. Open the Bao Dau thau site or the national e-procurement site.
  2. Search by keyword: a product name (about 2 words) or a solution name (about 4 words).
  3. Collect the tender packages found.
  4. Send a notice to the people concerned by chat or email.
- Expected output: a table (Excel or similar) sent automatically by chat or email.
- Your approval: none for the send, because the recipients are a fixed internal list declared in advance; each recipient checks the content and forwards it to management (owner decision 2026-11-09).
- Data class: normal.
- Leaves the machine?: yes: the table goes to the declared internal recipients by chat or email. Fetching public pages is outbound traffic too.
- Success check: each row has enough to find the original page again (link), plus field, closing date and bidding form; a package is selected when a keyword matches (no other rule).
- Failure to avoid: wrong data in the table, or a package that does not fit the need being selected; a missed package.
- Plugins you expect: `web` (new: fetch pages from an allowed list of hosts), `file` (write the Excel table), `email` or chat (new), possibly `llm` only for Russian or English matching.
- Test data available?: yes, real public pages saved as samples; no synthetic data needed.

### Core gaps this scenario exposes (to become issues before any plugin is built)

1. No web-fetch plugin. It is a network path, so it needs an allow-list of hosts, a rate limit, a size limit and a gate decision (read of public data, T1 or lower).
2. No send plugin and no "declared recipient list" rule. Sending to a fixed internal list needs a new approval rule: a pre-approved destination set, owner-edited in `config.toml`, never changed by a flow (compare `[approval.destinations]`).
3. Keyword matching across Vietnamese, English and Russian: diacritics and case folding; Russian needs no model if only exact terms are matched.
4. Pages that need a browser (scripts) cannot be read by a plain fetch; check first whether the site offers an export or API.
5. Duplicates across days: the flow needs a memory of tenders already sent (a state file or the events store).

## S2: Software technology research

Source: the owner's real workflow, recorded 2026-11-12. Public data only.

- Why it matters: 2 to 4 hours a week; information is scattered across many sites, most of it is in English, and the owner cannot verify all of it by hand.
- Frequency: daily.
- Trigger: a schedule (time of day to be set).
- Input: public web pages, PDF and Markdown from GitHub (trending and statistics pages, repositories), vendor docs (Microsoft, Google, Anthropic), blogs, and social networks (Facebook, LinkedIn, X). Mostly English.
- Steps today:
  1. Open GitHub, blogs and social networks.
  2. Skim statistics tables and top posts to see the trends.
  3. Pick a few standout trends to study in depth.
  4. Find the related docs and study them, with NotebookLM as an aid.
  5. Try it for real, when possible.
  6. Write up the lessons as a research document.
- Expected output: a Markdown file (or DOCX/PDF when it has figures) saved to the owner's personal drive (PC or cloud storage).
- Your approval: none for saving to the personal drive; approval only when the document is shared with other people.
- Data class: normal.
- Leaves the machine?: no for the output. Fetching public pages is outbound traffic. Whether NotebookLM stays in the loop is open: using it uploads public documents to Google (`?`, to be decided with the data-class rules).
- Success check: scientific structure, complete and accurate citations, new or applicable content, clear layout without font errors, sensible figures and tables. Checkable part: every citation points to a source the flow actually fetched and stored.
- Failure to avoid: the model invents facts (hallucination) and the document states something false.
- Plugins you expect: `web` (page fetch from allowed hosts), a GitHub reader, `llm` (translate, summarise), a document formatter (Markdown to Word/PDF), `file`.
- Test data available?: yes, real public pages (GitHub, Microsoft Learn, Google for Developers, X); no synthetic data needed.

### Core gaps this scenario exposes (to become issues before any plugin is built)

1. Social networks (Facebook, LinkedIn, X) need login or scripts and forbid scraping in their terms; a plain `web` fetch cannot read them. Decide per source: official API, RSS or newsletter, or leave out.
2. GitHub is better read through its API than as HTML; it needs a read-only token handled as a secret and an allow-list entry.
3. Citation check: the core needs a way to verify that each cited URL is in the set of pages the flow fetched, so a made-up source fails the run instead of reaching the document.
4. Long, multi-stage work (trend pick, deep read, write-up) with an open-ended choice of topics: decide which part is a flow and which stays interactive with the owner.
5. Step 5 (hands-on trial) and NotebookLM are outside LFMAP; the scenario covers only collect, translate, summarise and write up.
6. Document formatter: no plugin yet for Markdown to DOCX/PDF with figures.
7. Duplicates across days (as in S1): remember what was already read.
