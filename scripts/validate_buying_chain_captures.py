"""Replay unedited real captures through production GL3-017 code, isolated PostgreSQL schema.
Run from backend with PYTHONPATH=src and the repository's test env loaded.
No org/person claims are seeded. Not a live network or browser acceptance test.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import re
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.domain.permit_interpretation import assess_permit
from gridlens.ingestion.adapters.buying_chain_public import parse_document
from gridlens.intelligence.buying_chain import buying_chain_view, enrich_buying_chain
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    BuyingChainClaim,
    BuyingChainEvidence,
    BuyingChainRun,
    Evidence,
    Interpretation,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    Source,
)
from gridlens.settings import settings

PARSER_FILES = [
    "backend/src/gridlens/ingestion/adapters/buying_chain_public.py",
    "backend/src/gridlens/intelligence/buying_chain_extraction.py",
    "backend/src/gridlens/intelligence/buying_chain.py",
    "backend/src/gridlens/domain/buying_chain.py",
    "backend/src/gridlens/persistence/models.py",
]
TARGETS = [
    (
        "3459792",
        "https://gurtzelectric.com/david-steffenhagen/",
        "GURTZ ELECTRIC COMPANY",
        "David Steffenhagen",
    ),
    ("3451848", "https://kelso-burnett.com/about", "KELSO-BURNETT CO.", "Jeff Weir"),
    ("3442494", "https://kelso-burnett.com/about", "KELSO-BURNETT CO.", "Jeff Weir"),
]


def sha(body):
    return hashlib.sha256(body).hexdigest()


def dt(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def d(value):
    return date.fromisoformat(value) if value else None


def scalar_json(value):
    if isinstance(value, date | datetime | UUID):
        return value.isoformat() if not isinstance(value, UUID) else str(value)
    raise TypeError(type(value).__name__)


def fingerprints(repo):
    return {path: sha((repo / path).read_bytes()) for path in PARSER_FILES}


def counts(session):
    return {
        m.__tablename__: session.scalar(select(func.count()).select_from(m))
        for m in (
            Source,
            Project,
            Observation,
            Evidence,
            Interpretation,
            PowerNeed,
            NeedObservation,
            BuyingChainClaim,
            BuyingChainEvidence,
            BuyingChainRun,
        )
    }


def need_snapshot(session):
    return [
        dict(
            id=str(n.id),
            project_id=str(n.project_id),
            tier=n.tier,
            activity=n.activity_key,
            required_mw=n.required_mw,
            start_window=n.start_window,
            duration=n.duration,
            supply=n.supply,
        )
        for n in session.scalars(select(PowerNeed).order_by(PowerNeed.id))
    ]


def main():
    args = argparse.ArgumentParser()
    args.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    args.add_argument("--captures", type=Path, required=True)
    args.add_argument("--output", type=Path, default=None)
    args = args.parse_args()
    repo = args.repo.resolve()
    assert (
        Path(inspect.getfile(enrich_buying_chain)).resolve()
        == (repo / "backend/src/gridlens/intelligence/buying_chain.py").resolve()
    ), "PYTHONPATH must load production modules from --repo"
    now = datetime.now(UTC)
    output = args.output or repo / "docs/validation/gl3-017-real-acceptance.json"
    manifest = json.loads((args.captures / "manifest.json").read_text())
    corpus_path = repo / "docs/validation/gl3-016-jev-corpus.json"
    corpus = json.loads(corpus_path.read_text())
    initial_fingerprints = fingerprints(repo)
    attempts = []
    if output.exists():
        previous = json.loads(output.read_text())
        attempts = list(previous.get("previous_attempts", []))
        attempts.append(
            {
                k: previous[k]
                for k in (
                    "executed_at",
                    "status",
                    "counts_after",
                    "failures",
                    "failure_diagnostics",
                    "implementation_sha256_after",
                )
                if k in previous
            }
        )
    capture_by_url = {}
    source_manifest = []
    for capture in manifest["captures"]:
        body = (args.captures / Path(capture["path"]).name).read_bytes()
        assert sha(body) == capture["sha256"], "Capture SHA256 mismatch"
        assert len(body) == capture["bytes"], "Capture size mismatch"
        capture_by_url[capture["url"]] = (capture, body)
        source_manifest.append(
            {
                k: capture.get(k)
                for k in (
                    "url",
                    "httpStatus",
                    "fetchedAt",
                    "fetchedAt_note",
                    "contentType",
                    "format",
                    "fetch_method",
                    "sha256",
                    "bytes",
                    "body_provenance",
                )
            }
        )

    def lookup(url):
        if url in capture_by_url:
            return capture_by_url[url]
        p = urlsplit(url)
        q = parse_qs(p.query)
        matched = re.fullmatch(r"id='(\d+)'", q.get("$where", [""])[0])
        if (
            p.hostname == "data.cityofchicago.org"
            and p.path == "/resource/ydr8-5enu.json"
            and matched
        ):
            for capture, body in capture_by_url.values():
                if (
                    capture["contentType"].startswith("application/json")
                    and json.loads(body)[0]["id"] == matched[1]
                ):
                    assert len(json.loads(body)) == 1
                    return capture, body
        raise LookupError("No real capture retained for requested URL")

    fetched = []

    def fetch(url):
        capture, body = lookup(url)
        parsed = parse_document(url, body, capture["contentType"])
        parsed = replace(parsed, observed_at=dt(capture["fetchedAt"]))
        fetched.append(
            dict(
                requested_url=url,
                captured_url=capture["url"],
                capture_sha256=capture["sha256"],
                source_fetched_at=capture["fetchedAt"],
                parsed_title=parsed.title,
                parsed_text_sha256=sha(parsed.text.encode()),
                parsed_text_characters=len(parsed.text),
                publication_date=parsed.published_at,
                structured_records=len(parsed.structured),
            )
        )
        return parsed

    target_db, app_db = make_url(settings.test_database_url), make_url(settings.database_url)
    assert target_db.database.endswith("_test") and target_db != app_db
    schema = "gl3_017_acceptance_" + uuid4().hex[:12]
    control = create_engine(settings.test_database_url)
    with control.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        settings.test_database_url, connect_args={"options": f"-csearch_path={schema}"}
    )
    factory = sessionmaker(engine, expire_on_commit=False)
    result = dict(
        schema_version="gl3-017-captured-real-acceptance-v1",
        executed_at=now,
        status="running",
        scope=(
            "Captured-real-source production parser, extraction, PostgreSQL persistence "
            "and unchanged replay"
        ),
        direct_application_network_fetch="NOT VERIFIED",
        browser_interaction="NOT VERIFIED",
        source_corpus=dict(
            path=str(corpus_path.relative_to(repo)),
            sha256=sha(corpus_path.read_bytes()),
            source=corpus["source"],
            original_export_sha256=corpus["source_sha256"],
        ),
        seed_contract=(
            "Dedicated disposable test schema reconstructs the three already-accepted "
            "GL3-016 source identities and exact retained corpus evidence. Baseline "
            "Signal power activity and rationale are reconstructed by production "
            "assess_permit from original corpus fields. No organization, person, title, "
            "contact or buying-chain claim is seeded. Reconstruction UUIDs are "
            "deterministic local IDs, not original physical Project UUIDs."
        ),
        date_contract=(
            "Captured permit issue_date remains an event date; captured full permit and "
            "corporate sources have no publication date. Historical corpus publication "
            "dates are preserved without treating them as newly fetched source "
            "publication dates. Reconstructed original-evidence observed_at is execution "
            "time, not a claim about original corpus retrieval."
        ),
        url_contract=(
            "The application exact-record query uses $limit=1; retained municipal capture "
            "uses $limit=5 and contains exactly the same single selected record. Both "
            "requested and captured URLs are recorded; no native HTTP byte equivalence is "
            "claimed."
        ),
        source_manifest=source_manifest,
        implementation_sha256_before=initial_fingerprints,
        previous_attempts=attempts,
        validator_sha256=sha(Path(__file__).read_bytes()),
        projects=[],
        failures=[],
    )
    try:
        Base.metadata.create_all(engine)
        source_definition = next(
            s
            for s in json.loads((repo / "config/sources/registry.v1.json").read_text())["sources"]
            if s["id"] == "chicago-building-permits"
        )
        with factory.begin() as session:
            fields = {
                k: source_definition[k]
                for k in (
                    "id",
                    "publisher",
                    "endpoint",
                    "family",
                    "geography",
                    "industries",
                    "retrieval_method",
                    "cadence_hours",
                    "enabled",
                )
            }
            session.add(Source(**fields, health={}))
            session.flush()
            for external_id, _, _, _ in TARGETS:
                record = next(
                    r
                    for r in corpus["records"]
                    if r["state"]["title"].startswith(f"Chicago building permit {external_id} ")
                )
                state = record["state"]
                digest = record["evidence_hash"]
                identity = f"chicago-building-permits:{external_id}"
                original_fields = dict(
                    line.split(": ", 1) for line in state["abstract"].splitlines()
                )
                ordinary_permit = dict(
                    row_id=external_id,
                    description=original_fields["description"],
                    status=original_fields["status"],
                    address=" ".join(
                        original_fields.get(k, "")
                        for k in ("address", "street_direction", "street_name")
                    ).strip(),
                    city=source_definition["city"],
                    state=source_definition["state"],
                    project=original_fields.get("project"),
                )
                baseline_assessment = assess_permit(
                    dict(
                        permit=ordinary_permit,
                        event_date=state["event_date"],
                        html_url=state["url"],
                    ),
                    as_of=now.date(),
                )
                assert baseline_assessment["decision"] == "accepted"
                assert (
                    baseline_assessment["subject"] == state["project_name"]
                    and baseline_assessment["location"] == state["location"]
                )
                project = Project(
                    id=uuid5(NAMESPACE_URL, identity),
                    identity_key=identity,
                    name=state["project_name"],
                    location=state["location"],
                    source_id=state["source_id"],
                    external_id=external_id,
                    asset_type=state["asset_type"],
                    identity_facts={},
                )
                obs = Observation(
                    id=uuid5(NAMESPACE_URL, identity + ":observation"),
                    source_id=state["source_id"],
                    external_id=external_id,
                    title=state["title"],
                    abstract=state["abstract"],
                    published_at=d(state["published_at"]),
                    url=state["url"],
                    content_hash=digest,
                )
                session.add_all([project, obs])
                session.flush()
                session.add(
                    Evidence(
                        id=uuid5(NAMESPACE_URL, identity + ":evidence:" + digest),
                        observation_id=obs.id,
                        content_hash=digest,
                        title=state["title"],
                        abstract=state["abstract"],
                        url=state["url"],
                        published_at=d(state["published_at"]),
                        observed_at=now,
                        extraction_location="retained GL3-016 corpus evidence",
                        event_date=d(state["event_date"]),
                        event_date_label=state["event_date_label"],
                    )
                )
                # This acceptance reconstruction preserves pre-existing Signal acceptance only.
                # Enrichment is not allowed to create or promote a power need.
                session.add(
                    Interpretation(
                        observation_id=obs.id,
                        content_hash=digest,
                        status="accepted",
                        assessment={
                            **baseline_assessment,
                            "evidence_hash": digest,
                            "semantic_hash": digest,
                            "project_identity_key": identity,
                        },
                    )
                )
                need = PowerNeed(
                    id=UUID(record["record_id"]),
                    project_id=project.id,
                    activity_key=baseline_assessment["power_activity"],
                    tier=baseline_assessment["tier"],
                    rationale=baseline_assessment["reason"],
                )
                session.add(need)
                session.flush()
                session.add(NeedObservation(need_id=need.id, observation_id=obs.id))
        with factory() as session:
            result["counts_before"] = counts(session)
            result["power_needs_before"] = need_snapshot(session)
        for external_id, role_url, expected_org, expected_person in TARGETS:
            project_id = uuid5(NAMESPACE_URL, f"chicago-building-permits:{external_id}")
            fetched.clear()
            with factory.begin() as session:
                project = session.get(Project, project_id)
                baseline_counts = counts(session)
                first = enrich_buying_chain(
                    session, project_id, source_urls=[role_url], fetcher=fetch, now=now
                )
                first_fetches = list(fetched)
                after = counts(session)
            # Separate committed transactions verify durable persistence, then replay.
            with factory() as session:
                reloaded = buying_chain_view(session, project_id, now=now)
                durable_ids = {str(c["id"]) for c in reloaded["candidates"]}
            fetched.clear()
            with factory.begin() as session:
                second = enrich_buying_chain(
                    session,
                    project_id,
                    source_urls=[role_url],
                    fetcher=fetch,
                    now=now + timedelta(minutes=2),
                )
                replay_counts = counts(session)
                candidates = second["candidates"]
                named = [c for c in candidates if c["person_name"]]
                wanted = [
                    c
                    for c in named
                    if c["person_name"] == expected_person and c["organization"] == expected_org
                ]
                stored = session.scalars(
                    select(BuyingChainEvidence).where(BuyingChainEvidence.project_id == project_id)
                ).all()
                citation_integrity = all(
                    any(str(e.id) == str(cite["id"]) and cite["quote"] in e.excerpt for e in stored)
                    for c in candidates
                    for cite in c["evidence"]
                )
                checks = dict(
                    expected_named_chain_present=len(wanted) == 1,
                    expected_chain_role_supported=len(wanted) == 1
                    and wanted[0]["organization_relationship"] == "DIRECT"
                    and wanted[0]["person_organization_relationship"] == "CURRENT"
                    and wanted[0]["person_project_relationship"] == "ROLE_SUPPORTED",
                    unchanged_replay_counts=after == replay_counts,
                    committed_round_trip_ids={str(c["id"]) for c in first["candidates"]}
                    == durable_ids,
                    durable_candidate_ids_unchanged=durable_ids
                    == {str(c["id"]) for c in candidates},
                    no_named_direct_assignment=all(
                        c["person_project_relationship"] != "DIRECT" for c in named
                    ),
                    unknown_authority_exposed=any(
                        "purchasing authority" in u and "UNKNOWN" in u for u in second["unresolved"]
                    ),
                    exact_citation_substrings=citation_integrity,
                    no_fabricated_contacts=all(not c["public_contacts"] for c in candidates),
                    corporate_publication_unknown=all(
                        f["publication_date"] is None
                        for f in first_fetches
                        if f["captured_url"] == role_url
                    ),
                    corporate_role_evidence_retained=any(e.url == role_url for e in stored),
                )
                per = dict(
                    external_id=external_id,
                    project_id=project_id,
                    original_corpus_record_id=next(
                        r["record_id"]
                        for r in corpus["records"]
                        if r["state"]["title"].startswith(f"Chicago building permit {external_id} ")
                    ),
                    project_name=project.name,
                    location=project.location,
                    role_url=role_url,
                    expected_comparison_only=dict(
                        organization=expected_org, person=expected_person
                    ),
                    first_fetches=first_fetches,
                    replay_fetches=list(fetched),
                    counts_before=baseline_counts,
                    counts_after_first=after,
                    counts_after_replay=replay_counts,
                    candidate_count=len(candidates),
                    named_candidate_count=len(named),
                    checks=checks,
                    parsed_result=second,
                )
                result["projects"].append(per)
                for key, value in checks.items():
                    if not value:
                        result["failures"].append(f"{external_id}: {key}")
                print(
                    json.dumps(
                        dict(
                            external_id=external_id,
                            candidates=len(candidates),
                            people=[c["person_name"] for c in named],
                            checks=checks,
                        )
                    )
                )
        with factory() as session:
            result["counts_after"] = counts(session)
            result["power_needs_after"] = need_snapshot(session)
        result["checks"] = {
            "source_bytes_match_manifest": True,
            "no_tier_or_power_claim_changes": result["power_needs_before"]
            == result["power_needs_after"],
            "production_files_unchanged_during_run": initial_fingerprints == fingerprints(repo),
        }
        result["implementation_sha256_after"] = fingerprints(repo)
        for key, value in result["checks"].items():
            if not value:
                result["failures"].append(key)
        result["status"] = (
            "PASS_CAPTURED_SOURCE_ONLY" if not result["failures"] else "FAIL_CAPTURED_SOURCE"
        )
    except Exception as exc:
        result["status"] = "ERROR"
        result["failures"].append(f"{type(exc).__name__}: {exc}")
        raise
    finally:
        result["finished_at"] = datetime.now(UTC)
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2, default=scalar_json) + "\n")
        finally:
            engine.dispose()
            with control.begin() as conn:
                conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            control.dispose()
    print(
        json.dumps(
            dict(
                status=result["status"],
                counts=result["counts_after"],
                failures=result["failures"],
                output=str(output),
            )
        )
    )
    return 0 if not result["failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
