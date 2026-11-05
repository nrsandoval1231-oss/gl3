"""Minimal pure-Python PDF writer for permit-document tests (text pages, no binaries)."""

from __future__ import annotations

BS = chr(92)


def _escape(text: str) -> str:
    return text.replace(BS, BS + BS).replace("(", BS + "(").replace(")", BS + ")")


def make_pdf(pages: list[list[str]]) -> bytes:
    """One Helvetica page per entry; each string is written as its own text line."""
    objects: list[bytes] = []

    def add(body: str | bytes) -> int:
        objects.append(body.encode("latin-1") if isinstance(body, str) else body)
        return len(objects)

    add("<< /Type /Catalog /Pages 2 0 R >>")
    add("PAGES")  # placeholder, replaced below
    font = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    kids: list[int] = []
    for lines in pages:
        content = ["BT", "/F1 10 Tf"]
        y = 760
        for line in lines:
            content.append(f"1 0 0 1 40 {y} Tm ({_escape(line)}) Tj")
            y -= 14
        content.append("ET")
        stream = "\n".join(content)
        content_id = add(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
        page_id = add(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font} 0 R >> >> /Contents {content_id} 0 R >>"
        )
        kids.append(page_id)
    objects[1] = (
        f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>"
    ).encode("latin-1")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(out)
