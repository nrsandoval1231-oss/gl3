"""Run unchanged browser workflows against a new, isolated SYNTHETIC database.

This is workflow proof, never retained PR23 corpus or live-source proof. No fixture
is installed into the application database. Public source URLs describe fixture
shapes only; this runner performs no external source acquisition or model calls.
The created database and receipt remain available for inspection; none is dropped.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))


def npm_command(arguments: list[str], *, windows: bool | None = None) -> list[str]:
    """Resolve npm's platform executable for subprocess-based browser runs."""
    is_windows = os.name == "nt" if windows is None else windows
    executable = shutil.which("npm.cmd" if is_windows else "npm")
    if executable is None:
        raise FileNotFoundError("npm executable is not available on PATH")
    return [executable, *arguments]


def fixtures(definitions):
    from gridlens.ingestion.adapters.el_paso_permits import _row
    from gridlens.ingestion.adapters.socrata_permits import render_record

    today = datetime.now(UTC).date()
    dated = (today - timedelta(days=4)).isoformat()
    scopes = [
        ("100 KRAMER LN", "800A construction power temporary service"),
        ("811 CLAYTON LN", "New Data Center construction temporary power service"),
        (
            "6301 E STASSNEY LN BLDG 8",
            "New light manufacturing construction temporary power service",
        ),
        *[
            (f"{200 + i} SYNTHETIC ACCEPTANCE LN", "New Data Center foundation construction")
            for i in range(9)
        ],
    ]
    austin = [
        {
            "permit_number": f"{today.year}-{990001 + index} EP",
            "issue_date": dated,
            "description": (
                f"{scope}. SYNTHETIC browser acceptance fixture; not a real project claim."
            ),
            "original_address1": address,
            "original_city": "Austin",
            "original_state": "TX",
            "permit_class_mapped": "Commercial",
            "work_class": "New",
            "permit_type_desc": "Electrical Permit",
            "status_current": "Active",
            "project_id": f"synthetic-browser-{index}",
            "contractor_company_name": f"Synthetic Acceptance Electric {index} LLC",
            "contractor_full_name": "Synthetic Fixture Person",
            "contractor_phone": "5125550100",
        }
        for index, (address, scope) in enumerate(scopes)
    ]
    chicago = {
        "id": "999999991",
        "permit_": "SYNTHETIC-DC-001",
        "issue_date": dated,
        "work_description": (
            "Convert existing office building into a data center. "
            "SYNTHETIC browser acceptance fixture."
        ),
        "work_type": "NEW CONSTRUCTION",
        "permit_type": "PERMIT - NEW CONSTRUCTION",
        "permit_status": "ISSUED",
        "street_number": "400",
        "street_direction": "S",
        "street_name": "LASALLE",
        "contact_1_type": "CONTRACTOR-ELECTRICAL",
        "contact_1_name": "Synthetic Chicago Electric LLC",
    }
    georgia_url = "https://epd.georgia.gov/document/document/synthetic-browser-narrative/download"
    draft_url = "https://epd.georgia.gov/document/document/synthetic-browser-draft/download"
    scope = (
        "Construct a greenfield data center with 100 MW planned campus capacity "
        "and emergency generators."
    )
    abstract = "\n".join(
        [
            "Facility: QTS ATL3 SYNTHETIC acceptance fixture",
            "Location: Augusta, Georgia",
            "Application number: SYNTHETIC-30169",
            f"Application received date: {dated}",
            (
                f"Official narrative excerpt: Page 1: Purpose of Application: {scope} "
                "SYNTHETIC fixture, not real source evidence."
            ),
            (
                "Draft identity (page 1): Facility Name: Synthetic Georgia Campus LLC "
                "Facility Address: 100 Fixture Road Augusta Georgia "
                "Facility AIRS Number: SYNTHETIC-001 is issued a Permit for the following: "
                "Construction of a new data center with emergency generators."
            ),
            f"narrative URL: {georgia_url}; draft permit URL: {draft_url}",
        ]
    )
    companions = [
        {
            "title": f"Georgia EPD {label}",
            "abstract": f"Page 1: SYNTHETIC fixture. {scope}",
            "url": url,
            "content_hash": hashlib.sha256(url.encode()).hexdigest(),
            "extraction_location": "Synthetic PDF page 1",
        }
        for label, url in [("narrative", georgia_url), ("draft permit", draft_url)]
    ]
    ga = {
        "document_number": "synthetic-browser-georgia-001",
        "title": "QTS ATL3 SYNTHETIC acceptance fixture",
        "abstract": abstract,
        "publication_date": None,
        "event_date": dated,
        "event_date_label": "Application received date (source-stated)",
        "html_url": "https://epd.georgia.gov/air-protection-branch/air-branch-programs/air-permitting/title-v-draft-permits",
        "extraction_location": "Synthetic listing and narrative fixture",
        "companions": companions,
        "permit": {
            "source_type": "georgia-air-draft-title-v",
            "row_id": "SYNTHETIC-30169",
            "record_id": "synthetic-browser-georgia-001",
            "address": "Augusta",
            "city": "Augusta",
            "state": "GA",
            "status": "Draft permit listed",
            "description": scope,
            "current_scope": scope,
            "current_scope_pages": [1],
            "source_fields": {"facility": "field_1", "application_number": "field_8"},
            "document_links": {"narrative": georgia_url, "draft permit": draft_url},
            "generator_facts": [],
        },
    }
    ep = _row(
        {
            "OBJECTID": 999999,
            "B1_ALT_ID": "SYNTHETIC-EP-001",
            "ISSUEDATE": int(
                datetime.combine(today - timedelta(days=4), datetime.min.time(), UTC).timestamp()
                * 1000
            ),
            "Address": "100 SYNTHETIC FIXTURE RD",
            "Descriptio": "New industrial warehouse construction. SYNTHETIC fixture.",
            "Record_Typ": "New commercial building",
            "B1_SPECIAL": "SYNTHETIC acceptance warehouse",
            "B1_APPL_ST": "Inspection",
            "OWNNAME": "Synthetic El Paso Owner LLC",
        },
        today,
    )
    return austin, {
        "austin-building-permits": [
            render_record(definitions["austin-building-permits"], row) for row in austin
        ],
        "chicago-building-permits": [
            render_record(definitions["chicago-building-permits"], chicago)
        ],
        "georgia-air-draft-title-v": [ga],
        "el-paso-new-commercial-permits": [ep],
    }


def isolated_runtime():
    from sqlalchemy.engine import make_url

    from gridlens.settings import settings

    if not make_url(settings.database_url).database.startswith("gl3_synthetic_browser_"):
        raise RuntimeError("Fixture execution requires an isolated gl3_synthetic_browser_ database")
    settings.openai_api_key = settings.typesafe_api_key = settings.firecrawl_api_key = None
    settings.autonomous_research_enabled = False
    from gridlens.jobs.worker import sync_registry

    definitions = {row["id"]: row for row in sync_registry()}
    austin, records = fixtures(definitions)
    from gridlens.ingestion import adapters, service
    from gridlens.ingestion.adapters import pursuit_public
    from gridlens.ingestion.adapters.buying_chain_public import PublicDocument

    def retrieve_source(source, *args, **kwargs):
        return records.get(source["id"], [])

    service.retrieve_source = adapters.retrieve_source = retrieve_source

    def retrieve_austin(permit_id, *, deadline, on_request):
        on_request()
        row = next(row for row in austin if row["permit_number"] == permit_id)
        record = next(
            record
            for record in records["austin-building-permits"]
            if record["document_number"] == permit_id
        )
        return PublicDocument(
            record["html_url"],
            "SYNTHETIC Austin permit fixture",
            record["abstract"],
            structured=(row,),
        )

    def retrieve_tabs(address, *, deadline, on_request, fetch_limit):
        on_request()
        key = "clayton" if "clayton" in address else "stassney" if "stassney" in address else None
        if key is None:
            return []
        site = "811 CLAYTON LN" if key == "clayton" else "6301 E STASSNEY LN BLDG 8"
        scope = "EV charging" if key == "clayton" else "Administrative office work"
        return [
            PublicDocument(
                "https://example.invalid/synthetic-registration/" + key,
                "SYNTHETIC state registration fixture",
                scope,
                structured=(
                    {
                        "project_number": "SYNTHETIC-TABS-" + key,
                        "address": site,
                        "scope": scope,
                        "project_name": "SYNTHETIC " + scope,
                        "start": "2026-01-01",
                        "end": "2026-12-31",
                    },
                ),
            )
        ]

    pursuit_public.retrieve_austin = retrieve_austin
    pursuit_public.retrieve_tabs = retrieve_tabs
    return definitions, records


def seed():
    from sqlalchemy import func, select

    from gridlens.jobs.queue import enqueue
    from gridlens.jobs.worker import run_one
    from gridlens.persistence.database import SessionLocal
    from gridlens.persistence.models import Job, Observation, PowerNeed, Pursuit

    definitions, records = isolated_runtime()
    with SessionLocal() as session:
        if session.scalar(select(func.count()).select_from(Observation)):
            raise RuntimeError("Refusing to seed a nonempty database")
    for source_id in records:
        with SessionLocal.begin() as session:
            job_id = enqueue(session, source_id)
        run_one(definitions, job_ids=[job_id])
        with SessionLocal() as session:
            job = session.get(Job, job_id)
            if job.status != "succeeded":
                raise RuntimeError(f"Synthetic ingestion failed: {source_id}: {job.error}")
    # Existing ingestion queues the ordinary pursuit job; no synthesized snapshots.
    while run_one(definitions):
        pass
    with SessionLocal.begin() as session:
        enqueue(session, "austin-building-permits", kind="pursuit_research")
    while run_one(definitions):
        pass
    from gridlens.intelligence.pursuits import list_pursuits

    with SessionLocal() as session:
        summary = list_pursuits(session, include_dropped=True)
        print(
            json.dumps(
                {
                    "label": "SYNTHETIC workflow fixture; NOT retained or live corpus",
                    "observations": session.scalar(select(func.count()).select_from(Observation)),
                    "needs": session.scalar(select(func.count()).select_from(PowerNeed)),
                    "pursuits": session.scalar(select(func.count()).select_from(Pursuit)),
                    "items": [
                        {"site": item["site"], "state": item["action_status"]}
                        for item in summary["items"]
                    ],
                }
            )
        )


def worker():
    from gridlens.jobs.worker import run_one

    definitions, _ = isolated_runtime()
    while True:
        if not run_one(definitions):
            time.sleep(0.2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["run", "seed", "worker"], default="run")
    parser.add_argument("--output", type=Path, default=ROOT / ".artifacts" / "synthetic-browser")
    parser.add_argument(
        "--full-suite",
        action="store_true",
        help="Run every browser test against the isolated fixture runtime",
    )
    parser.add_argument("--api-port", type=int, default=8137)
    parser.add_argument("--web-port", type=int, default=5237)
    args = parser.parse_args()
    if args.mode == "seed":
        seed()
        return
    if args.mode == "worker":
        worker()
        return
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url

    from gridlens.settings import settings

    for port in (args.api_port, args.web_port):
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", port))
    name = "gl3_synthetic_browser_" + uuid4().hex[:12]
    source = make_url(settings.database_url)
    target = source.set(database=name)
    env = {
        **os.environ,
        "DATABASE_URL": target.render_as_string(hide_password=False),
        "PYTHONPATH": str(ROOT / "backend" / "src"),
        "WORKER_AUTO_REFRESH": "false",
        "AUTONOMOUS_RESEARCH_ENABLED": "false",
        "OPENAI_API_KEY": "",
        "TYPESAFE_API_KEY": "",
        "FIRECRAWL_API_KEY": "",
        "COOKIE_SECURE": "false",
        "GRIDLENS_API_PORT": str(args.api_port),
        "GRIDLENS_WEB_PORT": str(args.web_port),
        "TRUSTED_ORIGINS": f"http://127.0.0.1:{args.web_port}",
    }
    output = args.output.resolve() / name
    output.mkdir(parents=True, exist_ok=False)
    env["PLAYWRIGHT_JSON_OUTPUT_NAME"] = str(output / "browser-results.json")
    (output / "manifest.json").write_text(
        json.dumps(
            {
                "database": name,
                "data_kind": "SYNTHETIC fixture-only workflow proof",
                "retained_PR23_corpus": False,
                "live_source_proof": False,
                "full_suite": args.full_suite,
                "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "created_at": datetime.now(UTC).isoformat(),
                "candidate": subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
                ).strip(),
            },
            indent=2,
        )
        + "\n"
    )
    engine = create_engine(source.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with engine.connect() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
    engine.dispose()
    with (output / "migrations.log").open("w") as log:
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=ROOT / "backend",
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=True,
        )
    with (output / "seed.log").open("w") as log:
        subprocess.run(
            [sys.executable, __file__, "--mode", "seed"],
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=True,
        )
    with (output / "worker.log").open("w") as log, (output / "browser.log").open("w") as browser:
        process = subprocess.Popen(
            [sys.executable, __file__, "--mode", "worker"],
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            result = subprocess.run(
                npm_command(
                    [
                    "--prefix",
                    "web",
                    "run",
                    "test",
                    "--",
                    *([] if args.full_suite else ["first_path.spec.ts$", "/pursuits.spec.ts$"]),
                    "--workers=1",
                    "--reporter=list,json",
                    f"--output={output / 'browser-results'}",
                    ]
                ),
                cwd=ROOT,
                env=env,
                stdout=browser,
                stderr=subprocess.STDOUT,
            )
        finally:
            process.terminate()
            process.wait(timeout=10)
    print(
        f"SYNTHETIC acceptance receipt: {output}; "
        f"browser exit code {result.returncode}. Database preserved."
    )
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
