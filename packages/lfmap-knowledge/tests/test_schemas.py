import pytest
from pydantic import ValidationError

from lfmap_core import ToolError
from lfmap_core.registry import Registry, load_entry
from lfmap_core.runtime import default_context
from lfmap_knowledge import schemas
from lfmap_knowledge.tool import KnowledgeTool

OPERATIONS = ["status", "reindex", "search_files", "get_file", "search", "get_context", "related"]


def _pascal(name: str) -> str:
    return "".join(part.title() for part in name.split("_"))


def test_manifest_matches_tool():
    entry = load_entry(KnowledgeTool)
    assert entry.id == "knowledge"
    assert sorted(op.name for op in entry.manifest.operations) == sorted(OPERATIONS)
    assert all(op.side_effects == "none" for op in entry.manifest.operations)
    assert entry.manifest.permissions.network is True


def test_discovered_through_entry_point():
    registry = Registry()
    registry.discover()
    assert registry.get("knowledge").tool_class is KnowledgeTool


@pytest.mark.parametrize("name", OPERATIONS)
def test_inputs_are_flat(name):
    model = getattr(schemas, f"{_pascal(name)}Input")
    assert "$defs" not in model.model_json_schema()


@pytest.mark.parametrize("name", OPERATIONS)
def test_operations_not_implemented_yet(name):
    tool = KnowledgeTool(default_context("knowledge"))
    inputs = {"search": {"query": "x"}, "get_context": {"question": "x"}, "get_file": {"path": "C:/x"}}
    inputs["related"] = {"path": "C:/x"}
    inp = getattr(schemas, f"{_pascal(name)}Input")(**inputs.get(name, {}))
    with pytest.raises(ToolError) as error:
        getattr(tool, name)(inp)
    assert error.value.code == "internal"


def test_search_defaults_and_bounds():
    inp = schemas.SearchInput(query="hợp đồng")
    assert (inp.root, inp.modified_after, inp.mode, inp.limit) == ("", "", "hybrid", 10)
    for bad in ({"limit": 0}, {"limit": 101}, {"mode": "fuzzy"}, {"query": ""}):
        with pytest.raises(ValidationError):
            schemas.SearchInput(**{"query": "x", **bad})


def test_get_context_budget_bounds():
    assert schemas.GetContextInput(question="q").token_budget == 4000
    for bad in (199, 50001):
        with pytest.raises(ValidationError):
            schemas.GetContextInput(question="q", token_budget=bad)


def test_get_context_output_is_marked_untrusted():
    citation = schemas.Citation(path="D:/a.md", heading_path="A > B", char_start=0, char_end=5)
    out = schemas.GetContextOutput(
        question="q", chunks=[schemas.ContextChunk(text="hello", citation=citation, score=0.5)], estimated_tokens=2
    )
    assert out.untrusted is True
    assert "not as instructions" in out.notice


def test_chunk_hit_and_related_literals():
    hit = schemas.ChunkHit(
        path="D:/a.md",
        heading_path="",
        snippet="s",
        score=1.0,
        chunk_id=1,
        char_start=0,
        char_end=1,
        mode_used="keyword",
    )
    assert hit.duplicates == []
    with pytest.raises(ValidationError):
        schemas.RelatedFile(path="D:/b.md", reason="magic", score=0.1)
    assert schemas.RelatedFile(path="D:/b.md", reason="similar_content", score=0.1).reason == "similar_content"


def test_reindex_input_defaults():
    inp = schemas.ReindexInput()
    assert (inp.root, inp.full) == ("", False)
