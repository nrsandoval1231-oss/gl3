"""Run normal exact-well worker jobs against actual captured official HTTP pages.

Only the HTTP transport is replayed. Identity parsing, fencing, source evidence,
derived facts and later saved-generation publication use the application code.
This does not establish current production access or a successful live job.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    import httpx
    from sqlalchemy import select
    from sqlalchemy.engine import make_url

    from gridlens.ingestion.adapters import (
        rrc_completion,
        rrc_well_lifecycle as adapter,
    )
    from gridlens.ingestion.registry import load_registry
    from gridlens.intelligence.rrc_well_research import KIND, POLICY, SOURCE
    from gridlens.jobs.worker import run_one
    from gridlens.persistence.database import SessionLocal
    from gridlens.persistence.models import Job, Observation, Project
    from gridlens.settings import settings

    url = make_url(settings.database_url)
    if (
        url.host != "127.0.0.1"
        or url.database != "gridlens_issue128_local"
        or url.query
    ):
        raise RuntimeError(
            "Only the exact isolated local candidate database is permitted"
        )
    if args.receipt.exists():
        raise RuntimeError("Refusing to overwrite a replay receipt")
    settings.saved_browse_enabled = False
    settings.rrc_well_research_enabled = True
    settings.openai_api_key = settings.typesafe_api_key = settings.firecrawl_api_key = (
        None
    )
    manifest = json.loads(args.manifest.read_text())
    original = adapter.retrieve_w1_detail
    original_completion = rrc_completion.retrieve_completion_history
    receipts = []
    for capture in manifest:
        requests = []

        def transport(request):
            requests.append(
                {
                    "method": request.method,
                    "path": re.sub(
                        r";jsessionid=[^/?;]+", "", request.url.path, flags=re.I
                    ),
                }
            )
            if request.url.host == "webapps.rrc.texas.gov":
                packet = request.url.params.get("packetSummaryId")
                path = (
                    capture["completion_packets"][packet]
                    if packet
                    else capture["completion_listing"]
                )
            elif request.method == "POST":
                path = capture["results"]
            elif "drillingPermitDetailAction" in request.url.path:
                path = capture["detail"]
            elif "drillingPermitsQueryAction" in request.url.path:
                path = capture["form"]
            else:
                raise RuntimeError("Replay attempted an uncaptured HTTP route")
            return httpx.Response(200, content=Path(path).read_bytes(), request=request)

        with httpx.Client(transport=httpx.MockTransport(transport)) as client:
            adapter.retrieve_w1_detail = lambda record, *, deadline: original(
                record, deadline=deadline, client=client
            )
            rrc_completion.retrieve_completion_history = (
                lambda identity, *, deadline: original_completion(
                    identity, deadline=deadline, client=client
                )
            )
            with SessionLocal.begin() as session:
                project = session.scalar(
                    select(Project).where(
                        Project.source_id == SOURCE,
                        Project.external_id == capture["permit"],
                    )
                )
                if project is None:
                    raise RuntimeError("Captured permit has no retained native project")
                observation = session.scalar(
                    select(Observation).where(
                        Observation.source_id == SOURCE,
                        Observation.external_id == project.external_id,
                    )
                )
                job = Job(
                    source_id=SOURCE,
                    kind=KIND,
                    target_id=project.id,
                    checkpoint=json.dumps(
                        {
                            "policy": POLICY,
                            "native_content_hash": observation.content_hash,
                        }
                    ),
                )
                session.add(job)
                session.flush()
                job_id = job.id
            run_one({item["id"]: item for item in load_registry()}, job_ids=[job_id])
            with SessionLocal() as session:
                job = session.get(Job, job_id)
                if job.status != "succeeded":
                    raise RuntimeError(
                        f"Well capture job failed for {capture['permit']}: {job.error}"
                    )
                project = session.get(Project, job.target_id)
                retained = project.identity_facts["rrc_official_well"]
                receipts.append(
                    {
                        "permit": capture["permit"],
                        "job_status": job.status,
                        "request_count": len(requests),
                        "requests": requests,
                        "api_number": retained["facts"]["asset_identity"]["value"],
                        "events": retained["facts"]["events"],
                        "source_url": retained["source_url"],
                        "source_hash": retained["content_hash"],
                        "evidence_id": retained["evidence_id"],
                        "completion_research": json.loads(job.checkpoint).get(
                            "completion_research"
                        ),
                        "historical_completion_events": [
                            event
                            for record in project.identity_facts.get(
                                "rrc_official_completion", []
                            )
                            for event in record["facts"].get("events", [])
                        ],
                        "native_content_hash": retained["native_content_hash"],
                        "input_hashes": {
                            key: hashlib.sha256(
                                Path(capture[key]).read_bytes()
                            ).hexdigest()
                            for key in ("form", "results", "detail")
                        },
                    }
                )
    adapter.retrieve_w1_detail = original
    rrc_completion.retrieve_completion_history = original_completion
    args.receipt.write_text(
        json.dumps(
            {
                "kind": "actual_official_capture_worker_replay",
                "network_requests": 0,
                "scope": "isolated local candidate; no live-worker/production proof",
                "jobs": receipts,
            },
            indent=2,
        )
        + "\n"
    )
    print(
        json.dumps({"jobs": len(receipts), "status": "passed", "network_requests": 0})
    )


if __name__ == "__main__":
    main()
