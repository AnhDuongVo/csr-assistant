"""`csr --help`: ICH E3 structure check, table-grounded drafting and claim review for clinical study reports."""

from __future__ import annotations

import asyncio
import json
import uuid
from importlib import resources
from pathlib import Path

import typer
from rich.console import Console
from rich.markdown import Markdown

from .agent import Options, build_graph
from .config import get_settings
from .llm import NIMClient
from .sources import load_package
from .structure import check_structure

app = typer.Typer(
    add_completion=False,
    help="Assistant for ICH E3 clinical study reports: structure check, grounded drafting, number review.",
)
console = Console()


def sample_dir() -> Path:
    return Path(str(resources.files("csr_assistant") / "samples" / "study_syn301"))


def _paths(draft: Path, tables: Path, synopsis: Path | None) -> dict:
    return {"draft": str(draft), "tables": str(tables), "synopsis": str(synopsis) if synopsis else None}


def _write(out_dir: Path, state: dict, docx: bool) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "revised_csr.md").write_text(state["revised_md"])
    (out_dir / "review_report.md").write_text(state["report_md"])
    (out_dir / "findings.json").write_text(json.dumps(state["findings"], indent=2))
    (out_dir / "drafted_sections.json").write_text(json.dumps(state["drafted"], indent=2))
    (out_dir / "structure.json").write_text(json.dumps(state["structure"], indent=2))
    if docx:
        from .export import markdown_to_docx

        markdown_to_docx(state["revised_md"], out_dir / "revised_csr.docx")


async def _run(
    paths: dict, review: bool, max_revisions: int, out_dir: Path, docx: bool, review_only: bool = False
) -> dict:
    llm = NIMClient(get_settings())
    graph = build_graph(llm, Options(max_revisions=max_revisions, human_review=review, review_only=review_only))
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    state = await graph.ainvoke({"paths": paths}, config)
    if review:
        snap = await graph.aget_state(config)
        console.print(Markdown(snap.values["report_md"]))
        drafted = [d["number"] for d in snap.values["drafted"] if d["status"] == "drafted"]
        console.print(f"Drafted sections: {', '.join(drafted) or 'none'}")
        rejected = typer.prompt(
            "Reject drafted sections (numbers, comma-separated, empty = accept all)", default="", show_default=False
        )
        dismissed = typer.prompt(
            "Dismiss findings you disagree with (ids like F2,F5, empty = none)", default="", show_default=False
        )
        name = typer.prompt("Your name", default="Medical writer")
        await graph.aupdate_state(
            config,
            {
                "rejected": [x.strip() for x in rejected.split(",") if x.strip()],
                "dismissed": [x.strip().upper() for x in dismissed.split(",") if x.strip()],
                "reviewer": name,
            },
        )
        state = await graph.ainvoke(None, config)
    _write(out_dir, state, docx)
    return state


@app.command(name="review")
def review_cmd(
    draft: Path = typer.Argument(..., exists=True, help="Draft CSR (.md or .docx)"),
    tables: Path = typer.Argument(..., exists=True, file_okay=False, help="Folder of source tables (.csv)"),
    synopsis: Path = typer.Option(None, exists=True, help="Protocol synopsis (.md / .txt)"),
    review: bool = typer.Option(True, help="Pause for the medical writer to accept/reject drafts and findings"),
    max_revisions: int = typer.Option(1),
    docx: bool = typer.Option(False, help="Also export revised_csr.docx (requires the 'docx' extra)"),
    review_only: bool = typer.Option(False, help="Only review claims, do not draft sections (e.g. EPAR text)"),
    out_dir: Path = typer.Option(Path("runs/latest")),
):
    """Check structure, draft missing sections from the tables, and review every claim."""
    state = asyncio.run(_run(_paths(draft, tables, synopsis), review, max_revisions, out_dir, docx, review_only))
    if not review:
        console.print(Markdown(state["report_md"]))
    console.print(f"[green]Saved to {out_dir}/[/]")


@app.command()
def demo(out_dir: Path = typer.Option(Path("runs/demo")), docx: bool = typer.Option(False)):
    """Synthetic study SYN-301-03 (drug SYN-301): a draft with missing sections and four planted errors."""
    s = sample_dir()
    state = asyncio.run(_run(_paths(s / "draft_csr.md", s / "tables", s / "synopsis.md"), False, 1, out_dir, docx))
    console.print(Markdown(state["report_md"]))
    console.print(f"[green]Saved to {out_dir}/[/]")


@app.command()
def structure(draft: Path = typer.Argument(..., exists=True)):
    """ICH E3 structure check only (no LLM, no tables needed)."""
    pkg = load_package(draft, draft.parent, None)
    rep = asyncio.run(check_structure(pkg.sections, None))
    console.print(f"Missing: {', '.join(rep.missing) or 'none'}\nEmpty: {', '.join(rep.empty) or 'none'}")
    for issue in rep.order_issues:
        console.print(f"Order: {issue}")


@app.command(name="epar")
def epar_cmd(
    pdf: Path = typer.Argument(..., exists=True),
    pages: str = typer.Option(..., help="e.g. 45-60"),
    out_dir: Path = typer.Option(Path("runs/epar_package")),
):
    """Extract narrative and tables from an EMA EPAR page range into a package and print the review command."""
    from .epar import extract

    pkg = extract(pdf, pages, out_dir)
    n = len(list((pkg / "tables").glob("*.csv")))
    console.print(
        f"Extracted {n} tables. Check the CSVs, then: "
        f"csr review {pkg}/draft_csr.md {pkg}/tables --no-review --review-only"
    )


@app.command(name="eval")
def eval_cmd(
    package: Path = typer.Option(None, help="Package folder with expected.json (default: bundled)"),
    out_dir: Path = typer.Option(Path("runs/eval")),
):
    """Structure detection, planted-error recall, false alarms and citation validity."""
    from .evaluate import evaluate

    summary = asyncio.run(evaluate(NIMClient(get_settings()), package or sample_dir(), out_dir))
    console.print_json(json.dumps(summary))


@app.command()
def models():
    """List the model IDs your key can use (check these against .env)."""
    from openai import OpenAI

    s = get_settings()
    client = OpenAI(base_url=s.base_url, api_key=s.require_api_key())
    ids = sorted(m.id for m in client.models.list().data)
    for mid in ids:
        mark = " <- reasoning" if mid == s.model_reasoning else " <- fast" if mid == s.model_fast else ""
        console.print(f"{mid}{mark}")
    for role, mid in (("CSR_MODEL_REASONING", s.model_reasoning), ("CSR_MODEL_FAST", s.model_fast)):
        if mid not in ids:
            console.print(f"[red]{role}={mid} is not in the list. Pick another ID in .env[/]")


if __name__ == "__main__":
    app()
