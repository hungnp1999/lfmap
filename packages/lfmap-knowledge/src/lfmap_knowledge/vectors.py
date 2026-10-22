"""LanceDB vector store: one table per embedding model under data_dir/vectors."""

import os
import re
from pathlib import Path
from typing import Any

import lancedb
import pyarrow as pa
from lancedb.index import IvfHnswSq

from lfmap_core import ToolError

ANN_INDEX_MIN_ROWS = 50_000  # K0 result: build the ANN index from about 50k vectors

_HASH = re.compile(r"^[0-9a-f]{64}$")


def model_slug(model: str) -> str:
    """Lower case and replace every run of characters outside [a-z0-9] with one underscore."""
    return re.sub(r"[^a-z0-9]+", "_", model.lower()).strip("_")


class LanceVectorStore:
    """Implements the VectorStore protocol (spec 5.4); nothing is opened or created until needed."""

    def __init__(self, path: Path, table: str) -> None:
        self.path = path
        self.table_name = table
        self._db: Any = None
        self._table: Any = None

    def _connect(self, create: bool = False) -> Any:
        if self._db is None:
            if not create and not os.path.isdir(self.path):
                return None
            self.path.mkdir(parents=True, exist_ok=True)
            self._db = lancedb.connect(self.path)
        return self._db

    def _open(self) -> Any:
        if self._table is None:
            db = self._connect()
            if db is None:
                return None
            try:
                self._table = db.open_table(self.table_name)
            except ValueError:
                return None
        return self._table

    def exists(self) -> bool:
        return self._open() is not None

    def count(self) -> int:
        table = self._open()
        return 0 if table is None else table.count_rows()

    def has_index(self) -> bool:
        table = self._open()
        return table is not None and any("vector" in index.columns for index in table.list_indices())

    def upsert(self, chunk_ids: list[int], content_hashes: list[str], vectors: list[list[float]]) -> None:
        if not (len(chunk_ids) == len(content_hashes) == len(vectors)):
            raise ToolError("invalid_input", "chunk_ids, content_hashes and vectors differ in length")
        if not chunk_ids:
            return
        table = self._open()
        dim = table.schema.field("vector").type.list_size if table is not None else len(vectors[0])
        if dim == 0 or any(len(vector) != dim for vector in vectors):
            raise ToolError("invalid_input", "Vector dimension does not match the table", {"dimension": dim})
        schema = pa.schema(
            [
                pa.field("chunk_id", pa.int64()),
                pa.field("content_hash", pa.string()),
                pa.field("vector", pa.list_(pa.float32(), dim)),
            ]
        )
        data = pa.Table.from_pydict({"chunk_id": chunk_ids, "content_hash": content_hashes, "vector": vectors}, schema)
        if table is None:
            self._table = self._connect(create=True).create_table(self.table_name, data)
            return
        table.merge_insert("chunk_id").when_matched_update_all().when_not_matched_insert_all().execute(data)

    def delete_content(self, content_hash: str) -> None:
        if not _HASH.match(content_hash):
            raise ToolError("invalid_input", "content_hash must be 64 lower-case hex characters")
        table = self._open()
        if table is not None:
            table.delete(f"content_hash = '{content_hash}'")

    def search(self, vector: list[float], limit: int) -> list[tuple[int, float]]:
        """Best first as (chunk_id, score), score = 1 - cosine distance."""
        table = self._open()
        if table is None:
            return []
        rows = (
            table.search(vector, vector_column_name="vector")
            .distance_type("cosine")
            .select(["chunk_id", "_distance"])
            .limit(limit)
            .to_list()
        )
        return [(row["chunk_id"], 1.0 - row["_distance"]) for row in rows]

    def vector_of(self, chunk_ids: list[int]) -> list[list[float]]:
        """Vectors in the order of chunk_ids; an unknown id is not_found."""
        if not chunk_ids:
            return []
        table = self._open()
        found: dict[int, list[float]] = {}
        if table is not None:
            ids = ", ".join(str(int(chunk_id)) for chunk_id in set(chunk_ids))
            rows = table.search().where(f"chunk_id IN ({ids})").select(["chunk_id", "vector"]).to_list()
            found = {row["chunk_id"]: list(row["vector"]) for row in rows}
        missing = [chunk_id for chunk_id in chunk_ids if chunk_id not in found]
        if missing:
            raise ToolError("not_found", "No vector for these chunk ids", {"chunk_ids": missing[:20]})
        return [found[chunk_id] for chunk_id in chunk_ids]

    def drop(self) -> None:
        """Drop this model's table only; the vectors folder stays."""
        if self._open() is not None:
            self._db.drop_table(self.table_name)
            self._table = None

    def optimize(self) -> None:
        """Build the cosine ANN index once the table is large enough, then compact."""
        table = self._open()
        if table is None:
            return
        if self.count() >= ANN_INDEX_MIN_ROWS and not self.has_index():
            table.create_index("vector", config=IvfHnswSq(distance_type="cosine"))
        table.optimize()
