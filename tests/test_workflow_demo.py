import sys
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest


def test_actual_workflow_and_review():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "examples"))
    sys.modules.pop("demo_fixture", None)
    a = AppTest.from_file(str(root / "examples/workflow.py"), default_timeout=30).run()
    assert not a.exception, a.exception
    next(b for b in a.button if b.label.startswith(("Run pre", "Review and", "Run simulated"))).click().run()
    assert not a.exception, a.exception
    state = a.session_state.state
    assert state["revisions"] == 1 and any(
        "120 patients" in s["text"] for d in state["drafted"] for s in d["sentences"]
    )
    assert [x["number"] for x in state["structure"]["sections"] if x["status"] == "missing" and x["required"]] == [
        "5.3",
        "10.1",
        "12.1",
    ]
    a.multiselect[0].set_value(["12.1"]).run()
    next(b for b in a.button if b.label == "Record synthetic writer decisions").click().run()
    assert not a.exception, a.exception
    assert a.session_state.state["reviewer"] == "Demo medical writer"

    assert "Extent of Exposure" not in a.session_state.state["revised_md"]
