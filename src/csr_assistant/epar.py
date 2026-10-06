"""Use public EMA European Public Assessment Reports (EPARs) as realistic test material.

An EPAR is the regulator's assessment, not a CSR, but its clinical efficacy and safety chapters contain
exactly the kind of narrative-plus-tables that a CSR has. This module extracts the text and tables of a
page range so the reviewer can check every narrative claim against the tables printed in the same report.

Find EPARs at https://www.ema.europa.eu/en/medicines (search a medicine, tab "Assessment history", the
"Public assessment report" PDF). Download the PDF yourself and pass the file path.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path


def extract(pdf_path: str | Path, pages: str, out_dir: str | Path) -> Path:
    """Write <out_dir>/draft_csr.md (narrative as one results section) and <out_dir>/tables/*.csv."""
    try:
        import pdfplumber
    except ImportError as err:  # pragma: no cover
        raise RuntimeError("pip install -e '.[pdf]'") from err
    first, last = (int(x) for x in pages.split("-")) if "-" in pages else (int(pages), int(pages))
    out = Path(out_dir)
    (out / "tables").mkdir(parents=True, exist_ok=True)
    text_parts, n_tables = [], 0
    with pdfplumber.open(str(pdf_path)) as pdf:
        for pno in range(first, min(last, len(pdf.pages)) + 1):
            page = pdf.pages[pno - 1]
            tables = page.find_tables()
            for t in tables:
                rows = [[(c or "").replace("\n", " ").strip() for c in row] for row in t.extract()]
                rows = [r for r in rows if any(r)]
                if len(rows) < 2:
                    continue
                n_tables += 1
                with (out / "tables" / f"p{pno:03d}_table{n_tables:02d}.csv").open("w", newline="") as fh:
                    fh.write(f"# title: EPAR page {pno} table {n_tables}\n")
                    csv.writer(fh).writerows(rows)
            # Text outside the table areas is the narrative.
            body = page
            for t in tables:
                body = body.outside_bbox(t.bbox)
            text_parts.append(body.extract_text() or "")
    narrative = re.sub(r"-\n(\w)", r"\1", "\n".join(text_parts))  # undo hyphenation
    narrative = re.sub(r"\n(?!\n)", " ", narrative)
    (out / "draft_csr.md").write_text(
        f"# 11 Efficacy and safety narrative (EPAR pages {pages})\n\n{narrative.strip()}\n", encoding="utf-8"
    )
    return out
