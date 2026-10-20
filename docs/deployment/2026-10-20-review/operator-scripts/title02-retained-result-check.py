"""Read-only completion/cache/unknown proof; never reserves or invokes a provider."""
import json
import subprocess
from pathlib import Path

journal = Path('/opt/gridlens/releases/title02-802cbb4055c5/validation-control/title02-six-intents.jsonl').read_text()
code = r'''
import json,sys
from uuid import UUID
from sqlalchemy import select,func,text
from gridlens.persistence.database import SessionLocal
from gridlens.persistence.models import Job,LogicalCall,LogicalCallBudget,PowerNeedTitle,PowerNeedTitleVersion
from gridlens.integrations.legacy_calls import perform_legacy_call,LegacyCallUnknown
events=[json.loads(line) for line in sys.stdin.read().splitlines()]
intents=events[0]['intents']
results=[]
def forbidden():
    raise AssertionError('Provider invocation forbidden during retained-result check')
with SessionLocal() as session:
    assert session.scalar(text('SHOW transaction_read_only'))=='on'
    baseline=session.scalar(select(func.count()).select_from(LogicalCall))
for intent in intents:
    with SessionLocal() as session:
        job=session.get(Job,UUID(intent['job_id']))
        checkpoint=json.loads(job.checkpoint or '{}')
        call=session.get(LogicalCall,UUID(checkpoint['logical_call_id'])) if 'logical_call_id' in checkpoint else None
        item={'job_id':str(job.id),'kind':job.kind,'status':job.status,'attempts':job.attempts,'error':job.error}
        if call:
            item.update(call_id=str(call.id),call_status=call.status,reservation_usd=str(call.max_cost_usd),
                dispatched_at=str(call.dispatched_at),finished_at=str(call.finished_at),
                response_payload_available=call.result_payload is not None,
                reconciliation_ref=call.reconciliation_ref,actual_cost_usd=str(call.actual_cost_usd))
            args=dict(task_type=intent['task_type'],task_key=intent['task_key'],payload={},
                source_id=intent['source_id'],project_id=UUID(intent['project_id']),job_id=job.id,
                worker_id='title02-read-only-cache-check',fence_token=0,invoke=forbidden,existing_call_id=call.id)
            if call.status=='COMPLETED':
                cached=perform_legacy_call(**args)
                assert cached.cached
                item['cached_without_dispatch']=True
            else:
                assert call.status=='SENT_OUTCOME_UNKNOWN'
                try: perform_legacy_call(**args)
                except LegacyCallUnknown as e: item['repeat_blocked']=str(e)
                else: raise AssertionError('Unknown call unexpectedly replayable')
        else:
            assert job.kind=='signal_adjudication' and job.attempts==0 and job.status=='failed'
            item['never_dispatched']=True
        results.append(item)
with SessionLocal() as session:
    assert session.scalar(select(func.count()).select_from(LogicalCall))==baseline==10
    titles=[]
    for intent in intents:
        if intent['kind']!='power_need_title':continue
        row=session.get(PowerNeedTitle,UUID(intent['target_id']))
        titles.append({'need_id':str(row.need_id),'status':row.status,'result':row.result,'citations':row.citations,
            'versions':session.scalar(select(func.count()).select_from(PowerNeedTitleVersion).where(PowerNeedTitleVersion.need_id==row.need_id))})
    budgets=[{'scope':r.scope,'period':r.period,'period_key':r.period_key,'call_count':r.call_count,
        'reservation_usd':str(r.cost_usd),'active_count':r.active_count} for r in session.scalars(
            select(LogicalCallBudget).where(LogicalCallBudget.scope=='global:global'))]
assert sum(x.get('cached_without_dispatch',False) for x in results)==4
assert sum('repeat_blocked' in x for x in results)==1
assert sum(x.get('never_dispatched',False) for x in results)==1
print(json.dumps({'read_only':True,'provider_calls':0,'logical_calls':baseline,'results':results,'titles':titles,'global_budgets':budgets}))
'''
out = subprocess.run(['docker','exec','-i','-e','PGOPTIONS=-c default_transaction_read_only=on',
    'gridlens-api-1','uv','run','python','-c',code], input=journal, capture_output=True,text=True)
assert out.returncode==0, 'Retained result proof failed; inspect privately'
print(out.stdout.strip())
