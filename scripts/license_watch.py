"""Watch the license files of upstream projects LFMAP depends on or learns from (RT-01, ADR-021).

Fetches each watched file from the default branch on GitHub, hashes it with SHA-256 and compares
the hash with the baseline in `docs/research/license-watch.json`. Standard library only.

    python scripts/license_watch.py            # check: exit 1 when a file changed, 2 when a fetch failed
    python scripts/license_watch.py --update   # write the current hashes as the new baseline

A change is trigger K1 of the research plan: review the new text within a week.
"""

import argparse
import hashlib
import json
import sys
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "docs" / "research" / "license-watch.json"
RAW_URL = "https://raw.githubusercontent.com/{repo}/HEAD/{path}"
TIMEOUT = 30

# name -> (GitHub repository, license file path on the default branch)
WATCHED: dict[str, tuple[str, str]] = {
    "n8n": ("n8n-io/n8n", "LICENSE.md"),
    "n8n-ee": ("n8n-io/n8n", "LICENSE_EE.md"),
    "open-webui": ("open-webui/open-webui", "LICENSE"),
    "nats-server": ("nats-io/nats-server", "LICENSE"),
    "valkey": ("valkey-io/valkey", "COPYING"),
    "ollama": ("ollama/ollama", "LICENSE"),
    "librechat": ("danny-avila/LibreChat", "LICENSE"),
    "activepieces": ("activepieces/activepieces", "LICENSE"),
    "node-red": ("node-red/node-red", "LICENSE"),
    "markitdown": ("microsoft/markitdown", "LICENSE"),
    "lancedb": ("lancedb/lancedb", "LICENSE"),
}

Fetch = Callable[[str], bytes]


def fetch_url(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "lfmap-license-watch"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.read()


def snapshot(fetch: Fetch = fetch_url) -> tuple[dict[str, dict], dict[str, str]]:
    """Return (entries, errors): one entry per watched file that could be fetched."""
    entries: dict[str, dict] = {}
    errors: dict[str, str] = {}
    for name, (repo, path) in WATCHED.items():
        url = RAW_URL.format(repo=repo, path=path)
        try:
            data = fetch(url)
        except OSError as exc:
            errors[name] = f"{type(exc).__name__}: {exc}"
            continue
        first_line = data.decode("utf-8", errors="replace").strip().splitlines()[0][:120] if data.strip() else ""
        entries[name] = {
            "url": url,
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "first_line": first_line,
        }
    return entries, errors


def compare(baseline: dict[str, dict], current: dict[str, dict]) -> list[tuple[str, str]]:
    """Return (name, status) for every watched name; status is same, changed, new or missing."""
    report = []
    for name in sorted(set(baseline) | set(current)):
        if name not in current:
            report.append((name, "missing"))
        elif name not in baseline:
            report.append((name, "new"))
        elif baseline[name]["sha256"] != current[name]["sha256"]:
            report.append((name, "changed"))
        else:
            report.append((name, "same"))
    return report


def load_baseline(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))["files"]


def write_baseline(path: Path, entries: dict[str, dict]) -> None:
    document = {
        "checked": datetime.now(UTC).strftime("%Y-%m-%d"),
        "note": "SHA-256 of upstream license files (RT-01). Update with scripts/license_watch.py --update "
        "only after reviewing a change.",
        "files": dict(sorted(entries.items())),
    }
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None, fetch: Fetch = fetch_url) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--update", action="store_true", help="write the current hashes as the baseline")
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    args = parser.parse_args(argv)

    current, errors = snapshot(fetch)
    for name, error in errors.items():
        print(f"ERROR    {name}: {error}")
    if args.update:
        if errors:
            print("Baseline not written: fix the fetch errors first.")
            return 2
        write_baseline(args.baseline, current)
        print(f"Baseline written: {len(current)} files -> {args.baseline}")
        return 0

    baseline = load_baseline(args.baseline)
    changed = False
    for name, status in compare(baseline, current):
        if name in errors:
            continue
        print(f"{status:<8} {name}: {current.get(name, baseline.get(name, {})).get('url', '')}")
        changed |= status in {"changed", "new"}
    if changed:
        print("License text changed (trigger K1): review it, then run with --update.")
        return 1
    return 2 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
