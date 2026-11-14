from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url

ROOT = Path(os.environ.get('GRIDLENS_SOURCE_ROOT', str(Path(__file__).resolve().parents[4])))
MANIFEST = Path(os.environ.get('GRIDLENS_SMOKE_MANIFEST', '/workspace/task-runtime/retained_ui_smoke_seed_replay.json'))
if MANIFEST.exists():
    raise RuntimeError('Refusing to overwrite a smoke manifest')
BACKEND = ROOT / 'backend'
BASE_TEST = make_url(os.environ['TEST_DATABASE_URL'])
APPLICATION = make_url(os.environ['DATABASE_URL'])
if not BASE_TEST.database or not BASE_TEST.database.endswith('_test'):
    raise RuntimeError('Configured test base database must end in _test')
if BASE_TEST.host not in {'127.0.0.1', '::1', 'localhost'}:
    raise RuntimeError('Configured TEST_DATABASE_URL must be loopback')
if BASE_TEST == APPLICATION:
    raise RuntimeError('Test and application databases must be distinct')

name = f'gl3_retained_ui_smoke_20261113_{uuid.uuid4().hex[:8]}_test'
target = BASE_TEST.set(database=name)
admin = create_engine(BASE_TEST.set(database='postgres'), isolation_level='AUTOCOMMIT')
created = False
try:
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
        created = True

    target_text = target.render_as_string(hide_password=False)
    migration_env = os.environ.copy()
    migration_env['DATABASE_URL'] = target_text
    subprocess.run(
        [sys.executable, '-m', 'alembic', 'upgrade', 'head'],
        cwd=BACKEND,
        env=migration_env,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    os.environ['DATABASE_URL'] = target_text
    sys.path.insert(0, str(BACKEND / 'src'))
    from gridlens.ingestion.adapters.retained_company_projects import (
        FAMILY,
        RETRIEVAL_METHOD,
        SOURCE_ID,
        interpret_retained_company_project,
        retained_records,
    )
    from gridlens.ingestion.service import process_records
    from gridlens.intelligence.buying_chain import enrich_buying_chain
    from gridlens.intelligence.customer_results import group_open, groups
    from gridlens.intelligence.saved_browse import rebuild
    from gridlens.persistence.models import (
        BuyingChainIdentityLink,
        BrowseCustomerMembership,
        Evidence,
        Job,
        PowerNeed,
        Project,
        Source,
    )

    records, held = retained_records(ROOT / 'eval/customer-commercial-v1')
    corpus_retained_count = len(records)
    # This smoke deliberately selects two historical real sources, not the entire evaluation cohort.
    records = [record for record in records if any(
        file in {'sources/databank.json', 'sources/cyrusone.json'}
        for file in record['retained_company_project']['source_files']
    )]
    if len(records) != 2:
        raise RuntimeError('Expected exactly the two selected historical source records')
    for record in records:
        if interpret_retained_company_project(record) is None:
            raise RuntimeError('Native adapter record failed fresh reparse')
    engine = create_engine(target)
    factory = __import__('sqlalchemy.orm', fromlist=['sessionmaker']).sessionmaker(
        engine, expire_on_commit=False
    )
    source_definition = {
        'id': SOURCE_ID,
        'publisher': 'retained offline public documents',
        'endpoint': 'https://offline.invalid/retained',
        'family': FAMILY,
        'geography': 'United States',
        'industries': ['data centers'],
        'retrieval_method': RETRIEVAL_METHOD,
        'cadence_hours': 24,
        'enabled': False,
        'registry_enabled': False,
    }
    worker = 'retained-ui-smoke-seeder'
    try:
        with factory.begin() as session:
            session.add(Source(**source_definition))
            session.flush()
            job = Job(
                source_id=SOURCE_ID,
                status='running',
                lease_owner=worker,
                fence=1,
                lease_until=datetime.now(UTC) + timedelta(minutes=10),
            )
            session.add(job)
            session.flush()
            job_id = job.id
        with factory() as session:
            ingestion = process_records(
                session, job_id, worker, 1, source_definition, records, allow_model=False
            )
        with factory.begin() as session:
            projects = session.scalars(select(Project).order_by(Project.name)).all()
            evidence_rows = session.scalars(select(Evidence).order_by(Evidence.url)).all()
            for project in projects:
                evidence = next(
                    (
                        item
                        for item in evidence_rows
                        if item.provenance.get('retained_company_project', {}).get(
                            'project_name'
                        )
                        == project.name
                    ),
                    None,
                )
                if evidence is not None:
                    enrich_buying_chain(
                        session,
                        project.id,
                        retained_only=True,
                        retained_target_evidence_id=evidence.id,
                    )
        browse = rebuild(factory)
        if browse.get('status') != 'published':
            raise RuntimeError(f'Saved browse did not publish: {browse}')
        with factory() as session:
            project_count = session.scalar(select(func.count()).select_from(Project))
            need_count = session.scalar(select(func.count()).select_from(PowerNeed))
            evidence_count = session.scalar(select(func.count()).select_from(Evidence))
            company_link_count = session.scalar(
                select(func.count())
                .select_from(BuyingChainIdentityLink)
                .where(
                    BuyingChainIdentityLink.entity_type == 'company',
                    BuyingChainIdentityLink.state == 'current',
                )
            )
            membership_count = session.scalar(
                select(func.count()).select_from(BrowseCustomerMembership)
            )
            ordinary = groups(
                session,
                sector='data_centers',
                sort='priority',
                limit=25,
                offset=0,
                shortlist=False,
            )
            shortlist = groups(
                session,
                sector='data_centers',
                sort='priority',
                limit=25,
                offset=0,
                shortlist=True,
            )
            ui_group = next(iter(ordinary['items']), None)
            opened = (
                group_open(
                    session,
                    ui_group['id'],
                    sector='data_centers',
                    sort='priority',
                    limit=25,
                    shortlist=False,
                )
                if ui_group
                else None
            )
    finally:
        engine.dispose()

    result = {
        'database_name': name,
        'database_host': BASE_TEST.host,
        'database_port': BASE_TEST.port,
        'migrated_to_head_before_seed': True,
        'seed_source': 'native retained adapter + process_records + enrich + saved browse rebuild',
        'gold_oracle_used_for_seeding': False,
        'preserved_for_ui_smoke': True,
        'candidate_source_records': len(records),
        'full_corpus_retained_records': corpus_retained_count,
        'selected_smoke_sources': ['sources/databank.json', 'sources/cyrusone.json'],
        'held_source_documents': len(held),
        'source_record_ingestion': ingestion,
        'project_rows': project_count,
        'power_need_rows': need_count,
        'evidence_rows': evidence_count,
        'company_identity_links': company_link_count,
        'browse_customer_memberships': membership_count,
        'ordinary_customer_groups': ordinary['total'],
        'default_shortlist_groups': shortlist['total'],
        'opened_group': opened['group']['name'] if opened else None,
    }
    MANIFEST.write_text(
        json.dumps(result, indent=2, sort_keys=True) + '\n'
    )
    print(json.dumps(result, sort_keys=True))
except Exception:
    if created:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
    raise
finally:
    admin.dispose()
