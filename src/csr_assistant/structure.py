"""Check a draft CSR against the ICH E3 structure: which required sections are present, missing or empty."""

from __future__ import annotations

import re
from itertools import pairwise

from .e3 import BY_NUMBER, SECTIONS, E3Section, number_key
from .llm import LLM, complete_structured
from .prompts import MAP_HEADINGS, SYSTEM
from .schemas import HeadingMap, SectionStatus, StructureReport
from .sources import DocSection

EMPTY_WORDS = 5
_W = re.compile(r"[a-z]+")
_STOP = {"and", "of", "the", "or", "for", "to", "in", "a", "an", "other", "including", "related"}


def _words(text: str) -> set[str]:
    return {w for w in _W.findall(text.lower()) if w not in _STOP}


def title_match(heading: str, section: E3Section) -> bool:
    h = _words(heading)
    if not h:
        return False
    for candidate in (section.title, *section.aliases):
        c = _words(candidate)
        if c and len(h & c) / len(h | c) >= 0.6:
            return True
        if candidate.lower() == heading.lower().strip():
            return True
    return False


async def check_structure(sections: list[DocSection], llm: LLM | None = None) -> StructureReport:
    assigned: dict[str, tuple[DocSection, str]] = {}
    unmatched: list[DocSection] = []
    for s in sections:
        if s.number and s.number in BY_NUMBER and s.number not in assigned:
            assigned[s.number] = (s, "number")
            continue
        hit = next((e for e in SECTIONS if e.number not in assigned and title_match(s.title, e)), None)
        if hit:
            assigned[hit.number] = (s, "title")
        else:
            unmatched.append(s)

    if unmatched and llm is not None:
        e3_list = "\n".join(f"{e.number} {e.title}" for e in SECTIONS if e.number not in assigned)
        heads = "\n".join(f"- {s.title}" for s in unmatched)
        try:
            result = await complete_structured(
                llm,
                [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": MAP_HEADINGS.format(e3=e3_list, headings=heads)},
                ],
                HeadingMap,
                role="fast",
                step="map_headings",
            )
            by_title = {str(m.get("heading", "")).strip(): str(m.get("e3_number", "none")) for m in result.mapping}
            still = []
            for s in unmatched:
                num = by_title.get(s.title.strip(), "none")
                if num in BY_NUMBER and num not in assigned:
                    assigned[num] = (s, "llm")
                else:
                    still.append(s)
            unmatched = still
        except Exception:
            pass  # structure check still works on numbers and titles

    def content_words(number: str) -> int:
        """Words in the section plus all its subsections in the draft."""
        total = 0
        for num, (doc, _) in assigned.items():
            if num == number or num.startswith(number + "."):
                # An explicit "None." / "Not applicable." is a valid, complete section.
                explicit = re.fullmatch(r"\s*(none|not applicable|n/?a)\.?\s*", doc.text, re.I)
                total += EMPTY_WORDS if explicit else doc.word_count
        return total

    statuses = []
    for e in SECTIONS:
        if e.number in assigned:
            doc, method = assigned[e.number]
            status = "empty" if content_words(e.number) < EMPTY_WORDS and e.number not in {"3"} else "present"
            statuses.append(
                SectionStatus(
                    number=e.number,
                    title=e.title,
                    required=e.required,
                    status=status,
                    matched_heading=doc.title,
                    line=doc.line,
                    method=method,
                )
            )
        else:
            statuses.append(SectionStatus(number=e.number, title=e.title, required=e.required, status="missing"))

    order = []
    seen = [(n, doc.line) for n, (doc, _) in assigned.items()]
    seen.sort(key=lambda x: x[1])
    for (a, _), (b, line) in pairwise(seen):
        if number_key(b) < number_key(a):
            order.append(f"{b} appears after {a} (line {line})")
    return StructureReport(sections=statuses, unmatched_headings=[s.title for s in unmatched], order_issues=order)


def draft_targets(report: StructureReport) -> list[E3Section]:
    """Sections to draft or mark: missing/empty required ones, descending to the subsections that have data."""
    targets: list[E3Section] = []
    for number in report.missing + report.empty:
        sec = BY_NUMBER[number]
        children = [e for e in SECTIONS if e.number.startswith(number + ".") and e.tables and e.level == sec.level + 1]
        if sec.tables and children:
            targets += [c for c in children if c not in targets][:1]
        elif sec.tables or not children:
            targets.append(sec)
    return targets
