"""Bounded RRC permit snapshots. All child bytes retained; no restriction interpretation."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import UTC, date, datetime, timedelta
from email.message import Message
from typing import Any
from zoneinfo import ZoneInfo

from gridlens.ingestion.adapters.federal_register import SourceParseError

SOURCE_ID = "texas-rrc-drilling-permits"
PORTAL = "https://mft.rrc.texas.gov/link/5f07cc72-2e79-4df8-ade1-9aeb792e03fc"


def source_today(now: datetime | None = None) -> date:
    """Select Texas monthly products by the publisher's local calendar day."""
    return (now or datetime.now(UTC)).astimezone(ZoneInfo("America/Chicago")).date()


def _text(row: bytes, first: int, last: int) -> str:
    # The export is fixed-width single-byte text. Names occasionally carry
    # non-ASCII bytes (for example an accented operator name); latin-1 maps
    # every byte to one character so field offsets stay exact.
    return row[first - 1 : last].decode("latin-1").strip()


def _date(value: str) -> str | None:
    if not value or set(value) <= {"0", " "}:
        return None
    try:
        return datetime.strptime(value, "%Y%m%d").date().isoformat()
    except ValueError as exc:
        raise SourceParseError("RRC malformed source date") from exc


def parse_snapshot(
    body: bytes, *, filename: str, today: date, source_url: str = PORTAL
) -> list[dict[str, Any]]:
    """Frame roots and masters; preserve opaque children including embedded CRLF.

    OGA049M root positions are unchanged. The master copybook prints its record
    ID twice; this export has a single ID. Cross-check its identity and original
    issue date against every root before using the two-byte-adjusted positions.
    Child records are not interpreted as current project/power facts.
    """
    if not body or len(body) > 10_000_000 or not body.endswith(b"\r\n"):
        raise SourceParseError("RRC snapshot empty, oversized or truncated")
    lines = body.split(b"\r\n")[:-1]
    blocks: list[list[bytes]] = []
    for line in lines:
        if line.startswith(b"01") and len(line) == 212:
            blocks.append([line])
        elif not blocks:
            raise SourceParseError("RRC data before first root")
        else:
            blocks[-1].append(line)
    if not 1 <= len(blocks) <= 5000:
        raise SourceParseError("RRC root count outside bounds")
    reconstructed = b"".join(b"\r\n".join(block) + b"\r\n" for block in blocks)
    if reconstructed != body:
        raise SourceParseError("RRC framing did not account for every source byte")
    output = []
    seen = set()
    for ordinal, block in enumerate(blocks, 1):
        if len(block) < 2 or len(block[1]) != 510 or not block[1].startswith(b"02"):
            raise SourceParseError("RRC root lacks exactly framed master")
        root, master = block[:2]
        permit = _text(root, 113, 119)
        status_number = _text(root, 3, 9)
        sequence = _text(root, 10, 11)
        if (
            not permit.isdigit()
            or int(permit) == 0
            or not status_number.isdigit()
            or not sequence.isdigit()
            or not 1 <= int(sequence) <= 99
            or master[2:11] != (permit + sequence).encode()
        ):
            raise SourceParseError("RRC root/master identity disagreement")
        key = (permit, sequence)
        if key in seen:
            raise SourceParseError("RRC duplicate permit sequence in snapshot")
        seen.add(key)
        issue = _date(_text(root, 120, 127))
        if issue != _date(_text(master, 130, 137)):
            raise SourceParseError("RRC root/master issue-date disagreement")
        received = _date(_text(root, 59, 66))
        amended = _date(_text(master, 138, 145))
        if not issue or any(
            v and date.fromisoformat(v) > today for v in (issue, received, amended)
        ):
            raise SourceParseError("RRC missing or future permit date")
        # These bytes are source continuation/child text, never discarded and
        # never interpreted as people, fuel, MW or lifecycle dates.
        previous_kind = b"02"
        for child in block[2:]:
            if len(child) > 510:
                raise SourceParseError("RRC child exceeds documented record bound")
            kind = child[:2]
            if child.startswith(b"\x85") and previous_kind == b"08":
                continue  # CRLF embedded in the official freeform restriction.
            if kind not in {
                b"03",
                b"04",
                b"05",
                b"06",
                b"07",
                b"08",
                b"09",
                b"10",
                b"11",
                b"12",
                b"13",
                b"14",
                b"15",
            }:
                raise SourceParseError("RRC unknown or unframed child record")
            previous_kind = kind
            if child.startswith((b"01", b"02")) and len(child) in {212, 510}:
                raise SourceParseError("RRC unexpected nested root/master")
            if len(child) > 510:
                raise SourceParseError("RRC child exceeds documented record bound")
        if _text(master, 480, 480) not in {"", "P", "F"}:
            raise SourceParseError("RRC cancellation flag is undocumented")
        raw = b"\r\n".join(block) + b"\r\n"
        if len(raw) > 100_000:
            raise SourceParseError("RRC permit group exceeds evidence bound")
        output.append(
            {
                "number": permit,
                "sequence": int(sequence),
                "status_number": status_number,
                "operator": _text(root, 67, 98),
                "operator_number": _text(root, 49, 54),
                "lease": _text(root, 15, 46),
                "well": _text(root, 157, 162),
                "county_code": _text(master, 12, 14),
                "application_status": _text(root, 101, 101),
                "cancelled_flag": _text(master, 480, 480),
                "application_type": _text(master, 66, 67),
                "issued": issue,
                "received": received,
                "amended": amended,
                "filename": filename,
                "source_url": source_url,
                "ordinal": ordinal,
                "raw_b64": base64.b64encode(raw).decode(),
                "raw_sha256": hashlib.sha256(raw).hexdigest(),
                "opaque_child_lines": len(block) - 2,
            }
        )
    return output


def records_from_snapshots(snapshots: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Oldest snapshot first; lowest sequence is latest amendment, not a new well."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for snapshot in snapshots:
        for row in snapshot:
            grouped.setdefault(row["number"], []).append(row)
    output = []
    for number, versions in sorted(grouped.items()):
        minimum = min(v["sequence"] for v in versions)
        current = [v for v in versions if v["sequence"] == minimum][-1]
        status = (
            "Cancelled"
            if current["cancelled_flag"] == "P"
            else "Filing cancelled; permit status unknown"
            if current["cancelled_flag"] == "F"
            else {
                "A": "Approved",
                "W": "Withdrawn",
                "D": "Dismissed",
                "E": "Denied",
                "C": "Closed",
                "X": "Deleted",
                "Z": "Cancelled",
                "P": "Pending",
            }.get(current["application_status"], "Unknown")
        )
        event_date = current["amended"] or current["issued"]
        location = f"RRC county code {current['county_code']}, Texas"
        kind = {
            "01": "Drill",
            "05": "Other",
            "07": "Reenter",
            "09": "Field transfer",
            "14": "Recompletion",
            "15": "Reclass",
        }.get(current["application_type"], "Unknown application type")
        description = (
            f"W-1 well permit {number}: {kind}; lease {current['lease']}, well {current['well']}."
        )
        facts = {
            "row": number,
            "amendment_sequence": str(minimum),
            "operator": current["operator"],
            "operator_number": current["operator_number"],
            "lease": current["lease"],
            "well": current["well"],
            "county_code": current["county_code"],
            "type": "W-1 well permit — " + kind,
            "application_type": current["application_type"],
            "date": current["issued"],
            "application_received": current["received"] or "Unknown",
            "amended_date": current["amended"] or "Unknown",
            "status": status,
            "description": description,
        }
        raw_versions = {v["raw_sha256"]: v["raw_b64"] for v in versions}
        digest = hashlib.sha256(
            json.dumps([facts, sorted(raw_versions)], sort_keys=True).encode()
        ).hexdigest()
        provenance = [
            {k: v[k] for k in ("filename", "source_url", "ordinal", "sequence", "raw_sha256")}
            for v in versions
        ]
        abstract = "\n".join(f"{k}: {v}" for k, v in facts.items())
        abstract += "\nSource segment provenance: " + json.dumps(provenance, sort_keys=True)
        abstract += "\nOpaque source bytes (base64; not interpreted): " + json.dumps(
            raw_versions, sort_keys=True
        )
        output.append(
            {
                "document_number": number,
                "title": description,
                "abstract": abstract,
                "publication_date": event_date,
                "event_date": event_date,
                "event_date_label": "Reported permit amendment date"
                if current["amended"]
                else "Reported original permit issue date",
                "html_url": PORTAL,
                "extraction_location": f"OGA049M root/master; permit {number}; sequence {minimum}",
                "source_hash": digest,
                "permit": {
                    "source_type": SOURCE_ID,
                    "project": number,
                    "row_id": number,
                    "description": description,
                    "address": "",
                    "city": "",
                    "state": "TX",
                    "location": location,
                    "status": status,
                    "sequence": minimum,
                    "operator": current["operator"],
                    "operator_number": current["operator_number"],
                    "lease": current["lease"],
                    "well": current["well"],
                    "application_type": current["application_type"],
                },
            }
        )
    return output


def reconstruct_retained_record(
    abstract: str, *, permit_number: str, observed_at: datetime
) -> dict[str, Any]:
    """Validate retained native bytes, without claiming a new retrieval.

    Filename and ordinal are ingestion provenance, not independently authenticated
    publisher facts. Raw root/master/opaque children must recreate the whole stored
    abstract exactly; callers must also bind the result to canonical row fields.
    """
    provenance_marker = "\nSource segment provenance: "
    raw_marker = "\nOpaque source bytes (base64; not interpreted): "
    try:
        if (
            not isinstance(abstract, str)
            or len(abstract.encode("utf-8")) > 750_000
            or not re.fullmatch(r"[0-9]{7}", permit_number)
            or not isinstance(observed_at, datetime)
            or observed_at.tzinfo is None
            or observed_at.utcoffset() is None
            or abstract.count(provenance_marker) != 1
            or abstract.count(raw_marker) != 1
        ):
            raise SourceParseError("RRC retained input shape or byte bound invalid")

        def unique_object(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise SourceParseError("RRC retained JSON duplicate key")
                result[key] = value
            return result

        _, sections = abstract.split(provenance_marker)
        provenance_text, raw_text = sections.split(raw_marker)
        provenance = json.loads(provenance_text, object_pairs_hook=unique_object)
        raw_versions = json.loads(raw_text, object_pairs_hook=unique_object)
        if (
            not isinstance(provenance, list)
            or not 1 <= len(provenance) <= 20
            or not isinstance(raw_versions, dict)
            or not 1 <= len(raw_versions) <= 20
        ):
            raise SourceParseError("RRC retained segment count invalid")
        decoded = {}
        total = 0
        for raw_hash, encoded in raw_versions.items():
            if not re.fullmatch(r"[a-f0-9]{64}", raw_hash) or not isinstance(encoded, str):
                raise SourceParseError("RRC retained raw identity invalid")
            raw = base64.b64decode(encoded, validate=True)
            total += len(raw)
            if total > 750_000 or base64.b64encode(raw).decode("ascii") != encoded:
                raise SourceParseError(
                    "RRC retained decoded bytes exceed bounds or encoding invalid"
                )
            if hashlib.sha256(raw).hexdigest() != raw_hash:
                raise SourceParseError("RRC retained raw hash mismatch")
            decoded[raw_hash] = raw
        expected_keys = {"filename", "source_url", "ordinal", "sequence", "raw_sha256"}
        seen_provenance = set()
        sequence_hashes: dict[int, str] = {}
        used_hashes = set()
        snapshots = []
        today = source_today(observed_at)
        for item in provenance:
            if not isinstance(item, dict) or set(item) != expected_keys:
                raise SourceParseError("RRC retained provenance fields invalid")
            if (
                type(item["ordinal"]) is not int
                or not 1 <= item["ordinal"] <= 5000
                or type(item["sequence"]) is not int
                or not 1 <= item["sequence"] <= 99
                or not isinstance(item["filename"], str)
                or not isinstance(item["source_url"], str)
                or not isinstance(item["raw_sha256"], str)
            ):
                raise SourceParseError("RRC retained provenance values invalid")
            filename = item["filename"]
            if item["source_url"] == PORTAL:
                valid_file = filename == "daf420.dat"
            elif item["source_url"] == MONTHLY_PORTAL:
                valid_file = bool(
                    re.fullmatch(r"daf420\.dat\.[0-9]{2}-[0-9]{2}-[0-9]{4}", filename)
                )
                if valid_file:
                    month_end = datetime.strptime(
                        filename.removeprefix("daf420.dat."), "%m-%d-%Y"
                    ).date()
                    valid_file = (month_end + timedelta(days=1)).day == 1 and month_end <= today
            else:
                valid_file = False
            if not valid_file:
                raise SourceParseError("RRC retained source URL or filename invalid")
            identity = json.dumps(item, sort_keys=True)
            if identity in seen_provenance:
                raise SourceParseError("RRC retained duplicate provenance")
            seen_provenance.add(identity)
            raw_hash = item["raw_sha256"]
            if raw_hash not in decoded:
                raise SourceParseError("RRC retained provenance lacks bytes")
            previous_hash = sequence_hashes.setdefault(item["sequence"], raw_hash)
            if previous_hash != raw_hash:
                raise SourceParseError("RRC retained conflicting same-sequence bytes")
            rows = parse_snapshot(
                decoded[raw_hash], filename=filename, today=today, source_url=item["source_url"]
            )
            if (
                len(rows) != 1
                or rows[0]["number"] != permit_number
                or rows[0]["sequence"] != item["sequence"]
            ):
                raise SourceParseError("RRC retained permit or sequence mismatch")
            # The source ordinal cannot be recovered from a retained single permit block.
            rows[0]["ordinal"] = item["ordinal"]
            snapshots.append(rows)
            used_hashes.add(raw_hash)
        if used_hashes != set(decoded):
            raise SourceParseError("RRC retained unreferenced bytes")
        records = records_from_snapshots(snapshots)
        if len(records) != 1 or records[0]["abstract"] != abstract:
            raise SourceParseError("RRC retained abstract does not exactly reconstruct")
        return records[0]
    except SourceParseError:
        raise
    except (ValueError, TypeError, KeyError, OverflowError, UnicodeError, RecursionError) as exc:
        raise SourceParseError("RRC retained content is malformed") from exc


def amendment_sequence(abstract: str | None) -> int | None:
    values = re.findall(r"^amendment_sequence: (\d{1,2})$", abstract or "", re.M)
    return int(values[0]) if len(values) == 1 else None


def _official_url(base: str, path: str) -> str:
    from urllib.parse import urljoin, urlsplit

    url = urljoin(base, path)
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "mft.rrc.texas.gov":
        raise SourceParseError("RRC link leaves the reviewed official host")
    return url


def _request(
    http: Any, method: str, url: str, deadline: float, data: dict | None = None
) -> tuple[Any, bytes]:
    """Bound both the normal public form POST and its same-host download redirect."""
    from gridlens.ingestion.adapters.bounded_http import remaining_seconds

    remaining = remaining_seconds(deadline)
    with http.stream(
        method, url, data=data, follow_redirects=False, timeout=min(20, remaining or 20)
    ) as response:
        if response.status_code not in {200, 302, 303}:
            response.raise_for_status()
            raise SourceParseError("RRC unexpected response status")
        limit = 10_000_000 if method == "GET" else 2_000_000
        declared = response.headers.get("content-length")
        if declared and (not declared.isdigit() or int(declared) > limit):
            raise SourceParseError("RRC response exceeds byte bound")
        parts, size = [], 0
        for part in response.iter_bytes():
            remaining_seconds(deadline)
            size += len(part)
            if size > limit:
                raise SourceParseError("RRC response exceeds byte bound")
            parts.append(part)
        return response, b"".join(parts)


def _download_listing_file(
    http: Any,
    portal: str,
    filename: str,
    today: date,
    deadline: float,
    *,
    archive_date: date | None = None,
) -> tuple[bytes, str]:
    from bs4 import BeautifulSoup

    _, listing = _request(http, "GET", portal, deadline)
    if len(listing) > 2_000_000:
        raise SourceParseError("RRC listing exceeds bound")
    soup = BeautifulSoup(listing, "html.parser")
    form = soup.select_one("form#fileList")
    matches = [a for a in soup.select("#fileTable_data tr a") if a.get_text(strip=True) == filename]
    if form is None or len(matches) != 1:
        raise SourceParseError(
            f"RRC snapshot {filename} is absent or ambiguous in official listing"
        )
    anchor = matches[0]
    row = anchor.find_parent("tr")
    label = row.get_text(" ", strip=True) if row else ""
    stamp = re.search(r"\b(\d{1,2}/\d{1,2}/\d{2})\s+(\d{1,2}:\d{2}:\d{2}\s+[AP]M)", label)
    if not stamp:
        raise SourceParseError("RRC modification timestamp missing")
    modified = datetime.strptime(stamp[1], "%m/%d/%y").date()
    if archive_date:
        if not archive_date <= modified <= archive_date + timedelta(days=7) or modified > today:
            raise SourceParseError(
                "RRC month-end snapshot modification date disagrees with interval"
            )
    elif not 0 <= (today - modified).days <= 4:
        raise SourceParseError("RRC current snapshot is future-dated or more than four days old")
    data = {
        str(i["name"]): str(i.get("value", "")) for i in form.select('input[type="hidden"][name]')
    }
    identity = str(anchor.get("id", ""))
    if not identity or not form.get("action"):
        raise SourceParseError("RRC public download form changed")
    data[identity] = identity
    response, body = _request(
        http, "POST", _official_url(portal, str(form["action"])), deadline, data
    )
    for _ in range(3):
        if response.status_code == 200:
            break
        response, body = _request(
            http,
            "GET",
            _official_url(str(response.url), response.headers.get("location", "")),
            deadline,
        )
    disposition = Message()
    disposition["content-disposition"] = response.headers.get("content-disposition", "")
    if response.status_code != 200 or disposition.get_filename() != filename:
        raise SourceParseError("RRC snapshot download identity not verified")
    return body, modified.isoformat()


MONTHLY_PORTAL = "https://mft.rrc.texas.gov/link/f5dfea9c-bb39-4a5e-a44e-fb522e088cba"


def retrieve(source: dict[str, Any], client: Any = None) -> list[dict[str, Any]]:
    import time

    import httpx

    if source.get("id") != SOURCE_ID or source.get("endpoint") != PORTAL:
        raise SourceParseError("RRC source is outside its reviewed endpoint")
    http = client or httpx.Client(timeout=20, follow_redirects=False)
    today = source_today()
    end = today.replace(day=1) - timedelta(days=1)
    filename = "daf420.dat." + end.strftime("%m-%d-%Y")
    deadline = time.monotonic() + 120
    try:
        # The separate official EOM product closes the preceding month; never
        # infer that a first-day daily backup is the final monthly file.
        archive, _ = _download_listing_file(
            http, MONTHLY_PORTAL, filename, today, deadline, archive_date=end
        )
        current, _ = _download_listing_file(http, PORTAL, "daf420.dat", today, deadline)
        return records_from_snapshots(
            [
                parse_snapshot(archive, filename=filename, today=today, source_url=MONTHLY_PORTAL),
                parse_snapshot(current, filename="daf420.dat", today=today),
            ]
        )
    finally:
        if client is None:
            http.close()
