# ADR-026 draft: Cloud AI provider for production use of Lan Hài

- Status: **Proposed** (draft for the owner's gate, `gate:po`). Not part of `03_Decisions_ADR.md` until accepted.
- Date: 2026-11-13
- Issue: #279. Related: #189 (ModelClient), #191 and draft PR #265 (acceptance scenarios), #157 and `docs/research/2026-11-10-lanhai-assistant-architecture.md` (§4.2, consequence 4), ADR-022, ADR-025, `docs/specs/model-client.md` §4, §5, §12.
- Role: Architect / Research. No paid API call was made and no project data was sent anywhere while writing this.

## 1. Question

The owner has a Claude Pro subscription and no API key. Development work uses the plan quota (ADR-022). Lan Hài, once it runs for real, puts a cloud model at the front door (owner decision 4 of 2026-11-10): the cloud model reads each request, plans, and routes work; `private` and `secret` data stays on the local model. Which provider backs that cloud route, and can it be the Pro plan instead of a paid API?

## 2. Facts checked (2026-11-13)

| # | Fact | Source | Checked |
| --- | --- | --- | --- |
| F1 | Consumer Terms (effective 2025-10-08), section 3: you may not "access the Services through automated or non-human means, whether through a bot, script, or otherwise", **except** "when you are accessing our Services via an Anthropic API Key or where we otherwise explicitly permit it". | <https://www.anthropic.com/legal/consumer-terms> | fetched 2026-11-13 |
| F2 | Consumer Terms: "Our Commercial Terms of Service govern your use of any Anthropic API key". You may not make your account available to anyone else. | same | fetched 2026-11-13 |
| F3 | Support article "Use the Claude Agent SDK with your Claude plan": banner 2026-06-15 "We've paused the previously-announced changes to Claude Agent SDK usage. Claude Agent SDK, `claude -p`, and third-party app usage still draw from your subscription limits." Banner 2026-10-07: Max, Ultra and Team plans get monthly API credits; Pro is not named. | <https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan> | fetched 2026-11-13 |
| F4 | The paused June 2026 plan would have moved Agent SDK and `claude -p` usage off the subscription limits into a separate monthly credit (Pro: USD 20). | secondary: <https://www.theregister.com/ai-ml/2026/05/14/anthropic-tosses-agents-into-the-api-billing-pool/5240748>, <https://zed.dev/blog/anthropic-subscription-changes> | search 2026-11-13, not primary |
| F5 | Claude API prices per million tokens (input / cache hit / output): Opus 5.5 4 / 0.20 / 20; Sonnet 5.5 2 / 0.10 / 10; Haiku 5.5 0.10 / 0.01 / 0.50 for prompts up to 100 000 tokens (0.50 / 0.05 / 2.50 above). Batch API halves input and output. US-only inference (`inference_geo: "us"`) costs 1.1x; the default is global. | <https://platform.claude.com/docs/en/about-claude/pricing> | fetched 2026-11-13 |
| F6 | DeepSeek API, `deepseek-flash` (V4.1 Flash): input USD 0.15 off-peak / 0.30 peak, output 0.60 / 1.20, cache hit 0.003 / 0.006; peak 01:00–04:00 and 06:00–10:00 UTC on weekdays. | secondary: <https://www.yottalabs.ai/post/deepseek-v4-1-flash-pricing-specs-v4-pro-routing-2026>, <https://benchlm.ai/deepseek/api-pricing>. Official page <https://api-docs.deepseek.com/quick_start/pricing> is **not reachable from the Cloud session** (DNS blocked) | **unverified**: the owner checks the official page in a browser before any decision that rests on it |
| F7 | DeepSeek privacy policy: "we directly collect, process and store your Personal Data in People's Republic of China". Whether API traffic is excluded from training is not stated clearly; secondary sources disagree. | <https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy-2025-02-14.html> (search snippet, 2025-02-14 version) | partly verified |
| F8 | Anthropic API data is governed by the Commercial Terms (not used for training by default; fixed retention window). | F2 and Anthropic privacy centre (<https://privacy.claude.com>, not reachable from the Cloud session) | **retention period unverified**; check before acceptance |

Not checked: payment from Vietnam (card acceptance, VAT on invoices) for either provider; Console spend-limit feature names.

## 3. Volume estimate

No real traffic exists yet, so this is a model with stated assumptions. It uses the three filled scenarios of #191 (PR #265) and the intake pattern of the Lan Hài sketch §4.2.

| Load | Assumption per unit | Per month (30 days) |
| --- | --- | --- |
| Interactive requests (cloud intake) | 20 requests a day; per request two calls (plan + answer): 8 000 cached tokens (system prompt and tool catalogue), 5 000 uncached input, 2 300 output | 600 requests: 4.8 M cached, 3.0 M uncached, 1.38 M output |
| S1 tender search | flow is fixed, so no intake; one optional matching call on English/Russian rows: 20 000 in, 2 000 out per day | 0.6 M in, 0.06 M out |
| S2 technology research | public pages only (class `normal`): about 30 pages of 5 000 tokens summarised, plus one write-up call of 30 000 in / 5 000 out: 180 000 in, 20 000 out per day | 5.4 M in, 0.6 M out |
| S3 meal planning | health data steps local (class `private`); one cloud call for menu ideas from `normal` data: 10 000 in, 2 000 out per day | 0.3 M in, 0.06 M out |
| **Total** | output raised by 50 % for thinking tokens, which are billed as output | **9.3 M uncached in, 4.8 M cached in, 3.15 M out** |

Not in this total: development work (Leading review, coding). That stays on the Pro plan under ADR-022 and is unchanged by this ADR.

## 4. Monthly cost per option (USD, from F5 and F6)

| Option | Base load | Heavy load (3x, 60 requests a day) |
| --- | --- | --- |
| Claude API, Haiku 5.5 for everything | about 2.6 | about 8 |
| Claude API, Sonnet 5.5 for intake, Haiku 5.5 for bulk (S1–S3) | about 28 | about 85 |
| Claude API, Sonnet 5.5 for everything | about 51 | about 150 |
| Claude API, Opus 5.5 for everything | about 101 | about 300 |
| `claude -p` on Pro | 0 extra (Pro is paid anyway) | 0 extra, until the shared weekly limit runs out |
| DeepSeek `deepseek-flash` (unverified prices) | about 3.3 off-peak to 6.6 peak | about 10 to 20 |
| Local only | 0 (electricity) | 0 |

Reading the table: **Haiku 5.5 is cheaper than DeepSeek Flash at these list prices** (input 0.10 against 0.15–0.30, output 0.50 against 0.60–1.20). The cost argument for DeepSeek does not hold for the bulk tier. The real cost question is how much of the planning needs Sonnet rather than Haiku, which only a bench can answer (section 7).

## 5. Options

### A. Claude API (Anthropic first-party) behind `ModelClient` (recommended)

- How: a `kind = "cloud"` endpoint in `[models]`. Note: `ModelClient` v1 speaks the OpenAI-compatible protocol. Anthropic's native API is `POST /v1/messages`; whether Anthropic offers an OpenAI-compatible endpoint good enough for tool calling must be checked before the endpoint is configured, or `models_http.py` gets a second small client for the Messages API (stdlib only, no SDK, in line with ADR-021). Decide in the ModelClient v2 spec (streaming + tool calling), which Lan's L2 needs anyway.
- Model tiers: Haiku 5.5 default for intake and bulk; Sonnet 5.5 only for requests the intake marks complex; Opus not routed by default.
- Data classes: `scratch` and `normal` may go out through the gate (T3 or a standing `[approval.destinations]` entry). `private` and `secret` never go out (owner decision 4, ADR-025, `model-client.md` §4 rule 4). The owner's own request text counts as `normal` unless the pre-check matches (sketch §4.2; still to be written into the cloud-intake ADR).
- Terms: clean. API keys are the sanctioned route for automated access (F1, F2). Commercial Terms apply.
- Privacy: data goes to Anthropic, processed globally by default; no Vietnam residency. Retention window to be confirmed (F8).
- Cost control: a monthly spend limit in the Anthropic Console (owner sets it) **plus** a daily token budget in `[models]` that `ModelRouter` enforces (already listed as needed in the sketch §4.2 consequence 4). Starting cap proposal: USD 20 a month.
- Cost: about USD 3–30 a month at base load depending on how much goes to Sonnet.

### B. Claude Code headless on the Pro plan (`claude -p`)

- How: a new endpoint kind that runs `claude -p` as a subprocess with all tools disabled and returns text. Not OpenAI-compatible, so it is new adapter code in the core plus `/security-review` (subprocess, a full agent harness that can read files and run commands if a flag is wrong).
- Terms today: allowed. Claude Code is an Anthropic product, and the support article says `claude -p` draws from subscription limits (F3), so it falls under "where we otherwise explicitly permit it" (F1). This is an interpretation from Anthropic's published pages, not legal advice.
- Risks:
  1. **Policy is volatile.** Anthropic announced in 2026 that `claude -p` would move to a separate USD 20 credit for Pro, then paused it (F3, F4). The core would depend on a rule that changed twice in six months.
  2. **Shared quota.** Lan's traffic and development work draw from the same weekly limit (reset Wednesday 18:00 VN). On a heavy week Lan stops answering, or development stops. Today the budget for development is already tight (about 14 % a day).
  3. **Not an API.** No token accounting per call, no spend limit, no stable latency; output is a CLI transcript, not structured JSON with usage.
  4. **Same data path as A** (data goes to Anthropic) but under the Consumer Terms, where model-training use depends on the owner's account setting.
- Use: acceptable as a **prototype bridge** for L2 work on synthetic data, if the owner wants to try Lan before buying API credit. Not the production core.

### C. DeepSeek API

- How: OpenAI-compatible, so `ModelClient` v1 could call it with config only.
- Cost: about USD 3–7 a month at base load (F6, unverified). No cheaper than Haiku 5.5 at list price.
- Privacy: data stored in the People's Republic of China (F7); training use of API data unclear; no fixed retention window published. A foreign jurisdiction with no data-processing agreement for an individual customer.
- Data classes: at most `scratch` and **public** `normal` data (S1 and S2 page text that is already public). It must never receive the intake: request text, memory facts and the data-root list describe the owner's life even when each item is `normal`.
- Terms: normal API terms; usable.
- Verdict: no cost advantage and weaker data terms, so not chosen. It stays possible as a config-only fallback for public-data bulk work if Anthropic prices rise, because ModelClient keeps providers swappable.

### D. Local only (baseline, not a real option)

The owner overrode "local by default" on 2026-11-10 because of the 16 GB GPU. It stays as the fallback when the cloud is unreachable or the "local only" switch is on, and always for `private` and `secret` steps. There is no automatic fallback from local to cloud (`model-client.md` §4 rule 2), and none from cloud to a different cloud provider either.

## 6. Decision (proposed)

1. Production cloud route = **Option A, Claude API first-party**, with Haiku 5.5 as the default cloud model and Sonnet 5.5 only for requests the intake marks complex. Model IDs live in `[models]` config, not code.
2. **Nothing is bought now.** The first API key, credit purchase and spend limit come with the first L2 task in Phase 3, after the class-label precondition of `model-client.md` §4 rule 5 is met, and need the owner's separate approval (paid API, project rule 5).
3. Spend controls before the first real call: Console monthly limit (start USD 20), `[models]` daily token budget enforced by `ModelRouter`, and a monthly cost line in the periodic report built from the `model_call` lines of `audit.jsonl` (token counts need two more fields: `tokens_in`, `tokens_out`).
4. `claude -p` on Pro is **allowed only as a prototype bridge** on synthetic or public data, never as the production route; it is dropped as soon as A is live. If Anthropic re-introduces the separate credit for Pro, the bridge is re-evaluated, not extended.
5. DeepSeek is **not used**. It may be reconsidered only for public `normal` bulk work, by a new ADR, if Anthropic's bulk price rises above it.
6. Data classes per provider:

| Class | Anthropic API (A) | `claude -p` bridge (B) | DeepSeek (C) | Local |
| --- | --- | --- | --- | --- |
| `scratch` | yes, through the gate | synthetic data only | not used | yes |
| `normal` (incl. the owner's request text) | yes, through the gate | synthetic or public data only | not used | yes |
| `private` | no | no | no | yes |
| `secret` | no (refused before the gate) | no | no | yes |

7. This ADR records the provider choice only. It does not change ADR-022: development stays on the Pro plan quota.

## 7. Consequences

- Gains: no provider SDK, no new dependency; terms risk is low; the provider stays swappable by config; cost is small and capped.
- Costs: a paid account and a card; a few USD to a few tens of USD a month; data in `normal` (including what the owner asks) is seen by Anthropic.
- Work this creates (Phase 3, not scheduled now):
  - ModelClient v2 spec: streaming, tool calling, and the Messages API client decision (section 5 A).
  - Bench B-intake (about 30 synthetic Vietnamese requests) to measure Haiku 5.5 against Sonnet 5.5 for planning; estimated cost under USD 1, but it is a paid call, so it needs the owner's approval when scheduled.
  - `tokens_in` / `tokens_out` fields in the egress record (decision 5 of `model-client.md` §12 makes the log format hard to change later, so add them in the first cloud PR).
  - The cloud-intake ADR (request text class, pre-check, standing destination) and the plan-level approval ADR from the sketch §9, both still open.
- Reversal: change the endpoint in `config.toml`; nothing in the core is provider-specific except, possibly, the Messages API client.

## 8. Options considered and rejected

- `claude -p` on Pro as the production core: volatile policy, shared quota with development, no accounting (section 5 B).
- DeepSeek as the core: data in a foreign jurisdiction with unclear training use, and no cost advantage over Haiku 5.5 (section 5 C).
- Opus 5.5 as the default cloud model: about four times the Sonnet-for-intake cost with no measured need.
- Claude on Amazon Bedrock or Google Vertex AI (regional hosting, for example Singapore): same models, separate cloud account and billing, more set-up for one person; reconsider only if data residency in Asia becomes a requirement.
- Other providers (OpenAI, Google Gemini): not evaluated in this draft; `ModelClient` would accept them by config. Can be added if the owner asks.

## 9. For the owner to check before accepting

1. DeepSeek official price page (F6), only if the owner wants option C kept as a fallback.
2. Anthropic API retention period (F8).
3. Whether the owner's card can pay the Anthropic Console (Vietnam).
