import multiprocessing
import time
from io import BytesIO
from types import SimpleNamespace

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from gridlens.ingestion.adapters.bounded_http import ResponseTooLarge, run_isolated
from gridlens.ingestion.adapters.buying_chain_public import (
    MAX_TEXT,
    PublicAccessRestricted,
    PublicExtractionUnavailable,
    parse_document,
    retrieve,
)


def pdf_bytes(texts, *, encrypted=False):
    writer = PdfWriter()
    for text in texts:
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject({
            NameObject('/Type'): NameObject('/Font'),
            NameObject('/Subtype'): NameObject('/Type1'),
            NameObject('/BaseFont'): NameObject('/Helvetica'),
        })
        page[NameObject('/Resources')] = DictionaryObject({
            NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})
        })
        stream = DecodedStreamObject()
        stream.set_data(f'BT /F1 12 Tf 20 700 Td ({text}) Tj ET'.encode())
        page[NameObject('/Contents')] = writer._add_object(stream)
    if encrypted:
        writer.encrypt('secret')
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.mark.parametrize('tail', [
    'The Orion project was cancelled.',
    'This is an unsourced AI-generated summary.',
])
def test_long_page_never_admits_a_prefix_that_omits_adverse_context(tail):
    body = ('<article>The Orion project is under construction. ' + 'x' * MAX_TEXT + tail
            + '</article>').encode()
    with pytest.raises(ResponseTooLarge, match='30000'):
        parse_document('https://acme.com/project', body, 'text/html')


def test_pdf_keeps_every_page_and_location_without_invented_publication_date():
    document = parse_document('https://acme.com/project.pdf', pdf_bytes([
        'Orion project is under construction.', 'Orion project was cancelled.'
    ]), 'application/pdf')
    assert '[Page 1]' in document.text and '[Page 2]' in document.text
    assert 'cancelled' in document.text
    assert document.published_at is None
    assert document.extraction_location == 'PDF pages 1-2 (inline page markers)'


@pytest.mark.parametrize('texts', [[''] , ['Project update'] * 21, ['x' * (MAX_TEXT + 1)]])
def test_pdf_with_unreadable_or_out_of_bound_pages_is_rejected_whole(texts):
    with pytest.raises(ValueError):
        parse_document('https://acme.com/project.pdf', pdf_bytes(texts), 'application/pdf')


def test_encrypted_pdf_never_permits_fallback():
    with pytest.raises(PublicAccessRestricted):
        parse_document('https://acme.com/project.pdf', pdf_bytes(['Project'], encrypted=True),
                       'application/pdf')


def test_pdf_text_footer_does_not_certify_an_unreadable_image_page():
    writer = PdfWriter()
    writer.add_page(PdfReader(BytesIO(pdf_bytes(['Page 1']))).pages[0])
    image = DecodedStreamObject()
    image.set_data(b'undecoded scanned cancellation')
    image[NameObject('/Subtype')] = NameObject('/Image')
    writer.pages[0]['/Resources'][NameObject('/XObject')] = DictionaryObject({
        NameObject('/Scan'): writer._add_object(image)
    })
    output = BytesIO()
    writer.write(output)
    with pytest.raises(ValueError, match='image or form'):
        parse_document('https://acme.com/project.pdf', output.getvalue(), 'application/pdf')


def test_only_explicit_public_javascript_shell_permits_rendering_fallback():
    with pytest.raises(PublicExtractionUnavailable):
        parse_document('https://acme.com/project', b'<body>Enable JavaScript</body>', 'text/html')
    with pytest.raises(PublicAccessRestricted):
        parse_document('https://acme.com/project',
                       b'<title>Access denied</title><body>Enable JavaScript</body>', 'text/html')


@pytest.mark.parametrize('restriction', ['Sign in.', 'Verify you are human.', 'CAPTCHA'])
def test_body_access_controls_are_never_rendering_fallback(restriction):
    with pytest.raises(PublicAccessRestricted):
        parse_document('https://acme.com/project',
                       ('<title>Project</title><body>' + restriction
                        + '<noscript>Enable javascript</noscript></body>').encode(), 'text/html')


def test_body_siblings_and_footer_corrections_remain_in_admission_input():
    document = parse_document('https://acme.com/project',
                             b'<body><main>Orion construction is underway.</main>'
                             b'<p>Orion project was cancelled.</p>'
                             b'<footer>This is an AI-generated summary.</footer></body>',
                             'text/html')
    assert 'cancelled' in document.text
    assert 'AI-generated' in document.text


def test_title_adverse_suffix_is_not_silently_truncated():
    with pytest.raises(ResponseTooLarge, match='title'):
        parse_document('https://acme.com/project',
                       ('<title>' + 'x' * 500 + ' cancelled</title>'
                        + '<body>Orion project construction is underway.</body>').encode(),
                       'text/html')


def test_vector_painted_pdf_content_is_not_certified_by_text_footer():
    writer = PdfWriter()
    writer.add_page(PdfReader(BytesIO(pdf_bytes(['Page 1']))).pages[0])
    stream = DecodedStreamObject()
    stream.set_data(b'0 0 10 10 re f BT /F1 12 Tf 20 700 Td (Page 1) Tj ET')
    writer.pages[0][NameObject('/Contents')] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    with pytest.raises(ValueError, match='vector-painted'):
        parse_document('https://acme.com/project.pdf', output.getvalue(), 'application/pdf')


def test_stalled_operation_is_killed_at_shared_wall_clock_deadline():
    before = {child.pid for child in multiprocessing.active_children()}
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        run_isolated('time:sleep', (30,), {}, deadline=started + 0.35)
    assert time.monotonic() - started < 2
    assert {child.pid for child in multiprocessing.active_children()} == before


def test_isolated_result_and_safe_parser_error_round_trip():
    result = run_isolated('builtins:len', ([1, 2],), {}, deadline=time.monotonic() + 5)
    assert result == 2
    with pytest.raises(ResponseTooLarge):
        run_isolated('gridlens.ingestion.adapters.buying_chain_public:parse_document',
                     ('https://acme.com', b'x' * (MAX_TEXT + 1), 'text/plain'), {},
                     deadline=time.monotonic() + 5)


def test_public_reader_uses_hard_boundary_before_dns(monkeypatch):
    calls = []
    monkeypatch.setattr('gridlens.ingestion.adapters.buying_chain_public.run_isolated',
                        lambda *args, **kwargs: calls.append((args, kwargs)))
    retrieve('https://acme.com', deadline=123, max_bytes=100)
    assert calls[0][0][0].endswith(':_retrieve_direct')
    assert calls[0][1]['deadline'] == 123
    assert calls[0][0][2]['max_bytes'] == 100


def test_api_projection_requires_current_capture_for_public_supplement():
    from gridlens.api.app import _assessment_for_evidence
    from gridlens.ingestion.adapters.buying_chain_public import CAPTURE_VERSION

    observation = SimpleNamespace(source_id='research-public-example', content_hash='same')
    evidence = SimpleNamespace(id='id', content_hash='same')
    assessment = {'semantic_hash': 'same', 'evidence_hash': 'same', 'evidence': {'id': 'id'}}
    interpretation = SimpleNamespace(assessment=assessment)
    assert _assessment_for_evidence(interpretation, observation, evidence) is None
    assessment['acquisition_capture_version'] = CAPTURE_VERSION
    assert _assessment_for_evidence(interpretation, observation, evidence) == assessment
