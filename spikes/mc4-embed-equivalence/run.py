"""MC-4: does bge-m3 via /v1/embeddings (OpenAICompatibleClient) equal /api/embed (OllamaEmbedder)?

Run from the repo root:
    uv run python spikes/mc4-embed-equivalence/run.py --out D:\\Tmp\\mc4.json
    uv run python spikes/mc4-embed-equivalence/run.py --fake pass|fail      (no Ollama; checks the verdict logic)

Both indexes live in fresh temporary folders (explicit data_dir, no environment variable is set); the only
file system read outside them is bench/iso-vi/docs. Verdict rule: spec section 8 and decision 6.
"""

import argparse
import hashlib
import importlib.util
import json
import math
import random
import shutil
import sqlite3
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

from lfmap_core import ToolContext
from lfmap_core.models_http import OpenAICompatibleClient
from lfmap_core.permissions import PermissionManager
from lfmap_knowledge.schemas import GetContextInput, ReindexInput, SearchInput
from lfmap_knowledge.tool import KnowledgeTool

ROOT = Path(__file__).resolve().parents[2]
BENCH = ROOT / "packages" / "lfmap-knowledge" / "bench" / "iso-vi"
OLLAMA = "http://127.0.0.1:11434"
MODEL = "bge-m3"
COSINE_MIN = 0.9999
SAMPLE = 500
SEED = 20261112
THRESHOLDS = (0.0, 0.3, 0.4, 0.5)


def _load_bench() -> Any:
    spec = importlib.util.spec_from_file_location("context_bench", BENCH / "context_bench.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OllamaEmbedder:
    """The embedder `knowledge` used before MC-5 (native POST /api/embed), kept here as the reference path."""

    def __init__(self, url: str, model: str, perms: PermissionManager) -> None:
        self.url, self.model, self.perms = url.rstrip("/"), model, perms
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), 128):
            body = json.dumps({"model": self.model, "input": texts[i : i + 128]}).encode()
            request = urllib.request.Request(
                f"{self.url}/api/embed", data=body, headers={"Content-Type": "application/json"}
            )
            with self._opener.open(request, timeout=120) as response:
                out.extend(json.load(response)["embeddings"])
        return out


class V1Embedder:
    """Embedder over OpenAICompatibleClient, in batches."""

    def __init__(self, base_url: str, model: str, batch: int = 64) -> None:
        self.model = model
        self.batch = batch
        self._client = OpenAICompatibleClient(base_url, embed_model=model)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [v for i in range(0, len(texts), self.batch) for v in self._client.embed(texts[i : i + self.batch])]


class FakeEmbedder:
    """Deterministic 16-dim vectors; noise > 0 makes the second path differ."""

    def __init__(self, noise: float = 0.0) -> None:
        self.model = MODEL
        self.noise = noise

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            digest = hashlib.blake2b(text.encode(), digest_size=16).digest()
            out.append([b / 255 - 0.5 + (self.noise if i % 2 else 0.0) for i, b in enumerate(digest)])
        return out


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def norm(v: list[float]) -> float:
    return math.sqrt(sum(x * x for x in v))


def compare_vectors(old: list[list[float]], new: list[list[float]]) -> dict:
    cos = [cosine(a, b) for a, b in zip(old, new, strict=True)]
    return {
        "count": len(cos),
        "dim_old": sorted({len(v) for v in old}),
        "dim_new": sorted({len(v) for v in new}),
        "cos_min": min(cos),
        "cos_mean": sum(cos) / len(cos),
        "below_threshold": sum(c < COSINE_MIN for c in cos),
        "norm_old": [min(map(norm, old)), max(map(norm, old))],
        "norm_new": [min(map(norm, new)), max(map(norm, new))],
        "normalised_old": all(abs(norm(v) - 1) < 1e-3 for v in old),
        "normalised_new": all(abs(norm(v) - 1) < 1e-3 for v in new),
    }


class _Tool(KnowledgeTool):
    embedder: Any = None

    def _embedder(self) -> Any:
        return self.embedder


def make_tool(docs: Path, data_dir: Path, embedder: Any) -> _Tool:
    perms = PermissionManager([str(docs)], [str(data_dir)], network=True)
    ctx = ToolContext(plugin_id="knowledge", permissions=perms, data_dir=data_dir, settings={"embed_model": MODEL})
    tool = _Tool(ctx)
    tool.embedder = embedder
    return tool


def chunk_texts(data_dir: Path) -> list[str]:
    conn = sqlite3.connect(data_dir / "catalog.db")
    try:
        return [row[0] for row in conn.execute("SELECT text FROM chunks ORDER BY chunk_id")]
    finally:
        conn.close()


def sample_texts(chunks: list[str]) -> list[str]:
    """SAMPLE distinct texts with a fixed seed from the chunks, their paragraphs, lines and adjacent line pairs."""
    pool: set[str] = set(chunks)
    for chunk in chunks:
        pool.update(p.strip() for p in chunk.split("\n\n") if len(p.strip()) > 40)
        lines = [x.strip() for x in chunk.splitlines() if len(x.strip()) > 30]
        pool.update(lines)
        pool.update(f"{x}\n{y}" for x, y in zip(lines, lines[1:], strict=False))
    ordered = sorted(pool)
    if len(ordered) < SAMPLE:
        raise SystemExit(f"only {len(ordered)} distinct texts to sample from")
    return random.Random(SEED).sample(ordered, SAMPLE)


def run_bench(tool: _Tool, questions: list[dict], bench: Any) -> list[dict]:
    rows = []
    for q in questions:
        hits = tool.search(SearchInput(query=q["question"], limit=10)).hits
        top10 = [bench._code(h.path) for h in hits]
        row = {"id": q["id"], "top10": top10, "gold_in_top10": sorted(set(top10) & set(q["gold"])), "thresholds": {}}
        for t in THRESHOLDS:
            result = tool.get_context(GetContextInput(question=q["question"], token_budget=4000, min_relative_score=t))
            row["thresholds"][str(t)] = bench.score(q, result.model_dump())
        rows.append(row)
    return rows


def verdict(vectors: dict, old: list[dict], new: list[dict]) -> dict:
    checks = {
        "cosine_all_ge_0.9999": vectors["below_threshold"] == 0,
        "dimension_equal": vectors["dim_old"] == vectors["dim_new"] and len(vectors["dim_old"]) == 1,
        "gold_in_top10_same_all_questions": all(
            a["gold_in_top10"] == b["gold_in_top10"] for a, b in zip(old, new, strict=True)
        ),
        "precision_not_lower": all(
            b["thresholds"][t]["precision"] >= a["thresholds"][t]["precision"]
            for a, b in zip(old, new, strict=True)
            for t in a["thresholds"]
        ),
        "tokens_not_lower": all(
            b["thresholds"][t]["tokens"] >= a["thresholds"][t]["tokens"]
            for a, b in zip(old, new, strict=True)
            for t in a["thresholds"]
        ),
    }
    return {"checks": checks, "verdict": "PASS" if all(checks.values()) else "FAIL"}


def run(old_emb: Any, new_emb: Any, work: Path) -> dict:
    bench = _load_bench()
    questions = json.loads((BENCH / "questions.json").read_text(encoding="utf-8"))
    docs = BENCH / "docs"
    tools = {}
    for name, emb in (("old", old_emb), ("new", new_emb)):
        data_dir = work / name
        data_dir.mkdir()
        tools[name] = make_tool(docs, data_dir, emb)
        out = tools[name].reindex(ReindexInput())
        if out.errors or not out.embedded:
            raise SystemExit(f"{name}: index failed: errors={out.errors} embedded={out.embedded}")
    chunks = chunk_texts(work / "old")
    assert chunks == chunk_texts(work / "new"), "the two indexes chunked differently"
    texts = chunks + sample_texts(chunks)
    vectors = compare_vectors(old_emb.embed(texts), new_emb.embed(texts))
    vectors["texts"] = {"chunks": len(chunks), "sample": len(texts) - len(chunks)}
    old_rows = run_bench(tools["old"], questions, bench)
    new_rows = run_bench(tools["new"], questions, bench)
    return {"vectors": vectors, "bench_old": old_rows, "bench_new": new_rows} | verdict(vectors, old_rows, new_rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fake", choices=("pass", "fail"))
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    work = Path(tempfile.mkdtemp(prefix="mc4-"))
    try:
        if args.fake:
            old_emb, new_emb = FakeEmbedder(), FakeEmbedder(0.0 if args.fake == "pass" else 0.3)
        else:
            perms = PermissionManager([], [], network=True)
            old_emb = OllamaEmbedder(OLLAMA, MODEL, perms)
            new_emb = V1Embedder(f"{OLLAMA}/v1", MODEL)
        result = run(old_emb, new_emb, work)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    text = json.dumps(result, indent=1, ensure_ascii=False)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    sys.stdout.write(json.dumps({k: result[k] for k in ("vectors", "checks", "verdict")}, indent=1) + "\n")
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
