"""Domain models shared by the engine, OCR layer, and API."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Verdict(str, Enum):
    MATCH = "match"
    REVIEW = "review"
    MISMATCH = "mismatch"
    NOT_FOUND = "not_found"
    NOT_APPLICABLE = "not_applicable"


# Worst-first priority when rolling up to an overall verdict.
VERDICT_PRIORITY: dict[Verdict, int] = {
    Verdict.MISMATCH: 4,
    Verdict.NOT_FOUND: 3,
    Verdict.REVIEW: 2,
    Verdict.MATCH: 1,
    Verdict.NOT_APPLICABLE: 0,
}


class ApplicationData(BaseModel):
    """The data from the label application (what the label *should* say)."""

    application_id: str | None = None
    brand_name: str
    class_type: str = Field(alias="class/type")
    alcohol_pct: float = Field(ge=0, le=100)
    net_contents_ml: float = Field(gt=0)
    bottler_name: str
    bottler_address: str
    is_import: bool = False
    country_of_origin: str | None = None

    model_config = {"populate_by_name": True}


class FieldCheck(BaseModel):
    """Result of comparing one mandatory label field against the application."""

    field: str
    label: str
    verdict: Verdict
    expected: str | None = None
    found: str | None = None
    note: str | None = None


class VerificationResult(BaseModel):
    application_id: str | None = None
    overall: Verdict
    checks: list[FieldCheck]
    elapsed_ms: int
    ocr_text: str = ""

    @property
    def worst(self) -> Verdict:
        return max((c.verdict for c in self.checks), key=lambda v: VERDICT_PRIORITY[v])
