"""Read only explicitly nonsecret controls needed for the proposed activation."""
import json
from datetime import UTC, datetime
from gridlens.settings import settings

keys = ['worker_auto_refresh','intelligence_enabled','intelligence_mode','intelligence_enabled_contracts',
        'intelligence_openai_enabled','intelligence_typesafe_enabled','jev_enabled',
        'openai_brief_model','intelligence_openai_reasoning_model',
        'intelligence_openai_reasoning_priced_model_id','intelligence_openai_reasoning_pricing_verified',
        'intelligence_openai_reasoning_input_usd_per_million','intelligence_openai_reasoning_output_usd_per_million',
        'intelligence_max_active_calls','intelligence_max_call_usd',
        'intelligence_typesafe_model','intelligence_typesafe_priced_model_id',
        'intelligence_typesafe_pricing_verified','intelligence_typesafe_billing_mode',
        'intelligence_typesafe_billing_model_id','intelligence_typesafe_billing_contract_id',
        'intelligence_typesafe_billing_policy_id','intelligence_typesafe_billing_verified',
        'intelligence_typesafe_total_input_bound_verified']
for scope in ('global','provider','model','source','project'):
    for period in ('daily','monthly'):
        for kind in ('calls','usd'):
            keys.append('intelligence_'+scope+'_'+period+'_'+kind)
print(json.dumps({'checked_at': datetime.now(UTC).isoformat(), 'read_only': True,
                  'controls': {key: getattr(settings,key) for key in keys}}, default=str))
