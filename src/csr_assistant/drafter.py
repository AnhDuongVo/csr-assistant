"""Draft missing sections from source tables, citing a table row for every data sentence."""

from __future__ import annotations

from .e3 import E3Section
from .llm import LLM, complete_structured
from .prompts import DRAFT, SYSTEM
from .schemas import DraftSection
from .sources import SourcePackage

NOT_DRAFTABLE_NEEDS = {
    "5.3": ["how and when informed consent was obtained", "version of the patient information sheet (appendix 16.1.3)"],
    "6": ["investigators, sites, CRO and committees (appendix 16.1.4)"],
    "9.7.2": ["sample size assumptions: effect size, standard deviation, power, alpha, dropout rate"],
}


def placeholder(section: E3Section) -> DraftSection:
    needs = NOT_DRAFTABLE_NEEDS.get(section.number) or [section.guidance or "content described in ICH E3"]
    return DraftSection(number=section.number, title=section.title, gaps=needs, status="placeholder")


async def draft_section(section: E3Section, pkg: SourcePackage, llm: LLM, feedback: str = "") -> DraftSection:
    tables = pkg.tables_of(section.tables)
    if not tables:
        return placeholder(section)
    out = await complete_structured(
        llm,
        [
            {"role": "system", "content": SYSTEM},
            {
                "role": "user",
                "content": DRAFT.format(
                    number=section.number,
                    title=section.title,
                    guidance=section.guidance or "see ICH E3",
                    synopsis=pkg.synopsis or "(none)",
                    tables="\n\n".join(t.render() for t in tables),
                    feedback=f"\nFix these problems found by the reviewer in your previous draft:\n{feedback}\n"
                    if feedback
                    else "",
                ),
            },
        ],
        DraftSection,
        role="reasoning",
        step="draft_section",
    )
    # The model fills content only; identity, status and the writer's decision are set by code.
    return out.model_copy(
        update={"number": section.number, "title": section.title, "status": "drafted", "decision": "pending"}
    )
