import asyncio
import uuid
from importlib.resources import files
from pathlib import Path

import streamlit as st
from demo_fixture import fake_draft, fake_review

from csr_assistant.agent import Options, build_graph
from csr_assistant.llm import FakeLLM

st.set_page_config(layout="wide", page_title="csr-assistant workflow")
st.markdown(
    """<style>.block-container{padding-top:1.3rem;max-width:1400px}h1{font-size:1.9rem!important}h2{font-size:1.3rem!important}h3{font-size:1.1rem!important}div[data-testid=stMetricValue]{font-size:1.5rem}textarea{font-size:13px!important}</style>""",
    unsafe_allow_html=True,
)


st.title("csr-assistant: source package → reviewed report")
st.caption(
    "OFFLINE · Synthetic SYN-301 study · Scripted drafting and model review · Actual ICH E3 structure screen, numerical/citation checks, revision loop and writer review. No live model generation."
)
S = Path(str(files("csr_assistant") / "samples" / "study_syn301"))
paths = {"draft": str(S / "draft_csr.md"), "tables": str(S / "tables"), "synopsis": str(S / "synopsis.md")}
a, b = st.columns([1, 1.3])
with a:
    st.subheader("Input · draft, tables and synopsis")
    source = st.selectbox(
        "Inspect source",
        ["Draft CSR", "Protocol synopsis"] + [p.name for p in sorted((S / "tables").glob("*")) if p.is_file()],
    )
    path = (
        S / "draft_csr.md"
        if source == "Draft CSR"
        else S / "synopsis.md"
        if source == "Protocol synopsis"
        else S / "tables" / source
    )
    st.text_area("Source text", path.read_text(), height=380, disabled=True)
    st.caption("The bundled draft contains planted errors and missing sections. Source tables remain unchanged.")
    if st.button("Review and draft missing sections", type="primary"):

        async def run():
            graph = build_graph(
                FakeLLM({"draft_section": fake_draft, "review_claim": fake_review, "map_headings": {"mapping": []}}),
                Options(max_revisions=1, human_review=True),
            )
            cfg = {"configurable": {"thread_id": str(uuid.uuid4())}}
            state = await graph.ainvoke({"paths": paths}, cfg)
            return graph, cfg, state

        graph, cfg, state = asyncio.run(run())
        st.session_state.update(graph=graph, cfg=cfg, state=state)
with b:
    st.subheader("Output · structure, findings and proposed sections")
    if "state" not in st.session_state:
        st.info("Run the real repository workflow to build a reviewable report.")
    else:
        state = st.session_state.state
        c, d, e = st.columns(3)
        c.metric(
            "Missing E3 sections",
            sum(x["status"] == "missing" and x["required"] for x in state["structure"]["sections"]),
        )
        d.metric("Automatic revisions", state.get("revisions", 0))
        e.metric("Open findings", sum(not x.get("dismissed", False) for x in state["findings"]))
        view = st.selectbox("Inspect output", ["Findings", "ICH E3 structure", "Proposed sections", "Revised report"])
        if view == "Findings":
            for f in state["findings"]:
                if not f.get("dismissed"):
                    st.warning(f"{f['id']} · {f['section']} · {f['type']} · {f['origin']}")
                    st.write(f["sentence"])
                    st.caption(f["detail"])
        elif view == "ICH E3 structure":
            st.dataframe(
                [{k: x[k] for k in ["number", "title", "status"]} for x in state["structure"]["sections"]],
                hide_index=True,
                height=350,
            )
        elif view == "Proposed sections":
            for draft in state["drafted"]:
                st.write(f"**{draft['number']} {draft['title']} · {draft['status']} · {draft['decision']}**")
                for sent in draft["sentences"]:
                    st.write(sent["text"] + " [" + ", ".join(sent["citations"]) + "]")
                for gap in draft["gaps"]:
                    st.caption("Needs writer input: " + gap)
        else:
            st.text_area("Revised CSR · draft for writer review", state["revised_md"], height=400, disabled=True)
        if not state.get("reviewer"):
            with st.expander("Medical writer review"):
                rejected = st.multiselect("Reject proposed sections", [x["number"] for x in state["drafted"]])
                st.caption(
                    "The remaining proposals will be recorded as accepted in this synthetic exercise; findings remain open."
                )
                if st.button("Record synthetic writer decisions"):

                    async def finalize():
                        await st.session_state.graph.aupdate_state(
                            st.session_state.cfg, {"rejected": rejected, "reviewer": "Demo medical writer"}
                        )
                        return await st.session_state.graph.ainvoke(None, st.session_state.cfg)

                    st.session_state.state = asyncio.run(finalize())
                    st.rerun()
        else:
            st.success("Synthetic writer decisions recorded · unresolved findings remain visible")
        st.download_button("Download revised draft", state["revised_md"], "revised_csr.md")
        st.download_button("Download review report", state["report_md"], "review_report.md")
