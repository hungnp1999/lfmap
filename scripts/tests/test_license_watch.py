import importlib.util
import json
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("license_watch", Path(__file__).parents[1] / "license_watch.py")
lw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lw)


def fake_fetch(texts: dict[str, bytes]):
    def fetch(url: str) -> bytes:
        for name, (repo, path) in lw.WATCHED.items():
            if url == lw.RAW_URL.format(repo=repo, path=path):
                if name not in texts:
                    raise OSError("unreachable")
                return texts[name]
        raise AssertionError(url)

    return fetch


@pytest.fixture
def texts() -> dict[str, bytes]:
    return {name: f"{name} License\nterms\n".encode() for name in lw.WATCHED}


def test_update_then_check_reports_no_change(tmp_path: Path, texts: dict[str, bytes]) -> None:
    baseline = tmp_path / "watch.json"
    assert lw.main(["--update", "--baseline", str(baseline)], fake_fetch(texts)) == 0
    files = json.loads(baseline.read_text(encoding="utf-8"))["files"]
    assert set(files) == set(lw.WATCHED)
    assert files["n8n"]["first_line"] == "n8n License"
    assert lw.main(["--baseline", str(baseline)], fake_fetch(texts)) == 0


def test_changed_hash_is_reported(tmp_path: Path, texts: dict[str, bytes], capsys) -> None:
    baseline = tmp_path / "watch.json"
    lw.main(["--update", "--baseline", str(baseline)], fake_fetch(texts))
    document = json.loads(baseline.read_text(encoding="utf-8"))
    document["files"]["open-webui"]["sha256"] = "0" * 64
    baseline.write_text(json.dumps(document), encoding="utf-8")
    assert lw.main(["--baseline", str(baseline)], fake_fetch(texts)) == 1
    assert "changed  open-webui" in capsys.readouterr().out


def test_fetch_error_is_exit_2_and_blocks_update(tmp_path: Path, texts: dict[str, bytes]) -> None:
    baseline = tmp_path / "watch.json"
    lw.main(["--update", "--baseline", str(baseline)], fake_fetch(texts))
    del texts["valkey"]
    assert lw.main(["--baseline", str(baseline)], fake_fetch(texts)) == 2
    before = baseline.read_text(encoding="utf-8")
    assert lw.main(["--update", "--baseline", str(baseline)], fake_fetch(texts)) == 2
    assert baseline.read_text(encoding="utf-8") == before


def test_compare_statuses() -> None:
    old = {"a": {"sha256": "1"}, "b": {"sha256": "2"}, "c": {"sha256": "3"}}
    new = {"a": {"sha256": "1"}, "b": {"sha256": "9"}, "d": {"sha256": "4"}}
    assert lw.compare(old, new) == [("a", "same"), ("b", "changed"), ("c", "missing"), ("d", "new")]


def test_committed_baseline_covers_every_watched_file() -> None:
    assert set(lw.load_baseline(lw.BASELINE)) == set(lw.WATCHED)
