# Validation evidence — 9 October 2026

`pip install -e ".[dev]"` succeeded in a fresh virtual environment for this repository, independently of the other projects. Tests ran on Python 3.12.14 / Darwin arm64 CPU. Other Python versions in CI have not been executed locally here.

| Check | Result |
|---|---|
| Offline test suite | 11 passed |
| Ruff lint | Passed |
| Ruff formatting | Passed |
| Mocked/simulated integration | Tested within the scope below |
| Live NVIDIA hosted endpoint | Not executed |
| Self-hosted GPU endpoint | Not executed |
| Clinical/scientific domain validation | Not completed |

## Tested scope

Numerical direction/sign checks, explicit arm/value cells, endpoint-scoped rows, generated wrong-endpoint claims, repeated cross-section value conflicts, structure/drafting/review/FHIR-independent exports.

The GitHub workflows have been added or retained, but their remote execution has not been verified after these changes. Unit tests establish behavior on fixtures; they do not establish semantic or clinical correctness.

## NAT configuration

`nat validate --config_file configs/workflow.yml` passed with the installed toolkit. This checks configuration/schema validity and plugin discovery; it does not execute a live model workflow or verify the example model IDs.

## Small offline evaluation

The bundled synthetic study with scripted drafting/review produced 4 detections for 4 planted errors, no false alarms on its supplied correct-claim list, and 5 generated sentences without findings. Missing-section precision/recall were both 1.0 on this fixture. [Raw results](offline-evaluation.json). The scripted judge and small dataset do not establish clinical validity; cross-section matching only detects repeated statement templates, not arbitrary contradictory paraphrases.


## Workflow recording — 13 October 2026

The recording runs this repository’s source loading → ICH E3 structure screen → missing-section drafting → checking/revision → medical writer review → assembly workflow. The synthetic SYN-301 draft, CSV tables and synopsis are visible. Drafting and qualitative model reviews are scripted. Actual code detects missing sections and numerical errors, revises a planted generated count from 125 to 120, preserves the consent section as needing writer input, and records synthetic writer decisions. Findings in the original draft remain open; accepting proposed sections does not resolve them. The output is a revised draft and a review report, not a final clinical document.

The added optional Streamlit AppTest executes the repository pipeline and verifies the resulting output and review behavior. Install `.[demo,dev]` to include it. This does not validate hosted/self-hosted endpoints or domain correctness.

Validation for this change: full local suite **12 passed**. Ruff checks passed for the interface, fixtures and added regression test. MP4 decoding passed without errors. No live endpoint or domain validation was performed.
