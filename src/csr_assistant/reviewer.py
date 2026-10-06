"""Reviewer agent: flags statements that the source data do not support.

Two layers, cheapest first:
1. Code: every number must trace to the sources (cited rows for generated text, any source for the
   writer's draft), and every citation must point to a real row.
2. LLM (reasoning model): qualitative claims ("superior", "well tolerated", "no safety signal",
   "significant", "balanced", ...) are checked against the tables, with a neutral rewrite.
"""

from __future__ import annotations

import asyncio
import re

from .e3 import RESULTS_SECTIONS
from .llm import LLM, complete_structured
from .numcheck import numbers, unverified
from .prompts import REVIEW, SYSTEM
from .schemas import DraftSection, Finding, ReviewVerdict, StructureReport
from .sources import SourcePackage

QUALITATIVE = re.compile(
    r"\b(superior|inferior|better|worse|best|non-?inferior|well[- ]tolerated|tolerab|safe\b|safety signal|"
    r"significant(?:ly)?|no (?:new |relevant )?(?:safety )?(?:concerns?|signals?)|balanced|comparable|similar|"
    r"consistent|robust|favou?rable|clinically (?:meaningful|relevant)|all approved|first[- ]in[- ]class|"
    r"dramatic|marked|substantial)",
    re.IGNORECASE,
)
_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
IGNORE_NUMBERS = {95.0}  # "95% CI"


def sentences(text: str) -> list[str]:
    text = re.sub(r"^>.*$", "", text, flags=re.M)  # skip banners / quotes
    return [s.strip() for s in _SPLIT.split(" ".join(text.split())) if len(s.strip()) > 3]


def in_scope(number: str | None) -> bool:
    return bool(number) and number.split(".")[0] in RESULTS_SECTIONS


_GENERIC = set(
    [
        "patients",
        "patient",
        "group",
        "groups",
        "placebo",
        "week",
        "weeks",
        "table",
        "mean",
        "total",
        "number",
        "study",
        "treatment",
        "with",
        "were",
        "was",
        "the",
        "and",
        "of",
        "in",
        "on",
        "at",
        "for",
        "versus",
        "compared",
        "respectively",
    ]
)
_WORDS = re.compile(r"[a-z][a-z0-9]+")


def _terms(text: str) -> set[str]:
    return {w for w in _WORDS.findall(text.lower()) if w not in _GENERIC and len(w) > 2}


def candidate_rows(pkg: SourcePackage, sentence: str) -> list[str]:
    """All rows of the table(s) whose row labels best match the sentence ("nausea", "hba1c", "death").

    Table-level scope: a confidence interval or p-value often sits in neighbouring rows of the same table.
    """
    terms = _terms(sentence)
    scored = [(len(terms & _terms(pkg.row_labels[rid])), rid) for rid in pkg.rows]
    best = max((sc for sc, _ in scored), default=0)
    if not best:
        return []
    tables = {rid.split(".")[0] for sc, rid in scored if sc == best}
    return [rid for rid in pkg.rows if rid.split(".")[0] in tables]


def tables_for(pkg: SourcePackage, sentence: str, k: int = 4) -> str:
    """Only the most relevant tables go into the LLM prompt, to keep it small for real CSRs."""
    terms = _terms(sentence)
    ranked = sorted(pkg.tables, key=lambda t: -len(terms & _terms(t.title + " " + " ".join(r[0] for r in t.rows if r))))
    return "\n\n".join(t.render() for t in ranked[:k])


async def review(
    pkg: SourcePackage,
    drafted: list[DraftSection],
    llm: LLM | None,
    structure: StructureReport | None = None,
    max_parallel: int = 4,
) -> list[Finding]:
    findings: list[Finding] = []
    llm_jobs: list[tuple[str, str, str]] = []  # (section, sentence, origin)
    all_sources = [pkg.synopsis] + list(pkg.rows.values())
    # Unnumbered headings (Word auto-numbering, free-form drafts) are scoped through the E3 mapping.
    by_line = {s.line: s.number for s in structure.sections if s.line} if structure else {}

    def add(**kw):
        findings.append(Finding(id=f"F{len(findings) + 1}", **kw))

    # 1. The writer's draft: results and conclusions sections.
    for sec in pkg.sections:
        number = sec.number or by_line.get(sec.line)
        if not in_scope(number):
            continue
        for s in sentences(sec.text):
            # Check against the rows the sentence is about first ("nausea" -> the nausea row), so a number
            # that happens to appear elsewhere in the tables does not pass; then against all sources.
            rows = candidate_rows(pkg, s)
            missing = (
                unverified(
                    s,
                    [pkg.synopsis] + [pkg.rows[r] for r in rows],
                    IGNORE_NUMBERS,
                    count_sources=[pkg.row_values[r] for r in rows],
                )
                if rows
                else None
            )
            if missing is None or (missing and not unverified(s, all_sources, IGNORE_NUMBERS)):
                # No specific row, or the number exists elsewhere: check all sources, flag a weaker finding.
                anywhere = unverified(s, all_sources, IGNORE_NUMBERS, list(pkg.row_values.values()))
                if missing and not anywhere:
                    add(
                        section=number,
                        sentence=s,
                        origin="draft",
                        type="number",
                        severity="medium",
                        detail=f"number(s) {', '.join(missing)} not in the rows this sentence is about "
                        f"({', '.join(rows[:3])}); they appear elsewhere in the tables",
                        suggestion="Check that the number belongs to the right endpoint, group and population.",
                    )
                    continue
                missing = anywhere
            if missing:
                add(
                    section=number,
                    sentence=s,
                    origin="draft",
                    type="number",
                    severity="high",
                    detail=f"number(s) not found in the source tables or synopsis: {', '.join(missing)}",
                    suggestion="Check against the tables and correct, or cite the source.",
                )
            elif QUALITATIVE.search(s):
                llm_jobs.append((number, s, "draft"))

    # 2. Generated sections: citations must exist and must contain the numbers.
    for d in drafted:
        if d.status != "drafted":
            continue
        for s in d.sentences:
            bad = [c for c in s.citations if c not in pkg.rows]
            if bad:
                add(
                    section=d.number,
                    sentence=s.text,
                    origin="generated",
                    type="invalid_citation",
                    severity="high",
                    detail=f"cited rows do not exist: {', '.join(bad)}",
                )
                continue
            has_numbers = [n for n in numbers(s.text) if n[0] not in IGNORE_NUMBERS]
            if has_numbers and not s.citations:
                add(
                    section=d.number,
                    sentence=s.text,
                    origin="generated",
                    type="missing_citation",
                    severity="high",
                    detail="sentence contains data but cites no table row",
                )
                continue
            missing = (
                unverified(
                    s.text,
                    [pkg.rows[c] for c in s.citations],
                    IGNORE_NUMBERS,
                    count_sources=[pkg.row_values[c] for c in s.citations],
                )
                if s.citations
                else []
            )
            if missing:
                add(
                    section=d.number,
                    sentence=s.text,
                    origin="generated",
                    type="number",
                    severity="high",
                    detail=f"number(s) not in the cited rows {', '.join(s.citations)}: {', '.join(missing)}",
                )
            elif QUALITATIVE.search(s.text):
                llm_jobs.append((d.number, s.text, "generated"))

    # 3. LLM review of qualitative claims, in parallel.
    if llm is not None and llm_jobs:
        sem = asyncio.Semaphore(max_parallel)

        async def judge(section: str, sentence: str, origin: str):
            async with sem:
                try:
                    v = await complete_structured(
                        llm,
                        [
                            {"role": "system", "content": SYSTEM},
                            {
                                "role": "user",
                                "content": REVIEW.format(
                                    section=section,
                                    sentence=sentence,
                                    synopsis=pkg.synopsis,
                                    tables=tables_for(pkg, sentence),
                                ),
                            },
                        ],
                        ReviewVerdict,
                        role="reasoning",
                        step="review_claim",
                        max_tokens=1024,
                    )
                except Exception as err:
                    return section, sentence, origin, err
                return section, sentence, origin, v

        for section, sentence, origin, v in await asyncio.gather(*(judge(*j) for j in llm_jobs)):
            if isinstance(v, Exception):
                add(
                    section=section,
                    sentence=sentence,
                    origin=origin,
                    type="review_error",
                    severity="low",
                    detail=f"claim could not be reviewed: {str(v)[:200]}",
                    suggestion="Review manually.",
                )
                continue
            if v.verdict != "supported":
                add(
                    section=section,
                    sentence=sentence,
                    origin=origin,
                    type=v.verdict,
                    severity="high" if v.verdict == "unsupported" else "medium",
                    detail=v.explanation,
                    suggestion=v.suggested_rewrite,
                )
    elif llm_jobs:
        for section, sentence, origin in llm_jobs:
            add(
                section=section,
                sentence=sentence,
                origin=origin,
                type="overstated",
                severity="low",
                detail="qualitative claim not checked (no LLM reviewer configured)",
            )
    return findings
