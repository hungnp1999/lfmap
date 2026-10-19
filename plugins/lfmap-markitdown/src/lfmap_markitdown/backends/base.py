from typing import BinaryIO, Protocol


class Backend(Protocol):
    name: str

    def version(self) -> str: ...

    def to_markdown(self, stream: BinaryIO, extension: str, filename: str) -> str: ...
