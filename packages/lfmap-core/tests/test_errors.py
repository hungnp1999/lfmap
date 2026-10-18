import pytest

from lfmap_core import ToolError


def test_to_dict():
    error = ToolError("not_found", "File missing", {"path": "a.pdf"})
    assert error.to_dict() == {"code": "not_found", "message": "File missing", "details": {"path": "a.pdf"}}


def test_details_default_to_empty_dict():
    assert ToolError("internal", "boom").details == {}


def test_str():
    assert str(ToolError("timeout", "Too slow")) == "timeout: Too slow"


def test_is_exception():
    with pytest.raises(ToolError) as caught:
        raise ToolError("invalid_input", "Bad")
    assert caught.value.code == "invalid_input"
