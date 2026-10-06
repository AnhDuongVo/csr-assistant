from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, Field


def _row_ids(value: Any) -> list[str]:
    """Accept ["T3.R2", "t3 r2", "[T3.R2]"] and normalise."""
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        value = [value]
    out = []
    for v in value:
        m = re.search(r"T\s*(\d+)\s*\.?\s*R\s*(\d+)", str(v), re.I)
        if m and f"T{m.group(1)}.R{m.group(2)}" not in out:
            out.append(f"T{m.group(1)}.R{m.group(2)}")
    return out


RowIds = Annotated[list[str], BeforeValidator(_row_ids)]


class SectionStatus(BaseModel):
    number: str
    title: str
    required: bool
    status: Literal["present", "missing", "empty"]
    matched_heading: str | None = None
    line: int | None = None
    method: Literal["number", "title", "llm", "none"] = "none"


class StructureReport(BaseModel):
    sections: list[SectionStatus]
    unmatched_headings: list[str] = Field(default_factory=list)
    order_issues: list[str] = Field(default_factory=list)

    @property
    def missing(self) -> list[str]:
        return [s.number for s in self.sections if s.required and s.status == "missing"]

    @property
    def empty(self) -> list[str]:
        return [s.number for s in self.sections if s.required and s.status == "empty"]


class HeadingMap(BaseModel):
    mapping: list[dict] = Field(description='[{"heading": "...", "e3_number": "10.1" or "none"}]')


class DraftSentence(BaseModel):
    text: str
    citations: RowIds = Field(default_factory=list, description="Source table rows, e.g. T3.R2")


class DraftSection(BaseModel):
    number: str
    title: str
    sentences: list[DraftSentence] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list, description="Information this section needs that the sources lack")
    status: Literal["drafted", "placeholder"] = "drafted"
    decision: Literal["pending", "accepted", "rejected"] = "pending"

    def markdown(self) -> str:
        body = []
        if self.status == "placeholder":
            body.append(
                f"> **MISSING (ICH E3 {self.number}).** Not drafted: the source tables do not contain this "
                f"information. Needed: {'; '.join(self.gaps) or 'see ICH E3'}."
            )
        else:
            body.append(
                "> **DRAFT generated from source tables. Every sentence cites its rows. "
                "Medical writer review required.**"
            )

            def cite(s: DraftSentence) -> str:
                if not s.citations:
                    return s.text
                text = s.text.rstrip()
                end = text[-1] if text and text[-1] in ".!?" else "."
                return f"{text.rstrip('.!?')} [{', '.join(s.citations)}]{end}"

            body.append(" ".join(cite(s) for s in self.sentences))
            if self.gaps:
                body.append("Open points: " + "; ".join(self.gaps))
        return "\n\n".join(body)


class ReviewVerdict(BaseModel):
    verdict: Literal["supported", "unsupported", "overstated"]
    explanation: str
    suggested_rewrite: str = ""


class Finding(BaseModel):
    id: str
    section: str
    sentence: str
    origin: Literal["draft", "generated"]
    type: Literal["number", "unsupported", "overstated", "invalid_citation", "missing_citation", "review_error"]
    severity: Literal["high", "medium", "low"]
    detail: str
    suggestion: str = ""
    dismissed: bool = False
