"""Bounded public pursuit research using existing identity, evidence, Jev and worker.

No tier writes, inferred contacts, model-memory facts or outbound communication.
Research snapshots/history and owner notes have separate persistence boundaries.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import Integer, case, func, select
from sqlalchemy.orm import Session

from gridlens.domain.commercial_presentation import commercial_size_status
from gridlens.domain.pursuit_screening import normalized, screen, work_identity
from gridlens.domain.pursuits import MAX_BATCH, MAX_FETCHES, MAX_MODELS, POLICY_VERSION, SOURCES
from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
from gridlens.ingestion.adapters.retained_permits import fields
from gridlens.ingestion.service import _need_has_current_support
from gridlens.intelligence.buying_chain import buying_chain_view, enrich_buying_chain
from gridlens.intelligence.signal_adjudication import adjudicate
from gridlens.jobs.queue import assert_fence
from gridlens.persistence.database import SessionLocal
from gridlens.persistence.models import (
    Evidence,
    Interpretation,
    Job,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    Pursuit,
    PursuitCallNote,
    PursuitDocument,
    PursuitResearchRun,
    Source,
)
from gridlens.settings import settings

CITY_PERMIT_SOURCES = SOURCES[2:]
PRESENTATION_POLICY_VERSION = "pursuit-company-titles-v2"


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


class ResearchBudgetExceeded(Exception):
    """Safe operator-facing bound, never a source exception body."""


def daily_usage(session: Session, model: bool = False) -> int:
    now = datetime.now(UTC).astimezone(ZoneInfo("America/Chicago"))
    day = now.date().isoformat()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    column = PursuitResearchRun.model_count if model else PursuitResearchRun.fetch_count
    key = "model" if model else "fetch"
    legacy = case(
        (PursuitResearchRun.snapshot.has_key("_usage"), 0),
        (PursuitResearchRun.created_at >= midnight, column),
        else_=0,
    )
    counted = func.coalesce(
        PursuitResearchRun.snapshot["_usage"][day][key].astext.cast(Integer), legacy
    )
    return int(session.scalar(select(func.coalesce(func.sum(counted), 0))) or 0)


def candidates(session: Session) -> list[dict]:
    groups: dict[str, dict] = {}
    rows = session.execute(
        select(PowerNeed, Project, Observation, Evidence, Interpretation)
        .join(Project, Project.id == PowerNeed.project_id)
        .join(NeedObservation, NeedObservation.need_id == PowerNeed.id)
        .join(Observation, Observation.id == NeedObservation.observation_id)
        .join(Interpretation, Interpretation.observation_id == Observation.id)
        .join(
            Evidence,
            (Evidence.observation_id == Observation.id)
            & (Evidence.content_hash == Interpretation.assessment["evidence_hash"].astext),
        )
        .where(
            PowerNeed.active.is_(True),
            PowerNeed.tier == "Signal",
            Observation.source_id.in_(SOURCES),
        )
        .order_by(Project.id, Observation.external_id)
    ).all()
    for need, project, observation, evidence, interpretation in rows:
        if not _need_has_current_support(
            session, need, project, links=[(observation, evidence, interpretation)]
        ):
            continue
        assessment = interpretation.assessment or {}
        if (
            commercial_size_status(
                need.required_mw,
                need.activity_key,
                assessment.get("action"),
                assessment.get("reported_power_facts", []),
            )
            == "below_floor"
        ):
            continue
        parsed = {
            k: v[0] for k, v in fields(observation.source_id, evidence.abstract or "").items()
        }
        site = parsed.get("address", project.location or "Site unknown")
        key = work_identity(observation.source_id, observation.external_id, site)
        display_site = site
        if observation.source_id == SOURCES[1]:
            display_site = (
                parsed.get("lease", "Named asset unknown")
                + " · well "
                + parsed.get("well", "unknown")
                + " · "
                + site
            )
        group = groups.setdefault(
            key,
            {
                "identity_key": key,
                "source_id": observation.source_id,
                "site": display_site,
                "projects": [],
                "records": [],
                "facts": [],
            },
        )
        if str(project.id) not in [p["id"] for p in group["projects"]]:
            group["projects"].append(
                {"id": str(project.id), "name": project.name, "location": project.location}
            )
        if str(observation.id) not in [r["observation_id"] for r in group["records"]]:
            group["facts"].append(parsed)
            group["records"].append(
                {
                    "observation_id": str(observation.id),
                    "evidence_id": str(evidence.id),
                    "external_id": observation.external_id,
                    "hash": evidence.content_hash,
                    "url": evidence.url,
                    "title": evidence.title,
                    "text": (evidence.abstract or "").split("\nOpaque source bytes")[0],
                    "published_at": evidence.published_at.isoformat()
                    if evidence.published_at
                    else None,
                    "observed_at": evidence.observed_at.isoformat(),
                }
            )
    for group in groups.values():
        group["screen"] = screen(group["facts"], group["source_id"], datetime.now(UTC).date())
        group["input_hash"] = digest(
            [POLICY_VERSION, PRESENTATION_POLICY_VERSION, group["records"]]
        )
    return list(groups.values())


def select_batch(session: Session, groups: list[dict], *, force: bool = False) -> list[dict]:
    known = {p.identity_key: p for p in session.scalars(select(Pursuit)).all()}

    def ordering(g: dict):
        s = g["screen"]
        previous = known.get(g["identity_key"])
        recent = bool(
            previous
            and previous.last_attempt_at
            and previous.last_attempt_at > datetime.now(UTC) - timedelta(hours=24)
        )
        return (
            recent,
            -s["scope_priority"],
            previous.last_attempt_at.timestamp() if previous and previous.last_attempt_at else 0,
            -s["timing_priority"],
            g["identity_key"],
        )

    eligible = []
    for group in groups:
        s = group["screen"]
        if s["drop_reason"] or s["scope_priority"] == 0:
            continue
        prior = known.get(group["identity_key"])
        fresh = bool(
            prior
            and prior.last_researched_at
            and prior.last_researched_at > datetime.now(UTC) - timedelta(hours=24)
            and prior.snapshot.get("_input_hash") == group["input_hash"]
            and prior.research_status == "succeeded"
        )
        if not force and fresh:
            continue
        eligible.append(group)
    austin = sorted([g for g in eligible if g["source_id"] == SOURCES[0]], key=ordering)[:8]
    # One named fixed asset per operator before a second asset of that operator.
    # This bounds a prolific operator without inventing cross-asset links.
    rrc = sorted([g for g in eligible if g["source_id"] == SOURCES[1]], key=ordering)
    by_operator: dict[str, list[dict]] = defaultdict(list)
    for group in rrc:
        by_operator[group["facts"][0].get("operator_number", group["identity_key"])].append(group)
    diversified: list[dict] = []
    while by_operator and len(diversified) < 4:
        for key in list(by_operator):
            diversified.append(by_operator[key].pop(0))
            if not by_operator[key]:
                del by_operator[key]
            if len(diversified) >= 4:
                break
    city_permits = [
        group
        for source_id in CITY_PERMIT_SOURCES
        for group in sorted((g for g in eligible if g["source_id"] == source_id), key=ordering)[:4]
    ]
    return (austin + city_permits + diversified)[:MAX_BATCH]


def _source(doc: PublicDocument, reason: str, source_date: str) -> dict:
    return {
        "url": doc.url,
        "title": doc.title,
        "excerpt": doc.text[:18000],
        "retrieved_at": doc.observed_at.isoformat(),
        "published_at": doc.published_at.isoformat() if doc.published_at else None,
        "source_date": source_date,
        "match_reason": reason,
        "content_hash": digest([doc.title, doc.text, doc.structured]),
    }


def registration_query(site: str) -> str:
    tokens = normalized(site).split()
    ignored = {"e", "w", "n", "s", "east", "west", "north", "south", "1", "2"}
    street = next(
        (token for token in tokens[1:] if token not in ignored and not token.isdigit()), ""
    )
    return f"{tokens[0]} {street}" if tokens and street else site


def _tabs_match(site: str, data: dict) -> tuple[bool, str]:
    # Base address supports contextual comparison only. It does not merge phases,
    # tenants or areas. Require matching street number + substantive street tokens.
    target = normalized(site).split()
    address = normalized(str(data.get("address", ""))).split()
    ignored = {
        "e",
        "w",
        "n",
        "s",
        "east",
        "west",
        "north",
        "south",
        "rd",
        "road",
        "ln",
        "lane",
        "st",
        "street",
        "blvd",
        "austin",
        "tx",
        "texas",
        "bldg",
        "building",
        "unit",
        "suite",
    }
    street = [t for t in target[1:] if t not in ignored and not t.isdigit()][:1]
    matched = bool(
        target
        and address
        and target[0] == address[0]
        and street
        and all(t in address for t in street)
    )

    # Where both specify a building, it must agree; base address only remains context.
    def building(value: str):
        match = re.search(r"\b(?:bldg|building)\s+([a-z0-9]+)\b", normalized(value))
        return match[1] if match else None

    a, b = building(site), building(str(data.get("address", "")))
    if a and b and a != b:
        matched = False
    return (
        matched,
        (
            "Matching street address; registration scope/phase remains "
            "separate context, not a merged permit."
        ),
    )


def _organization_involvement(role: str | None, facts: list[dict], organization: str) -> str:
    labels = {
        "owner": "Permit-listed owner / occupant; legal ownership unverified",
        "operator": "Permit-listed operator; current operating role unverified",
        "applicant": "Permit-listed applicant; no owner or buyer role inferred",
        "lp_business_name": "Permit-listed LP Business Name; role unverified",
        "contractor": "Permit-listed contractor",
    }
    label = labels.get(role) if role else None
    label = label or "Permit-listed organization; role unknown"
    if role == "contractor":
        trade = next(
            (
                fact.get("contractor_trade") or "contractor"
                for fact in facts
                if fact.get("contractor_company_name") == organization
            ),
            "contractor",
        )
        label += f" · {trade}"
    return label + "; construction/power-package responsibility unverified"


def _snapshot(
    group: dict, docs: list[PublicDocument], buying: dict, model_states: list[str]
) -> dict:
    facts = group["facts"]
    s = group["screen"]
    records = group["records"]
    organization = next(
        (
            f[key]
            for key in ("owner_company_name", "operator", "applicant_org", "lp_business_name")
            for f in facts
            if f.get(key)
        ),
        None,
    )
    organization_role = next(
        (
            role
            for key, role in (
                ("owner_company_name", "owner"),
                ("operator", "operator"),
                ("applicant_org", "applicant"),
                ("lp_business_name", "lp_business_name"),
            )
            for f in facts
            if f.get(key) == organization
        ),
        None,
    )
    if not organization:
        organization = next(
            (f["contractor_company_name"] for f in facts if f.get("contractor_company_name")),
            "Organization unknown",
        )
        organization_role = "contractor" if organization != "Organization unknown" else None
    display_organization = organization or "Organization unknown"
    organization_title_role = (
        "LP Business Name · role unverified"
        if organization_role == "lp_business_name"
        else organization_role
    )
    fallback_activity = next(
        (f.get("description") for f in facts if f.get("description")), "Activity unknown"
    )[:100]
    contacts, people, sources, conflicts, timing, utility, load = [], [], [], [], [], [], []
    registration_context: list[str] = []
    for fact, record in zip(facts, records, strict=True):
        date_label = f"Original permit issue date {fact.get('date', 'unknown')[:10]}"
        if fact.get("amended_date") and fact["amended_date"] != "Unknown":
            date_label += f" · amendment date {fact['amended_date']} (not a new construction start)"
        sources.append(
            {
                "url": record["url"],
                "title": record["title"],
                "excerpt": record["text"][:18000],
                "retrieved_at": record["observed_at"],
                "published_at": record["published_at"],
                "source_date": date_label,
                "match_reason": "Accepted source evidence linked to this physical work scope.",
                "content_hash": record["hash"],
            }
        )
        timing.append(date_label + "; permit approval does not establish construction or startup.")
        for match in re.finditer(
            r"\b\d+(?:\.\d+)?\s*(?:amp(?:s|ere)?|A|[kM]W|[kM]VA|volts?|[kM]?V)\b",
            fact.get("description", ""),
            re.I,
        ):
            load.append(
                f"Reported in permit scope: {match[0]}. Not a rental requirement; "
                f"no MW conversion performed."
            )
        if re.search(
            r"transformer|energiz|temporary service|t-pole", fact.get("description", ""), re.I
        ):
            utility.append(
                "Permit scope: "
                + fact.get("description", "")
                + " No utility delay or rental demand inferred."
            )
        name = fact.get("contractor_full_name")
        org = fact.get("contractor_company_name", organization)
        if name:
            people.append(
                {
                    "name": name,
                    "organization": org,
                    "corporate_role": (
                        "Unknown; permit-listed name only, current employment/title unverified"
                    ),
                    "project_assignment": (
                        "Named on this permit; power-package assignment unverified"
                    ),
                    "purchasing_authority": "Unknown",
                    "source_url": record["url"],
                }
            )
        if fact.get("contractor_phone"):
            contacts.append(
                {
                    "organization": org,
                    "kind": "phone",
                    "value": fact["contractor_phone"],
                    "source_url": record["url"],
                    "label": (
                        "Permit-listed business routing contact; not a verified direct buyer number"
                    ),
                }
            )
    for doc in docs:
        if not doc.structured or "project_number" not in doc.structured[0]:
            continue
        data = doc.structured[0]
        matched, reason = _tabs_match(group["site"], data)
        if not matched:
            continue
        sources.append(_source(doc, reason, "State registration; source publication date unknown"))
        registration_context.append(
            f"Address-matched, unlinked state registration {data.get('project_number')}: "
            f"planned start "
            f"{data.get('start') or 'unknown'}; planned completion "
            f"{data.get('end') or 'unknown'}. Registration scope/area: "
            f"{data.get('scope') or 'unknown'} / {data.get('square_footage') or 'unknown'} SF. "
            f"These planned dates are not assigned to city work or rental duration."
        )
        city_scope = " ".join(f.get("description", "") for f in facts).casefold()
        state_scope = str(data.get("scope", "")) + " " + str(data.get("project_name", ""))
        if re.search(r"data[ -]center", city_scope) and re.search(
            r"(?:ev|electric vehicle).{0,25}charg", state_scope, re.I
        ):
            conflicts.append(
                f"City describes data-center scope; state "
                f"{data.get('project_number')} describes EV charging. Same address "
                f"does not establish the same project or power scope."
            )
        if "manufacturing" in city_scope and re.search(r"office|administrative", state_scope, re.I):
            conflicts.append(
                f"City describes light manufacturing; state "
                f"{data.get('project_number')} describes office work. Areas, phase "
                f"and scope need reconciliation; do not assign state timing to "
                f"city work."
            )
        if not conflicts and re.search(r"data[ -]center", city_scope) != re.search(
            r"data[ -]center", state_scope, re.I
        ):
            # Only an explicit incompatible use is a conflict; silence isn't contradiction.
            if re.search(r"residential|apartment|retail", state_scope, re.I):
                conflicts.append(
                    "Address-matched registration describes a different use; identity "
                    "needs verification."
                )
    for candidate in buying.get("candidates", []):
        if candidate["organization"] == organization:
            for contact in candidate.get("public_contacts", []):
                # Evidence-proven corporate routes remain routing contacts, never named buyers.
                contacts.append(
                    {
                        "organization": organization,
                        "kind": contact["kind"],
                        "value": contact["value"],
                        "source_url": contact["source_url"],
                        "label": "Public business routing contact; purchasing authority unverified",
                    }
                )

    def unique(rows: list) -> list:
        return list({json.dumps(row, sort_keys=True): row for row in rows}.values())

    contacts, people = unique(contacts), unique(people)
    reachable = bool(
        any(c["organization"] == organization for c in contacts)
        and organization != "Organization unknown"
    )
    action = (
        "Drop"
        if s["drop_reason"] or not s["scope_priority"]
        else "Verify first"
        if conflicts
        else "Call now"
        if s["scope_priority"] >= 2 and reachable
        else "Monitor"
    )
    unknowns = [
        (
            "Actual rental-generation requirement and whether utility "
            "temporary service already covers the scope"
        ),
        "Activity-specific MW, voltage, phase, power factor and duty cycle",
        "NG/propane availability, pressure, quality and permitted fuel route",
        "Confirmed work/startup window and meaningful rental duration",
        "Power-package purchasing authority and current project assignment",
    ]
    if not reachable:
        unknowns.append("Reachable relevant organization business contact route")
    if s["fixed_asset"]:
        unknowns.append(
            "W-1 drilling approval is not an injection operating "
            "authorization, well completion or production date; site "
            "construction and electrical design unverified"
        )
    if not settings.typesafe_api_key:
        unknowns.append(
            "Jev unavailable: TYPESAFE_API_KEY is not configured; screening "
            "uses deterministic evidence rules"
        )
    unknowns.append(
        "Corporate-source discovery is not configured in this app runtime; "
        "permit-listed names and routes do not verify current employment or buyer authority"
    )
    unknowns += [v for v in model_states if "unavailable" in v or "error" in v]
    if conflicts:
        next_action = (
            f"Verify the city/state scope and physical work identity at "
            f"{group['site']} before contacting a power buyer."
        )
    elif action == "Call now":
        next_action = (
            f"Call the sourced business routing contact for {organization}, "
            f"cite {records[0]['external_id']} at {group['site']}, and ask who "
            f"owns the temporary/commissioning power package and whether "
            f"utility service covers the scope."
        )
    elif s["fixed_asset"]:
        next_action = (
            f"Verify whether {facts[0].get('lease', 'the named asset')} well "
            f"{facts[0].get('well', 'unknown')} has actual site "
            f"work/electrical design and a power-package contact; do not use "
            f"unrelated regional announcements."
        )
    else:
        next_action = (
            f"Research the current work phase and project contractor business "
            f"route for {group['site']} before a power qualification call."
        )
    reasons = s["ranking_reasons"] + [
        "Sourced project-organization business routing contact is available."
        if reachable
        else "No verified reachable buyer route yet.",
        (
            "NG/propane feasibility unknown; 310/500 kW equipment fit and "
            "scalable demand require qualification."
        ),
    ]
    return {
        "project": (
            f"{organization} · {organization_title_role} · {group['site']}"
            if organization_role
            else f"{group['site']} · {fallback_activity}"
        ),
        "site": group["site"],
        "organization": organization,
        "organization_involvement": _organization_involvement(
            organization_role, facts, display_organization
        ),
        "action_status": action,
        "rank_key": [s["scope_priority"], s["timing_priority"], int(reachable), 0],
        "ranking_reasons": reasons,
        "trigger": " | ".join(dict.fromkeys(f.get("description", "") for f in facts)),
        "trigger_date": sources[0]["source_date"],
        "timing": unique(timing),
        "registration_context": unique(registration_context),
        "people": people,
        "contacts": contacts,
        "load_facts": unique(load),
        "fuel_facts": [],
        "utility_facts": unique(utility),
        "unknowns": unique(unknowns),
        "conflicts": unique(conflicts),
        "next_action": next_action,
        "evidence": sources,
        "tier": "Signal",
    }


def note_view(note: PursuitCallNote) -> dict:
    return {
        key: getattr(note, key)
        for key in (
            "id",
            "client_id",
            "note",
            "outcome",
            "next_action",
            "follow_up",
            "owner",
            "created_at",
        )
    }


def pursuit_view(session: Session, row: Pursuit, *, current: dict[str, dict] | None = None) -> dict:
    item = {
        **row.snapshot,
        "id": row.id,
        "project_id": row.project_id,
        "project_ids": row.project_ids,
        "last_researched_at": row.last_researched_at,
        "last_attempt_at": row.last_attempt_at,
        "research_status": row.research_status,
        "research_errors": row.research_errors,
        "notes": [
            note_view(n)
            for n in session.scalars(
                select(PursuitCallNote)
                .where(PursuitCallNote.pursuit_id == row.id)
                .order_by(PursuitCallNote.created_at.desc(), PursuitCallNote.id)
            ).all()
        ],
    }

    current = (
        current if current is not None else {g["identity_key"]: g for g in candidates(session)}
    )
    group = current.get(row.identity_key)
    reason = (
        "No currently supported active Signal; retained for research and call history."
        if group is None
        else group["screen"]["drop_reason"]
        or (
            "Current accepted scope has no specific power trigger."
            if not group["screen"]["scope_priority"]
            else None
        )
    )
    if reason:
        item["action_status"] = "Drop"
        item["ranking_reasons"] = [reason] + item["ranking_reasons"]
        item["next_action"] = "Review retained history; no active power pursuit is supported."
    elif group is not None and row.snapshot.get("_input_hash") != group["input_hash"]:
        item["action_status"] = "Verify first"
        item["ranking_reasons"] = [
            "Accepted project evidence changed since saved research."
        ] + item["ranking_reasons"]
        item["next_action"] = "Refresh research to reconcile the changed accepted project evidence."
    return item


def list_pursuits(session: Session, *, include_dropped: bool = False, offset: int = 0) -> dict:
    current = {g["identity_key"]: g for g in candidates(session)}
    rows = session.scalars(select(Pursuit)).all()
    items, excluded = [], 0
    for row in rows:
        if not row.snapshot:
            continue
        item = pursuit_view(session, row, current=current)
        if item["action_status"] == "Drop":
            excluded += 1
            if not include_dropped:
                continue
        items.append(item)
    items.sort(
        key=lambda i: (i["action_status"] == "Drop", *[-n for n in i["rank_key"]], str(i["id"]))
    )
    jobs = session.scalars(
        select(Job).where(Job.kind == "pursuit_research").order_by(Job.created_at.desc()).limit(5)
    ).all()
    return {
        "usage": {
            "fetch_requests_today": daily_usage(session),
            "model_requests_today": daily_usage(session, True),
            "daily_fetch_limit": settings.pursuits_daily_fetch_limit,
            "daily_model_limit": settings.pursuits_daily_model_limit,
            "batch_candidates": MAX_BATCH,
            "batch_fetch_limit": MAX_FETCHES,
        },
        "items": items[offset : offset + 10] if include_dropped else items[:10],
        "total": len(items),
        "offset": offset if include_dropped else 0,
        "excluded_count": excluded,
        "jobs": [job_view(j) for j in jobs],
    }


def job_view(job: Job) -> dict:
    return {
        key: getattr(job, key)
        for key in ("id", "status", "attempts", "error", "created_at", "checkpoint")
    }


def process_research_job(job_id: UUID, worker_id: str, fence: int) -> None:
    """Each request debit and completed candidate is committed under the job fence.

    A crash retains already completed candidates and all incurred request budgets.
    Interrupted candidates retry through the same lease/backoff mechanism.
    """
    from gridlens.ingestion.adapters import pursuit_public as public

    deadline = time.monotonic() + 350
    with SessionLocal() as session:
        job = assert_fence(session, job_id, worker_id, fence)
        state = (
            json.loads(job.checkpoint) if job.checkpoint and job.checkpoint.startswith("{") else {}
        )
        groups = candidates(session)
        selected = select_batch(session, groups, force=bool(state.get("force")))
        session.commit()
    batch_fetches = batch_models = 0
    rrc_cache: list[dict] | None = None
    rrc_error: str | None = None
    rrc_archives: dict[str, list[dict] | None] = {}
    city_records: dict[str, dict[str, dict]] = {}
    city_errors: dict[str, str] = {}
    for group in selected:
        if time.monotonic() >= deadline:
            raise TimeoutError("Pursuit batch deadline exhausted")
        with SessionLocal() as session:
            assert_fence(session, job_id, worker_id, fence)
            row = session.scalar(
                select(Pursuit).where(Pursuit.identity_key == group["identity_key"])
            )
            if row is None:
                row = Pursuit(
                    identity_key=group["identity_key"],
                    project_id=UUID(group["projects"][0]["id"]),
                    project_ids=[p["id"] for p in group["projects"]],
                )
                session.add(row)
                session.flush()
            row.project_ids = [p["id"] for p in group["projects"]]
            completed = session.scalar(
                select(PursuitResearchRun).where(
                    PursuitResearchRun.job_id == job_id,
                    PursuitResearchRun.pursuit_id == row.id,
                    PursuitResearchRun.input_hash == group["input_hash"],
                    PursuitResearchRun.status.in_(["succeeded", "partial", "failed"]),
                )
            )
            if completed:
                session.commit()
                continue
            run = PursuitResearchRun(
                job_id=job_id,
                pursuit_id=row.id,
                input_hash=group["input_hash"],
                policy_version=POLICY_VERSION,
            )
            session.add(run)
            row.last_attempt_at = datetime.now(UTC)
            row.research_status = "running"
            session.commit()

            def debit(model: bool = False, *, run: PursuitResearchRun = run) -> None:
                nonlocal batch_fetches, batch_models
                assert_fence(session, job_id, worker_id, fence)
                used = daily_usage(session, model)
                cap = (
                    settings.pursuits_daily_model_limit
                    if model
                    else settings.pursuits_daily_fetch_limit
                )
                batch_used, batch_limit = (
                    (batch_models, MAX_MODELS) if model else (batch_fetches, MAX_FETCHES)
                )
                if used >= cap or batch_used >= batch_limit or time.monotonic() >= deadline:
                    raise ResearchBudgetExceeded(
                        "Daily or batch research request cap/deadline reached; "
                        "work is paused and previous findings retain their actual freshness"
                    )
                day = datetime.now(UTC).astimezone(ZoneInfo("America/Chicago")).date().isoformat()
                usage = dict(run.snapshot.get("_usage", {}))
                counts = dict(usage.get(day, {"fetch": 0, "model": 0}))
                key = "model" if model else "fetch"
                counts[key] = counts.get(key, 0) + 1
                usage[day] = counts
                run.snapshot = {**run.snapshot, "_usage": usage}
                if model:
                    run.model_count += 1
                    batch_models += 1
                else:
                    run.fetch_count += 1
                    batch_fetches += 1
                session.commit()

            errors: list[str] = []
            docs: list[PublicDocument] = []
            fresh_facts: list[dict[str, str]] = []
            fresh_records: list[dict] = []

            def failure(label: str, exc: Exception, *, errors: list[str] = errors):
                errors.append(
                    str(exc)
                    if isinstance(exc, ResearchBudgetExceeded)
                    else f"{label}: {type(exc).__name__}; source was not freshly verified."
                )

            if group["source_id"] == SOURCES[0]:
                for record in group["records"]:
                    try:
                        doc = public.retrieve_austin(
                            record["external_id"], deadline=deadline, on_request=debit
                        )
                        data = doc.structured[0]
                        from gridlens.ingestion.adapters.socrata_permits import MAPS

                        mapping = MAPS[SOURCES[0]]
                        fact = {
                            key: str(data.get(field, "")) for key, field in mapping.items() if field
                        }
                        if normalized(fact.get("address", "")) != normalized(group["site"]):
                            raise ValueError("Fresh source site identity changed")
                        docs.append(doc)
                        fresh_facts.append(fact)
                        fresh_records.append(
                            {
                                **record,
                                "text": doc.text,
                                "url": doc.url,
                                "observed_at": doc.observed_at.isoformat(),
                                "hash": digest(doc.text),
                                "published_at": None,
                            }
                        )
                    except Exception as exc:
                        failure("Exact official permit retrieval", exc)
                # Registration query is generic site research, never a challenge-case lookup.
                try:
                    docs.extend(
                        public.retrieve_tabs(
                            registration_query(group["site"]),
                            deadline=deadline,
                            on_request=debit,
                            fetch_limit=3,
                        )
                    )
                except Exception as exc:
                    failure("State project-registration research", exc)
            elif group["source_id"] in CITY_PERMIT_SOURCES:
                source_id = group["source_id"]
                try:
                    if source_id not in city_records and source_id not in city_errors:
                        debit()
                        source = session.get(Source, source_id)
                        if source is None:
                            raise LookupError("Registered city permit source is unavailable")
                        from gridlens.ingestion.adapters import retrieve_source

                        rows = retrieve_source(
                            {
                                "id": source.id,
                                "endpoint": source.endpoint,
                                "retrieval_method": source.retrieval_method,
                            }
                        )
                        city_records[source_id] = {item["document_number"]: item for item in rows}
                    if source_id in city_errors:
                        raise RuntimeError(city_errors[source_id])
                    current = city_records[source_id]
                    for record in group["records"]:
                        fresh = current.get(record["external_id"])
                        if fresh is None:
                            errors.append(
                                "Exact permit row is absent from the current bounded city source; "
                                "prior evidence retains its original date."
                            )
                            continue
                        parsed = {
                            key: value[0]
                            for key, value in fields(source_id, fresh["abstract"]).items()
                        }
                        if normalized(parsed.get("address", "")) != normalized(group["site"]):
                            raise ValueError("Fresh city permit site identity changed")
                        observed = datetime.now(UTC)
                        doc = PublicDocument(
                            fresh["html_url"],
                            fresh["title"],
                            f"{fresh['title']}\n{fresh.get('abstract') or ''}",
                            None,
                            observed,
                            fresh.get("extraction_location", "official city permit row"),
                        )
                        docs.append(doc)
                        fresh_facts.append(parsed)
                        fresh_records.append(
                            {
                                **record,
                                "text": doc.text,
                                "url": doc.url,
                                "observed_at": observed.isoformat(),
                                "hash": fresh.get("source_hash") or digest(doc.text),
                                "published_at": None,
                            }
                        )
                except Exception as exc:
                    city_errors.setdefault(source_id, type(exc).__name__)
                    failure("Exact current city permit retrieval", exc)
            else:
                if rrc_cache is None and rrc_error is None:
                    try:
                        rrc_cache = public.retrieve_rrc_snapshot(
                            deadline=deadline, on_request=debit
                        )
                    except Exception as exc:
                        rrc_error = (
                            str(exc)
                            if isinstance(exc, ResearchBudgetExceeded)
                            else type(exc).__name__
                        )
                if rrc_cache is not None:
                    lookup = {r["document_number"]: r for r in rrc_cache}
                    for record in group["records"]:
                        fresh = lookup.get(record["external_id"])
                        historical = False
                        if fresh is None:
                            provenance = next(
                                (
                                    line.partition(": ")[2]
                                    for line in record["text"].splitlines()
                                    if line.startswith("Source segment provenance: ")
                                ),
                                "[]",
                            )
                            try:
                                versions = json.loads(provenance)
                                filenames = list(
                                    dict.fromkeys(
                                        v.get("filename", "")
                                        for v in versions
                                        if isinstance(v, dict)
                                        and re.fullmatch(
                                            r"daf420\.dat\.\d{2}-\d{2}-\d{4}", v.get("filename", "")
                                        )
                                    )
                                )
                                for filename in filenames:
                                    if filename not in rrc_archives and len(rrc_archives) < 2:
                                        try:
                                            rrc_archives[filename] = public.retrieve_rrc_archive(
                                                filename, deadline=deadline, on_request=debit
                                            )
                                        except Exception as exc:
                                            rrc_archives[filename] = None
                                            failure("Cited historical RRC archive retrieval", exc)
                                    if filename not in rrc_archives:
                                        errors.append(
                                            f"Cited historical archive {filename} deferred: "
                                            "two-file batch cap "
                                            "reached; this archive was not checked."
                                        )
                                    archival = rrc_archives.get(filename) or []
                                    fresh = next(
                                        (
                                            r
                                            for r in archival
                                            if r["document_number"] == record["external_id"]
                                        ),
                                        None,
                                    )
                                    if fresh:
                                        historical = True
                                        break
                            except (ValueError, TypeError, KeyError):
                                errors.append(
                                    "Historical RRC provenance is invalid; no archive inferred."
                                )
                        if historical:
                            errors.append(
                                "Cited historical EOM approval was re-retrieved; asset absent from "
                                "the current daily file. Current work, completion and "
                                "startup remain unverified."
                            )
                        if fresh:
                            fact = {
                                k: v[0] for k, v in fields(SOURCES[1], fresh["abstract"]).items()
                            }
                            fresh_facts.append(fact)
                            fresh_records.append(
                                {
                                    **record,
                                    "text": fresh["abstract"].split("\nOpaque source bytes")[0],
                                    "url": fresh["html_url"],
                                    "observed_at": datetime.now(UTC).isoformat(),
                                    "hash": fresh["source_hash"],
                                    "published_at": None,
                                }
                            )
                        else:
                            errors.append(
                                "Named asset absent from the freshly retrieved daily RRC file. "
                                "Prior archive approval retains its original retrieval time."
                            )
                else:
                    errors.append(
                        f"Official RRC retrieval: {rrc_error}; prior "
                        f"approval was not freshly verified."
                    )
            effective = group
            if fresh_facts and len(fresh_facts) == len(group["records"]):
                effective = {
                    **group,
                    "facts": fresh_facts,
                    "records": fresh_records,
                    "screen": screen(fresh_facts, group["source_id"], datetime.now(UTC).date()),
                }
            model_states = []
            if settings.typesafe_api_key and batch_models < MAX_MODELS:
                # Jev interprets only existing retained, evidence-bound input. It is
                # not a public-source retriever, buyer verifier or promotion gate.
                for record in group["records"][:1]:
                    try:
                        obs = session.get(Observation, UUID(record["observation_id"]))
                        evidence = session.get(Evidence, UUID(record["evidence_id"]))
                        assert obs and evidence
                        from gridlens.intelligence.signal_adjudication import _jev_call

                        decision = adjudicate(
                            session,
                            obs,
                            evidence,
                            retry_errors=True,
                            caller=lambda state, key: _jev_call(
                                state, key, on_request=lambda: debit(model=True)
                            ),
                        )
                        if decision.source == "jev_error":
                            errors.append(
                                "Jev interpretation unavailable or malformed; evidence retained "
                                "and interpretation deferred for a later bounded research job."
                            )
                        model_states.append(
                            f"Jev/display evidence adjudication: "
                            f"{decision.source} / {decision.decision}"
                        )
                    except Exception as exc:
                        failure("Evidence-bound Jev adjudication", exc)
            try:
                # Retained permit fields reuse existing buying enrichment with no
                # extra network, then the view conservatively labels permit people.
                buying = enrich_buying_chain(
                    session,
                    row.project_id,
                    fetcher=lambda url: (_ for _ in ()).throw(
                        RuntimeError(
                            "Additional corporate retrieval requires a configured primary source"
                        )
                    ),
                )
            except Exception as exc:
                buying = buying_chain_view(session, row.project_id)
                failure("Buying-path enrichment", exc)
            assert_fence(session, job_id, worker_id, fence)
            snapshot = _snapshot(effective, docs, buying, model_states)
            snapshot["_input_hash"] = group["input_hash"]
            if errors and row.snapshot:
                # Failed inputs retain previous sourced registration/conflict and
                # contact findings with their actual freshness; never erase them.
                old = row.snapshot
                for field in ("conflicts", "timing", "registration_context", "evidence"):
                    values = snapshot[field] + old.get(field, [])
                    snapshot[field] = list(
                        {json.dumps(v, sort_keys=True): v for v in values}.values()
                    )
                if snapshot["conflicts"] and snapshot["action_status"] != "Drop":
                    snapshot["action_status"] = "Verify first"
                    snapshot["next_action"] = old.get("next_action", snapshot["next_action"])
            if not fresh_facts and row.snapshot:
                # No exact project source succeeded: do not substitute a fresh
                # timestamp or model assessment for the last accepted findings.
                snapshot = {**row.snapshot}
            for source in snapshot["evidence"]:
                existing = session.scalar(
                    select(PursuitDocument).where(
                        PursuitDocument.pursuit_id == row.id,
                        PursuitDocument.url == source["url"],
                        PursuitDocument.content_hash == source["content_hash"],
                    )
                )
                if existing is None:
                    session.add(
                        PursuitDocument(
                            pursuit_id=row.id,
                            url=source["url"],
                            content_hash=source["content_hash"],
                            source=source,
                        )
                    )
            run.status = (
                "partial" if fresh_facts and errors else "succeeded" if fresh_facts else "failed"
            )
            run.errors, run.snapshot = (
                errors,
                {**snapshot, "_usage": run.snapshot.get("_usage", {})},
            )
            row.snapshot, row.research_errors, row.research_status = snapshot, errors, run.status
            if fresh_facts and not errors:
                row.last_researched_at = datetime.now(UTC)
            job = assert_fence(session, job_id, worker_id, fence)
            job.checkpoint = json.dumps({**state, "last_pursuit_id": str(row.id)})
            session.commit()
    with SessionLocal.begin() as session:
        job = assert_fence(session, job_id, worker_id, fence)
        job.status, job.lease_owner, job.lease_until = "succeeded", None, None
        job.error = None
