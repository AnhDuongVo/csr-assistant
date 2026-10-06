"""CSR assistant as a LangGraph workflow.

    structure (E3 check) -> draft (missing sections with data, in parallel; placeholders for the rest)
      -> review (writer's draft + generated text) --(generated text flagged, revisions left)--> redraft -> review
      -> assemble (revised CSR + review report) -> [medical writer review interrupt] -> finalize

Nothing generated is ever presented as final: drafted sections carry a DRAFT banner and their citations,
and the writer accepts or rejects each one.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from .drafter import draft_section, placeholder
from .e3 import BY_NUMBER, SECTIONS, number_key
from .llm import LLM
from .reviewer import review
from .schemas import DraftSection, Finding, StructureReport
from .sources import SourcePackage, load_package
from .structure import check_structure, draft_targets


class CSRState(TypedDict, total=False):
    paths: dict
    structure: dict
    drafted: list[dict]
    findings: list[dict]
    revisions: int
    rejected: list[str]  # section numbers the writer rejected
    dismissed: list[str]  # finding ids the writer dismissed
    reviewer: str
    revised_md: str
    report_md: str


@dataclass
class Options:
    max_revisions: int = 1
    human_review: bool = False
    review_only: bool = False  # e.g. EPAR text: check claims, do not draft sections


def assemble(
    pkg: SourcePackage,
    drafted: list[DraftSection],
    rejected: set[str] = frozenset(),
    structure: StructureReport | None = None,
) -> str:
    """Original document with drafted sections filled in or inserted at their E3 position."""
    by_num = {d.number: d for d in drafted if d.number not in rejected}
    by_line = {s.line: s.number for s in structure.sections if s.line} if structure else {}
    out: list[str] = []
    used: set[str] = set()

    def emit_new(before_key: tuple[int, ...] | None):
        for num in sorted(by_num, key=number_key):
            if num in used or (before_key is not None and number_key(num) >= before_key):
                continue
            d = by_num[num]
            out.append("#" * BY_NUMBER[num].level + f" {num} {d.title}\n\n{d.markdown()}\n")
            used.add(num)

    for sec in pkg.sections:
        number = sec.number or by_line.get(sec.line)
        if number:
            emit_new(number_key(number))
        heading = "#" * sec.level + " " + (f"{sec.number} " if sec.number else "") + sec.title
        if number in by_num and number not in used:  # existing but empty heading: fill it
            out.append(f"{heading}\n\n{by_num[number].markdown()}\n")
            used.add(number)
        else:
            out.append(f"{heading}\n{sec.text}\n" if sec.text else f"{heading}\n")
    emit_new(None)
    return "\n".join(out)


def report(
    structure: StructureReport,
    drafted: list[DraftSection],
    findings: list[Finding],
    name: str,
    reviewer: str | None = None,
) -> str:
    lines = [f"# CSR review report: {name}", ""]
    if reviewer:
        lines += [f"Reviewed by {reviewer}.", ""]
    lines += ["## ICH E3 structure", "", "| E3 | Section | Status | In draft |", "|---|---|---|---|"]
    for s in structure.sections:
        if s.required or s.status != "missing":
            mark = {"present": "present", "missing": "**MISSING**", "empty": "**EMPTY**"}[s.status]
            where = f"line {s.line} ({s.method})" if s.line else ""
            lines.append(f"| {s.number} | {s.title} | {mark} | {where} |")
    if structure.order_issues:
        lines += ["", "Order issues: " + "; ".join(structure.order_issues)]
    if structure.unmatched_headings:
        lines += ["", "Headings not mapped to E3: " + "; ".join(structure.unmatched_headings)]
    lines += ["", "## Drafted sections", ""]
    for d in drafted:
        state = d.decision if d.decision != "pending" else "awaiting writer review"
        kind = "placeholder (data not in sources)" if d.status == "placeholder" else f"{len(d.sentences)} sentences"
        lines.append(f"- **{d.number} {d.title}**: {kind}, {state}")
    open_f = [f for f in findings if not f.dismissed]
    lines += [
        "",
        f"## Reviewer findings ({len(open_f)} open)",
        "",
        "| ID | Section | Origin | Type | Severity | Statement | Detail | Suggested rewrite |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for f in open_f:
        cells = [f.id, f.section, f.origin, f.type, f.severity, f.sentence, f.detail, f.suggestion]
        lines.append("| " + " | ".join(c.replace("|", "/").replace("\n", " ") for c in cells) + " |")
    dismissed = [f for f in findings if f.dismissed]
    if dismissed:
        lines += ["", "Dismissed by the writer: " + ", ".join(f.id for f in dismissed)]
    lines += ["", "_Drafting and review support only. The medical writer and responsible clinician own the content._"]
    return "\n".join(lines) + "\n"


def build_graph(llm: LLM, options: Options | None = None, checkpointer: Any | None = None):
    opts = options or Options()

    def pkg_of(state: CSRState) -> SourcePackage:
        p = state["paths"]
        return load_package(p["draft"], p["tables"], p.get("synopsis"))

    async def structure(state: CSRState) -> dict:
        rep = await check_structure(pkg_of(state).sections, llm)
        return {"structure": rep.model_dump(), "revisions": 0}

    async def draft(state: CSRState) -> dict:
        if opts.review_only:
            return {"drafted": []}
        pkg = pkg_of(state)
        targets = draft_targets(StructureReport.model_validate(state["structure"]))

        async def one(t):
            if not t.tables:
                return placeholder(t)
            try:
                return await draft_section(t, pkg, llm)
            except Exception as err:  # one failed section must not stop the others
                p = placeholder(t)
                p.gaps = [f"automatic drafting failed ({str(err)[:120]}); draft manually"] + p.gaps
                return p

        drafts = await asyncio.gather(*(one(t) for t in targets))
        return {"drafted": [d.model_dump() for d in drafts]}

    async def do_review(state: CSRState) -> dict:
        drafted = [DraftSection.model_validate(d) for d in state["drafted"]]
        findings = await review(pkg_of(state), drafted, llm, StructureReport.model_validate(state["structure"]))
        return {"findings": [f.model_dump() for f in findings]}

    def after_review(state: CSRState) -> str:
        gen = [f for f in state["findings"] if f["origin"] == "generated" and f["type"] != "review_error"]
        return "redraft" if gen and state.get("revisions", 0) < opts.max_revisions else "assemble"

    async def redraft(state: CSRState) -> dict:
        pkg = pkg_of(state)
        problems: dict[str, list[str]] = {}
        for f in state["findings"]:
            if f["origin"] == "generated":
                problems.setdefault(f["section"], []).append(f'- "{f["sentence"]}": {f["detail"]}')
        drafted = [DraftSection.model_validate(d) for d in state["drafted"]]

        async def fix(d: DraftSection) -> DraftSection:
            if d.number not in problems:
                return d
            return await draft_section(BY_NUMBER[d.number], pkg, llm, feedback="\n".join(problems[d.number]))

        new = await asyncio.gather(*(fix(d) for d in drafted))
        return {"drafted": [d.model_dump() for d in new], "revisions": state.get("revisions", 0) + 1}

    async def build_outputs(state: CSRState) -> dict:
        pkg = pkg_of(state)
        rejected = set(state.get("rejected") or [])
        dismissed = set(state.get("dismissed") or [])
        drafted = []
        for d in state["drafted"]:
            d = DraftSection.model_validate(d)
            if state.get("reviewer"):
                d.decision = "rejected" if d.number in rejected else "accepted"
            drafted.append(d)
        findings = [Finding.model_validate({**f, "dismissed": f["id"] in dismissed}) for f in state["findings"]]
        return {
            "revised_md": assemble(pkg, drafted, rejected, StructureReport.model_validate(state["structure"])),
            "report_md": report(
                StructureReport.model_validate(state["structure"]), drafted, findings, pkg.name, state.get("reviewer")
            ),
            "drafted": [d.model_dump() for d in drafted],
            "findings": [f.model_dump() for f in findings],
        }

    g = StateGraph(CSRState)
    g.add_node("structure", structure)
    g.add_node("draft", draft)
    g.add_node("review", do_review)
    g.add_node("redraft", redraft)
    g.add_node("assemble", build_outputs)
    g.add_node("finalize", build_outputs)  # same builder, now with the writer's decisions
    g.add_edge(START, "structure")
    g.add_edge("structure", "draft")
    g.add_edge("draft", "review")
    g.add_conditional_edges("review", after_review, {"redraft": "redraft", "assemble": "assemble"})
    g.add_edge("redraft", "review")
    g.add_edge("assemble", "finalize")
    g.add_edge("finalize", END)
    if opts.human_review:
        return g.compile(checkpointer=checkpointer or MemorySaver(), interrupt_before=["finalize"])
    return g.compile(checkpointer=checkpointer)


async def run(paths: dict, llm: LLM, options: Options | None = None) -> CSRState:
    o = options or Options()
    opts = Options(max_revisions=o.max_revisions, human_review=False, review_only=o.review_only)
    return await build_graph(llm, opts).ainvoke({"paths": paths})


__all__ = ["SECTIONS", "Options", "assemble", "build_graph", "report", "run"]
