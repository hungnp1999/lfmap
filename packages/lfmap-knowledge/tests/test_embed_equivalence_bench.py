"""MC-4: bge-m3 through /v1/embeddings must equal /api/embed (spec model-client.md section 8, decision 6).

The live test needs Ollama with bge-m3 and no other model loaded; run it with `pytest -m local`. CI skips it.
"""

import importlib.util
import os
import shutil
import tempfile
import urllib.request
from pathlib import Path

import pytest

RUN = Path(__file__).resolve().parents[3] / "spikes" / "mc4-embed-equivalence" / "run.py"


def _load():
    spec = importlib.util.spec_from_file_location("mc4_run", RUN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ollama_has_bge_m3() -> bool:
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return b"bge-m3" in opener.open("http://127.0.0.1:11434/api/tags", timeout=3).read()
    except OSError:
        return False


@pytest.mark.local
@pytest.mark.skipif(bool(os.environ.get("CI")), reason="needs a local Ollama")
@pytest.mark.skipif(not _ollama_has_bge_m3(), reason="Ollama with bge-m3 is not running")
def test_v1_embeddings_equal_api_embed() -> None:
    run = _load()
    work = Path(tempfile.mkdtemp(prefix="mc4-test-"))
    try:
        perms = run.PermissionManager([], [], network=True)
        result = run.run(
            run.OllamaEmbedder(run.OLLAMA, run.MODEL, perms), run.V1Embedder(f"{run.OLLAMA}/v1", run.MODEL), work
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)
    assert result["checks"] == dict.fromkeys(result["checks"], True), result["checks"]
    assert result["vectors"]["cos_min"] >= run.COSINE_MIN
    assert result["verdict"] == "PASS"


def test_verdict_rule_fails_on_low_cosine() -> None:
    run = _load()
    vectors = {"below_threshold": 1, "dim_old": [1024], "dim_new": [1024]}
    row = {"id": "S1", "gold_in_top10": ["QT-01"], "thresholds": {"0.0": {"precision": 0.5, "tokens": 100}}}
    assert run.verdict(vectors, [row], [row])["verdict"] == "FAIL"
    assert run.verdict(vectors | {"below_threshold": 0}, [row], [row])["verdict"] == "PASS"
