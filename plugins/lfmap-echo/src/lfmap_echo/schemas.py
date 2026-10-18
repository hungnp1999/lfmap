from pydantic import BaseModel, Field


class SayInput(BaseModel):
    """Text to repeat."""

    text: str = Field(description="Text to repeat back.", examples=["xin chào"])
    upper: bool = Field(default=False, description="Return the text in upper case.")


class SayOutput(BaseModel):
    text: str = Field(description="The repeated text.")
    length: int = Field(description="Number of characters in text.")
