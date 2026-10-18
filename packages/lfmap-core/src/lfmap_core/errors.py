"""Business errors shared by every plugin; adapters map them to exit codes, MCP errors and HTTP status."""

from typing import Any, Literal

ErrorCode = Literal["invalid_input", "permission_denied", "not_found", "backend_unavailable", "timeout", "internal"]


class ToolError(Exception):
    def __init__(self, code: ErrorCode, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}
