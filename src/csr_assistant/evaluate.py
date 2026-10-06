"""Evaluate against a package with known problems (expected.json): structure detection, error detection,
false alarms on correct claims, and citation validity of generated text."""

from __future__ import annotations

import json
from pathlib import Path

from .agent import run
from .llm import LLM


def _prf(found: set[str], gold: set[str]) -> dict:
    tp = len(found & gold)
    p = tp / len(found) if found else 0.0
    r = tp / len(gold) if gold else 1.0
    return {"precision": round(p, 3), "recall": round(r, 3), "found": sorted(found), "expected": sorted(gold)}


async def evaluate(llm: LLM, package_dir: str | Path, out_dir: str | Path = "runs/eval") -> dict:
    pkg = Path(package_dir)
    expected = json.loads((pkg / "expected.json").read_text())
    state = await run(
        {"draft": str(pkg / "draft_csr.md"), "tables": str(pkg / "tables"), "synopsis": str(pkg / "synopsis.md")}, llm
    )
    structure = state["structure"]["sections"]
    missing = {s["number"] for s in structure if s["required"] and s["status"] == "missing"}
    empty = {s["number"] for s in structure if s["required"] and s["status"] == "empty"}
    findings = state["findings"]
    # Review errors (rate limits, context overflow) are not detections.
    draft_findings = [f for f in findings if f["origin"] == "draft" and f["type"] != "review_error"]

    caught = [e for e in expected["injected_errors"] if any(e["contains"] in f["sentence"] for f in draft_findings)]
    false_alarms = [c for c in expected.get("correct_claims", []) if any(c in f["sentence"] for f in draft_findings)]
    generated = [s for d in state["drafted"] if d["status"] == "drafted" for s in d["sentences"]]
    gen_flagged = {f["sentence"] for f in findings if f["origin"] == "generated"}
    summary = {
        "missing_sections": _prf(missing, set(expected["missing_sections"])),
        "empty_sections": _prf(empty, set(expected.get("empty_sections", []))),
        "error_recall": round(len(caught) / len(expected["injected_errors"]), 3),
        "errors_missed": [e["contains"] for e in expected["injected_errors"] if e not in caught],
        "false_alarms_on_correct_claims": len(false_alarms),
        "false_alarm_examples": false_alarms,
        "draft_findings_total": len(draft_findings),
        "review_errors": sum(1 for f in findings if f["type"] == "review_error"),
        "generated_sentences": len(generated),
        "generated_sentences_clean": sum(1 for s in generated if s["text"] not in gen_flagged),
        "revisions": state.get("revisions", 0),
    }
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    (out / "review_report.md").write_text(state["report_md"])
    (out / "revised_csr.md").write_text(state["revised_md"])
    return summary
