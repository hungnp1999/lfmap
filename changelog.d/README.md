# Changelog fragments

One file per change instead of editing `CHANGELOG.md`, so two open pull requests never conflict on the changelog.

## Add a fragment

Create `changelog.d/<name>.<category>.md`:

- `<name>`: a short slug, usually the issue (`192-principal`, `flows-fl3`). Lowercase letters, digits and `-`.
- `<category>`: `added`, `changed`, `fixed`, `removed` or `security`.
- Content: the text of one entry, without the leading `- `. Same style as `CHANGELOG.md`: English, one paragraph, name the issue, end with the dependency note when it matters.

Example, `changelog.d/192-principal.added.md`:

```
`principal` field (#192): every `audit.jsonl` line records who acted, always `owner` today. No new dependency.
```

Check your fragments: `uv run python scripts/changelog_fragments.py check`.

## Release

`uv run python scripts/changelog_fragments.py release X.Y.Z` writes a `## [X.Y.Z] - <date>` section into `CHANGELOG.md` (fragments grouped by category, then the entries that were under `[Unreleased]` before fragments existed), leaves an empty `[Unreleased]` and deletes the fragments. Review the diff before committing.

`CHANGELOG.md` itself is edited only by that command; the entries written before this folder existed stay under `[Unreleased]` until the first release.
