"""Scripted synthetic model fixtures for the offline workflow demo."""

import re

DRAFTS = {
    "10.1": [{"text": "In total, 125 patients were randomised to SYN-301.", "citations": ["T1.R1"]}],
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
    number = re.search('section (\\S+) "', msg).group(1)
    key = f"{number}-fixed" if "Fix these problems" in msg and f"{number}-fixed" in DRAFTS else number
    return {"number": number, "title": "x", "sentences": DRAFTS[key], "gaps": []}


def fake_review(messages):
    s = re.search("Statement: (.*)", messages[-1]["content"]).group(1)
    if "superior to all approved" in s:
        return {"verdict": "unsupported", "explanation": "no active comparator", "suggested_rewrite": ""}
    if "no gastrointestinal safety signal" in s:
        return {
            "verdict": "overstated",
            "explanation": "nausea 18.5% vs 5.0% [T7.R1]",
            "suggested_rewrite": "Gastrointestinal events were more frequent with SYN-301.",
        }
    return {"verdict": "supported", "explanation": "matches tables"}
