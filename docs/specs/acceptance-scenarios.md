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
  4. Find the related docs and study them, with NotebookLM as an aid (today; to be replaced by the `knowledge` and `llm` plugins).
  5. Try it for real, when possible.
  6. Write up the lessons as a research document.
- Expected output: a Markdown file (or DOCX/PDF when it has figures) saved to the owner's personal drive (PC or cloud storage).
- Your approval: none for saving to the personal drive; approval only when the document is shared with other people.
- Data class: normal.
- Leaves the machine?: no for the output. Fetching public pages is outbound traffic. NotebookLM is dropped from the flow (owner decision 2026-11-12): the `knowledge` and `llm` plugins do the deep reading locally, so no document is uploaded to a third party.
- Success check: scientific structure, complete and accurate citations, new or applicable content, clear layout without font errors, sensible figures and tables. Checkable part: every citation points to a source the flow actually fetched and stored.
- Failure to avoid: the model invents facts (hallucination) and the document states something false.
- Plugins you expect: `web` (page fetch from allowed hosts), a GitHub reader, `llm` (translate, summarise), a document formatter (Markdown to Word/PDF), `file`.
- Test data available?: yes, real public pages (GitHub, Microsoft Learn, Google for Developers, X); no synthetic data needed.

### Core gaps this scenario exposes (to become issues before any plugin is built)

1. Social networks (Facebook, LinkedIn, X) need login or scripts and forbid scraping in their terms; a plain `web` fetch cannot read them. Decide per source: official API, RSS or newsletter, or leave out.
2. GitHub is better read through its API than as HTML; it needs a read-only token handled as a secret and an allow-list entry.
3. Citation check: the core needs a way to verify that each cited URL is in the set of pages the flow fetched, so a made-up source fails the run instead of reaching the document.
4. Long, multi-stage work (trend pick, deep read, write-up) with an open-ended choice of topics: decide which part is a flow and which stays interactive with the owner.
5. Step 5 (hands-on trial) is outside LFMAP; the scenario covers collect, translate, deep reading through `knowledge`, summarise and write up. Check that `knowledge` handles the long, multi-source reading NotebookLM does today.
6. Document formatter: no plugin yet for Markdown to DOCX/PDF with figures.
7. Duplicates across days (as in S1): remember what was already read.

## S3: Family meal planning

Source: the owner's real workflow, recorded 2026-11-12. No personal data of family members is recorded here; only the kind of data.

- Why it matters: 15 to 30 minutes a day; hard to choose dishes and keep the nutrition balanced for a multi-generation family.
- Frequency: daily.
- Trigger: a schedule (time of day to be set); the shopping list must go out one day ahead.
- Input: what food is left at home (today only in memory or phone notes), family preferences, recipes from the web.
- Steps today:
  1. Check the food left at home.
  2. Ask the relatives for their wishes.
  3. Pick the main ingredients so dishes do not repeat and nutrition stays balanced.
  4. Look up recipes online when needed.
  5. Write the list of ingredients to buy in a phone note.
- Expected output: a menu note on phone or computer, and a combined, sensible shopping list sent automatically one day ahead.
- Your approval: the menu is confirmed with the relatives (a person other than the owner is in the loop).
- Data class: private. Health records and dietary restrictions of family members are part of the input (owner decision 2026-11-12) because they directly shape the menu; the rest (pantry, recipes) is normal.
- Health data handling: steps that read health data run on the local model only; the menu and shopping list that leave the machine carry no health details, only dishes and ingredients.
- Leaves the machine?: yes: the menu and shopping list go to the family members by message.
- Success check: balanced nutrition, matches everyone's taste, easy to cook, fewer shopping trips.
- Failure to avoid: wasted food; dishes unsuitable for some members' portions or needs.
- Plugins you expect: `web` (recipe search), a nutrition analyzer, a note app, `email` or chat (shared with S1), `file`.
- Test data available?: Claude generates; no sample data exists yet.

### Core gaps this scenario exposes (to become issues before any plugin is built)

1. The pantry has no digital source today (memory, phone notes). A flow cannot read it; the owner types or dictates it, or a small structured pantry file is kept. Decide the input channel before any plugin.
2. Human-in-the-loop with people other than the owner: the Gate has one approver (the owner). "Relatives confirm the menu" is either the owner relaying their answers, or a new feature. Recommended for now: the owner is the only approver; relatives only receive.
3. Send step needs the same declared recipient list as S1 (a family list, owner-edited in `config.toml`).
4. Preference and history memory (what was cooked recently, who dislikes what): a store with a data class; health entries are `private` (decided), so reading them needs the approval tier of that class and the local model. Open: how the output is checked to be free of health details before it is sent (a flow-level rule or a core filter).
5. Nutrition analysis needs a food composition dataset; check its licence first. An LLM alone is not a reliable source for a nutrition claim.
6. Schedule offset: the list goes out one day ahead of the cooking day, so the trigger and the target date differ.
7. Phone notes: no connector exists; plain files in a synced folder are the likely route.

## S4: Meeting minutes

Source: the owner's real workflow, recorded 2026-11-13. No meeting content is recorded here; only the kind of data.

- Why it matters: taking notes distracts from the meeting, full notes are hard to keep, and compiling and standardising minutes afterwards takes a long time.
- Frequency: per event.
- Trigger: a meeting starts on MS Teams, Google Meet, Zoom or similar.
- Input: audio, chat messages, shared screen, meeting documents; Vietnamese and English, sometimes Chinese, Korean, Japanese, Russian or French.
- Steps today:
  1. Follow the audio, chat, screen and documents during the meeting.
  2. Take notes in an app (notebook, Word, Notepad) or by hand on paper, with sketches.
  3. Listen to the recording again and transcribe it (when there is one).
  4. Compile the minutes.
  5. Email the attendees or attach the minutes to a system.
- Expected output: a DOCX or PDF file (the minutes), sent by email or uploaded to a system.
- Your approval: read and approve the minutes before they are sent.
- Data class: normal, private or secret, depending on the meeting. The class is set per meeting, not per scenario.
- Leaves the machine?: yes: the minutes go to the attendees by email or to a system. The audio must not leave the machine.
- Success check: basic details complete, the discussion and the decisions of the chair or the person in authority recorded.
- Failure to avoid: wrong figures, or opinions reported with a changed meaning.
- Plugins you expect: meeting bot, speech-to-text, translation, analysis, report writer (`llm`, `file`, `email`).
- Test data available?: Claude generates (real meetings are heavy and confidential and cannot be shared): synthetic audio from text-to-speech with a known script, so the expected minutes are known.

### Core gaps this scenario exposes (to become issues before any plugin is built)

1. A bot that joins Teams, Meet or Zoom is a separate product: it needs an account on a third-party platform, joins from outside the machine, and raises recording-consent and platform-terms questions. Not feasible as a Phase 2 plugin. Reduced version for acceptance: the owner drops a recording (or a local capture) into a declared folder and the flow starts from the file.
2. No speech-to-text plugin. The model must run locally (audio stays on the machine), be licence-checked, and share the GPU strictly serially with other models.
3. Multi-language speech and text (Vietnamese, English, plus CJK, Russian, French): decide the supported set for acceptance; the rest is best effort.
4. Data class per run: the same flow handles `normal` to `secret` input. The class has to come from the input (folder, tag) and decide where each step runs; `secret` forces local-only steps and a stricter approval.
5. Shared screen and handwritten notes need OCR or vision; `ocr` is on the Phase 2 list, vision is not. Leave out of the first version.
6. The approval step before send: the owner reads the minutes first. Needs the minutes as a reviewable file in the approval queue, then `email` with an attachment.
7. Output as DOCX/PDF: same document-formatter gap as S2.
8. Numbers and decisions must not be changed by the model: a check that every figure in the minutes appears in the transcript (like the citation check in S2).
