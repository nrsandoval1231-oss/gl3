"""Read-only public-source candidate selection; no provider calls or job writes."""
import json
from datetime import UTC, datetime
from sqlalchemy import select, text
from gridlens.persistence.database import SessionLocal
from gridlens.persistence.models import PowerNeed, Project, NeedObservation, Observation, Evidence, Interpretation, Source
from gridlens.intelligence.signal_adjudication import deterministic_override

with SessionLocal() as session:
    session.execute(text('SET TRANSACTION READ ONLY'))
    rows = session.execute(
        select(PowerNeed, Project, Observation, Evidence, Source)
        .join(Project, Project.id == PowerNeed.project_id)
        .join(NeedObservation, NeedObservation.need_id == PowerNeed.id)
        .join(Observation, Observation.id == NeedObservation.observation_id)
        .join(Evidence, Evidence.observation_id == Observation.id)
        .join(Interpretation, Interpretation.observation_id == Observation.id)
        .join(Source, Source.id == Observation.source_id)
        .where(PowerNeed.active.is_(True), Source.enabled.is_(True), Source.registry_enabled.is_(True),
               Observation.content_hash == Evidence.content_hash,
               Interpretation.content_hash == Observation.content_hash,
               Interpretation.status == 'accepted',
               Interpretation.assessment['evidence_hash'].as_string() == Evidence.content_hash,
               Source.id.like('austin%'))
        .order_by(Evidence.observed_at.desc(), PowerNeed.id).limit(30)
    ).all()
    output = []
    seen = set()
    for need, project, observation, evidence, source in rows:
        if need.id in seen:
            continue
        seen.add(need.id)
        output.append({'need_id': str(need.id), 'project_id': str(project.id),
                       'observation_id': str(observation.id), 'evidence_id': str(evidence.id),
                       'content_hash': evidence.content_hash, 'source_id': source.id,
                       'tier': need.tier, 'project': project.name, 'activity': need.activity_key,
                       'evidence_title': evidence.title, 'url': evidence.url,
                       'excerpt': (evidence.abstract or '')[:1200],
                       'deterministic_override': deterministic_override(
                           evidence.title + '\n' + (evidence.abstract or ''),
                           observation.published_at, evidence.url) is not None})
    print(json.dumps({'checked_at': datetime.now(UTC).isoformat(), 'read_only': True,
                      'provider_calls': 0, 'candidates': output}, default=str))
