import re
import uuid
from pathlib import Path

from csr_assistant.agent import Options, build_graph, run
from csr_assistant.evaluate import evaluate
from csr_assistant.llm import FakeLLM
from csr_assistant.numcheck import unverified
from csr_assistant.sources import load_package
from csr_assistant.structure import check_structure, draft_targets

S = Path(__file__).resolve().parents[1] / "src" / "csr_assistant" / "samples" / "study_syn301"
PATHS = {"draft": str(S / "draft_csr.md"), "tables": str(S / "tables"), "synopsis": str(S / "synopsis.md")}

DRAFTS = {
    "10.1": [{"text": "In total, 125 patients were randomised to SYN-301.", "citations": ["T1.R1"]}],  # wrong first
    "10.1-fixed": [
        {"text": "In total, 120 patients were randomised to SYN-301 and 120 to placebo.", "citations": ["T1.R1"]},
        {"text": "Study treatment was discontinued by 12 (10.0%) and 10 (8.3%) patients.", "citations": ["T1.R4"]},
    ],
    "12.1": [
        {
            "text": "Mean duration of exposure was 24.8 weeks with SYN-301 and 25.3 weeks with placebo.",
            "citations": ["T3.R1"],
        }
    ],
    "12.2.1": [
        {"text": "Adverse events were reported in 78 (65.5%) and 64 (53.3%) patients.", "citations": ["T6.R1"]},
        {"text": "Nausea occurred in 22 (18.5%) and 6 (5.0%) patients.", "citations": ["T7.R1"]},
    ],
}


def fake_draft(messages):
    msg = messages[-1]["content"]
    number = re.search(r'section (\S+) "', msg).group(1)
    key = f"{number}-fixed" if "Fix these problems" in msg and f"{number}-fixed" in DRAFTS else number
    return {"number": number, "title": "x", "sentences": DRAFTS[key], "gaps": []}


def fake_review(messages):
    s = re.search(r"Statement: (.*)", messages[-1]["content"]).group(1)
    if "superior to all approved" in s:
        return {"verdict": "unsupported", "explanation": "no active comparator", "suggested_rewrite": ""}
    if "no gastrointestinal safety signal" in s:
        return {
            "verdict": "overstated",
            "explanation": "nausea 18.5% vs 5.0% [T7.R1]",
            "suggested_rewrite": "Gastrointestinal events were more frequent with SYN-301.",
        }
    return {"verdict": "supported", "explanation": "matches tables"}


def fake_llm():
    return FakeLLM({"draft_section": fake_draft, "review_claim": fake_review, "map_headings": {"mapping": []}})


async def test_structure_and_targets():
    pkg = load_package(PATHS["draft"], PATHS["tables"], PATHS["synopsis"])
    rep = await check_structure(pkg.sections)
    assert set(rep.missing) == {"5.3", "10.1", "12.1"}
    assert rep.empty == ["12.2"]
    assert [t.number for t in draft_targets(rep)] == ["5.3", "10.1", "12.1", "12.2.1"]


def test_numbers():
    row = "Any adverse event | SYN-301 n (N=119): 78 | SYN-301 %: 65.5"
    assert unverified("78 (65.5%) patients", [row]) == []
    assert unverified("HbA1c fell by 1.4% (Table 14.2.1)", ["-1.21"]) == ["1.4%"]
    assert unverified("diff -0.90% (95% CI -1.12 to -0.68)", ["-0.90 -1.12 -0.68"], {95.0}) == []


async def test_pipeline_finds_planted_errors_and_repairs_draft():
    state = await run(PATHS, fake_llm(), Options(max_revisions=1))
    assert state["revisions"] == 1  # 10.1 had a wrong number and was redrafted
    draft_f = [f for f in state["findings"] if f["origin"] == "draft"]
    texts = " ".join(f["sentence"] for f in draft_f)
    for planted in ("decreased by 1.4%", "superior to all approved", "no gastrointestinal safety signal", "4.5 kg"):
        assert planted in texts
    assert not [f for f in state["findings"] if f["origin"] == "generated"]
    md = state["revised_md"]
    assert "# 10.1 Disposition of Patients" in md and "MISSING (ICH E3 5.3)" in md
    assert md.index("10.1 Disposition") < md.index("10.2 Protocol Deviations")
    assert "[T6.R1]" in md


async def test_writer_review_rejects_and_dismisses():
    graph = build_graph(fake_llm(), Options(human_review=True))
    cfg = {"configurable": {"thread_id": str(uuid.uuid4())}}
    await graph.ainvoke({"paths": PATHS}, cfg)
    snap = await graph.aget_state(cfg)
    assert snap.next == ("finalize",)
    first = snap.values["findings"][0]["id"]
    await graph.aupdate_state(cfg, {"rejected": ["12.1"], "dismissed": [first], "reviewer": "Writer W"})
    state = await graph.ainvoke(None, cfg)
    assert "Extent of Exposure" not in state["revised_md"]
    assert f"Dismissed by the writer: {first}" in state["report_md"] and "Reviewed by Writer W" in state["report_md"]


async def test_evaluate(tmp_path):
    summary = await evaluate(fake_llm(), S, tmp_path)
    assert summary["missing_sections"]["recall"] == 1.0 and summary["missing_sections"]["precision"] == 1.0
    assert summary["error_recall"] == 1.0
    assert summary["false_alarms_on_correct_claims"] == 0
    assert summary["generated_sentences_clean"] == summary["generated_sentences"]


def test_docx_export(tmp_path):
    from csr_assistant.export import markdown_to_docx

    p = markdown_to_docx("# 10.1 Disposition\n\n> **DRAFT**\n\nText.", tmp_path / "x.docx")
    assert p.exists() and p.stat().st_size > 1000
