# Vibe-coding tools for Claude: review and working method

- Date: 2026-10-28 · Author: Claude (Managing Agent) · Requested by: Hùng
- Status: **decided**. Hùng chose option A (§3) on 2026-10-28.
- Input: the owner's notes `toi_uu_vibe_coding.md` (context-saving tools for the AI, visualisation tools for the product owner, security-audit skills).
- Baseline: Claude Code (cloud and CLI), project with coordinator and threads, Pro plan, repositories lfmap, MarkitdownTool and isomp.
- Consistent with the first pass in `2026-10-23-local-model-tiers.md` §12.3. Changes from that pass are marked **[new]**.
- Licences were looked up on 2026-10-28 from listings and articles, not from each LICENSE file. Recheck before any install.

## 1. Tools

| Tool | Licence / status | What Claude already has | Verdict |
| --- | --- | --- | --- |
| CodeGraph (tree-sitter graph in SQLite over MCP) | No single upstream: several small projects share the name (codegraph-rust MIT, graphindex Apache-2.0, codegraph-ai licence not shown). The "59% fewer tokens" figure is a vendor claim | Grep/Glob and ranged reads in Claude Code; the Explore subagent; `lfmap-knowledge` `search` / `get_context` with a token budget | no; a symbol and caller index could become an in-house `lfmap-knowledge` extension later (`tree-sitter`, MIT) |
| Claude-Mem | README says AGPL-3.0, `ragtime/` is PolyForm Noncommercial; some articles say Apache-2.0. Hooks into every session and stores transcripts | project memory shared by coordinator and threads, `CLAUDE.md`, handoff files | no (licence policy; transcripts are a data risk) |
| Milvus + AST chunking | Apache-2.0, a server to run | LanceDB in `lfmap-knowledge` | no (an extra background service) |
| Repomix / AI-Digest | MIT | Claude Code reads files selectively; a digest only helps when pasting into a web chat | no |
| Archify (diagram skill, `tt-a1i/archify`) | MIT, Node.js, installed with `npx skills add` | the `artifact-diagramming` skill and Artifact pages: self-contained SVG/HTML diagrams with a shareable link that opens in any browser | **[new] not needed**: the built-in route covers it without third-party code (was "optional") |
| CodeSee | **[new] closed**: acquired by GitKraken in May 2024 and shut down | none needed | dropped |
| CodeScene | commercial SaaS; free for open-source repositories, paid plans about 20–30 USD per author per month; code or git history leaves the machine | partly: CodeQL on every PR, `/code-review`, `/simplify` | no for now; a free trial on public lfmap only with Hùng's approval (data leaves the machine) |
| Understand (SciTools) | commercial, about 90–120 USD per user per month, online licensing | not needed at this size | no |
| `shaxbozaka/security-audit` | not found (2026-10-23 and 2026-10-28); an unverifiable name is itself a warning sign | Claude Code `/security-review`, `/code-review`, CodeQL default setup on all three repositories | no |
| `agentnode-dev/skills-security-audit` | about 30 installs when checked on 2026-10-23, code not reviewed | not needed while no third-party skill or MCP server is installed | no |

## 2. Third-party skills and MCP servers

- A skill or MCP server runs with Claude's permissions. On DIEP-ANH that is read/write in `D:\Development`, shell commands and network access. Shell commands in a skill run before the model reads its text, so model-level prompt-injection defences do not see them (Datadog Security Labs).
- 2026 figures: Snyk audited 3,984 ClawHub skills, 36.8% had a security flaw and 76 carried confirmed malicious payloads; a USENIX Security 2026 study of 98,380 skills confirmed 157 malicious ones, 73% with hidden features. OWASP lists malicious skills as AST01 and warns about names that imitate popular tools.
- Rule (unchanged from §12.3, made explicit): install a third-party skill or MCP server only after reading all its code, checking the licence and adding a License Register row; pin it to a commit; try it in a cloud session before DIEP-ANH; changes under `.claude/` in a repository go through PR review.

## 3. Working method

Options considered:

- **A. Built-in tools plus three habits** (chosen): no new dependency.
- B. A plus Archify for diagrams: nicer interactive diagrams, but Node.js and third-party code that overlaps with Artifact pages.
- C. Adopt the notes as written (CodeGraph from day one, Claude-Mem, Repomix, CodeScene, third-party audit skills): AGPL and noncommercial terms, unverifiable tools, code leaving the machine, overlap with `lfmap-knowledge` and project memory.

The three habits of option A:

1. **A short `ARCHITECTURE.md`** (at most about 150 lines) in lfmap and MarkitdownTool; isomp already has `docs/ARCHITECTURE.md`. It holds the module map, main data flows and invariants, and `CLAUDE.md` points to it. A PR that changes the architecture updates it in the same PR.
2. **Architecture diagrams by milestone, not by calendar**: at the end of every Roadmap phase (with the phase-end document set) and after each large refactor PR. Claude draws them as Artifact pages, compares them with `ARCHITECTURE.md` and notes any drift in the PR. A fixed two-to-three-day cadence costs tokens without new information.
3. **Security review before merge**: CodeQL on every PR as today, plus `/security-review` for code PRs that touch caller-supplied paths, adapters (CLI, MCP, REST), network calls, subprocesses or `.claude/`. Docs-only PRs skip it.

The rules in the notes about narrow tasks and never asking to "read the whole project" already hold (`CLAUDE.md`, handoff files, task cards).

## Follow-up tasks

| Task | Environment | Done when |
| --- | --- | --- |
| Write `ARCHITECTURE.md` for lfmap and link it from `CLAUDE.md` | Cloud | docs-only PR merged |
| Same for MarkitdownTool | Cloud | docs-only PR merged |
| Add habits 2 and 3 to the `CLAUDE.md` workflow of the three repositories | Cloud | docs-only PRs merged |

## Sources

- [claude-mem licence notes (horadecodar)](https://horadecodar.com.br/claude-mem-github/), [mdskills.ai: claude-mem](https://www.mdskills.ai/plugins/claude-mem), [sourcepulse: claude-mem](https://www.sourcepulse.org/projects/17586212)
- [codegraph-rust](https://awesome.ecosyste.ms/projects/github.com%2Fsunerpy%2Fcodegraph-rust), [graphindex](https://pkg.go.dev/github.com/254binaryninja/graphindex)
- [Archify (Better Stack)](https://betterstack.com/community/guides/ai/archify-architecture/), [Archify (pyshine)](https://pyshine.com/Archify-Agent-Skill-Technical-Diagram-Generator/), [Archify 3.0.1: what to trust](https://braindetox.kr/en/posts/archify_code_to_system_diagram_agent_skill_2026.html)
- [GitKraken acquires CodeSee](https://www.schneider.im/fr/gitkraken-acquiert-codesee/), [CodeSee (CB Insights)](https://www.cbinsights.com/company/codesee)
- [CodeScene pricing (stackpick)](https://www.stackpick.net/pricing/codescene/), [Understand licensing (SciTools)](https://support.scitools.com/support/solutions/articles/70000582767-understand-licensing)
- [OWASP AST01 Malicious Skills](https://owasp.org/www-project-agentic-skills-top-10/ast01.html), [Datadog: malicious skills](https://securitylabs.datadoghq.com/articles/malicious-skills-supply-chain-risks-in-coding-agents-with-dynamic-context/), [CSA: five Claude skills risks](https://cloudsecurityalliance.org/blog/2026/06/25/5-claude-agent-skills-risks-every-ciso-should-know), [Straiker: ClawHub](https://www.straiker.ai/blog/built-on-clawhub-spread-on-moltbook-the-new-agent-to-agent-attack-chain)
