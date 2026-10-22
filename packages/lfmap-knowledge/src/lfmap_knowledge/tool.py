import sys

from lfmap_core import Tool, ToolError, operation
from lfmap_knowledge import indexer
from lfmap_knowledge.embed import OllamaEmbedder
from lfmap_knowledge.schemas import (
    GetContextInput,
    GetContextOutput,
    GetFileInput,
    GetFileOutput,
    ReindexInput,
    ReindexOutput,
    RelatedInput,
    RelatedOutput,
    SearchFilesInput,
    SearchFilesOutput,
    SearchInput,
    SearchOutput,
    StatusInput,
    StatusOutput,
)


def _print_progress(stage: str, done: int, total: int) -> None:
    print(f"{stage} {done}/{total}", file=sys.stderr, flush=True)


class KnowledgeTool(Tool):
    def _embedder(self) -> OllamaEmbedder:
        settings = self.ctx.settings
        return OllamaEmbedder(
            settings.get("ollama_url", "http://127.0.0.1:11434"),
            settings.get("embed_model", indexer.DEFAULT_EMBED_MODEL),
            self.ctx.permissions,
        )

    @operation("status")
    def status(self, inp: StatusInput) -> StatusOutput:
        """Show the knowledge roots, file counts by status, chunk count, embed model and whether Ollama answers.

        Read-only: opens the catalog without taking the indexer lock.
        """
        return indexer.status(self.ctx, ollama_available=self._embedder().ping())

    @operation("reindex")
    def reindex(self, inp: ReindexInput) -> ReindexOutput:
        """Bring the index in line with the knowledge folders: new, changed and deleted files, chunks and vectors.

        Only reads the user's files and only writes inside the plugin's data folder. `root` limits the scan to one
        knowledge root; `full` rebuilds chunks and vectors from the Markdown cache.
        """
        progress = _print_progress if self.ctx.channel == "cli" else None
        return indexer.reindex(self.ctx, self._embedder(), inp.root, inp.full, progress=progress)

    @operation("search_files")
    def search_files(self, inp: SearchFilesInput) -> SearchFilesOutput:
        """Search for local files."""
        raise ToolError("internal", "not implemented")

    @operation("get_file")
    def get_file(self, inp: GetFileInput) -> GetFileOutput:
        """Get information about a specific file."""
        raise ToolError("internal", "not implemented")

    @operation("search")
    def search(self, inp: SearchInput) -> SearchOutput:
        """Search for text within local files."""
        raise ToolError("internal", "not implemented")

    @operation("get_context")
    def get_context(self, inp: GetContextInput) -> GetContextOutput:
        """Get context for a specific question."""
        raise ToolError("internal", "not implemented")

    @operation("related")
    def related(self, inp: RelatedInput) -> RelatedOutput:
        """Find related files for a specific file."""
        raise ToolError("internal", "not implemented")
