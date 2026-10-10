"""Deterministic number verification: every number in a claim must be traceable to the sources.

A number counts as supported if it appears in the cited rows (or, for uncited text, anywhere in the source
tables and synopsis) after rounding to the precision written in the sentence, or if it is a percentage that
follows from two numbers in the same row (n / N). Explicit signs and directional changes are checked; contextual arm checks use labelled cells.
"""

from __future__ import annotations

import re
from itertools import permutations

_NUM = re.compile(
    r"(?<![\w.,])[-\u2212]?\d{1,3}(?:,\d{3})+(?![\d.,]\d)(?:\s?%)?|(?<![\w.,])[-\u2212]?\d+(?:[.,]\d+)?(?:\s?%)?"
)
_REFS = re.compile(
    r"\[(?:T\d+\.R\d+(?:,\s*)?)+\]"  # our row citations
    r"|\b(?:Tables?|Sections?|Figures?|Listings?|Appendix|Appendices)\s+\d+(?:\.\d+)*"  # document references
    r"|\b\d+\.\d+\.\d+(?:\.\d+)*\b"  # 14.2.1-style numbers are always references
    r"|\b\d{4}-\d{2}-\d{2}\b|\b(?:19|20)\d{2}\b"  # dates and years
    r"|\b[A-Z][A-Z0-9]*-\d+\b"  # study / product codes: SYN-301, ABC-123
    r"|\b\d+:\d+\b",  # ratios: 1:1 randomisation
    re.IGNORECASE,
)
_INCREASE = re.compile(r"\b(increas\w*|rose|rise|rising|gain\w*|higher)\b", re.I)
_DECREASE = re.compile(r"\b(decreas\w*|reduc\w*|lower\w*|fell|fall|declin\w*|loss|lost)\b", re.I)


def strip_refs(text: str) -> str:
    return _REFS.sub(" ", text)


def signed_values(text: str) -> list[float]:
    out = []
    for m in _NUM.finditer(strip_refs(text)):
        raw = m.group().replace("\u2212", "-").replace(" ", "").rstrip("%")
        raw = raw.replace(",", "") if re.fullmatch(r"-?\d{1,3}(?:,\d{3})+", raw) else raw.replace(",", ".")
        out.append(float(raw))
    return out


def numbers(text: str) -> list[tuple[float, int, bool, str]]:
    """(absolute value, decimals written, is_percent, raw) for each number in the text."""
    out = []
    for m in _NUM.finditer(strip_refs(text)):
        raw = m.group().replace("−", "-").replace(" ", "")
        pct = raw.endswith("%")
        digits = raw.rstrip("%").lstrip("-")
        digits = digits.replace(",", "") if re.fullmatch(r"\d{1,3}(?:,\d{3})+", digits) else digits.replace(",", ".")
        decimals = len(digits.split(".")[1]) if "." in digits else 0
        out.append((abs(float(digits)), decimals, pct, raw))
    return out


def _close(a: float, b: float, decimals: int) -> bool:
    return abs(round(b, decimals) - a) < 10 ** (-decimals) * 0.51 or abs(a - b) < 1e-9


def unverified(
    sentence: str, sources: list[str], ignore: set[float] | None = None, count_sources: list[str] | None = None
) -> list[str]:
    """Numbers in `sentence` that cannot be traced to any of the `sources` (each source = one row or text).

    * A number written with decimals matches a source value at that precision; a whole number must match a
      whole source value exactly (so "4 deaths" does not match 4.2).
    * A percentage may also be n / N of two whole counts in the same entry of `count_sources` (default
      `sources`; pass row values only, so header numbers like N=119 do not create spurious matches).
    * Direction: "increased by 1.2" does not match a source value of -1.2.
    """
    ignore = ignore or set()
    flat = [(v, d) for s in sources for v, d, _, _ in numbers(s)]
    signed: dict[float, list[float]] = {}
    for s in sources:
        for v in signed_values(s):
            signed.setdefault(abs(v), []).append(v)
    counts = [[v for v, d, pct, _ in numbers(s) if d == 0 and not pct and v >= 1] for s in (count_sources or sources)]
    increase = bool(_INCREASE.search(sentence)) and not _DECREASE.search(sentence)
    decrease = bool(_DECREASE.search(sentence)) and not _INCREASE.search(sentence)
    missing = []
    for value, decimals, pct, raw in numbers(sentence):
        if value in ignore:
            continue
        # Whole counts must match exactly ("4 deaths" is not 4.2); decimals and percentages match at the written precision.
        hits = [v for v, d in flat if (_close(value, v, decimals) if (decimals or pct) else v == value)]
        if hits:
            signs = [x for h in hits for x in signed.get(h, [h])]
            if raw.startswith("-") and not any(x < 0 for x in signs):
                missing.append(f"{raw} (signed value differs from source)")
            elif increase and not raw.startswith("-") and all(x < 0 for x in signs):
                missing.append(f"{raw} (source value is negative but the sentence says increase)")
            elif decrease and not raw.startswith("-") and all(x > 0 for x in signs) and (decimals or pct):
                missing.append(f"{raw} (source value is positive but the sentence says decrease)")
            continue
        if pct and any(
            a <= b and _close(value, 100 * a / b, decimals) for vals in counts for a, b in permutations(vals, 2)
        ):
            continue
        missing.append(raw)
    return missing


def contextual_unverified(sentence: str, sources: list[str]) -> list[str]:
    """Check explicit arm/value associations in labelled table cells.

    Only handles clauses naming a single arm. Multiple arms in one clause require
    semantic review; this helper does not infer 'respectively' ordering.
    """
    cells = []
    for source in sources:
        for cell in source.split(" | "):
            if ": " in cell:
                label, value = cell.split(": ", 1)
                cells.append((label, value))
    arms = set()
    for label, _ in cells:
        arm = re.sub(r"\s+(?:n\b.*|%.*|mean\b.*|change\b.*)", "", label, flags=re.I).strip()
        if arm and (arm.lower() == "placebo" or re.search(r"[A-Z]+-\d+", arm)):
            arms.add(arm)
    missing = []
    for clause in re.split(r"[;]|\band\b|\bversus\b|\bvs\.?\b", sentence, flags=re.I):
        named = [a for a in arms if re.search(r"(?<!\w)" + re.escape(a) + r"(?!\w)", clause, re.I)]
        if len(named) != 1:
            continue
        arm = named[0]
        values = [v for label, v in cells if label.lower().startswith(arm.lower())]
        for raw in unverified(clause, values, {95.0}):
            missing.append(f"{raw} not in {arm} cells")
    return missing
