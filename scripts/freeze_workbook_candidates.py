"""Freeze a deterministic, stratified sample of staged workbook assertions.

This only reads the isolated external-import tables. The manifest intentionally
labels these as unverified workbook candidates; it is not a qualified opportunity
cohort and it does not activate rows or publish canonical project claims.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def normalized(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def select_candidates(rows: list[dict]) -> list[dict]:
    """Choose 13 TX, 6 OK, 6 NM rows by stable hash after conservative dedupe."""
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        values = row["normalized"] or {}
        state = str(values.get("state") or "").strip().upper()
        name = normalized(values.get("project_name"))
        if state not in {"TX", "OK", "NM"} or not name or row["row_kind"] != "project":
            continue
        if row["match_status"] in {"invalid", "ignored"} or row["errors"]:
            continue
        groups[(state, name)].append(row)

    quotas = {"TX": 13, "OK": 6, "NM": 6}
    selected: list[dict] = []
    used_sites: set[tuple[str, str]] = set()
    for state, quota in quotas.items():
        ranked = []
        for (group_state, name), matches in groups.items():
            if group_state != state:
                continue
            # Stable provenance tie-break if a workbook repeats the same claim.
            row = min(matches, key=lambda item: (item["filename"], item["sheet"], item["row_number"]))
            raw = row["raw"] or {}
            try:
                lat, lon = float(raw.get("Latitude")), float(raw.get("Longitude"))
                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    continue
            except (TypeError, ValueError):
                continue
            # Exact normalized coordinate duplicates are conservatively treated
            # as the same site, even when workbook names differ.
            site = (f"{lat:.5f}", f"{lon:.5f}")
            rank = hashlib.sha256(
                f"{row['content_hash']}|{row['sheet']}|{row['row_number']}|{state}|{name}".encode()
            ).hexdigest()
            ranked.append((rank, site, row, lat, lon))
        count = 0
        for _rank, site, row, lat, lon in sorted(ranked, key=lambda item: item[0]):
            if site in used_sites:
                continue
            used_sites.add(site)
            values = row["normalized"] or {}
            raw = row["raw"] or {}
            power = values.get("facility_demand_mw")
            if isinstance(power, Decimal):
                power = float(power)
            selected.append(
                {
                    "candidate_status": "UNVERIFIED_WORKBOOK_SOURCE_ROW_CANDIDATE",
                    "qualification_status": "NOT_ESTABLISHED",
                    "project_name_assertion": values.get("project_name"),
                    "state_assertion": state,
                    "county_assertion": raw.get("County") or None,
                    "latitude_assertion": lat,
                    "longitude_assertion": lon,
                    "company_assertion": values.get("company_name"),
                    "facility_power_mw_assertion": power,
                    "power_basis_status": "UNVERIFIED_WORKBOOK_FACILITY_POWER_ONLY",
                    "source_url_status": "UNKNOWN_LINK_DISPLAY_TEXT_HAS_NO_RETAINED_TARGET",
                    "temporary_power_relevance": "UNKNOWN",
                    "current_future_timing": "UNKNOWN",
                    "residual_gap": "UNKNOWN",
                    "buyer_organization": "UNKNOWN",
                    "business_contact_method": "UNKNOWN",
                    "workbook_filename": row["filename"],
                    "workbook_sha256": row["content_hash"],
                    "workbook_sheet": row["sheet"],
                    "workbook_row_number": row["row_number"],
                    "staged_batch_id": row["batch_id"],
                    "staged_row_id": row["id"],
                    "activation_status": "ACTIVE" if row["active"] else "INACTIVE",
                    "selection_stratum": state,
                    "dedupe_key": "normalized_project_name+state; duplicate coordinates collapsed",
                }
            )
            count += 1
            if count == quota:
                break
        if count != quota:
            raise RuntimeError(f"Only {count} distinct coordinate-backed {state} rows; need {quota}")
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True, help="loopback PostgreSQL URL")
    parser.add_argument("--expected-database-name", default="gridlens_release_corpus")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    url = make_url(args.database_url)
    if url.host not in {"127.0.0.1", "localhost", "::1"} or url.database != args.expected_database_name:
        parser.error("requires the exact named loopback corpus database")
    if args.output.exists():
        parser.error("refusing to overwrite frozen cohort manifest")

    engine = create_engine(url, connect_args={"options": "-c default_transaction_read_only=on"})
    try:
        with engine.connect() as connection:
            connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
            rows = [
                dict(row)
                for row in connection.execute(
                    text("""
                        SELECT b.filename, b.content_hash, b.id::text AS batch_id,
                               r.id::text AS id, r.sheet, r.row_number, r.row_kind,
                               r.normalized, r.raw, r.errors, r.match_status,
                               a.active
                        FROM external_import_rows r
                        JOIN external_import_batches b ON b.id = r.batch_id
                        LEFT JOIN external_import_activations a ON a.row_id = r.id
                        ORDER BY b.filename, r.sheet, r.row_number
                    """)).mappings()
            ]
        selected = select_candidates(rows)
    finally:
        engine.dispose()

    result = {
        "kind": "frozen_unverified_workbook_source_row_candidates",
        "measured_at": datetime.now(UTC).isoformat(),
        "selection_frozen_before_contact_research": True,
        "source_database": args.expected_database_name,
        "requested_count": 25,
        "selected_count": len(selected),
        "selection_rule": (
            "Eligible staged project rows in TX/OK/NM with name and valid workbook coordinates; "
            "dedupe by normalized name+state, then collapse duplicate rounded coordinates; "
            "select stable SHA-256 rank within strata TX=13, OK=6, NM=6. No contact or "
            "commercial outcome field participates."
        ),
        "genuine_eligible_opportunity_cohort": "NOT_ESTABLISHED",
        "source_citation_status": "WORKBOOK_PROVENANCE_ONLY; source URL targets are not retained",
        "candidate_unknowns": [
            "public source URL and retrieval evidence",
            "independent project identity and physical-site validation",
            "source-supported 300 kW power basis",
            "temporary/rental-power relevance",
            "current/future need timing or ongoing constraint",
            "committed supply and residual gap",
            "buyer organization and attributable business contact method",
            "independent contact/mailbox verification and buying authority",
        ],
        "contact_research_executed": False,
        "paid_calls": 0,
        "candidates": selected,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Froze {len(selected)} unverified workbook candidates: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
