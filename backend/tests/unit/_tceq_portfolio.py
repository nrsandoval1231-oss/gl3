"""Pure-Python builders for synthetic TCEQ-style PDF portfolios and PI-1 workbooks."""

from __future__ import annotations

import io

from _permit_pdf import BS, make_pdf

COVER = ["If this page is the only one that appears, download the document and open it in Acrobat."]


def _lit(text: str) -> str:
    return "(" + text.replace(BS, BS + BS).replace("(", BS + "(").replace(")", BS + ")") + ")"


def make_portfolio(
    embedded: list[tuple[str, bytes]],
    *,
    declared: dict[str, int] | None = None,
    cover: list[str] | None = None,
) -> bytes:
    """One-page cover PDF whose catalog carries an /EmbeddedFiles name tree.

    ``declared`` overrides the /Params /Size of named files (a hostile declaration).
    """
    base = make_pdf([cover or COVER])
    # Append an incremental update: new objects plus a replacement catalog.
    text = base.decode("latin-1")
    size = int(text.split("/Size ")[1].split()[0].rstrip(">"))
    out = bytearray(base)
    offsets: dict[int, int] = {}
    next_id = size
    names: list[str] = []
    for name, content in embedded:
        stream_id, spec_id = next_id, next_id + 1
        next_id += 2
        offsets[stream_id] = len(out)
        declared_size = (declared or {}).get(name, len(content))
        out += (
            (
                f"{stream_id} 0 obj\n<< /Type /EmbeddedFile /Length {len(content)} "
                f"/Params << /Size {declared_size} >> >>\nstream\n"
            ).encode()
            + content
            + b"\nendstream\nendobj\n"
        )
        offsets[spec_id] = len(out)
        out += (
            f"{spec_id} 0 obj\n<< /Type /Filespec /F {_lit(name)} /UF {_lit(name)} "
            f"/EF << /F {stream_id} 0 R >> >>\nendobj\n"
        ).encode("latin-1", "replace")
        names.append(f"{_lit(name)} {spec_id} 0 R")
    catalog_id = 1
    offsets[catalog_id] = len(out)
    out += (
        f"1 0 obj\n<< /Type /Catalog /Pages 2 0 R /Names << /EmbeddedFiles << /Names "
        f"[{' '.join(names)}] >> >> >>\nendobj\n"
    ).encode("latin-1", "replace")
    xref = len(out)
    ids = sorted(offsets)
    out += b"xref\n"
    for object_id in ids:
        out += f"{object_id} 1\n{offsets[object_id]:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {next_id} /Root 1 0 R /Prev {text.split('startxref')[1].split()[0]} "
        f">>\nstartxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(out)


def pi1_workbook(
    units: list[tuple[str, str, str, str]],
    *,
    description: str | None = None,
) -> bytes:
    """Minimal PI-1 workbook: (FIN, EPN, source name, unit type) rows on the unit sheet."""
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.title = "Unit Types - Emission Rates"
    sheet["A10"] = "Action Requested (only 1 action per FIN)"
    sheet["C10"] = "Facility ID Number (FIN)"
    sheet["D10"] = "Emission Point Number (EPN)"
    sheet["E10"] = "Source Name"
    sheet["F10"] = "Pollutant"
    sheet["O10"] = "Unit Type (Used for reviewing BACT and Monitoring Requirements)"
    row = 11
    for fin, epn, name, unit_type in units:
        sheet[f"A{row}"], sheet[f"C{row}"] = "New/Modified", fin
        sheet[f"D{row}"], sheet[f"E{row}"], sheet[f"F{row}"] = epn, name, "NOx"
        sheet[f"F{row + 1}"], sheet[f"O{row + 1}"] = "CO", unit_type
        row += 2
    if description:
        book.create_sheet("General")["C5"] = description
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def electric_schedule_pdf(applicant: str = "Prairie Example LLC") -> bytes:
    """Inner composite PDF whose narrative states electric compressor motors."""
    return make_pdf(
        [
            ["Technical Review", "The facility will install three (3) 2,500-hp electric"],
            ["motor-driven compressors for inlet service at the plant site."],
        ]
    )


def pdf_from_pages(pages: list[list[str]]) -> bytes:
    return make_pdf(pages)
