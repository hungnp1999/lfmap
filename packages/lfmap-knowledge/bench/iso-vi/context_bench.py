"""Score knowledge get_context against the gold files of questions.json at several min_relative_score values.

Index docs/ first (a knowledge root that holds only this corpus), then run from the repo root:
    uv run python packages/lfmap-knowledge/bench/iso-vi/context_bench.py --out D:\\Tmp\\iso-vi-result.md
A chunk counts as relevant when its file code (the file name before the first "_") is in gold or acceptable;
recall counts gold files only.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
THRESHOLDS = (0.0, 0.3, 0.4, 0.5)


def _code(path: str) -> str:
    return Path(path).name.split("_", 1)[0]


def get_context(lfmap: str, question: str, threshold: float, budget: int) -> dict:
    cmd = [lfmap, "knowledge", "get_context", "--question", question, "--token-budget", str(budget)]
    cmd += ["--min-relative-score", str(threshold), "--json"]
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=True).stdout
    return json.loads(out)


def score(q: dict, result: dict) -> dict:
    codes = [_code(c["citation"]["path"]) for c in result["chunks"]]
    relevant = set(q["gold"]) | set(q["acceptable"])
    kept = len(codes)
    return {
        "chunks": kept,
        "tokens": result["estimated_tokens"],
        "precision": sum(c in relevant for c in codes) / kept if kept else 0.0,
        "gold_precision": sum(c in q["gold"] for c in codes) / kept if kept else 0.0,
        "recall": len(set(codes) & set(q["gold"])) / len(q["gold"]),
        "gold_chunks": sum(c in q["gold"] for c in codes),
        "top": codes[0] if codes else "",
    }


def report(rows: list[dict]) -> str:
    lines = [
        "| Q | type | threshold | chunks | tokens | precision | gold precision | gold-file recall | gold chunks"
        " | top |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['id']} | {r['type']} | {r['threshold']} | {r['chunks']} | {r['tokens']} | {r['precision']:.2f}"
            f" | {r['gold_precision']:.2f} | {r['recall']:.2f} | {r['gold_chunks']} | {r['top']} |"
        )
    lines += ["", "| type | threshold | avg tokens | avg precision | avg gold-file recall |", "|---|---|---|---|---|"]
    for kind in ("keyword", "semantic"):
        for t in THRESHOLDS:
            sel = [r for r in rows if r["type"] == kind and r["threshold"] == t]
            if sel:
                n = len(sel)
                lines.append(
                    f"| {kind} | {t} | {sum(r['tokens'] for r in sel) / n:.0f}"
                    f" | {sum(r['precision'] for r in sel) / n:.2f} | {sum(r['recall'] for r in sel) / n:.2f} |"
                )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lfmap", default="lfmap")
    parser.add_argument("--budget", type=int, default=4000)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    questions = json.loads((HERE / "questions.json").read_text(encoding="utf-8"))
    rows = []
    for q in questions:
        for t in THRESHOLDS:
            result = get_context(args.lfmap, q["question"], t, args.budget)
            rows.append({"id": q["id"], "type": q["type"], "threshold": t} | score(q, result))
    text = report(rows)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
