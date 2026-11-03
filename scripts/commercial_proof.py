"""Read-only, resumable commercial proof over the FULL accessible observation population.

Every Observation is evaluated; there is no top-N or sample cutoff. Batches are a processing unit
only. Progress is checkpointed to a JSONL file, so an interrupted run resumes, and anything not
processed or that failed is reported explicitly. The database session is READ ONLY: any attempted
write raises and is recorded as a failure instead of mutating data. Run against a disposable
database only (never production). Classification rules are evaluator rules, not product behavior,
and a "Commercial Hit" is automated until independently checked against its cited source.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select, text, tuple_

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from gridlens.persistence.database import SessionLocal  # noqa: E402
from gridlens.persistence.models import (  # noqa: E402
    Interpretation,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
)

VERSION = "commercial-proof-v1"
ORG_LABEL = re.compile(
    r"^\s*(?:applicant|operator|owner|developer|permittee|company|customer|facility owner|"
    r"project owner)\s*:\s*(.{3,120}?)\s*$",
    re.I | re.M,
)
QUANTIFIED = re.compile(r"\b\d[\d,.]*\s*(?:MW|megawatts?|kW|kV|hp|horsepower|MVA)\b", re.I)
TOPICAL = re.compile(
    r"substation|interconnect|large[- ]load|transformer|switchgear|generator|turbine|compressor"
    r"|data cent|power plant|electric(?:al)? (?:service|load|demand)|load letter|energization",
    re.I,
)
OWNER_ROLES = {"owner_developer", "asset_operator", "owner_construction", "owner_energy"}
SUFFIX = re.compile(r"\b(llc|l\.l\.c|inc|corp|corporation|co|company|lp|l\.p|ltd|texas)\b\.?", re.I)


def org_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", SUFFIX.sub("", name.casefold())).strip()


def classify(rec: dict) -> tuple[str, list[str]]:
    """Return (class, reason codes). Rules are explicit and recorded with each result."""
    reasons: list[str] = []
    has_org = bool(rec["organization"])
    power = rec["power_evidence"] != "none"
    project_ok = rec["project_id"] is not None and rec["region_status"] == "ELIGIBLE"
    card = rec.get("card") or {}
    if (
        project_ok
        and has_org
        and (rec["organization_role"] or "") in OWNER_ROLES
        and card
        and card.get("disposition") in {"ACTION NOW", "RESEARCH"}
        and card.get("next_action")
        and card.get("activity")
    ):
        return "Commercial Hit", ["eligible_project", "organization_named", "admitted_power_need"]
    if has_org and (power or rec["project_id"]):
        if rec["project_id"] is None:
            reasons.append("no_project_site")
        elif rec["region_status"] != "ELIGIBLE":
            reasons.append("site_unresolved_or_out_of_region")
        elif (rec["organization_role"] or "") not in OWNER_ROLES:
            reasons.append("buyer_not_identified_contractor_or_unknown_role")
        elif card.get("disposition") in {"WATCH", "REJECT"}:
            reasons.append(f"triage_{card['disposition'].lower().replace(' ', '_')}")
        if not power:
            reasons.append("no_power_evidence")
        return "Investigation Candidate", reasons or ["incomplete_commercial_chain"]
    if not has_org:
        reasons.append("no_organization")
    if not power and rec["project_id"] is None:
        reasons.append("no_power_evidence")
    return "Rejected", reasons or ["not_commercially_relevant"]


def evaluate_observation(session, obs: Observation, card_cache: dict) -> dict:
    from gridlens.intelligence.commercial_evaluation import evaluate_target

    interp = session.scalar(select(Interpretation).where(Interpretation.observation_id == obs.id))
    assessment = (interp.assessment if interp else None) or {}
    row = session.execute(
        select(PowerNeed, Project)
        .join(NeedObservation, NeedObservation.need_id == PowerNeed.id)
        .join(Project, Project.id == PowerNeed.project_id)
        .where(NeedObservation.observation_id == obs.id)
        .limit(1)
    ).first()
    need, project = (row[0], row[1]) if row else (None, None)
    body = f"{obs.title}\n{obs.abstract or ''}"
    labeled = ORG_LABEL.findall(body)
    card, card_error = None, None
    if need is not None:
        key = str(need.id)
        if key not in card_cache:
            try:
                card_cache[key] = evaluate_target(session, need.id)
            except Exception as exc:  # recorded, never silent
                card_cache[key] = {"__error__": f"{type(exc).__name__}: {str(exc)[:160]}"}
        card = card_cache[key]
        if card and "__error__" in card:
            card_error, card = card["__error__"], None
    organization = (card or {}).get("organization") or (labeled[0] if labeled else None)
    org_source = (
        "triage_card"
        if (card or {}).get("organization")
        else ("source_text_label" if labeled else None)
    )
    quantified = QUANTIFIED.findall(body)
    power = "quantified" if quantified else ("topical" if TOPICAL.search(body) else "none")
    rec = {
        "observation_id": str(obs.id),
        "source_id": obs.source_id,
        "external_id": obs.external_id,
        "url": obs.url,
        "published_at": obs.published_at.isoformat() if obs.published_at else None,
        "interpretation_decision": assessment.get("decision"),
        "interpretation_reason": (assessment.get("reason") or "")[:200],
        "project_id": str(project.id) if project else None,
        "project_identity_key": project.identity_key if project else None,
        "project_name": project.name if project else None,
        "project_location": project.location if project else None,
        "region_status": project.region_status if project else None,
        "need_id": str(need.id) if need else None,
        "organization": organization,
        "organization_source": org_source,
        "organization_role": (card or {}).get("organization_role"),
        "power_evidence": power,
        "power_evidence_quotes": quantified[:3],
        "required_mw": (card or {}).get("required_mw") or (need.required_mw if need else None),
        "commercial_application_hypothesis": (card or {}).get("hypothesis"),
        "triage_disposition": (card or {}).get("disposition"),
        "next_action": (card or {}).get("next_action"),
        "unknowns": (card or {}).get("unknowns"),
        "card_error": card_error,
        "card": {k: (card or {}).get(k) for k in ("disposition", "next_action", "activity")}
        if card
        else None,
    }
    rec["classification"], rec["reasons"] = classify(rec)
    if card_error:
        rec["reasons"].append("card_evaluation_failed")
    return rec


def run(out_dir: Path, batch: int) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    results = out_dir / "results.jsonl"
    done: set[str] = set()
    if results.exists():
        for line in results.read_text().splitlines():
            try:
                done.add(json.loads(line)["observation_id"])
            except (ValueError, KeyError):
                continue  # truncated final line from an interrupted run: re-evaluated
    failures: list[dict] = []
    card_cache: dict = {}
    started = datetime.now(UTC)
    with SessionLocal() as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        total = session.scalar(select(text("count(*)")).select_from(Observation))
        cursor = None
        with results.open("a") as sink:
            while True:
                q = select(Observation).order_by(Observation.first_seen_at, Observation.id)
                if cursor:
                    q = q.where(tuple_(Observation.first_seen_at, Observation.id) > cursor)
                rows = list(session.scalars(q.limit(batch)))
                if not rows:
                    break
                for obs in rows:
                    cursor = (obs.first_seen_at, obs.id)
                    if str(obs.id) in done:
                        continue
                    try:
                        sink.write(
                            json.dumps(evaluate_observation(session, obs, card_cache)) + "\n"
                        )
                        done.add(str(obs.id))
                    except Exception as exc:
                        session.rollback()
                        session.execute(text("SET TRANSACTION READ ONLY"))
                        failures.append(
                            {
                                "observation_id": str(obs.id),
                                "source_id": obs.source_id,
                                "error": f"{type(exc).__name__}: {str(exc)[:200]}",
                            }
                        )
                sink.flush()
    return summarize(out_dir, results, total, failures, started)


def summarize(out_dir: Path, results: Path, total: int, failures: list, started) -> dict:
    recs = [json.loads(line) for line in results.read_text().splitlines() if line.strip()]
    classes = Counter(r["classification"] for r in recs)
    reasons = Counter(code for r in recs for code in r["reasons"])
    projects = {r["project_id"] for r in recs if r["project_id"]}
    facilities = {
        re.sub(r"[^a-z0-9]+", " ", r["project_location"].casefold()).strip()
        for r in recs
        if r["project_location"]
    }
    orgs = defaultdict(set)
    for r in recs:
        if r["organization"]:
            orgs[org_key(r["organization"])].add(r["project_id"] or r["observation_id"])
    n = len(recs)

    def pct(k: int) -> float | None:
        return round(100 * k / n, 1) if n else None

    per_source = defaultdict(Counter)
    for r in recs:
        per_source[r["source_id"]][r["classification"]] += 1
    summary = {
        "version": VERSION,
        "run_started_utc": started.isoformat(),
        "records_in_population": total,
        "records_evaluated": n,
        "records_unprocessed": total - n,
        "evaluation_failures": failures,
        "unique_projects": len(projects),
        "unique_physical_locations_normalized": len(facilities),
        "unique_organizations_normalized": len(orgs),
        "classification": dict(classes),
        "reason_codes": dict(reasons),
        "failure_categories": dict(Counter(f["error"].split(":")[0] for f in failures)),
        "coverage": {
            "with_provenance_url_pct": pct(sum(bool(r["url"]) for r in recs)),
            "with_organization_pct": pct(sum(bool(r["organization"]) for r in recs)),
            "with_owner_role_pct": pct(
                sum((r["organization_role"] or "") in OWNER_ROLES for r in recs)
            ),
            "with_power_evidence_pct": pct(sum(r["power_evidence"] != "none" for r in recs)),
            "with_quantified_power_pct": pct(
                sum(r["power_evidence"] == "quantified" for r in recs)
            ),
            "with_eligible_project_pct": pct(sum(r["region_status"] == "ELIGIBLE" for r in recs)),
            "with_next_action_pct": pct(sum(bool(r["next_action"]) for r in recs)),
        },
        "yield": {
            "commercial_hits": classes.get("Commercial Hit", 0),
            "hits_per_evaluated_record_pct": pct(classes.get("Commercial Hit", 0)),
            "hits_per_unique_project_pct": round(
                100 * classes.get("Commercial Hit", 0) / len(projects), 1
            )
            if projects
            else None,
        },
        "multi_project_organizations": {k: len(v) for k, v in orgs.items() if len(v) > 1},
        "per_source": {k: dict(v) for k, v in sorted(per_source.items())},
        "notes": [
            "Commercial Hit is automated; independent verification against the cited source "
            "is required before it is treated as an actionable opportunity.",
            "Unique organizations use name normalization for counting only; no records or "
            "projects are merged by name.",
        ],
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--batch", type=int, default=200, help="Processing unit, not a cutoff.")
    args = ap.parse_args()
    s = run(args.out, args.batch)
    print(
        json.dumps(
            {
                k: s[k]
                for k in (
                    "records_in_population",
                    "records_evaluated",
                    "records_unprocessed",
                    "unique_projects",
                    "classification",
                )
            },
            indent=2,
        )
    )
