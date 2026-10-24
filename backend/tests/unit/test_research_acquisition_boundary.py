import base64
import hashlib
import multiprocessing
import os
import pickle
import threading
import time
from io import BytesIO
from types import SimpleNamespace

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from gridlens.ingestion.adapters.bounded_http import (
    AcquisitionFailure,
    ResponseTooLarge,
    _isolated_result_limit,
    _send_bounded_result,
    run_isolated,
)
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
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
        )
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 20 700 Td ({text}) Tj ET".encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    if encrypted:
        writer.encrypt("secret")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.mark.parametrize(
    "tail",
    [
        "The Orion project was cancelled.",
        "This is an unsourced AI-generated summary.",
    ],
)
def test_long_page_never_admits_a_prefix_that_omits_adverse_context(tail):
    body = (
        "<article>The Orion project is under construction. " + "x" * MAX_TEXT + tail + "</article>"
    ).encode()
    with pytest.raises(ResponseTooLarge, match="30000"):
        parse_document("https://acme.com/project", body, "text/html")


def test_pdf_keeps_every_page_and_location_without_invented_publication_date():
    document = parse_document(
        "https://acme.com/project.pdf",
        pdf_bytes(["Orion project is under construction.", "Orion project was cancelled."]),
        "application/pdf",
    )
    assert "[Page 1]" in document.text and "[Page 2]" in document.text
    assert "cancelled" in document.text
    assert document.published_at is None
    assert document.extraction_location == "PDF pages 1-2 (inline page markers)"


@pytest.mark.parametrize("texts", [[""], ["Project update"] * 21, ["x" * (MAX_TEXT + 1)]])
def test_pdf_with_unreadable_or_out_of_bound_pages_is_rejected_whole(texts):
    with pytest.raises(ValueError):
        parse_document("https://acme.com/project.pdf", pdf_bytes(texts), "application/pdf")


def test_encrypted_pdf_never_permits_fallback():
    with pytest.raises(PublicAccessRestricted):
        parse_document(
            "https://acme.com/project.pdf",
            pdf_bytes(["Project"], encrypted=True),
            "application/pdf",
        )


def test_pdf_text_footer_does_not_certify_an_unreadable_image_page():
    writer = PdfWriter()
    writer.add_page(PdfReader(BytesIO(pdf_bytes(["Page 1"]))).pages[0])
    image = DecodedStreamObject()
    image.set_data(b"undecoded scanned cancellation")
    image[NameObject("/Subtype")] = NameObject("/Image")
    writer.pages[0]["/Resources"][NameObject("/XObject")] = DictionaryObject(
        {NameObject("/Scan"): writer._add_object(image)}
    )
    output = BytesIO()
    writer.write(output)
    with pytest.raises(ValueError, match="image or form"):
        parse_document("https://acme.com/project.pdf", output.getvalue(), "application/pdf")


def test_only_explicit_public_javascript_shell_permits_rendering_fallback():
    with pytest.raises(PublicExtractionUnavailable):
        parse_document("https://acme.com/project", b"<body>Enable JavaScript</body>", "text/html")
    with pytest.raises(PublicAccessRestricted):
        parse_document(
            "https://acme.com/project",
            b"<title>Access denied</title><body>Enable JavaScript</body>",
            "text/html",
        )


@pytest.mark.parametrize("restriction", ["Sign in.", "Verify you are human.", "CAPTCHA"])
def test_body_access_controls_are_never_rendering_fallback(restriction):
    with pytest.raises(PublicAccessRestricted):
        parse_document(
            "https://acme.com/project",
            (
                "<title>Project</title><body>"
                + restriction
                + "<noscript>Enable javascript</noscript></body>"
            ).encode(),
            "text/html",
        )


def test_body_siblings_and_footer_corrections_remain_in_admission_input():
    document = parse_document(
        "https://acme.com/project",
        b"<body><main>Orion construction is underway.</main>"
        b"<p>Orion project was cancelled.</p>"
        b"<footer>This is an AI-generated summary.</footer></body>",
        "text/html",
    )
    assert "cancelled" in document.text
    assert "AI-generated" in document.text


def test_title_adverse_suffix_is_not_silently_truncated():
    with pytest.raises(ResponseTooLarge, match="title"):
        parse_document(
            "https://acme.com/project",
            (
                "<title>"
                + "x" * 500
                + " cancelled</title>"
                + "<body>Orion project construction is underway.</body>"
            ).encode(),
            "text/html",
        )


def test_vector_painted_pdf_content_is_not_certified_by_text_footer():
    writer = PdfWriter()
    writer.add_page(PdfReader(BytesIO(pdf_bytes(["Page 1"]))).pages[0])
    stream = DecodedStreamObject()
    stream.set_data(b"0 0 10 10 re f BT /F1 12 Tf 20 700 Td (Page 1) Tj ET")
    writer.pages[0][NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    with pytest.raises(ValueError, match="vector-painted"):
        parse_document("https://acme.com/project.pdf", output.getvalue(), "application/pdf")


def test_stalled_operation_is_killed_at_shared_wall_clock_deadline():
    before = {child.pid for child in multiprocessing.active_children()}
    receiver_threads = {
        thread.ident
        for thread in threading.enumerate()
        if thread.name == "gridlens-acquisition-ipc-receiver"
    }
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        run_isolated("time:sleep", (30,), {}, deadline=started + 0.35)
    assert time.monotonic() - started < 2
    assert {child.pid for child in multiprocessing.active_children()} == before
    assert not any(
        thread.name == "gridlens-acquisition-ipc-receiver" and thread.ident not in receiver_threads
        for thread in threading.enumerate()
    )


def test_isolated_result_and_safe_parser_error_round_trip():
    result = run_isolated("builtins:len", ([1, 2],), {}, deadline=time.monotonic() + 5)
    assert result == 2
    with pytest.raises(ResponseTooLarge):
        run_isolated(
            "gridlens.ingestion.adapters.buying_chain_public:parse_document",
            ("https://acme.com", b"x" * (MAX_TEXT + 1), "text/plain"),
            {},
            deadline=time.monotonic() + 5,
        )


def test_isolated_result_size_is_bounded_before_parent_unpickles():
    from gridlens.ingestion.adapters.bounded_http import MAX_ISOLATED_RESULT_BYTES

    with pytest.raises(AcquisitionFailure, match="acquisition_result_too_large"):
        run_isolated(
            "builtins:bytes",
            (MAX_ISOLATED_RESULT_BYTES + 1,),
            {},
            deadline=time.monotonic() + 5,
        )


def test_rrc_ipc_allowance_requires_exact_source_and_retrieval_method():
    from gridlens.ingestion.adapters.bounded_http import (
        _RRC_DRILLING_RESULT_BYTES,
        MAX_ISOLATED_RESULT_BYTES,
    )

    path = "gridlens.ingestion.adapters:_retrieve_source_direct"
    source = {
        "id": "texas-rrc-drilling-permits",
        "retrieval_method": "rrc-drilling-permits",
    }
    assert _isolated_result_limit(path, (source,)) == _RRC_DRILLING_RESULT_BYTES
    assert _isolated_result_limit(path, ({**source, "id": "spoofed"},)) == MAX_ISOLATED_RESULT_BYTES
    assert _isolated_result_limit(
        path, ({**source, "retrieval_method": "rrc-flare-exceptions"},)
    ) == MAX_ISOLATED_RESULT_BYTES
    assert _isolated_result_limit("builtins:bytes", (source,)) == MAX_ISOLATED_RESULT_BYTES
    assert (
        _isolated_result_limit(path, ("texas-rrc-drilling-permits",))
        == MAX_ISOLATED_RESULT_BYTES
    )


def test_rrc_ipc_bound_round_trips_large_exact_evidence_over_pipe():
    from gridlens.ingestion.adapters.bounded_http import (
        _RRC_DRILLING_RESULT_BYTES,
        MAX_ISOLATED_RESULT_BYTES,
    )

    source = {
        "id": "texas-rrc-drilling-permits",
        "retrieval_method": "rrc-drilling-permits",
    }
    limit = _isolated_result_limit(
        "gridlens.ingestion.adapters:_retrieve_source_direct", (source,)
    )
    raw = b"RRC fixture evidence\x00" * 350_000
    digest = hashlib.sha256(raw).hexdigest()
    record = {
        "source_id": source["id"],
        "retrieval_method": source["retrieval_method"],
        "provenance": {"filename": "daf420.dat", "ordinal": 7},
        "raw_b64": base64.b64encode(raw).decode("ascii"),
        "raw_sha256": digest,
    }
    assert len(pickle.dumps((True, [record]), protocol=5)) > MAX_ISOLATED_RESULT_BYTES
    assert limit == _RRC_DRILLING_RESULT_BYTES

    receiver, sender = multiprocessing.get_context("spawn").Pipe(duplex=False)
    send_errors = []

    def send_result():
        try:
            _send_bounded_result(
                sender,
                True,
                [record],
                function_path="gridlens.ingestion.adapters:_retrieve_source_direct",
                args=(source,),
            )
        except BaseException as exc:
            send_errors.append(exc)

    sender_thread = threading.Thread(target=send_result)
    sender_thread.start()
    received = receiver.recv_bytes(limit)
    sender_thread.join(timeout=5)
    receiver.close()
    sender.close()
    assert not sender_thread.is_alive()
    assert not send_errors
    success, rows = pickle.loads(received)
    assert success is True
    assert len(rows) == 1
    assert rows[0]["source_id"] == source["id"]
    assert rows[0]["retrieval_method"] == source["retrieval_method"]
    assert rows[0]["provenance"] == {"filename": "daf420.dat", "ordinal": 7}
    restored = base64.b64decode(rows[0]["raw_b64"], validate=True)
    assert restored == raw
    assert rows[0]["raw_sha256"] == hashlib.sha256(restored).hexdigest() == digest


def test_rrc_ipc_over_limit_is_replaced_with_safe_failure_payload():
    from gridlens.ingestion.adapters.bounded_http import _RRC_DRILLING_RESULT_BYTES

    receiver, sender = multiprocessing.get_context("spawn").Pipe(duplex=False)
    _send_bounded_result(
        sender,
        True,
        b"x" * (_RRC_DRILLING_RESULT_BYTES + 1),
        function_path="gridlens.ingestion.adapters:_retrieve_source_direct",
        args=({
            "id": "texas-rrc-drilling-permits",
            "retrieval_method": "rrc-drilling-permits",
        },),
    )
    message = receiver.recv_bytes(_RRC_DRILLING_RESULT_BYTES)
    receiver.close()
    sender.close()
    success, error = pickle.loads(message)
    assert success is False
    assert isinstance(error, AcquisitionFailure)
    assert str(error) == "acquisition_result_too_large"


def test_parent_pipe_rejects_payload_over_selected_rrc_cap_before_unpickle():
    from gridlens.ingestion.adapters.bounded_http import _RRC_DRILLING_RESULT_BYTES

    source = {
        "id": "texas-rrc-drilling-permits",
        "retrieval_method": "rrc-drilling-permits",
    }
    limit = _isolated_result_limit(
        "gridlens.ingestion.adapters:_retrieve_source_direct", (source,)
    )
    receiver, sender = multiprocessing.get_context("spawn").Pipe(duplex=False)
    send_error = []

    def send_oversized_payload():
        try:
            sender.send_bytes(b"x" * (limit + 1))
        except BaseException as exc:
            send_error.append(exc)

    sender_thread = threading.Thread(target=send_oversized_payload)
    sender_thread.start()
    with pytest.raises(OSError):
        receiver.recv_bytes(limit)
    sender_thread.join(timeout=5)
    receiver.close()
    sender.close()
    assert not sender_thread.is_alive()
    assert not send_error or isinstance(send_error[0], BrokenPipeError)
    assert limit == _RRC_DRILLING_RESULT_BYTES


def test_isolated_rss_snapshot_preserves_validator_metadata():
    snapshot = run_isolated(
        "gridlens.ingestion.adapters.publisher_rss:RSSSnapshot",
        ([{"document_number": "fixture-rss-item"}],),
        {
            "not_modified": True,
            "etag": '"fixture-v1"',
            "last_modified": "Sun, 18 Oct 2026 00:00:00 GMT",
        },
        deadline=time.monotonic() + 5,
    )
    from gridlens.ingestion.adapters.publisher_rss import RSSSnapshot

    assert isinstance(snapshot, RSSSnapshot)
    assert snapshot == [{"document_number": "fixture-rss-item"}]
    assert snapshot.not_modified is True
    assert snapshot.etag == '"fixture-v1"'
    assert snapshot.last_modified == "Sun, 18 Oct 2026 00:00:00 GMT"


def test_windows_job_object_reports_the_installed_512_mib_limit():
    from gridlens.ingestion.adapters import bounded_http

    if os.name == "nt":
        result = run_isolated(
            "gridlens.ingestion.adapters.bounded_http:_query_windows_job_memory_limit",
            (),
            {},
            deadline=time.monotonic() + 5,
        )
        assert result == 512 * 1024**2
        print(f"Windows Job Object process memory limit: {result} bytes")
    else:
        assert bounded_http._ACQUISITION_MEMORY_LIMIT == 512 * 1024**2


def test_windows_job_limit_configuration_checks_native_api_results(monkeypatch):
    from types import SimpleNamespace

    from gridlens.ingestion.adapters import bounded_http

    class ApiCall:
        def __init__(self, result):
            self.result = result
            self.calls = []

        def __call__(self, *args):
            self.calls.append(args)
            return self.result

    kernel32 = SimpleNamespace(
        CreateJobObjectW=ApiCall(202),
        SetInformationJobObject=ApiCall(1),
        GetCurrentProcess=ApiCall(101),
        AssignProcessToJobObject=ApiCall(1),
    )

    def fake_loader(_name, *, use_last_error):
        assert use_last_error
        return kernel32

    monkeypatch.setattr(bounded_http.ctypes, "WinDLL", fake_loader, raising=False)
    bounded_http._install_windows_memory_limit()
    assert kernel32.CreateJobObjectW.argtypes == [
        bounded_http.ctypes.c_void_p,
        bounded_http.ctypes.c_wchar_p,
    ]
    information = kernel32.SetInformationJobObject.calls[0][2]._obj
    assert information.BasicLimitInformation.LimitFlags == bounded_http._WINDOWS_JOB_LIMIT
    assert information.ProcessMemoryLimit == 512 * 1024**2

    kernel32.SetInformationJobObject = ApiCall(0)
    with pytest.raises(AcquisitionFailure, match="windows_job_limit_setup_failed"):
        bounded_http._install_windows_memory_limit()
    kernel32.SetInformationJobObject = ApiCall(1)
    kernel32.GetCurrentProcess = ApiCall(None)
    with pytest.raises(AcquisitionFailure, match="windows_current_process_failed"):
        bounded_http._install_windows_memory_limit()
    kernel32.GetCurrentProcess = ApiCall(101)
    kernel32.AssignProcessToJobObject = ApiCall(0)
    with pytest.raises(AcquisitionFailure, match="windows_job_assignment_failed"):
        bounded_http._install_windows_memory_limit()
    kernel32.CreateJobObjectW = ApiCall(None)
    with pytest.raises(AcquisitionFailure, match="windows_job_create_failed"):
        bounded_http._install_windows_memory_limit()


def test_memory_guard_failure_stops_before_acquisition_target(monkeypatch):
    from gridlens.ingestion.adapters import bounded_http

    class Connection:
        messages = []

        def send_bytes(self, value):
            self.messages.append(value)

        def close(self):
            pass

    def fail_guard():
        raise AcquisitionFailure("windows_job_assignment_failed")

    def forbid_import(*_args, **_kwargs):
        pytest.fail("The acquisition target must not load before guard setup")

    monkeypatch.setattr(bounded_http, "_configure_memory_limit", fail_guard)
    monkeypatch.setattr(bounded_http.importlib, "import_module", forbid_import)
    connection = Connection()
    bounded_http._isolated_entry(connection, "builtins:len", ([1],), {})
    assert len(connection.messages) == 1
    success, error = pickle.loads(connection.messages[0])
    assert not success
    assert isinstance(error, AcquisitionFailure)
    assert str(error) == "windows_job_assignment_failed"


def test_public_reader_uses_hard_boundary_before_dns(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "gridlens.ingestion.adapters.buying_chain_public.run_isolated",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    retrieve("https://acme.com", deadline=123, max_bytes=100)
    assert calls[0][0][0].endswith(":_retrieve_direct")
    assert calls[0][1]["deadline"] == 123
    assert calls[0][0][2]["max_bytes"] == 100


def test_api_projection_requires_current_capture_for_public_supplement():
    from gridlens.api.app import _assessment_for_evidence
    from gridlens.ingestion.adapters.buying_chain_public import CAPTURE_VERSION

    observation = SimpleNamespace(source_id="research-public-example", content_hash="same")
    evidence = SimpleNamespace(id="id", content_hash="same")
    assessment = {"semantic_hash": "same", "evidence_hash": "same", "evidence": {"id": "id"}}
    interpretation = SimpleNamespace(assessment=assessment)
    assert _assessment_for_evidence(interpretation, observation, evidence) is None
    assessment["acquisition_capture_version"] = CAPTURE_VERSION
    assert _assessment_for_evidence(interpretation, observation, evidence) == assessment
