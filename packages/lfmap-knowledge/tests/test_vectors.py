import random
from pathlib import Path

import pytest

from lfmap_core.errors import ToolError
from lfmap_knowledge import vectors
from lfmap_knowledge.vectors import LanceVectorStore, model_slug

DIM = 16


def content_hash(n: int) -> str:
    return f"{n:064x}"


def random_vectors(count: int, seed: int = 1) -> list[list[float]]:
    rng = random.Random(seed)
    return [[rng.gauss(0, 1) for _ in range(DIM)] for _ in range(count)]


@pytest.fixture
def store(data_dir: Path) -> LanceVectorStore:
    return LanceVectorStore(data_dir / "vectors", table="chunks_test")


def fill(store: LanceVectorStore, count: int = 100) -> list[list[float]]:
    vecs = random_vectors(count)
    store.upsert(list(range(count)), [content_hash(i // 10) for i in range(count)], vecs)
    return vecs


def test_model_slug():
    assert model_slug("bge-m3") == "bge_m3"
    assert model_slug("BAAI/bge-m3:latest") == "baai_bge_m3_latest"


def test_empty_store(store, data_dir):
    assert not store.exists()
    assert store.search([0.0] * DIM, 5) == []
    assert store.vector_of([]) == []
    store.delete_content(content_hash(1))
    store.drop()
    assert not store.exists()
    assert not (data_dir / "vectors").exists()


def test_search_finds_the_same_vector_first(store):
    vecs = fill(store)
    assert store.exists()
    hits = store.search(vecs[7], 5)
    assert len(hits) == 5
    assert hits[0][0] == 7
    scores = [score for _, score in hits]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] == pytest.approx(1.0, abs=1e-4)


def test_search_has_no_distance_deprecation_warning(store, capfd):
    # Lance logs this deprecation from Rust straight to stderr, not through Python warnings.
    vecs = fill(store, 20)
    capfd.readouterr()
    store.search(vecs[0], 3)
    err = capfd.readouterr().err
    if "Deprecation warning" in err:
        pytest.fail(f"LanceDB deprecation warning on search: {err.strip()}")


def test_upsert_replaces_by_chunk_id(store):
    fill(store)
    new = random_vectors(1, seed=99)[0]
    store.upsert([7], [content_hash(0)], [new])
    assert store.count() == 100
    assert store.vector_of([7])[0] == pytest.approx(new, abs=1e-5)


def test_vector_of_keeps_the_order(store):
    vecs = fill(store)
    got = store.vector_of([42, 3])
    assert got[0] == pytest.approx(vecs[42], abs=1e-5)
    assert got[1] == pytest.approx(vecs[3], abs=1e-5)


def test_vector_of_unknown_id(store):
    fill(store)
    with pytest.raises(ToolError) as error:
        store.vector_of([1000])
    assert error.value.code == "not_found"


def test_delete_content(store):
    fill(store)
    store.delete_content(content_hash(0))
    assert store.count() == 90
    assert all(chunk_id >= 10 for chunk_id, _ in store.search(random_vectors(100)[3], 100))


def test_delete_content_rejects_a_filter_injection(store):
    fill(store)
    with pytest.raises(ToolError) as error:
        store.delete_content("x' OR '1'='1")
    assert error.value.code == "invalid_input"
    assert store.count() == 100


def test_upsert_checks_lengths_and_dimension(store):
    fill(store)
    with pytest.raises(ToolError) as error:
        store.upsert([1, 2], [content_hash(0)], random_vectors(2))
    assert error.value.code == "invalid_input"
    with pytest.raises(ToolError) as error:
        store.upsert([500], [content_hash(50)], [[0.1] * (DIM + 1)])
    assert error.value.code == "invalid_input"


def test_reopen_sees_the_same_data(store, data_dir):
    vecs = fill(store)
    again = LanceVectorStore(data_dir / "vectors", table="chunks_test")
    assert again.exists() and again.count() == 100
    assert again.search(vecs[7], 1)[0][0] == 7


def test_drop(store, data_dir):
    fill(store)
    store.drop()
    assert not store.exists()
    assert store.search(random_vectors(1)[0], 5) == []


def test_tables_per_model_are_separate(data_dir):
    a = LanceVectorStore(data_dir / "vectors", table="chunks_a")
    b = LanceVectorStore(data_dir / "vectors", table="chunks_b")
    fill(a)
    assert a.exists() and not b.exists()
    b.drop()
    assert a.count() == 100


def test_optimize_without_index_below_threshold(store):
    fill(store)
    store.optimize()
    assert not store.has_index()
    assert store.count() == 100


def test_optimize_builds_the_ann_index_from_the_threshold(store, monkeypatch):
    assert vectors.ANN_INDEX_MIN_ROWS == 50_000
    monkeypatch.setattr(vectors, "ANN_INDEX_MIN_ROWS", 600)
    vecs = fill(store, 600)
    store.optimize()
    assert store.has_index()
    assert store.search(vecs[7], 3)[0][0] == 7
    store.upsert([600], [content_hash(60)], random_vectors(1, seed=5))
    store.optimize()
    assert store.has_index() and store.count() == 601


def test_delete_contents_in_several_filters(store, monkeypatch):
    fill(store)
    monkeypatch.setattr(vectors, "DELETE_BATCH", 2)
    store.delete_contents([content_hash(0), content_hash(3), content_hash(7)])
    assert store.count() == 70


def test_delete_contents_rejects_a_filter_injection(store):
    fill(store)
    with pytest.raises(ToolError) as error:
        store.delete_contents([content_hash(0), "x' OR '1'='1"])
    assert error.value.code == "invalid_input"
    assert store.count() == 100
