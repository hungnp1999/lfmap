import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("dependency_share", Path(__file__).parents[1] / "dependency_share.py")
ds = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ds)


class FakeDist:
    def __init__(self, root: Path, name: str, size: int, requires: list[str] | None = None) -> None:
        self.metadata = {"Name": name}
        self.requires = requires
        self._path = root / f"{name}.bin"
        self._path.write_bytes(b"x" * size)
        self.files = [self._path.name]

    def locate_file(self, file: str) -> Path:
        return self._path.parent / file


def make(tmp_path: Path) -> list:
    return [
        FakeDist(tmp_path, "lfmap-core", 10, ["pydantic>=2", "big[fast]==1"]),
        FakeDist(tmp_path, "lfmap-knowledge", 10, ["lfmap-core", "big"]),
        FakeDist(tmp_path, "pydantic", 100, ["typing-extensions"]),
        FakeDist(tmp_path, "typing_extensions", 5),
        FakeDist(tmp_path, "big", 1000, ["shared", "speedup; extra == 'fast'", "notinstalled; extra == 'x'"]),
        FakeDist(tmp_path, "speedup", 50),
        FakeDist(tmp_path, "shared", 7),
    ]


def test_measure_counts_third_party_only(tmp_path: Path) -> None:
    result = ds.measure(make(tmp_path), own_bytes=40)
    assert result["third_party_distributions"] == 5
    assert result["third_party_bytes"] == 1162
    assert result["third_party_share"] == round(1162 / 1202, 4)
    assert result["services_besides_model_runtime"] == 0
    assert result["largest"][0] == {"name": "big", "bytes": 1000}


def test_removable_bytes_follows_extras(tmp_path: Path) -> None:
    removable = {item["name"]: item for item in ds.removable_bytes(make(tmp_path))}
    assert removable["big"] == {"name": "big", "distributions": 3, "bytes": 1057}
    assert removable["pydantic"] == {"name": "pydantic", "distributions": 2, "bytes": 105}


def test_own_source_bytes_counts_src_only(tmp_path: Path) -> None:
    (tmp_path / "packages" / "a" / "src").mkdir(parents=True)
    (tmp_path / "packages" / "a" / "src" / "m.py").write_bytes(b"12345")
    (tmp_path / "packages" / "a" / "tests").mkdir()
    (tmp_path / "packages" / "a" / "tests" / "t.py").write_bytes(b"123")
    assert ds.own_source_bytes(tmp_path) == 5
