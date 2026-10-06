SYSTEM = (
    "You are an experienced regulatory medical writer working to ICH E3. You write neutral, factual text. "
    "You only state what the source tables and protocol synopsis support, and you cite the table rows (T#.R#) "
    "for every sentence that contains data. You never invent numbers, comparisons or conclusions."
)

MAP_HEADINGS = """Map each heading of a draft clinical study report to the ICH E3 section it corresponds to.
Use "none" if it does not correspond to any of the listed sections.

ICH E3 sections:
{e3}

Draft headings:
{headings}
"""

DRAFT = """Draft ICH E3 section {number} "{title}" for this clinical study report.

What the section should contain: {guidance}

Rules:
- One fact per sentence. Every sentence with a number cites the table rows it comes from in `citations`.
- Copy numbers exactly as in the tables (you may write n (%) as in the table). Do not compute new statistics.
- Report both treatment groups. No interpretation, no claims of superiority, safety or tolerability.
- If the section needs information that is not in the sources, list it in `gaps` instead of writing it.
{feedback}
Protocol synopsis:
{synopsis}

Source tables:
{tables}
"""

REVIEW = """You are the reviewer of a clinical study report. Check whether the statement is supported by the
source data. Answer:
- "supported": the data directly support the statement as worded
- "unsupported": the data do not contain the information (e.g. comparisons with treatments not studied)
- "overstated": the data exist but the wording goes further than they allow (e.g. "well tolerated" or
  "no safety signal" despite clear imbalances; "significant" without a test)
Give a short explanation that cites table rows (T#.R#) and, if not supported, a neutral rewrite.

Section: {section}
Statement: {sentence}

Protocol synopsis:
{synopsis}

Source tables:
{tables}
"""
