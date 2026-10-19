"""MarkItDown backend. Reads only from an already opened stream, so it never fetches a URL."""

from importlib.metadata import version
from typing import BinaryIO

from markitdown import MarkItDown, StreamInfo


class MarkItDownBackend:
    name = "markitdown"

    def __init__(self) -> None:
        self._converter = MarkItDown(enable_plugins=False)

    def version(self) -> str:
        return version("markitdown")

    def to_markdown(self, stream: BinaryIO, extension: str, filename: str) -> str:
        info = StreamInfo(extension=extension, filename=filename)
        return self._converter.convert_stream(stream, stream_info=info).markdown
