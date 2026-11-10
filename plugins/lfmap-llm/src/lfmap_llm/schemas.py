from typing import Literal

from pydantic import BaseModel, Field, model_validator

DataClass = Literal["normal", "private", "secret"]
FieldType = Literal["string", "number", "boolean", "list"]
MAX_FIELDS = 50


def _data() -> DataClass:
    return Field(default="normal", description="Data class of the text: secret never goes to a cloud model.")


class SummariseInput(BaseModel):
    """Text to summarise."""

    text: str = Field(min_length=1, description="The text to summarise.")
    max_words: int = Field(default=150, ge=10, le=1000, description="Upper bound for the summary length in words.")
    language: str = Field(
        default="same",
        pattern=r"^[^\W\d_](?:[^\W\d_]|[ \-]){0,39}$",
        description='Language of the summary, for example "English"; "same" keeps the language of the text.',
    )
    data: DataClass = _data()


class SummariseOutput(BaseModel):
    summary: str = Field(description="The summary.")
    model: str = Field(description="Model that answered.")
    truncated: bool = Field(description="True when the input was cut at a paragraph boundary before summarising.")


class FieldSpec(BaseModel):
    type: FieldType = Field(description="string, number, boolean or list.")
    description: str = Field(default="", max_length=500, description="What the field holds.")


class ExtractInput(BaseModel):
    """Text and the fields to pull out of it."""

    text: str = Field(min_length=1, description="The text to read.")
    schema_: dict[str, FieldSpec] = Field(
        alias="schema",
        min_length=1,
        max_length=MAX_FIELDS,
        description="Field name to {type, description}.",
        examples=[{"invoice_no": {"type": "string", "description": "Invoice number"}}],
    )
    data: DataClass = _data()

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def _names(self) -> "ExtractInput":
        if any(not name.strip() or len(name) > 100 for name in self.schema_):
            raise ValueError("field names must be non-empty and at most 100 characters")
        return self


class ExtractOutput(BaseModel):
    fields: dict[str, str | int | float | bool | list] = Field(description="Fields found, of the declared type.")
    missing: list[str] = Field(description="Schema fields the text did not give with the declared type.")
    model: str = Field(description="Model that answered.")


class ClassifyInput(BaseModel):
    """Text and the labels to choose from."""

    text: str = Field(min_length=1, description="The text to classify.")
    labels: list[str] = Field(min_length=2, max_length=20, description="Allowed labels, 2 to 20.")
    data: DataClass = _data()

    @model_validator(mode="after")
    def _labels(self) -> "ClassifyInput":
        if any(not label.strip() or len(label) > 100 for label in self.labels) or len(set(self.labels)) != len(
            self.labels
        ):
            raise ValueError("labels must be distinct, non-empty and at most 100 characters")
        return self


class ClassifyOutput(BaseModel):
    label: str = Field(description="Exactly one of the given labels.")
    model: str = Field(description="Model that answered.")
