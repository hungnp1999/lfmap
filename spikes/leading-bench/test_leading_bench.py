"""Offline tests for bench.py (--repeats, resume, run JSON) and aggregate_twostage.py.

Run from this folder: python -m unittest test_leading_bench -v
A fake Ollama server answers on a free loopback port; no GPU or model is needed.
"""

import contextlib
import io
import json
import pathlib
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

import aggregate_twostage as agg

HERE = pathlib.Path(__file__).resolve().parent
REPLIES: dict[str, dict] = {}
CALLS: list[dict] = []


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass

    def _send(self, data: dict) -> None:
        raw = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        self._send({"models": []} if self.path == "/api/ps" else {"models": [{"name": "m:1", "size": 1}]})

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        CALLS.append(body)
        if self.path != "/api/chat":
            return self._send({})
        case = body["messages"][1]["content"]
        verdict = {"verdict": "ready", "findings": []}
        for name, reply in REPLIES.items():
            if name in case:
                verdict = reply
        self._send({"message": {"content": json.dumps(verdict)}, "done_reason": "stop",
                    "eval_count": 10, "eval_duration": 10**9})


def run_bench(url: str, out: pathlib.Path, *extra: str) -> str:
    done = subprocess.run(
        [sys.executable, str(HERE / "bench.py"), "--models", "m:1", "--reviews-only", "--url", url,
         "--out", str(out), *extra],
        capture_output=True, text=True, check=True,
    )
    return done.stdout


class BenchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = HTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()

    def test_repeats_resume_and_num_gpu(self) -> None:
        CALLS.clear()
        REPLIES.clear()
        REPLIES["ORDER BY score DESC"] = {
            "verdict": "rework",
            "findings": [{"check": "C1", "quote": "ORDER BY score DESC", "problem": "worst first"},
                         {"check": "C1", "quote": "this line is invented", "problem": "x"}]}
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "o"
            run_bench(self.url, out, "--repeats", "2", "--cases", "K6-seed-order", "K6-clean", "--num-gpu", "54")
            files = sorted(p.name for p in (out / "runs").glob("*.json"))
            self.assertEqual(len(files), 4)
            chats = [c for c in CALLS if "messages" in c]
            self.assertEqual(len(chats), 4)
            self.assertTrue(all(c["options"]["num_gpu"] == 54 for c in chats))
            run = json.loads((out / "runs" / next(f for f in files if "K6-seed-order__r2" in f)).read_text("utf-8"))
            self.assertEqual((run["verdict"], run["repeat"], run["seeded_caught"], run["hallucinated"]),
                             ("rework", 2, 1, 1))
            self.assertEqual([f["valid"] for f in run["finding_list"]], [True, False])
            before = len(chats)
            text = run_bench(self.url, out, "--repeats", "3", "--cases", "K6-seed-order", "K6-clean")
            after = len([c for c in CALLS if "messages" in c])
            self.assertEqual(after - before, 2)  # only repeat 3 ran
            self.assertEqual(text.count("'skip'"), 4)

    def test_seed_cases_are_found(self) -> None:
        seeds = 0
        for case in (HERE / "cases").iterdir():
            exp = json.loads((case / "expected.json").read_text("utf-8"))
            seeds += len(exp["seeded"])
        self.assertEqual(len(list((HERE / "cases").iterdir())), 20)
        self.assertEqual(seeds, 12)


def make_run(case: str, repeat: int, verdict: str, wall: float, seeded: int = 0, caught: int = 0,
             findings: int = 0, invented: int = 0, expected: str = "rework") -> dict:
    return {"model": "x", "case": case, "repeat": repeat, "verdict": verdict, "wall_s": wall, "seeded": seeded,
            "seeded_caught": caught, "findings": findings, "hallucinated": invented, "expected": expected}


class AggregateTest(unittest.TestCase):
    def write(self, folder: pathlib.Path, runs: list[dict]) -> None:
        (folder / "runs").mkdir(parents=True)
        for i, run in enumerate(runs):
            (folder / "runs" / f"{i}.json").write_text(json.dumps(run), encoding="utf-8")

    def result(self, s1: list[dict], s2: list[dict]) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            a, b = pathlib.Path(tmp) / "a", pathlib.Path(tmp) / "b"
            self.write(a, s1)
            self.write(b, s2)
            return agg.summarise(agg.load_runs(a, None), agg.load_runs(b, None))

    def test_rule_win(self) -> None:
        s1, s2 = [], []
        for i in range(12):
            s1.append(make_run(f"s{i}", 1, "rework", 10, 1, 1, 1))
            s2.append(make_run(f"s{i}", 1, "rework", 100, 1, 1, 1))
        for i in range(20):  # clean cases settled by stage 1 alone
            s1.append(make_run(f"c{i}", 1, "ready", 10, expected="ready"))
            s2.append(make_run(f"c{i}", 1, "ready", 100, expected="ready"))
        res = agg.summarise({(r["case"], r["repeat"]): r for r in s1}, {(r["case"], r["repeat"]): r for r in s2})
        s = res["summary"]
        self.assertEqual((s["pipeline_caught"], s["seed_repeats"], s["stage2_skipped"]), (12, 12, 20))
        self.assertEqual(s["seconds_pipeline"], 12 * 110 + 20 * 10)
        self.assertEqual(s["seconds_alone"], 12 * 100 + 20 * 100)
        self.assertTrue(s["win"], s["criteria"])

    def test_false_ready_seed_loses(self) -> None:
        s1 = [make_run("a", 1, "ready", 5, 1, 0), make_run("b", 1, "ready", 5, 1, 0)]
        s2 = [make_run("a", 1, "rework", 100, 1, 1, 1), make_run("b", 1, "rework", 100, 1, 1, 1)]
        res = self.result(s1, s2)["summary"]
        self.assertEqual(res["false_ready_seeds"], ["a#r1", "b#r1"])
        self.assertEqual(res["pipeline_caught"], 0)
        self.assertEqual(res["alone_caught"], 2)
        self.assertFalse(res["win"])

    def test_finding_on_ready_runs_stage2_and_invented_counts(self) -> None:
        s1 = [make_run("a", 1, "ready", 5, 1, 0, findings=1)]
        s2 = [make_run("a", 1, "rework", 100, 1, 1, 2, invented=1)]
        res = self.result(s1, s2)
        self.assertTrue(res["rows"][0]["ran_stage2"])
        self.assertEqual(res["summary"]["invented_final"], 1)
        self.assertFalse(res["rows"][0]["false_ready_seed"])

    def test_unpaired_ignored_and_render(self) -> None:
        res = self.result([make_run("a", 1, "rework", 5), make_run("a", 2, "rework", 5)],
                          [make_run("a", 1, "rework", 50)])
        self.assertEqual(res["summary"]["unpaired"], [["a", 2]])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertIn("RESULT:", agg.render(res))


if __name__ == "__main__":
    unittest.main()
