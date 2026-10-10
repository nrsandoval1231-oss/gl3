"""Read-only, real-DB projection of the pinned Stage2 36+4 records.

Run in the Stage2 locked backend environment with this Stage3 backend on
PYTHONPATH. DATABASE_URL must point at the controller-owned Stage3 corpus.
The transaction is marked read-only before any application query.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import select, text

from gridlens.api.app import (
    SessionLocal,
    _opportunity_evidence_search_matches,
    opportunity_project_title,
    opportunity_projection,
)
from gridlens.intelligence.opportunity_browse import grouped_opportunities, opportunity_group_id
from gridlens.persistence.models import NeedObservation, Observation


ROOT = Path(__file__).resolve().parents[3]
STAGE2 = ROOT.parent / "gl3-stage2-source-quality-20261009" / ".artifacts" / "STAGE2" / "evidence"
FIXED = STAGE2 / "fixed-sample.6c29be89fc80ebfe.private.json"
FINAL4 = STAGE2 / "priority-supplement-final.private.json"
OUT = Path(os.environ["STAGE3_PROJECTION_OUT"])


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def row_key(abstract: str | None) -> str | None:
    if not abstract:
        return None
    match = re.search(r"^row:\s*(.+?)\s*$", abstract, re.I | re.M)
    return match.group(1).strip() if match else None


def rrc_source_operator(evidence_rows: list[dict]) -> list[dict]:
    matches = []
    for evidence in evidence_rows:
        if evidence.get("source_id") != "texas-rrc-drilling-permits":
            continue
        for value in re.findall(r"^\s*operator\s*:\s*(.+?)\s*$", evidence.get("abstract") or "", re.I | re.M):
            matches.append(
                {
                    "name": value.strip(),
                    "evidence_id": str(evidence.get("id")) if evidence.get("id") else None,
                    "content_hash": evidence.get("content_hash"),
                    "assessment_current": evidence.get("assessment_current"),
                }
            )
    return matches


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


fixed_data = json.loads(FIXED.read_text(encoding="utf-8"))
final_data = json.loads(FINAL4.read_text(encoding="utf-8"))
assert digest(FIXED) == "6c29be89fc80ebfe4779c8e4439cefe6c0457db0c1d58b74ffb59b9f2e633ccc", "fixed36 artifact hash mismatch"
assert digest(FINAL4) == "64092165875edfa80ee04ec8bf5b610cba2dad0c0532ad6251bef195a0693824", "priority4 artifact hash mismatch"
records = [("fixed36", item) for item in fixed_data["records"]]
records.extend(("priority4", item) for item in final_data["selected"])
assert len(records) == 40, len(records)

started = datetime.now(UTC)
with SessionLocal() as session:
    session.execute(text("SET TRANSACTION READ ONLY"))
    session.execute(text("SET LOCAL TIME ZONE 'UTC'"))
    database_name = session.execute(text("SELECT current_database()")).scalar_one()
    assert database_name == "gl3_s3_corpus", f"expected read-only gl3_s3_corpus, connected to {database_name}"
    summaries = opportunity_projection(session, tier="Signal", summary_only=True)
    _opportunity_evidence_search_matches(session, summaries, None)
    ordered_summaries = sorted(summaries, key=lambda item: str(item["id"]))
    ordered_summaries.sort(
        key=lambda item: item.get("_updated_at") or datetime.min, reverse=True
    )
    groups = grouped_opportunities(ordered_summaries)
    observation_ids = {item["observation_id"] for _sample_set, item in records}
    need_observation_rows = session.execute(
        select(NeedObservation.observation_id, NeedObservation.need_id)
        .join(Observation, Observation.id == NeedObservation.observation_id)
        .where(NeedObservation.observation_id.in_(observation_ids))
    ).all()
    need_ids_by_observation: dict[str, set[str]] = {}
    for observation_id, need_id in need_observation_rows:
        need_ids_by_observation.setdefault(str(observation_id), set()).add(str(need_id))
    sample_need_ids = {
        UUID(need_id)
        for values in need_ids_by_observation.values()
        for need_id in values
    }
    details = opportunity_projection(
        session,
        tier=None,
        include_below_floor=True,
        selected_need_ids=sample_need_ids,
        summary_only=False,
    )

summary_by_id = {str(item["id"]): item for item in summaries}
details_by_id = {str(item["id"]): item for item in details}
rows = []
for sample_set, record in records:
    external_id = record["stable_record_id"]
    sample_need_ids_for_record = need_ids_by_observation.get(str(record["observation_id"]), set())
    detail_matches = [details_by_id[key] for key in sorted(sample_need_ids_for_record) if key in details_by_id]
    summary_matches = [summary_by_id[key] for key in sorted(sample_need_ids_for_record) if key in summary_by_id]
    evidence_rows = [evidence for item in detail_matches for evidence in item.get("evidence", [])]
    rows.append(
        {
            "set": sample_set,
            "sample_id": record.get("sample_id"),
            "source_id": record.get("source_id"),
            "external_id": external_id,
            "source_origin": record.get("origin"),
            "stratum": record.get("stratum"),
            "observation_id": record.get("observation_id"),
            "content_hash": record.get("observation", {}).get("content_hash"),
            "visible_signal": bool(summary_matches),
            "detail_available": bool(detail_matches),
            "project_ids": sorted({str(item["project_id"]) for item in detail_matches}),
            "need_ids": sorted(sample_need_ids_for_record),
            "group_titles": sorted({opportunity_project_title(item) for item in summary_matches}),
            "detail_titles": sorted({opportunity_project_title(item) for item in detail_matches}),
            "names": sorted({str(item.get("name") or "") for item in detail_matches}),
            "tiers": sorted({str(item.get("tier") or "") for item in detail_matches}),
            "required_mw": sorted({str(item.get("required_mw")) for item in detail_matches}),
            "start_window": sorted({str(item.get("start_window")) for item in detail_matches}),
            "duration": sorted({str(item.get("duration")) for item in detail_matches}),
            "supply": sorted({str(item.get("supply")) for item in detail_matches}),
            "next_action": sorted({str(item.get("next_action")) for item in detail_matches}),
            "title_company": sorted({str(item.get("title_company")) for item in detail_matches}),
            "title_company_role": sorted({str(item.get("title_company_role")) for item in detail_matches}),
            "source_operator_evidence": rrc_source_operator(evidence_rows),
        }
    )

result = {
    "captured_at_utc": started.isoformat(),
    "finished_at_utc": datetime.now(UTC).isoformat(),
    "candidate_head": os.environ.get("STAGE3_CANDIDATE_HEAD", "UNKNOWN"),
    "candidate_tree": os.environ.get("STAGE3_CANDIDATE_TREE", "UNKNOWN"),
    "implementation_hashes": {
        relative: file_hash(ROOT / relative)
        for relative in (
            "backend/src/gridlens/intelligence/opportunity_browse.py",
            "web/src/features/opportunities/projectCards.ts",
        )
    },
    "database_name": "gl3_s3_corpus",
    "mode": "application projection over real isolated corpus; PostgreSQL transaction READ ONLY",
    "fixed36_path": str(FIXED),
    "fixed36_sha256": digest(FIXED),
    "priority4_path": str(FINAL4),
    "priority4_sha256": digest(FINAL4),
    "denominator": len(rows),
    "visible_signals": sum(row["visible_signal"] for row in rows),
    "detail_records_including_below_floor": len(
        set(details_by_id) & {str(need_id) for need_id in sample_need_ids}
    ),
    "all_group_count": len(groups),
    "ordered_cohort_ids": [str(item["id"]) for item in ordered_summaries],
    "ordered_group_ids": [opportunity_group_id(key) for key, _members in groups],
    "records": rows,
}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
print(json.dumps({"out": str(OUT), "denominator": 40, "visible": result["visible_signals"], "captured_at_utc": result["captured_at_utc"]}))
