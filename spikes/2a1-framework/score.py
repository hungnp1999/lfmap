"""Read results/ and print the spike tables: E1-E8, S1-S7 (raw values) and the spec section 6 measures.

Skeleton (task F0): measures that need a real run (F4), a second venv (E8, S2) or a code review (E6, S5-S7)
are printed as "manual" until those tasks fill them in. Normalisation to 0-10 and the decision rule (spec
sections 4 and 5) are done in the F5 report from these raw numbers.
"""

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path

from common.cases import load_expected
from common.metrics import code_lines, folder_lines
from common.models import RunRecord
from common.quote import seeds_caught

HERE = Path(__file__).resolve().parent
VARIANTS = ("plain", "pydanticai", "langgraph")
SHARED_GLUE = [HERE / "tests" / "contract_fixture.py", HERE / "tests" / "conftest.py"]
MAX_SWAPS = {"replay": 3, "plan": 4}  # Plan? -> Work -> Review -> Work (rework) -> Review


@dataclass
class Tally:
    """Per-variant totals over all runs."""

    runs: int = 0
    reviews: int = 0
    hallucinated: int = 0
    seeded: int = 0
    caught: int = 0
    verdict_match: int = 0
    with_expected: int = 0
    blocked: list[str] = field(default_factory=list)
    swap_violations: list[str] = field(default_factory=list)
    overhead_s: float = 0.0
    import_s: list[float] = field(default_factory=list)


def run_dirs(results: Path) -> list[Path]:
    """Every run folder under results (one holding reports.json)."""
    return sorted(p.parent for p in results.rglob("reports.json"))


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def add_run(tally: Tally, run: Path, cases: Path) -> None:
    """Add one run folder to its variant's tally."""
    record = RunRecord.model_validate_json((run / "reports.json").read_text(encoding="utf-8"))
    metrics = _json(run / "run_metrics.json")
    tally.runs += 1
    tally.reviews += len(record.reports)
    tally.hallucinated += sum(len(r.dropped) for r in record.reports)
    tally.blocked += metrics.get("guard_blocked", [])
    tally.overhead_s += metrics.get("overhead_s", 0.0)
    if "import_s" in metrics:
        tally.import_s.append(metrics["import_s"])
    kind = "replay" if metrics.get("case") else "plan"
    if metrics.get("swaps", 0) > MAX_SWAPS[kind]:
        tally.swap_violations.append(record.run_id)
    for card in record.cards:
        if (cases / card.id / "expected.json").is_file():
            _score_card(tally, record, card.id, load_expected(cases / card.id))


def _score_card(tally: Tally, record: RunRecord, card_id: str, expected: dict) -> None:
    """First review of the case's diff against expected.json (the B0 measure: first-pass verdict and seeds)."""
    first_report = next((r for r in record.reports if r.card_id == card_id), None)
    first_attempt = next((a for a in record.attempts if a.card_id == card_id), None)
    tally.with_expected += 1
    tally.verdict_match += bool(first_report) and first_report.verdict == expected["expected_verdict"]
    tally.seeded += len(expected.get("seeded", []))
    if first_report and first_attempt:
        tally.caught += len(seeds_caught(expected, first_attempt.diff, first_report.findings))


def static_measures(variant: str) -> dict:
    """S1 and S3 from the code (spec section 4)."""
    folder = HERE / "variants" / variant
    glue = sum(code_lines(p) for p in SHARED_GLUE if p.is_file())
    own = folder / "testing.py"
    return {"S1": folder_lines(folder), "S3": glue + (code_lines(own) if own.is_file() else 0)}


def _pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:.0f} % ({part}/{whole})" if whole else "n/a"


def print_tables(tallies: dict[str, Tally]) -> None:
    """Markdown tables of the raw measures."""
    print("| Variant | E2 blocked | E7 swap violations | S1 lines | S3 glue | S4 overhead s | import s |")
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for name, t in tallies.items():
        s = static_measures(name)
        imp = f"{max(t.import_s):.2f}" if t.import_s else "n/a"
        row = [name, len(t.blocked), len(t.swap_violations), s["S1"], s["S3"], f"{t.overhead_s:.1f}", imp]
        print("| " + " | ".join(map(str, row)) + " |")
    print("\nManual: E1 (licences), E3 (Windows real run), E4/E5 (contract test), E6 (code review), E8/S2 (venv diff),")
    print("S5 (NOTES.md), S6 (changelogs), S7 (sketch).\n")
    print("| Variant | runs | reviews | seeds caught | hallucinated / 10 reviews | first verdict = expected.json |")
    print("| --- | --- | --- | --- | --- | --- |")
    for name, t in tallies.items():
        per10 = f"{10 * t.hallucinated / t.reviews:.1f}" if t.reviews else "n/a"
        match = _pct(t.verdict_match, t.with_expected)
        print(f"| {name} | {t.runs} | {t.reviews} | {_pct(t.caught, t.seeded)} | {per10} | {match} |")


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("results", type=Path, nargs="?", default=HERE / "results")
    ap.add_argument("--cases-dir", type=Path, default=HERE / "cases")
    args = ap.parse_args(argv)
    tallies = {v: Tally() for v in VARIANTS}
    for run in run_dirs(args.results):
        record = _json(run / "reports.json")
        if record.get("variant") in tallies:
            add_run(tallies[record["variant"]], run, args.cases_dir)
    print_tables(tallies)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
