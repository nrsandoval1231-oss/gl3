"""Federal Register hp/driver evidence through normal ingestion on a disposable database.

Uses the retained real GovInfo notice fixture. The flag defaults off; behind it, the PDF evidence
carries ``provenance["fr_hp_driver"]`` and every quote is the evidence text at the stated span.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).parent))

from test_ferc_equipment_ingestion import (  # noqa: E402,F401
    PDF_PATH,
    _install_fixture_pdf,
    _record,
    _run,
    ferc_equipment_db,
)

from gridlens.persistence.models import Evidence, Interpretation  # noqa: E402


@pytest.fixture
def db(ferc_equipment_db):  # noqa: F811
    return ferc_equipment_db


def _forward_flag(monkeypatch):
    from gridlens.ingestion.adapters.govinfo_pdf import retrieve_companion

    content = PDF_PATH.read_bytes()
    seen: list[dict] = []

    def retrieve(record, _client=None, **kwargs):
        seen.append(dict(kwargs))
        client = httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200, content=content, headers={"content-type": "application/pdf"}
                )
            ),
            timeout=15.0,
        )
        try:
            return retrieve_companion(record, client, **kwargs)
        finally:
            client.close()

    monkeypatch.setattr("gridlens.ingestion.service.retrieve_companion", retrieve)
    return seen


def _pdf_evidence(factory):
    with factory() as session:
        rows = session.scalars(select(Evidence).where(Evidence.url.like("%govinfo.gov%"))).all()
        assert len(rows) == 1
        interpretation = session.scalar(select(Interpretation))
        return rows[0], (interpretation.assessment if interpretation else None)


def test_flag_off_leaves_evidence_without_the_block(db, monkeypatch):
    factory, definition, job_id = db
    provenance = _install_fixture_pdf(monkeypatch)
    seen = _forward_flag(monkeypatch)
    assert definition["query"].get("hp_driver_evidence", False) is False
    _run(factory, definition, job_id, _record(provenance))
    evidence, _ = _pdf_evidence(factory)
    assert evidence.provenance == {}
    assert seen == [{}]  # the companion call is unchanged: no extra argument


def test_flag_on_adds_verified_quotes_and_changes_nothing_else(db, monkeypatch):
    from gridlens.ingestion.adapters.govinfo_pdf import retrieve_companion

    factory, definition, job_id = db
    provenance = _install_fixture_pdf(monkeypatch)
    seen = _forward_flag(monkeypatch)
    record = _record(provenance)
    on_definition = {**definition, "query": {**definition["query"], "hp_driver_evidence": True}}
    _run(factory, on_definition, job_id, record)
    evidence, _assessment = _pdf_evidence(factory)

    assert {"hp_driver": True} in seen
    block = evidence.provenance["fr_hp_driver"]
    assert block["version"].startswith("fr-notice-hp-driver")
    # The real notice: CS302 installs one new electric motor driven compressor unit of 18,340 hp.
    # The CS343 re-wheel and the Units 7 and 8 uprate (+1,600 hp each) are not new equipment.
    (row,) = block["rows"]
    assert (
        row["equipment_type"],
        row["drive"],
        row["rating"],
        row["unit"],
        row["count"],
        row["state"],
    ) == ("compressor", "electric", "18340", "hp", 1, "proposed")
    assert row["electric_demand_evidenced"] is True and block["abstain"] is None
    for field in row["evidence"].values():
        assert evidence.abstract[field["start"] : field["end"]] == field["quote"]
    assert row["evidence"]["rating"]["quote"] == "18,340 hp"

    # The ordinary evidence fields are exactly what the unflagged companion retrieval gives.
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, content=PDF_PATH.read_bytes(), headers={"content-type": "application/pdf"}
            )
        ),
        timeout=15.0,
    ) as client:
        (plain,) = retrieve_companion(record, client)
    assert evidence.content_hash == plain["content_hash"]
    assert evidence.abstract == plain["abstract"]
    assert evidence.extraction_location == plain["extraction_location"]
