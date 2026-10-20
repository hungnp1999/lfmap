from lfmap_core import Tool, ToolError, operation
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


class KnowledgeTool(Tool):
    @operation("status")
    def status(self, inp: StatusInput) -> StatusOutput:
        """Get the status of the knowledge plugin."""
        raise ToolError("internal", "not implemented")

    @operation("reindex")
    def reindex(self, inp: ReindexInput) -> ReindexOutput:
        """Reindex the local files."""
        raise ToolError("internal", "not implemented")

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
