"""Offline two-stage Leading review result (plan A of docs/research/2026-11-06-leading-speed-plan.md).

Reads the per-run JSON files that bench.py writes to <out>/runs/ for two plain repeated runs,
pairs stage 1 (fast model, e.g. gpt-oss:20b) and stage 2 (qwen3.8:27b) by case and repeat, applies
the rule fixed before the run and prints the four win/lose criteria. No GPU, standard library only.

Rule (do not tune after seeing results):
- Stage 1 verdict `ready` with no finding at all: accept `ready`, stage 2 is not run (risky branch).
- Anything else (rework, escalate, any finding, invalid JSON): the final result is stage 2's.

Usage:
    python aggregate_twostage.py --stage1 out/A3-gptoss --stage2 out/A3-qwen [--json report.json]
    # both stages in one folder: --stage1 out/X --stage1-model gpt-oss:20b --stage2 out/X --stage2-model qwen3.8:27b
"""

import argparse
import json
import pathlib
import sys

MIN_SEEDS = 12
MIN_CATCH = 0.80
MAX_BELOW_ALONE = 1
MAX_TIME_RATIO = 0.50
MAX_FALSE_READY = 1


def load_runs(folder: pathlib.Path, model: str | None) -> dict[tuple[str, int], dict]:
    runs: dict[tuple[str, int], dict] = {}
    for path in sorted((folder / "runs").glob("*.json")):
        run = json.loads(path.read_text(encoding="utf-8"))
        if model is None or run.get("model") == model:
            runs[(run["case"], int(run.get("repeat", 1)))] = run
    return runs


def accepts_ready(stage1: dict) -> bool:
    """True when stage 1 alone settles the case: a clean `ready` with no finding."""
    return stage1.get("verdict") == "ready" and not stage1.get("findings")


def pipeline(stage1: dict, stage2: dict) -> dict:
    """Final result and seconds of one case-repeat under the fixed rule."""
    if accepts_ready(stage1):
        return {"final": "ready", "ran_stage2": False, "seeds_caught": 0, "invented": 0,
                "seconds": stage1["wall_s"]}
    return {"final": stage2.get("verdict"), "ran_stage2": True,
            "seeds_caught": stage2.get("seeded_caught", 0), "invented": stage2.get("hallucinated", 0),
            "seconds": stage1["wall_s"] + stage2["wall_s"]}


def summarise(stage1: dict[tuple[str, int], dict], stage2: dict[tuple[str, int], dict]) -> dict:
    keys = sorted(set(stage1) & set(stage2))
    rows, missing = [], sorted(set(stage1) ^ set(stage2))
    for key in keys:
        s1, s2 = stage1[key], stage2[key]
        out = pipeline(s1, s2)
        seeded = s2.get("seeded", 0)
        rows.append({
            "case": key[0], "repeat": key[1], "expected": s2.get("expected"), "seeded": seeded,
            "stage1_verdict": s1.get("verdict"), "stage1_findings": s1.get("findings", 0),
            "stage1_s": s1["wall_s"], "stage2_verdict": s2.get("verdict"), "stage2_s": s2["wall_s"],
            "alone_caught": s2.get("seeded_caught", 0), "alone_invented": s2.get("hallucinated", 0),
            "pipeline_final": out["final"], "ran_stage2": out["ran_stage2"],
            "pipeline_caught": out["seeds_caught"], "pipeline_invented": out["invented"],
            "pipeline_s": out["seconds"],
            "false_ready_seed": bool(seeded) and not out["ran_stage2"],
        })
    seed_rows = [r for r in rows if r["seeded"]]
    seed_cases = sorted({r["case"] for r in seed_rows})
    total = sum(r["seeded"] for r in seed_rows)
    caught, alone = sum(r["pipeline_caught"] for r in seed_rows), sum(r["alone_caught"] for r in seed_rows)
    time_pipeline, time_alone = sum(r["pipeline_s"] for r in rows), sum(r["stage2_s"] for r in rows)
    ready_rows = [r for r in rows if r["expected"] == "ready"]
    summary = {
        "pairs": len(rows), "unpaired": [list(k) for k in missing],
        "seed_cases": len(seed_cases), "seed_repeats": total,
        "pipeline_caught": caught, "alone_caught": alone,
        "pipeline_catch_rate": round(caught / total, 3) if total else 0.0,
        "alone_catch_rate": round(alone / total, 3) if total else 0.0,
        "invented_final": sum(r["pipeline_invented"] for r in rows),
        "invented_alone": sum(r["alone_invented"] for r in rows),
        "false_ready_seeds": [f'{r["case"]}#r{r["repeat"]}' for r in rows if r["false_ready_seed"]],
        "seconds_pipeline": round(time_pipeline, 1), "seconds_alone": round(time_alone, 1),
        "time_ratio": round(time_pipeline / time_alone, 3) if time_alone else 0.0,
        "stage2_skipped": sum(not r["ran_stage2"] for r in rows),
        "ready_cases_not_ready_pipeline": sum(r["pipeline_final"] != "ready" for r in ready_rows),
        "ready_cases_not_ready_alone": sum(r["stage2_verdict"] != "ready" for r in ready_rows),
        "ready_case_repeats": len(ready_rows),
    }
    summary["criteria"] = criteria(summary)
    summary["win"] = all(c["ok"] for c in summary["criteria"])
    return {"summary": summary, "rows": rows}


def criteria(s: dict) -> list[dict]:
    below = s["alone_caught"] - s["pipeline_caught"]
    return [
        {"id": 1, "text": f"seed catch >= {MIN_CATCH:.0%} over >= {MIN_SEEDS} seeds and at most "
                          f"{MAX_BELOW_ALONE} repeat below qwen alone",
         "value": f'{s["pipeline_caught"]}/{s["seed_repeats"]} ({s["pipeline_catch_rate"]:.0%}) on '
                  f'{s["seed_cases"]} seeds, {below} below alone',
         "ok": s["seed_cases"] >= MIN_SEEDS and s["pipeline_catch_rate"] >= MIN_CATCH and below <= MAX_BELOW_ALONE},
        {"id": 2, "text": "invented quotes in the final output = 0", "value": str(s["invented_final"]),
         "ok": s["invented_final"] == 0},
        {"id": 3, "text": f"total time <= {MAX_TIME_RATIO:.0%} of qwen alone",
         "value": f'{s["seconds_pipeline"]} s vs {s["seconds_alone"]} s ({s["time_ratio"]:.0%})',
         "ok": s["seconds_alone"] > 0 and s["time_ratio"] <= MAX_TIME_RATIO},
        {"id": 4, "text": f"false-ready seed repeats <= {MAX_FALSE_READY}",
         "value": f'{len(s["false_ready_seeds"])}', "ok": len(s["false_ready_seeds"]) <= MAX_FALSE_READY},
    ]


def render(result: dict) -> str:
    s = result["summary"]
    lines = [f'pairs {s["pairs"]}, stage 2 skipped on {s["stage2_skipped"]}; seeds {s["seed_cases"]} cases, '
             f'{s["seed_repeats"]} seed-repeats', ""]
    lines.append("case                     rep exp      s1 verdict (find) s1_s   s2 verdict   s2_s  final     caught")
    for r in result["rows"]:
        lines.append(f'{r["case"]:<24} {r["repeat"]:>3} {str(r["expected"]):<8} '
                     f'{str(r["stage1_verdict"]):<10} ({r["stage1_findings"]:>2}) {r["stage1_s"]:>5}  '
                     f'{str(r["stage2_verdict"]):<11} {r["stage2_s"]:>6}  {str(r["pipeline_final"]):<9} '
                     f'{r["pipeline_caught"]}/{r["seeded"]}'
                     + ("  FALSE-READY" if r["false_ready_seed"] else ""))
    lines += ["", f'qwen alone: seeds {s["alone_caught"]}/{s["seed_repeats"]} ({s["alone_catch_rate"]:.0%}), '
              f'invented {s["invented_alone"]}, ready cases not ready {s["ready_cases_not_ready_alone"]}/'
              f'{s["ready_case_repeats"]}',
              f'pipeline:   seeds {s["pipeline_caught"]}/{s["seed_repeats"]} ({s["pipeline_catch_rate"]:.0%}), '
              f'invented {s["invented_final"]}, ready cases not ready {s["ready_cases_not_ready_pipeline"]}/'
              f'{s["ready_case_repeats"]}', ""]
    for c in s["criteria"]:
        lines.append(f'[{"OK  " if c["ok"] else "FAIL"}] {c["id"]}. {c["text"]}: {c["value"]}')
    if s["unpaired"]:
        lines.append(f'unpaired runs (ignored): {s["unpaired"]}')
    lines.append("RESULT: " + ("WIN" if s["win"] else "LOSE"))
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--stage1", required=True, type=pathlib.Path, help="bench output folder of the fast model")
    ap.add_argument("--stage2", required=True, type=pathlib.Path, help="bench output folder of qwen3.8:27b")
    ap.add_argument("--stage1-model", default=None)
    ap.add_argument("--stage2-model", default=None)
    ap.add_argument("--json", type=pathlib.Path, default=None, help="also write the full result here")
    args = ap.parse_args()
    result = summarise(load_runs(args.stage1, args.stage1_model), load_runs(args.stage2, args.stage2_model))
    if not result["rows"]:
        print("no paired runs found", file=sys.stderr)
        return 2
    print(render(result))
    if args.json:
        args.json.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
