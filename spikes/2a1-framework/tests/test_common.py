"""Tests of the framework-free `common/` package: gates, quote check, guard, prompts, Ollama client, cases."""

import http.server
import json
import socket
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from contract_fixture import GOOD_CALC, make_package

from common.cases import case_dirs, load_card, load_expected, load_package
from common.fake import FakeModel, review_reply, work_reply
from common.gates import (
    changed,
    files_from_patch,
    make_diff,
    model_attempt,
    replay_attempt,
    review_log,
    snapshot,
    write_in,
)
from common.guard import SocketGuard, is_loopback
from common.metrics import Trace, code_lines, traced
from common.models import Card, Finding, Models, Report
from common.ollama import OllamaModel, check_loopback
from common.prompts import parse_cards, parse_file_reply, parse_report, review_user, work_user
from common.quote import check_quotes, position, seeds_caught

SPIKE = Path(__file__).resolve().parent.parent
CASES = SPIKE / "cases"
CALC = Card(id="calc", target="calc.py", tests=["tests/test_calc.py"], prompt="Write add.")


# --- cases -------------------------------------------------------------------------------------------


def test_cases_load_and_reach_twelve_seeds():
    dirs = case_dirs(CASES)
    assert len(dirs) >= 19
    seeds = [s for d in dirs for s in load_expected(d)["seeded"]]
    assert len(seeds) >= 12


@pytest.mark.parametrize("case", case_dirs(CASES), ids=lambda p: p.name)
def test_case_is_consistent(case: Path):
    card, expected = load_card(case), load_expected(case)
    assert expected["id"] == case.name
    assert expected["expected_verdict"] in ("ready", "rework", "escalate")
    assert set(files_from_patch(card.replay_diff or "")) == {card.target}
    assert card.tests and card.tests[0].startswith("packages/lfmap-knowledge/tests/")
    lines = [ln[1:] for ln in (card.replay_diff or "").splitlines()]
    for seed in expected["seeded"]:
        assert position(lines, seed) >= 0, seed


def test_k4_k7_package_loads():
    package = load_package(CASES / "packages" / "K4-K7")
    assert package.id == "K4-K7" and "embed.py" in package.goal and "C1" in package.standard


# --- quote check -------------------------------------------------------------------------------------


def test_check_quotes_moves_invented_quotes_to_dropped():
    diff = make_diff("calc.py", "", GOOD_CALC)
    report = Report(
        card_id="calc",
        verdict="rework",
        findings=[
            Finding(check="C1", quote="  return   a + b", problem="x"),
            Finding(check="C3", quote="os.system(cmd)", problem="y"),
            Finding(check="C3", quote="", problem="z"),
        ],
    )
    checked = check_quotes(report, diff)
    assert [f.quote for f in checked.findings] == ["  return   a + b"]
    assert [f.quote for f in checked.dropped] == ["os.system(cmd)", ""]


def test_seed_caught_by_nearby_quote_or_keyword():
    case = CASES / "K6-seed-order"
    diff, expected = load_card(case).replay_diff or "", load_expected(case)
    near = Finding(check="C1", quote="ORDER BY score DESC", problem="wrong")
    keyword = Finding(check="C1", quote="import sqlite3", problem="bm25 is lower-is-better")
    unrelated = Finding(check="C1", quote="import sqlite3", problem="unused import")
    assert seeds_caught(expected, diff, [near]) == expected["seeded"]
    assert seeds_caught(expected, diff, [keyword]) == expected["seeded"]
    assert seeds_caught(expected, diff, [unrelated]) == []


# --- prompts -----------------------------------------------------------------------------------------


def test_parse_report_handles_wrapped_and_invalid_json():
    wrapped = "Here you go:\n" + review_reply("rework", [{"check": "C2", "quote": "q", "problem": "p"}, {"x": 1}])
    report = parse_report("c", wrapped)
    assert report.verdict == "rework" and [f.quote for f in report.findings] == ["q"]
    assert parse_report("c", "no json").verdict == "invalid_json"
    assert parse_report("c", '{"verdict": "maybe"}').verdict == "invalid_json"


def test_parse_file_reply_and_cards():
    assert parse_file_reply(work_reply("a.py", "x = 1\n")) == ("a.py", "x = 1\n")
    assert parse_file_reply("```python\nx = 1\n```") == (None, "x = 1\n")
    assert parse_file_reply("FILE: a.py\nno block") == ("a.py", None)
    cards = parse_cards('{"cards": [{"id": "a", "target": "a.py", "prompt": "p"}, {"id": "bad"}]}')
    assert [c.id for c in cards] == ["a"]


def test_messages_carry_the_card_id_and_feedback():
    assert work_user(CALC).startswith("CARD ID: calc")
    assert "FIX THIS:\nboom" in work_user(CALC, "boom")
    assert "TEST LOG" in review_user(CALC, "diff", "log") and "TEST LOG" not in review_user(CALC, "diff")


# --- gates -------------------------------------------------------------------------------------------


def test_write_in_refuses_paths_outside_the_workdir(tmp_path: Path):
    with pytest.raises(ValueError):
        write_in(tmp_path, "../escape.py", "x")
    with pytest.raises(ValueError):
        write_in(tmp_path, str(tmp_path.parent / "abs.py"), "x")
    for unc in ("\\\\server\\share\\a.py", "//server/share/a.py"):
        with pytest.raises(ValueError, match="relative"):
            write_in(tmp_path, unc, "x")
    assert write_in(tmp_path, "pkg/a.py", "x\n") == ""
    assert write_in(tmp_path, "pkg/a.py", "y\n") == "x\n"


def test_snapshot_skips_caches_and_detects_changes(tmp_path: Path):
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "a.pyc").write_bytes(b"x")
    (tmp_path / "a.py").write_text("a")
    before = snapshot(tmp_path)
    assert list(before) == ["a.py"]
    (tmp_path / "a.py").write_text("b")
    (tmp_path / "b.py").write_text("b")
    assert changed(before, snapshot(tmp_path)) == {"a.py", "b.py"}


def test_model_attempt_passes_gates(tmp_path: Path):
    attempt = model_attempt(make_package(tmp_path), CALC, 1, work_reply("calc.py", GOOD_CALC))
    assert attempt.ok, attempt.gate_log()
    assert [g.name for g in attempt.gates] == ["scope", "tests_unchanged", "ruff_check", "ruff_format", "pytest"]
    assert "+    return a + b" in attempt.diff


def test_model_attempt_fails_tests_and_lint(tmp_path: Path):
    bad = "import os\ndef add(a,b):\n    return a-b\n"
    attempt = model_attempt(make_package(tmp_path), CALC, 1, work_reply("calc.py", bad))
    failed = {g.name for g in attempt.gates if not g.ok}
    assert failed == {"ruff_check", "ruff_format", "pytest"}
    assert "[pytest]" in attempt.gate_log()


def test_model_attempt_never_writes_another_file(tmp_path: Path):
    package = make_package(tmp_path)
    attempt = model_attempt(package, CALC, 1, work_reply("tests/test_calc.py", "assert True\n"))
    assert not attempt.ok and attempt.gates[0].name == "reply"
    assert "add(2, 3)" in (package.workdir / "tests" / "test_calc.py").read_text()
    assert not model_attempt(package, CALC, 1, "no code").ok


def test_scope_and_frozen_test_gates(tmp_path: Path):
    package = make_package(tmp_path)
    card = CALC.model_copy(update={"target": "tests/test_calc.py", "scope": ["tests/test_calc.py"]})
    attempt = model_attempt(package, card, 1, work_reply("tests/test_calc.py", "def test_x():\n    pass\n"))
    assert {g.name for g in attempt.gates if not g.ok} == {"tests_unchanged"}
    outside = CALC.model_copy(update={"replay_diff": make_diff("other.py", "", "x = 1\n")})
    assert replay_attempt(package, outside).gates[0].name == "scope"


def test_replay_attempt_without_workdir_uses_the_case_log():
    card = load_card(CASES / "K5-red")
    package = load_package(CASES / "packages" / "K4-K7")
    attempt = replay_attempt(package, card)
    assert attempt.gates == [] and attempt.diff == card.replay_diff
    assert "AssertionError" in review_log(card, attempt)


# --- guard -------------------------------------------------------------------------------------------


@pytest.mark.parametrize("address", [("127.0.0.1", 1), ("::1", 1, 0, 0), ("localhost", 1), ("127.8.9.1", 2), "/sock"])
def test_loopback_addresses(address: object):
    assert is_loopback(address)


@pytest.mark.parametrize("address", [("192.0.2.1", 80), ("example.com", 443), ("::ffff:192.0.2.1", 1), None])
def test_non_loopback_addresses(address: object):
    assert not is_loopback(address)


def test_guard_refuses_and_records_non_loopback():
    with SocketGuard() as inner:
        with socket.socket() as sock, pytest.raises(ConnectionRefusedError):
            sock.connect(("192.0.2.1", 9))
        with socket.socket() as sock, pytest.raises(ConnectionRefusedError):
            sock.connect_ex(("198.51.100.7", 9))
    assert len(inner.blocked) == 2
    assert socket.socket.connect is not None


def test_guard_allows_loopback(tmp_path: Path):
    with socket.create_server(("127.0.0.1", 0)) as server, SocketGuard() as inner:
        with socket.create_connection(server.getsockname(), timeout=5):
            pass
    assert inner.blocked == [] and len(inner.allowed) == 1


# --- Ollama client -----------------------------------------------------------------------------------


class _Ollama(http.server.BaseHTTPRequestHandler):
    bodies: list[dict] = []

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).bodies.append(body)
        reply = json.dumps({"message": {"role": "assistant", "content": "ok"}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(reply)

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def ollama() -> Iterator[str]:
    _Ollama.bodies = []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Ollama)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


@pytest.mark.parametrize("url", ["http://10.0.0.5:11434", "https://127.0.0.1", "http://u:p@127.0.0.1", "ftp://x"])
def test_ollama_url_must_be_loopback(url: str):
    with pytest.raises(ValueError):
        check_loopback(url)


def test_ollama_chat_body_and_no_proxy(ollama: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HTTP_PROXY", "http://192.0.2.1:3128")
    monkeypatch.setenv("http_proxy", "http://192.0.2.1:3128")
    model = OllamaModel("qwen2.5-coder:14b", ollama + "/")
    assert model.chat("sys", "user", {"type": "object"}) == "ok"
    body = _Ollama.bodies[0]
    assert body["model"] == "qwen2.5-coder:14b" and body["stream"] is False and body["format"] == {"type": "object"}
    assert body["options"] == {"temperature": 0, "num_ctx": 16384, "num_predict": 8192}
    assert [m["role"] for m in body["messages"]] == ["system", "user"] and "think" not in body


# --- fake and metrics --------------------------------------------------------------------------------


def test_fake_model_replies_in_order_and_refuses_unknown():
    fake = FakeModel("f").on("A", "1", "2")
    assert [fake.chat("", "xA"), fake.chat("", "A"), fake.chat("", "A")] == ["1", "2", "2"]
    with pytest.raises(AssertionError):
        fake.chat("", "B")


def test_trace_counts_swaps():
    trace = Trace()
    models = traced(Models(leading=FakeModel("L").on("", "x"), working=FakeModel("W").on("", "y")), trace)
    for model in (models.leading, models.working, models.working, models.leading):
        model.chat("s", "u")
    assert trace.sequence() == ["L", "W", "L"] and trace.swaps() == 2
    assert trace.calls[0].prompt_chars == 2 and trace.calls[0].reply_chars == 1


def test_code_lines_skip_blank_comment_and_docstring(tmp_path: Path):
    source = '"""Module\ndoc."""\n\n# comment\nx = 1  # trailing\n\n\ndef f():\n    """Doc."""\n    return "s"\n'
    (tmp_path / "m.py").write_text(source)
    assert code_lines(tmp_path / "m.py") == 3
