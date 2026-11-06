import base64
import hashlib
import io
import struct

import pytest
from pypdf import PdfWriter

from gridlens.ingestion.adapters.govinfo_scan import MAX_PDF_PAGES
from gridlens.integrations.intelligence_provider import ocr_request_payload
from gridlens.intelligence.ocr_public_pages import (
    PageApprovalRequired,
    approved_source_pages,
    page_approval_key,
    render_page_images,
    require_page_approval,
)

DOC_HASH = "a" * 64


def _pdf(*, encrypted=False):
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Title": "incidental private title"})
    writer.add_attachment("incidental.txt", b"incidental private attachment")
    if encrypted:
        writer.encrypt(user_password="", owner_password="owner")
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def _png_chunks(image_bytes):
    position = 8
    chunks = []
    while position < len(image_bytes):
        length = struct.unpack(">I", image_bytes[position : position + 4])[0]
        chunks.append(image_bytes[position + 4 : position + 8].decode("ascii"))
        position += 12 + length
    return chunks


def test_renderer_produces_approved_pixel_only_image_and_provider_request():
    rendered = render_page_images(_pdf(), local_pages=[1], source_pages=[7])
    png = base64.b64decode(rendered[0]["image_base64"], validate=True)
    assert rendered[0]["source_page"] == 7
    assert rendered[0]["width"] == 612 and rendered[0]["height"] == 792
    assert rendered[0]["pixel_sha256"] == hashlib.sha256(png).hexdigest()
    assert set(_png_chunks(png)) <= {"IHDR", "IDAT", "IEND"}
    assert b"incidental private" not in png

    approval = page_approval_key(DOC_HASH, 7, rendered[0]["pixel_sha256"])
    require_page_approval(DOC_HASH, rendered, approval)
    request = ocr_request_payload(
        model="gpt-6.1-sol",
        page_images=rendered,
        detail="low",
        max_output_tokens=1000,
    )
    serialized = str(request)
    assert request["service_tier"] == "default"
    assert request["prompt_cache_options"] == {"ttl": "30m"}
    assert [part["type"] for part in request["input"][0]["content"]] == [
        "input_text",
        "input_image",
    ]
    assert "input_file" not in serialized and "application/pdf" not in serialized
    assert "incidental private" not in serialized


def test_unreviewed_render_is_rejected_and_empty_approval_is_default_off():
    rendered = render_page_images(_pdf(), local_pages=[1], source_pages=[1])
    with pytest.raises(PageApprovalRequired):
        require_page_approval(DOC_HASH, rendered, "")
    with pytest.raises(PageApprovalRequired):
        require_page_approval(DOC_HASH, rendered, "b" * 64 + ":1:" + "c" * 64)


def test_page_selection_uses_exact_approved_page_before_document_limit():
    render = render_page_images(_pdf(), local_pages=[1], source_pages=[392])[0]
    approval = page_approval_key(DOC_HASH, 392, render["pixel_sha256"])
    assert approved_source_pages(DOC_HASH, [30, 392, 435], approval) == [392]
    assert approved_source_pages(DOC_HASH, [30, 435], approval) == []


def test_renderer_rejects_empty_user_password_encrypted_pdf():
    with pytest.raises(ValueError):
        render_page_images(_pdf(encrypted=True), local_pages=[1], source_pages=[1])


def test_renderer_keeps_five_page_request_bound():
    writer = PdfWriter()
    for _ in range(MAX_PDF_PAGES + 1):
        writer.add_blank_page(width=612, height=792)
    output = io.BytesIO()
    writer.write(output)
    with pytest.raises(ValueError):
        render_page_images(
            output.getvalue(),
            local_pages=list(range(1, MAX_PDF_PAGES + 2)),
            source_pages=list(range(1, MAX_PDF_PAGES + 2)),
        )
