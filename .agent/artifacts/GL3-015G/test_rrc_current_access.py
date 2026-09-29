from __future__ import annotations

import hashlib
import json

import httpx
import pytest

from bounded_rrc_http import bounded_request
import replay_current_compat
from rrc_current_access import (
    FOLDER_URL,
    GO_DRIVE,
    AccessError,
    ListingSelection,
    allowlisted,
    download_post,
    parse_index,
    parse_listing,
    selected_view_state,
    selection_post,
    validate_attachment,
    validate_jsf_partial,
    validate_response,
)
from verify_rrc_compat import verify_snapshot


def _index(*, duplicate: bool = False) -> bytes:
    links = (
        f'<tr><td>Drilling Permit Master and Trailer - Daily File</td>'
        f'<td><a href="{FOLDER_URL}">ASCII Format</a></td></tr>'
    )
    return ("<html><body><table>" + links + (links if duplicate else "") + "</table></body></html>").encode()


def _listing(*, filename: str = "daf420.dat", duplicate: bool = False, view_state: str = "fresh") -> bytes:
    links = (
        f'<tr data-ri="0" data-rk="8187"><td class="NameColumn">'
        f'<a href="#">{filename}</a></td><td class="ModifiedOnColumn">9/29/26 1:00 AM</td>'
        f'<td class="SizeColumn">2.28 MB</td></tr>'
    )
    if duplicate:
        links += links.replace('data-rk="8187"', 'data-rk="8188"')
    return f'''<html><head><title>RRC Web Client - GoDrive</title></head><body>
    <form id="fileList"><input type="hidden" name="javax.faces.ViewState" value="{view_state}"/>
    <input type="hidden" name="fileTable_selection" value=""/><table>{links}</table></form>
    <form id="download" action="/webclient/godrive/PublicGoDrive.xhtml">
    <input type="hidden" name="j_id_3e_SUBMIT" value="1"/>
    <input type="hidden" name="javax.faces.ViewState" value="{view_state}"/>
    <button name="j_id_3f:j_id_3f">Download</button></form></body></html>'''.encode()


def _valid_snapshot() -> bytes:
    root = bytearray(b" " * 212)
    root[0:2], root[2:9], root[9:11] = b"01", b"0918584", b"99"
    root[11:14], root[58:66], root[100:101] = b"001", b"20260910", b"A"
    root[112:119], root[119:127] = b"0918584", b"20260914"
    permit = bytearray(b" " * 510)
    permit[0:2], permit[2:9], permit[9:11] = b"02", b"0918584", b"99"
    permit[11:14], permit[121:129], permit[129:137] = b"001", b"20260910", b"20260914"
    permit[137:161], permit[502:510] = b"00000000" * 3, b"00132879"
    return bytes(root) + b"\r\n" + bytes(permit) + b"\r\n"


def test_index_accepts_only_one_exact_official_daily_link():
    assert parse_index(_index()) == FOLDER_URL
    with pytest.raises(AccessError, match="matching daily-folder links"):
        parse_index(_index(duplicate=True))


def test_allowlist_is_exact_https_host_and_path():
    assert allowlisted(FOLDER_URL)
    assert allowlisted(GO_DRIVE)
    assert not allowlisted(FOLDER_URL.replace("https:", "http:"))
    assert not allowlisted(FOLDER_URL + "?next=bad")
    assert not allowlisted("https://evil.example/webclient/godrive/PublicGoDrive.xhtml")
    assert not allowlisted("https://user@mft.rrc.texas.gov/link/" + "x")


def test_listing_requires_unique_row_zero_and_same_session_state():
    parsed = parse_listing(_listing())
    assert parsed == ListingSelection("8187", "fresh", "9/29/26 1:00 AM", "2.28 MB")
    with pytest.raises(AccessError, match="2 exact"):
        parse_listing(_listing(duplicate=True))
    with pytest.raises(AccessError, match="0 exact"):
        parse_listing(_listing(filename="another.dat"))
    with pytest.raises(AccessError, match="ViewState"):
        parse_listing(_listing(view_state=""))


def test_login_and_non_html_jsf_errors_are_not_listings():
    with pytest.raises(AccessError, match="not an HTML listing"):
        parse_listing(b"<?xml version='1.0'?><partial-response><error/></partial-response>")
    login = b"<html><head><title>Login</title></head><form id='user-login-form'></form></html>"
    with pytest.raises(AccessError, match="title"):
        parse_listing(login)


def test_selection_uses_listing_viewstate_and_row_key_and_updates_state():
    parsed = parse_listing(_listing())
    post = selection_post(parsed)
    assert post["fileTable_selection"] == "8187"
    assert post["javax.faces.ViewState"] == "fresh"
    partial = b'<partial-response><changes><update id="j_id__v_0:javax.faces.ViewState:4"><![CDATA[new-state]]></update></changes></partial-response>'
    assert selected_view_state(partial, "fresh") == "new-state"
    with pytest.raises(AccessError, match="error partial"):
        validate_jsf_partial(200, {"content-type": "text/xml"}, GO_DRIVE, b"<partial-response><error/></partial-response>")
    with pytest.raises(AccessError, match="redirect"):
        validate_jsf_partial(302, {"location": "https://evil.example"}, GO_DRIVE, b"")
    with pytest.raises(AccessError, match="valid partial"):
        selected_view_state(b"<partial-response><error/></partial-response>", "fresh")


def test_download_form_reuses_state_and_only_attachment_can_be_accepted():
    body = _listing()
    form = download_post(body, "new-state")
    assert form["javax.faces.ViewState"] == "new-state"
    assert form["j_id_3f:j_id_3f"] == "j_id_3f:j_id_3f"
    validate_attachment(200, {"content-type": "application/force-download"}, GO_DRIVE, b"01data")
    for status, headers, payload, text in (
        (302, {"location": "https://evil.example"}, b"", "redirect"),
        (200, {"content-type": "text/html"}, b"<html>login</html>", "HTML/XML"),
        (200, {"content-type": "text/xml"}, b"<partial-response/>", "HTML/XML"),
        (200, {"content-type": "text/plain"}, b"error", "attachment"),
    ):
        with pytest.raises(AccessError, match=text):
            validate_attachment(status, headers, GO_DRIVE, payload)


def test_http_redirect_is_not_followed_and_oversize_is_bounded():
    calls = []

    def redirect(request: httpx.Request) -> httpx.Response:
        calls.append(request.url)
        return httpx.Response(302, headers={"location": "https://evil.example/"})

    client = httpx.Client(transport=httpx.MockTransport(redirect), follow_redirects=False)
    status, headers, body, _ = bounded_request(client, "GET", FOLDER_URL)
    assert len(calls) == 1
    with pytest.raises(AccessError, match="redirect"):
        validate_response(status=status, headers=headers, url=FOLDER_URL, body=body, max_bytes=5)

    large = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"x" * 5_100_000))
    )
    status, headers, body, metadata = bounded_request(large, "GET", FOLDER_URL)
    assert len(body) == 5_000_001
    assert metadata["body_bytes_read"] == 5_000_001
    with pytest.raises(AccessError, match="byte limit"):
        validate_response(status=status, headers=headers, url=FOLDER_URL, body=body, max_bytes=5_000_000)

    with pytest.raises(AccessError, match="outside.*allowlist"):
        bounded_request(client, "GET", "https://evil.example/file")


def test_independent_new_hash_verifier_checks_profile_and_returns_citations():
    result = verify_snapshot(_valid_snapshot())
    assert result["decision"] == "GO"
    assert result["permit_revision_count"] == 1
    assert result["sample"][0]["identity"] == "0918584/99"
    assert result["sample"][0]["root_line"] == 1
    assert result["sample"][0]["permit_line"] == 2
    bad = bytearray(_valid_snapshot())
    bad[2] = ord("x")
    rejected = verify_snapshot(bytes(bad))
    assert rejected["decision"] == "REDIRECT"
    assert "reason" in rejected


def test_independent_verifier_rejects_new_segment_and_interrupted_root():
    valid = _valid_snapshot()
    root = valid[:212]
    permit = valid[214:]
    assert verify_snapshot(root + b"\r\n16bad\r\n" + permit)["decision"] == "REDIRECT"
    assert verify_snapshot(root + b"\r\n03other\r\n" + permit)["decision"] == "REDIRECT"


@pytest.mark.parametrize(
    ("offset", "label"),
    ((14, "DAROOT mapped fields"), (214 + 48, "DAPERMIT mapped fields")),
)
def test_independent_verifier_rejects_non_ascii_mapped_text_fields(offset, label):
    invalid = bytearray(_valid_snapshot())
    invalid[offset] = 0xE9
    result = verify_snapshot(bytes(invalid))
    assert result["decision"] == "REDIRECT"
    assert label in result["reason"]


def test_independent_verifier_rejects_non_a_status_duplicate_keys_and_dates():
    valid = _valid_snapshot()
    pending = bytearray(valid)
    pending[100] = ord("P")
    assert "non-A" in verify_snapshot(bytes(pending))["reason"]
    assert "duplicate" in verify_snapshot(valid[:-2] + b"\r\n" + valid)["reason"]
    invalid_date = bytearray(valid)
    invalid_date[214 + 129:214 + 137] = b"20260230"
    assert "invalid calendar date" in verify_snapshot(bytes(invalid_date))["reason"]


def test_readonly_receipt_replay_keeps_no_attachment_as_unknown(tmp_path):
    receipt = tmp_path / "access.json"
    receipt.write_text(
        '{"decision":"REDIRECT","reason":"download redirect","file_pulls":[],"attempts":[]}',
        encoding="utf-8",
    )
    result = replay_current_compat.replay(receipt)
    assert result["decision"] == "REDIRECT"
    assert result["current_file_sha256"] == "UNKNOWN"
    assert result["compatibility"] == "UNKNOWN"


def test_readonly_receipt_replay_independently_verifies_two_matching_new_hashes(
    tmp_path, monkeypatch
):
    raw = tmp_path / "raw"
    raw.mkdir()
    payload = _valid_snapshot()
    digest = hashlib.sha256(payload).hexdigest()
    pulls = []
    for index in (1, 2):
        path = raw / f"pull-{index}.dat"
        path.write_bytes(payload)
        pulls.append(
            {
                "raw_path": str(path.relative_to(tmp_path)),
                "sha256": digest,
                "bytes": len(payload),
                "advertised_modified": "same",
                "advertised_size": "small",
            }
        )
    receipt = tmp_path / "access.json"
    receipt.write_text(json.dumps({"file_pulls": pulls}), encoding="utf-8")
    monkeypatch.setattr(replay_current_compat, "ROOT", tmp_path)
    monkeypatch.setattr(replay_current_compat, "RAW_ROOT", raw.resolve())
    result = replay_current_compat.replay(receipt)
    assert result["decision"] == "GO_FOR_EXACT_HASH"
    assert result["current_file_sha256"] == digest
    assert result["compatibility"] == "GO"
