"""Rebuild derived browse under actual disabled title policy; preserve saved results."""
import json
import subprocess
def query(sql):
    return subprocess.check_output(['docker','exec','-e','PGOPTIONS=-c default_transaction_read_only=on',
        'gridlens-db-1','psql','-U','gridlens','-d','gridlens_restore_20261014','-X','-At','-c',sql],text=True).strip()
def state():
    return {table:query("SELECT count(*)::text||':'||md5(coalesce(string_agg(md5(row_to_json(t)::text),'' ORDER BY md5(row_to_json(t)::text)),'')) FROM "+table+' t')
        for table in ('logical_calls','logical_call_budgets','power_need_titles','power_need_title_versions','signal_decisions')}
info=json.loads(subprocess.check_output(['docker','inspect','gridlens-api-1'],text=True))[0]
assert info['Image']=='sha256:be07ead1cecc353e500a1f657ae3d4c8ab6062820c4f121f2558adc6f23ded07'
env=dict(x.split('=',1) for x in info['Config']['Env'] if '=' in x)
assert env.get('POWER_NEED_TITLES_ENABLED','false')=='false'
assert env['JEV_ENABLED']=='false'
before=state()
out=subprocess.run(['docker','exec','gridlens-api-1','uv','run','python','-m','gridlens.jobs.browse','rebuild'],capture_output=True,text=True,timeout=300)
assert out.returncode==0, 'Derived browse rebuild failed'
assert state()==before, 'Saved results or accounting changed'
print(json.dumps({'passed':True,'derived_browse_rebuilt_under_actual_disabled_policy':True,'saved_results_and_accounting_preserved':before}))
