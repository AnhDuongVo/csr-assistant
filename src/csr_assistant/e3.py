"""ICH E3 clinical study report structure as data.

Section numbers and titles follow ICH E3 "Structure and Content of Clinical Study Reports" (EMA step 5 /
CPMP/ICH/137/95). The `guidance` lines are short paraphrases written for this tool, not guideline text;
always check the guideline itself: https://www.ema.europa.eu/en/documents/scientific-guideline/ich-e-3-structure-and-content-clinical-study-reports-step-5_en.pdf

`tables` lists the kinds of source tables a section can be drafted from. Sections with no tables (ethics,
investigators, ...) are never drafted by the model: the tool lists what information is missing instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class E3Section:
    number: str
    title: str
    guidance: str = ""
    tables: tuple[str, ...] = ()
    aliases: tuple[str, ...] = field(default=())

    @property
    def level(self) -> int:
        return self.number.count(".") + 1

    @property
    def required(self) -> bool:
        """Top-level sections and their first-level subsections are checked for presence."""
        return self.level <= 2


SECTIONS: list[E3Section] = [
    E3Section(
        "1",
        "Title Page",
        "Study title, product, indication, design, sponsor, protocol id, phase, dates, GCP statement.",
    ),
    E3Section("2", "Synopsis", "Brief summary of the whole study with key numbers.", aliases=("summary",)),
    E3Section(
        "3", "Table of Contents for the Individual Clinical Study Report", aliases=("table of contents", "contents")
    ),
    E3Section("4", "List of Abbreviations and Definition of Terms", aliases=("abbreviations",)),
    E3Section("5", "Ethics"),
    E3Section(
        "5.1", "Independent Ethics Committee (IEC) or Institutional Review Board (IRB)", aliases=("ethics committee",)
    ),
    E3Section(
        "5.2",
        "Ethical Conduct of the Study",
        "Confirmation of conduct according to the Declaration of Helsinki and GCP.",
    ),
    E3Section(
        "5.3",
        "Patient Information and Consent",
        "How and when informed consent was obtained; sample information sheet in an appendix.",
        aliases=("informed consent", "consent"),
    ),
    E3Section("6", "Investigators and Study Administrative Structure"),
    E3Section("7", "Introduction"),
    E3Section("8", "Study Objectives"),
    E3Section("9", "Investigational Plan"),
    E3Section("9.1", "Overall Study Design and Plan - Description", aliases=("study design",)),
    E3Section("9.2", "Discussion of Study Design, including the Choice of Control Groups"),
    E3Section("9.3", "Selection of Study Population", aliases=("study population",)),
    E3Section("9.4", "Treatments"),
    E3Section("9.5", "Efficacy and Safety Variables"),
    E3Section("9.6", "Data Quality Assurance"),
    E3Section(
        "9.7",
        "Statistical Methods Planned in the Protocol and Determination of Sample Size",
        aliases=("statistical methods",),
    ),
    E3Section("9.7.1", "Statistical and Analytical Plans"),
    E3Section("9.7.2", "Determination of Sample Size", aliases=("sample size",)),
    E3Section("9.8", "Changes in the Conduct of the Study or Planned Analyses"),
    E3Section("10", "Study Patients"),
    E3Section(
        "10.1",
        "Disposition of Patients",
        "Numbers randomised, treated, completed and discontinued per group, with reasons for discontinuation.",
        tables=("disposition",),
        aliases=("patient disposition", "disposition"),
    ),
    E3Section("10.2", "Protocol Deviations"),
    E3Section("11", "Efficacy Evaluation"),
    E3Section("11.1", "Data Sets Analysed", aliases=("analysis sets", "analysis populations")),
    E3Section(
        "11.2",
        "Demographic and Other Baseline Characteristics",
        "Baseline demographics and disease characteristics per group.",
        tables=("demographics",),
        aliases=("baseline characteristics", "demographics"),
    ),
    E3Section("11.3", "Measurements of Treatment Compliance"),
    E3Section("11.4", "Efficacy Results and Tabulations of Individual Patient Data", tables=("efficacy",)),
    E3Section(
        "11.4.1",
        "Analysis of Efficacy",
        "Primary endpoint first (estimate, confidence interval, p-value), then secondary endpoints.",
        tables=("efficacy",),
        aliases=("efficacy results", "primary endpoint"),
    ),
    E3Section("11.4.7", "Efficacy Conclusions", tables=("efficacy",)),
    E3Section("12", "Safety Evaluation"),
    E3Section(
        "12.1",
        "Extent of Exposure",
        "Duration of exposure and patient-years per group.",
        tables=("exposure",),
        aliases=("exposure",),
    ),
    E3Section("12.2", "Adverse Events (AEs)", tables=("adverse_events",), aliases=("adverse events",)),
    E3Section(
        "12.2.1",
        "Brief Summary of Adverse Events",
        "Overall incidence of adverse events, serious adverse events, discontinuations due to AEs and deaths, "
        "then the most common events, per group, without interpretation beyond the data.",
        tables=("adverse_events",),
    ),
    E3Section(
        "12.3", "Deaths, Other Serious Adverse Events, and Other Significant Adverse Events", tables=("adverse_events",)
    ),
    E3Section("12.4", "Clinical Laboratory Evaluation"),
    E3Section("12.5", "Vital Signs, Physical Findings, and Other Observations Related to Safety"),
    E3Section("12.6", "Safety Conclusions", tables=("adverse_events",)),
    E3Section("13", "Discussion and Overall Conclusions"),
    E3Section("14", "Tables, Figures and Graphs Referred to but not Included in the Text"),
    E3Section("15", "Reference List"),
    E3Section("16", "Appendices"),
]

BY_NUMBER = {s.number: s for s in SECTIONS}
RESULTS_SECTIONS = ("2", "10", "11", "12", "13")  # where factual claims about data live


def number_key(number: str) -> tuple[int, ...]:
    return tuple(int(p) for p in number.split(".") if p.isdigit())


def parent(number: str) -> str | None:
    return number.rsplit(".", 1)[0] if "." in number else None
