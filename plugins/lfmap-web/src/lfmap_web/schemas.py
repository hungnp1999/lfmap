from pydantic import BaseModel, Field


class FetchInput(BaseModel):
    """One page to read."""

    url: str = Field(
        description="Absolute https URL on a host in [web] allowed_hosts.", examples=["https://example.org/"]
    )
    max_bytes: int | None = Field(
        default=None, description="Lower the byte cap for this call (1024 up to the configured cap)."
    )
    save: bool = Field(default=False, description="Also write a copy of the page to the plugin's data folder.")


class FetchOutput(BaseModel):
    url_final: str = Field(description="URL after redirects.")
    status: int = Field(description="HTTP status of the final response (2xx).")
    content_type: str = Field(description="Media type without parameters.")
    text: str = Field(description="The page as text, exactly as served; never interpreted.")
    bytes: int = Field(description="Body bytes read.")
    truncated: bool = Field(description="The body was longer than the cap and was cut.")
    fetched_at: str = Field(description="UTC ISO time of the fetch.")
    saved_path: str | None = Field(default=None, description="Where the copy was written, when save is true.")
