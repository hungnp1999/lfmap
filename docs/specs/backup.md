# Backup and restore of owner state (#196)

Decided by the owner on 2026-11-08: option A, metadata only. Rejected: a full backup encrypted with an owner-held key, and a second local disk only.

## 1. Commands

- `lfmap backup [--to <folder>] [--json]` writes one zip `lfmap-backup-YYYYMMDDTHHMMSSZ.zip` and prunes old ones. Runs anywhere (the scheduled task uses it).
- `lfmap backup list` lists the zips in the declared folder.
- `lfmap backup restore <zip>` runs only at a TTY and needs the typed confirmation code (like `config add-folder`). No MCP form.

## 2. Configuration (`config.toml`, edited by hand like every other path)

```toml
[backup]
folder = 'D:\Backups\lfmap'   # required, absolute, local; may be a OneDrive folder
keep = 7                       # optional, 1 to 365, default 7
daily = "03:00"                # optional; `lfmap jobs register` then creates task \LFMAP\backup
```

## 3. What is in the zip

| Member | Source |
| --- | --- |
| `config.toml`, `jobs.toml`, `flows.toml`, `grants.json`, `audit.jsonl` | files, as is |
| `approvals/**`, `flows/runs/**` | files, symlinks skipped |
| `events.db` | `sqlite3.Connection.backup` snapshot (source opened read-only) |
| `knowledge/catalog.db` | snapshot, then `chunks`, `contents` and `chunks_fts` emptied and `indexed` files set `pending` (document text never leaves the app folder) |
| `manifest.json` | format, time, SHA-256 and size per member, list of exclusions |

Left out because they are rebuilt from the source files: `knowledge/vectors/` and `knowledge/cache/md/`. After a restore run `lfmap knowledge reindex`.

## 4. Rules

- The folder comes only from `config.toml`. `--to` must lie inside it: the target goes through `PermissionManager.require_write` with the declared folder as the only root (UNC and device paths refused before I/O).
- A zip is written under a `.part` name and renamed; an existing name is never overwritten (conflict error). Retention deletes only files matching the backup name pattern, after a successful write.
- Restore: the zip path is read through `PermissionManager(explicit_read=True)` (a person typed it). Before anything is written, the manifest must match the member list, every member name must be one LFMAP restores (fixed names or plain relative paths under `approvals/` and `flows/runs/`, no `..`, drive or backslash), every size is capped, and every SHA-256 must match. Members are staged beside their destination (`*.restoring`), then swapped in; files replaced (and any `-wal`, `-shm`, `-journal` of a database) move to `restore-previous\<time>\` in the app folder. A failure before the swap changes nothing.
- ADR-023 ACLs: the zip carries no ACLs. A restored file is created in its own folder, so it inherits that folder's ACL (owner only); a restore never widens access. A person should still run `lfmap jobs doctor` after restoring on a new machine.
- Close MCP servers and wait for running jobs before restoring (no lock yet).
- Audit: `backup created` and `backup restored` lines, target = zip file name only.

## 5. Where may the app folder live?

`app_dir()` is `%LOCALAPPDATA%\lfmap`, derived only from `LOCALAPPDATA`; there is no setting for it. Moving it to D: today means a directory junction (`mklink /J`) from the C: location to a D: folder; all path checks use `realpath`, so they resolve consistently. Not verified on Windows from the cloud. A `data_dir` setting is a separate decision (it would touch every module that calls `app_dir()`); not part of this change.

## 6. Tests

`packages/lfmap-core/tests/test_backup.py`: content of the zip, scrubbed catalog, live WAL snapshot, no overwrite, retention, target outside the folder, undeclared or UNC folder, round trip with files moved aside, tampered member, escaping names, zip without manifest, task command, CLI create/list, restore refused without a TTY or with a wrong code.
