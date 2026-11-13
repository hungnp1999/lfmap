import hashlib
import os
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from lfmap_core import Tool, ToolError, operation
from lfmap_core.web import WebResult, check_url, long_query
from lfmap_web.schemas import FetchInput, FetchOutput

EXTENSIONS = {
    "text/html": "html",
    "application/xhtml+xml": "html",
    "text/plain": "txt",
    "text/markdown": "txt",
    "text/xml": "xml",
    "application/xml": "xml",
    "application/rss+xml": "xml",
    "application/atom+xml": "xml",
    "application/json": "json",
    "text/csv": "csv",
}


class WebTool(Tool):
    @classmethod
    def call_tier(cls, operation: str, inp: BaseModel, settings: dict[str, Any]) -> str | None:
        """Owner decision 16.1: T0, but a URL whose query is longer than the core bound can carry text out: T3."""
        url = getattr(inp, "url", "")
        return "T3" if isinstance(url, str) and long_query(url) else "T0"

    @operation("fetch")
    def fetch(self, inp: FetchInput) -> FetchOutput:
        """Read one public page over HTTPS from a host the owner listed in [web] allowed_hosts; returns its text."""
        result = self.ctx.web.fetch(inp.url, max_bytes=inp.max_bytes)
        saved = self._save(result) if inp.save else None
        return FetchOutput(**result.model_dump(), saved_path=saved)

    def _save(self, result: WebResult) -> str:
        """Write the page text to `data_dir/pages/<UTC time>-<host>-<sha256[:8]>.<ext>`, a name of validated parts."""
        if self.ctx.data_dir is None:
            raise ToolError("backend_unavailable", "The plugin has no data folder", {"reason": "no_data_dir"})
        body = result.text.encode("utf-8")
        moment = datetime.fromisoformat(result.fetched_at).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
        extension = EXTENSIONS.get(result.content_type, "txt")
        name = f"{moment}-{check_url(result.url_final).host}-{hashlib.sha256(body).hexdigest()[:8]}.{extension}"
        root = os.path.realpath(self.ctx.data_dir)
        folder = os.path.realpath(os.path.join(root, "pages"))
        if not folder.startswith(root + os.sep):
            raise ToolError("permission_denied", "The pages folder is outside the data folder", {})
        os.makedirs(folder, exist_ok=True)
        target = os.path.realpath(os.path.join(folder, name))
        if not target.startswith(folder + os.sep):
            raise ToolError("permission_denied", "The copy would be written outside the pages folder", {})
        with open(target, "wb") as handle:
            handle.write(body)
        return target
