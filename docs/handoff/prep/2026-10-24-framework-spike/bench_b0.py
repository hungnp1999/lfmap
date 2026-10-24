"""B0 benchmark for Leading Agent candidates on a local Ollama (standard library only).

Per model: licence, load time, VRAM, GPU share, generation speed at two context sizes,
then one first-pass review per case in cases/ and one package split.
Results: out/<stamp>/bench.csv, reviews.csv, answers/*.json.

Usage (from this folder):
    python bench.py --models gpt-oss:20b devstral-small-2:24b qwen3-coder:30b --pull
"""

import argparse
import csv
import datetime as dt
import json
import pathlib
import re
import subprocess
import time
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
URL = "http://127.0.0.1:11434"
CONTEXTS = (8192, 16384)
REVIEW_CTX = 16384

SPEED_PROMPT = (
    "Write a Python 3.12 function `merge_intervals(items: list[tuple[int, int]]) -> list[tuple[int, int]]` "
    "with a one-line docstring, then five pytest tests for it. Code only."
)

STANDARD = """You are the Leading Agent: a strict first-pass code reviewer. A small model wrote the diff
below for the task card. Check it against the card and this checklist:
C1 behaviour matches the card's API and rules; C2 edge cases and error handling the card asks for;
C3 security (SQL built from strings, paths, network use without permission, proxies, credentials);
C4 tests would fail (see the test log if given).
Style (docstring length, comments, naming) is NOT a finding: put at most one style remark in "notes";
it never changes the verdict.
Report only real problems against C1-C4. Every finding must quote ONE line copied exactly from the diff.
Verdict: "ready" (no C1-C4 problem), "rework" (fixable C1-C4 problems), "escalate" (wrong approach
or beyond a small fix). Answer with JSON only, in this shape:
{"verdict": "ready|rework|escalate", "findings": [{"check": "C1", "quote": "...", "problem": "..."}], "notes": "..."}"""

SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["ready", "rework", "escalate"]},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "check": {"type": "string"},
                    "quote": {"type": "string"},
                    "problem": {"type": "string"},
                },
                "required": ["check", "quote", "problem"],
            },
        },
    },
    "required": ["verdict", "findings"],
}
SCHEMA["properties"]["notes"] = {"type": "string"}

OPTS = {"think": None, "schema": True}

SPLIT_PROMPT = """You are the Leading Agent. Split this work package into at most 4 S task cards for a
small 14B coding model. Each card: id, target file, functions with signatures, rules, which of the
frozen tests it must pass. Do not change tests. Answer in Markdown.

WORK PACKAGE
Goal: add a `lessons` module to qwen-loop (plain Python 3.12, standard library only).
- lessons.toml holds entries: id, rule, applies_to (glob), seen (int), last_seen (ISO date).
- load(path) -> list[Lesson]; match(lessons, target_path) -> list[Lesson] (max 10, most seen first);
  bump(path, lesson_id, today) updates seen/last_seen atomically; retire(lessons, batches_unseen=3).
- render(lessons) -> str: a RULES block appended to a card prompt.
Frozen tests: tests/test_lessons.py (load, match, bump, retire, render)."""


def call(path: str, body: dict, timeout: int = 3600) -> dict:
    body = {"stream": False, **body}
    req = urllib.request.Request(
        URL + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def get(path: str) -> dict:
    with urllib.request.urlopen(URL + path, timeout=60) as resp:
        return json.loads(resp.read())


def run(cmd: list[str]) -> str:
    done = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return (done.stdout + done.stderr).strip()


def vram_mb() -> int:
    out = run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"])
    return int(out.splitlines()[0]) if out[:1].isdigit() else -1


def unload_all() -> None:
    for m in get("/api/ps").get("models", []):
        call("/api/generate", {"model": m["name"], "keep_alive": 0})
    time.sleep(3)


def gpu_share(model: str) -> float:
    for m in get("/api/ps").get("models", []):
        if m["name"] == model and m.get("size"):
            return round(100 * m.get("size_vram", 0) / m["size"], 1)
    return -1.0


def rate(count: int, ns: int) -> float:
    return round(count / (ns / 1e9), 1) if ns else 0.0


def measure(model: str, ctx: int) -> dict:
    unload_all()
    t0 = time.time()
    warm = call(
        "/api/generate",
        {"model": model, "prompt": "OK", "keep_alive": "30m", "options": {"num_ctx": ctx, "num_predict": 1}},
    )
    load_s = round(time.time() - t0, 1)
    r = call(
        "/api/generate",
        {
            "model": model,
            "prompt": SPEED_PROMPT,
            "stream": False,
            "keep_alive": "30m",
            "options": {"num_ctx": ctx, "num_predict": 600, "temperature": 0},
        },
    )
    return {
        "model": model,
        "num_ctx": ctx,
        "load_s": load_s,
        "load_ns_reported": warm.get("load_duration", 0),
        "gpu_pct": gpu_share(model),
        "vram_mb": vram_mb(),
        "prompt_tok_s": rate(r.get("prompt_eval_count", 0), r.get("prompt_eval_duration", 0)),
        "gen_tok_s": rate(r.get("eval_count", 0), r.get("eval_duration", 0)),
        "gen_tokens": r.get("eval_count", 0),
    }


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def diff_lines(diff: str) -> str:
    lines = [ln[1:] if ln[:1] in "+- " else ln for ln in diff.splitlines()]
    return norm("\n".join(lines))


def line_index(diff: str) -> list[str]:
    return [norm(ln[1:] if ln[:1] in "+- " else ln) for ln in diff.splitlines()]


def position(lines: list[str], text: str) -> int:
    text = norm(text)
    for i, ln in enumerate(lines):
        if text and (text == ln or (len(text) > 12 and text in ln)):
            return i
    return -1


def parse(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if 0 <= start < end:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
    return {"verdict": "invalid_json", "findings": []}


def caught_seed(seed: str, keywords: list[str], lines: list[str], findings: list[dict]) -> bool:
    m = position(lines, seed)
    for f in findings:
        i = position(lines, f.get("quote", ""))
        if m >= 0 and i >= 0 and abs(i - m) <= 3:
            return True
        if any(k.lower() in f.get("problem", "").lower() for k in keywords):
            return True
    return False


def review(model: str, case: pathlib.Path, answers: pathlib.Path) -> dict:
    diff = (case / "diff.patch").read_text(encoding="utf-8")
    card = (case / "card.md").read_text(encoding="utf-8")
    log = case / "test.log"
    expected = json.loads((case / "expected.json").read_text(encoding="utf-8"))
    user = f"TASK CARD\n{card}\n\nDIFF\n{diff}"
    if log.exists():
        user += f"\n\nTEST LOG (tail)\n{log.read_text(encoding='utf-8')}"
    body = {
        "model": model,
        "stream": False,
        "keep_alive": "30m",
        "options": {"num_ctx": REVIEW_CTX, "temperature": 0, "num_predict": 8192},
        "messages": [{"role": "system", "content": STANDARD}, {"role": "user", "content": user}],
    }
    if OPTS["schema"]:
        body["format"] = SCHEMA
    if OPTS["think"] is not None:
        body["think"] = OPTS["think"]
    t0 = time.time()
    r = call("/api/chat", body)
    wall = round(time.time() - t0, 1)
    msg = r.get("message", {})
    text = msg.get("content", "")
    data = parse(text)
    haystack = diff_lines(diff)
    lines = line_index(diff)
    findings = [f for f in data.get("findings", []) if isinstance(f, dict)]
    real = [f for f in findings if norm(f.get("quote", "")) and norm(f.get("quote", "")) in haystack]
    caught = [s for s in expected["seeded"] if caught_seed(s, expected.get("keywords", []), lines, real)]
    safe = model.replace(":", "_").replace("/", "_") + f"__think-{OPTS['think']}"
    (answers / f"{safe}__{case.name}.json").write_text(
        json.dumps(
            {
                "raw": text,
                "thinking": msg.get("thinking", ""),
                "done_reason": r.get("done_reason"),
                "options": OPTS,
                "parsed": data,
                "expected": expected,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return {
        "model": model,
        "think": OPTS["think"],
        "schema": OPTS["schema"],
        "case": case.name,
        "expected": expected["expected_verdict"],
        "verdict": data.get("verdict"),
        "findings": len(findings),
        "quotes_found": len(real),
        "hallucinated": len(findings) - len(real),
        "seeded": len(expected["seeded"]),
        "seeded_caught": len(caught),
        "wall_s": wall,
        "gen_tok_s": rate(r.get("eval_count", 0), r.get("eval_duration", 0)),
        "prompt_tokens": r.get("prompt_eval_count", 0),
        "gen_tokens": r.get("eval_count", 0),
        "thinking_chars": len(msg.get("thinking", "") or ""),
        "done_reason": r.get("done_reason"),
    }


def split(model: str, answers: pathlib.Path) -> float:
    t0 = time.time()
    r = call(
        "/api/generate",
        {
            "model": model,
            "prompt": SPLIT_PROMPT,
            "stream": False,
            "keep_alive": "30m",
            "options": {"num_ctx": REVIEW_CTX, "temperature": 0},
        },
    )
    safe = model.replace(":", "_").replace("/", "_")
    (answers / f"{safe}__split.md").write_text(r.get("response", ""), encoding="utf-8")
    return round(time.time() - t0, 1)


def append(path: pathlib.Path, row: dict) -> None:
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(row))
        if new:
            w.writeheader()
        w.writerow(row)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", required=True)
    ap.add_argument("--pull", action="store_true")
    ap.add_argument("--think", default=None, help="true, false, low, medium or high; default: model default")
    ap.add_argument("--no-schema", action="store_true", help="ask for JSON in the prompt instead of format=schema")
    ap.add_argument("--reviews-only", action="store_true", help="skip speed runs and the split task")
    args = ap.parse_args()
    if args.think is not None:
        OPTS["think"] = {"true": True, "false": False}.get(args.think, args.think)
    OPTS["schema"] = not args.no_schema
    out = HERE / "out" / dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    answers = out / "answers"
    answers.mkdir(parents=True)
    cases = sorted(p for p in (HERE / "cases").iterdir() if p.is_dir())
    for model in args.models:
        if args.pull:
            print(run(["ollama", "pull", model])[-300:], flush=True)
        lic = run(["ollama", "show", model, "--license"])
        (answers / f"{model.replace(':', '_')}__LICENSE.txt").write_text(lic, encoding="utf-8")
        size = next((m["size"] for m in get("/api/tags")["models"] if m["name"] == model), 0)
        for ctx in () if args.reviews_only else CONTEXTS:
            row = measure(model, ctx)
            row.update({"size_gb": round(size / 1e9, 1), "license_head": norm(lic[:80])})
            append(out / "bench.csv", row)
            print(row, flush=True)
        for case in cases:
            row = review(model, case, answers)
            append(out / "reviews.csv", row)
            print(row, flush=True)
        if not args.reviews_only:
            print({"model": model, "split_wall_s": split(model, answers)}, flush=True)
        unload_all()
    print(f"DONE {out}")


if __name__ == "__main__":
    main()
