from pydantic import BaseModel, Field


class ShoutInput(BaseModel):
    text: str = Field(description="Text to upper-case.")


class ShoutOutput(BaseModel):
    text: str


class SaveInput(BaseModel):
    path: str = Field(description="File to write.")
    text: str


class SaveOutput(BaseModel):
    path: str
    bytes: int


class MissingInput(BaseModel):
    pass
