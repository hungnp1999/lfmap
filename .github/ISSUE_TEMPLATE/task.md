---
name: Task
about: One task from a handoff, small enough for one Claude Code, Antigravity or qwen session
title: "<task id>: <short goal>"
labels: []
---

## Goal

<!-- One or two sentences: what and why. -->

## Source

- Roadmap: <!-- x.y -->
- Handoff: docs/handoff/<!-- file -->.md, task <!-- id -->
- ADR: <!-- ADR-xxx or "none" -->

## File scope (required)

May change or create:

- `path/...`

Must not touch:

- `path/...`

## Steps

<!-- Required for exec:QW and exec:AG: numbered steps, one function or file per step. Optional for exec:CC. -->

1.

## Frozen tests

<!-- Test files the task must pass without editing them, or "none". -->

## Dependencies

Blocked by: <!-- #N, or "none" -->

## Resource

<!-- none | res:gpu | res:office (serial resources on DIEP-ANH) -->

## Completion criteria

- [ ] <!-- checkable -->
- [ ] Tests pass on CI (and on Windows when the task says so)

## Notes for the agent

<!-- Model, warnings, what not to do. Labels: exec:CC/AG/QW/PO, P1..P3, gate:po when the owner must approve the PR. -->
