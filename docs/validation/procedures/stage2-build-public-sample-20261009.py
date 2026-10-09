import json,hashlib
from pathlib import Path
root=Path.cwd()
src=root/'.artifacts/STAGE2/evidence/fixed-sample.6c29be89fc80ebfe.private.json'
obj=json.loads(src.read_text(encoding='utf-8'))
expected_sample='6c29be89fc80ebfe4779c8e4439cefe6c0457db0c1d58b74ffb59b9f2e633ccc'
if hashlib.sha256(src.read_bytes()).hexdigest()!=expected_sample: raise SystemExit('fixed sample hash mismatch')
pool=root/'.artifacts/STAGE2/evidence/full-candidate-pool.b854f043bc20aa5d.private.json'
expected_pool='b854f043bc20aa5dc1d87af3ecd67eedb6b8173d80022f7bd2cb479e3dead52c'
if hashlib.sha256(pool.read_bytes()).hexdigest()!=expected_pool: raise SystemExit('candidate pool hash mismatch')
ambiguous={'el-paso-new-commercial-permits|BCNN25-00099'}
unavailable={f'texas-rrc-flare-vent-exceptions|{x}' for x in ('35906','35918','35915','35944')}
continuity={'austin-building-permits|2026-037732 BP'}
visible={'austin-building-permits|2026-026051 EP','dallas-monthly-permits|2210211015_174492520-001',*[f'texas-rrc-drilling-permits|{x}' for x in ('0917090','0917987','0909414','0918387','0918094')]}
hidden={'houston-weekly-permits|26017927:Building Pmt:2026-09-01'}
def getdate(r):
 versions=r.get('evidence_versions') or []
 if versions and versions[-1].get('event_date'): return versions[-1]['event_date']
 i=r.get('latest_interpretation') or {}; a=i.get('assessment') or {}
 return a.get('event_date') or i.get('event_date')
activity={
 '2024-127408 BP':'Smart-housing floor finish-out; permit scope does not state power demand.',
 '2026-126020 EP':'Exterior illuminated sign installation.',
 '2026-083018 EP':'Training-center finish-out; source status is final.',
 '2026-037732 BP':'Existing-business like-kind UPS replacement; possible continuity investigation only.',
 '2024-000493 BP':'Three-story multifamily new construction.',
 '2026-026051 EP':'New shell warehouse construction.',
 'COM-NEW-26-000210':'Commercial car-wash construction.',
 'COM-NEW-25-000306':'Retirement-housing construction.',
 'COM-NEW-25-000161':'Restaurant construction.',
 'COM-NEW-25-000261':'Commercial parking garage; shell-only scope is construction evidence, not a power gap.',
 'COM-NEW-26-000071':'Office construction.',
 '2210211015_174492520-001':'Warehouse construction.',
 'BCNN25-00158':'Parking-garage construction.',
 'BCNN26-00078':'Source work-name says El Paso Water but does not identify water-plant scope.',
 'BCNN26-00115':'Sparse permit row; scope not established in retained source fields.',
 'BCSN26-00094':'Apartment project name; power-specific scope not shown.',
 'BCNN25-00099':'Same source ID resolves to three features, two sites and two event dates; site attribution remains ambiguous.',
 'BCSN26-00080':'Canopy construction.',
 '26065390:Building Pmt:2026-09-11':'Residential addition/remodel.',
 '26064937:Building Pmt:2026-08-28':'Single-family residence with attached garage.',
 '26048195:Building Pmt:2026-09-11':'Single-family residential construction.',
 '26066413:Building Pmt:2026-09-02':'Apartment-foundation repair.',
 '26079896:Building Pmt:2026-09-11':'Minor residential repair.',
 '26017927:Building Pmt:2026-09-01':'35 kW fixed natural-gas generator replacement; below visible floor and not rental demand.',
 '0917090':'RRC W-1 drilling permit application; application is not an active power project.',
 '0917987':'RRC W-1 drilling permit application; application is not an active power project.',
 '0909414':'RRC W-1 drilling permit application; application is not an active power project.',
 '0918387':'RRC W-1 drilling permit application; application is not an active power project.',
 '0918094':'RRC W-1 drilling permit application; application is not an active power project.',
 '0918692':'RRC well reclassification application.',
 '36173':'Retained flare/vent exception record; only application-level facts were checked, no fixed power scope inferred.',
 '35906':'Retained flare/vent exception record; original row unavailable in bounded comparison.',
 '35918':'Retained flare/vent exception record; original row unavailable in bounded comparison.',
 '36122':'Retained flare/vent exception record; only application-level facts were checked, no fixed power scope inferred.',
 '35915':'Retained flare/vent exception record; original row unavailable in bounded comparison.',
 '35944':'Retained flare/vent exception record; original row unavailable in bounded comparison.'}
sites={
 '2024-127408 BP':'2001 S Lamar Blvd, Floor 3, Austin, TX',
 '2026-126020 EP':'9761 Great Hills Trail, Unit B, Austin, TX',
 '2026-083018 EP':'14125 The Lakes Blvd, Unit 101, Austin, TX',
 '2026-037732 BP':'1404 Park Center Dr, Austin, TX',
 '2024-000493 BP':'Olivaris Blvd, Building 13, Austin, TX (multi-family site)',
 '2026-026051 EP':'8001 Metropolis Dr, Building 3, Austin, TX',
 'COM-NEW-26-000210':'5815 S Westmoreland Rd, Dallas, TX',
 'COM-NEW-25-000306':'6400 S Westmoreland Rd, Dallas, TX',
 'COM-NEW-25-000161':'14897 Preston Rd, Dallas, TX',
 'COM-NEW-25-000261':'2401 McKinney Ave, Dallas, TX',
 'COM-NEW-26-000071':'11600 Welch Rd, Dallas, TX',
 '2210211015_174492520-001':'10851 Miller Rd, Dallas, TX',
 'BCNN25-00158':'San Marcos address, El Paso, TX',
 'BCNN26-00078':'701 Executive Center Blvd, El Paso, TX',
 'BCNN26-00115':'North Loop address, El Paso, TX',
 'BCSN26-00094':'1040 Mesa Hills Dr, El Paso, TX',
 'BCNN25-00099':'Latest stored feature: 11213 Gateway West, El Paso; source ID also has a 2025 feature at 1323 Lee Trevino and a second 2026 feature at Gateway West',
 'BCSN26-00080':'11330 Montwood Dr, El Paso, TX',
 '26065390:Building Pmt:2026-09-11':'Houston, TX (residential street address withheld from public sample)',
 '26064937:Building Pmt:2026-08-28':'Houston, TX (residential street address withheld from public sample)',
 '26048195:Building Pmt:2026-09-11':'Houston, TX (residential street address withheld from public sample)',
 '26066413:Building Pmt:2026-09-02':'Houston, TX (apartment site; street address withheld from public sample)',
 '26079896:Building Pmt:2026-09-11':'Houston, TX (residential street address withheld from public sample)',
 '26017927:Building Pmt:2026-09-01':'Houston, TX (commercial generator replacement site; exact address retained in official source record)',
 '0917090':'RRC well/lease identifier; exact coordinates not compared in this source quality pass',
 '0917987':'RRC well/lease identifier; exact coordinates not compared in this source quality pass',
 '0909414':'RRC well/lease identifier; exact coordinates not compared in this source quality pass',
 '0918387':'RRC well/lease identifier; exact coordinates not compared in this source quality pass',
 '0918094':'RRC well/lease identifier; exact coordinates not compared in this source quality pass',
 '0918692':'RRC well/lease identifier; exact coordinates not compared in this source quality pass'}
def next_question(r,key,visibility):
 rid=r['stable_record_id']
 if key in ambiguous: return 'Which GIS feature/site is intended, and should the two permit observations be linked?'
 if rid=='COM-NEW-25-000261': return 'Can a current operator confirm whether this shell-only garage project has an active construction load needing temporary capacity?'
 if key in continuity: return 'Is this existing business facility operating, and is continuity or bridge capacity needed during like-kind UPS replacement?'
 if key in unavailable: return 'Could the original record be checked through an authorized current source route?'
 if visibility=='visible_signal': return 'Does this permit/application map to a current project power need, and who has authority to confirm it?'
 return 'Does this permit record support a current power need beyond the described construction or administrative filing?'
def defect_classification(r,key,visibility):
 rid=r['stable_record_id']
 if key in ambiguous: return 'identity_ambiguity'
 if key in unavailable: return 'original_source_evidence_unavailable_UNKNOWN'
 if key in continuity or rid=='COM-NEW-25-000261': return 'potential_recall_investigation_NOT_CONFIRMED'
 if visibility=='visible_signal': return 'presentation_carry_through; buyer_authority_UNKNOWN'
 return 'no_demonstrated_source_fidelity_defect; commercial_power_need_UNKNOWN'
records=[]
for r in obj['records']:
 key=r['source_id']+'|'+r['stable_record_id']; o=r['observation']; i=r.get('latest_interpretation') or {}; a=i.get('assessment') or {}; versions=r.get('evidence_versions') or []
 if key in ambiguous: original='ambiguous_multi_feature'
 elif key in unavailable: original='original_payload_unavailable'
 else: original='source_fields_independently_compared'
 if key in visible: visibility='visible_signal'
 elif key in hidden: visibility='excluded_below_floor'
 else: visibility='not_admitted'
 if key in continuity: judgment='Original source explicitly describes like-kind UPS replacement at an existing business building. This is a potential continuity-investigation recall question, not a confirmed missed power need; rental demand, load, duration, active work, and supply gap remain UNKNOWN.'
 elif key in ambiguous: judgment='Original direct query resolves this ID to three GIS features at two addresses with two event dates. Persisted evidence represents one latest-dated feature; identity/site/date association is ambiguous, not absent or uniquely resolved.'
 elif key in unavailable: judgment='Retained historical flare record; original row was outside the bounded current route and unavailable for comparison. Source truth, identity fidelity, and absent-versus-missed facts remain UNKNOWN.'
 elif key in hidden: judgment='Original workbook row confirms a 35 kW fixed generator replacement. The linked PowerNeed is excluded below the ordinary 300 kW floor; this is not visible false-positive admission. Rental demand and gap remain UNKNOWN.'
 elif r['stable_record_id']=='COM-NEW-25-000261': judgment='Compared source fields describe a 445,627 SF, approximately $45M shell-only commercial garage with Balfour Beatty as applicant. This is a construction-investigation recall candidate, not proof of temporary load or a missed qualified need; qualification appropriateness remains UNKNOWN.'
 elif visibility=='visible_signal': judgment='Source identity/activity is consistent with the independent original comparison or retained RRC segment. Signal is investigation-level only; no size/gap/start/duration/buyer authority is established by the permit/application.'
 else: judgment='Compared source fields support the cited identity/site/scope/event facts where available. The recorded rejected disposition is observed, but its correctness and potential recall cannot be determined from a permit/application alone; current power need, active work and buyer path remain UNKNOWN. Do not treat absence of a power-gap field as proof that rejection was correct.'
 evidence_ids=[v.get('evidence_id') for v in versions]
 record={
  'sample_id':r['sample_id'],'source_id':r['source_id'],'stable_record_id':r['stable_record_id'],
  'selection_sha256':r['selection_sha256'],'sample_stratum':r['stratum'],'pipeline_status':i.get('status') or 'UNKNOWN',
  'origin':r['origin'],'observation_id':r['observation_id'],'evidence_ids':evidence_ids,
  'current_content_sha256':o.get('content_hash'),'prior_content_sha256':[v.get('content_hash') for v in versions if v.get('content_hash')!=o.get('content_hash')],
  'source_url':o.get('url'),'source_event_date':getdate(r),'date_attribution':((versions[-1].get('event_date_label') if versions else None) or i.get('issue_date_label') or i.get('event_date_label') or ('UNKNOWN; no source event date retained' if getdate(r) is None else 'Source event/application date; publisher publication time UNKNOWN')),
  'publisher_publication_time':'UNKNOWN','retrieval_or_observation_time':(versions[-1].get('observed_at') if versions else o.get('first_seen_at')),
  'original_comparison':original,'source_fact_status':('compared source fields support only the cited record/site/scope/date fields' if original=='source_fields_independently_compared' else ('official stable ID resolves to multiple features; unique site/activity linkage UNKNOWN' if original=='ambiguous_multi_feature' else 'source original unavailable; stored evidence only, truth UNKNOWN')),'qualification_or_admission_correctness':('no unsupported claim proven in limited visible Signal review; overall correctness UNKNOWN' if visibility=='visible_signal' else ('below-floor exclusion confirmed; commercial need UNKNOWN' if visibility=='excluded_below_floor' else 'rejection observed; correctness and missed-opportunity status UNKNOWN')),'current_projection':visibility,
  'project_group_count':len(r.get('projects') or []),'power_need_count':len(r.get('power_needs') or []),
  'commercial_priority':('potential continuity investigation only' if key in continuity else ('potential construction investigation; not confirmed' if r['stable_record_id']=='COM-NEW-25-000261' else ('low/conditional Signal usefulness' if visibility=='visible_signal' else 'not established'))),
  'source_activity_finding':activity.get(r['stable_record_id'],'Source activity UNKNOWN'),
  'source_excerpt':activity.get(r['stable_record_id'],'Activity UNKNOWN'),
  'source_excerpt_kind':'paraphrase of independently inspected original source fields' if original in ('source_fields_independently_compared','ambiguous_multi_feature') else 'retained parsed record only; original excerpt UNCORROBORATED',
  'failure_category':('identity' if key in ambiguous else ('UNKNOWN' if key in unavailable else ('presentation' if visibility=='visible_signal' else 'absent_evidence'))),
  'failure_detected':visibility=='visible_signal' or key in ambiguous,
  'commercial_requirement_evidence':'No temporary/rental power requirement, utility gap or buyer authority established by this source; Houston record is fixed 35 kW generator replacement only' if key in hidden else 'No source-backed saleable power load/supply gap demonstrated; UNKNOWN whether one exists outside this record',
  'source_activity_extraction_location':(versions[-1].get('extraction_location') if versions else 'UNKNOWN'),
  'site_or_area':sites.get(r['stable_record_id'],'Original site UNKNOWN'),
  'next_question':next_question(r,key,visibility),
  'defect_classification':defect_classification(r,key,visibility),
  'site_finding':'official-source site fields agree with retained record' if original=='source_fields_independently_compared' else ('three-feature/two-site ambiguity; do not assert unique site' if original=='ambiguous_multi_feature' else 'UNKNOWN; source original unavailable'),
  'source_supported_organization_role_present':(visibility=='visible_signal' or bool(any(s in (o.get('abstract') or '').lower() for s in ('contractor_company_name:','applicant_org:','operator:','lp business name','business_name')))),
  'buyer_authority':'UNKNOWN','required_mw':'UNKNOWN' if key not in hidden else 'UNKNOWN (source reports fixed 35 kW generator only)',
  'utility_supply':'UNKNOWN','power_gap':'UNKNOWN','active_work':'UNKNOWN unless the source record itself is a permit status only',
  'review_judgment':judgment
 }
 records.append(record)
result={
 'title':'GL3 Stage2 frozen mixed-record source-quality review',
 'code_base':'c761e38f6ac00e7d54d6f6b57959cf40cdcf4d79',
 'sampling_procedure':'docs/validation/procedures/stage2-source-quality-review-20261009.md',
 'sampling_procedure_sha256':obj['protocol_sha256_frozen'],
 'pool_sha256':'b854f043bc20aa5dc1d87af3ecd67eedb6b8173d80022f7bd2cb479e3dead52c',
 'fixed_sample_sha256':'6c29be89fc80ebfe4779c8e4439cefe6c0457db0c1d58b74ffb59b9f2e633ccc',
 'selected_records':36,'candidate_pool_by_source':obj['candidate_pool_by_source'],'source_fidelity_counts':{'source_fields_independently_compared':31,'ambiguous_multi_feature':1,'original_payload_unavailable':4,'denominator':36},
 'quality_metric_denominators':{'persisted_event_or_application_date_attribution_present':{'count':36,'denominator':36,'source_date_comparison':{'supported_fields':31,'ambiguous_feature_key':1,'original_unavailable':4}},'publisher_publication_time':{'known':0,'unknown':36,'denominator':36},'persisted_retrieval_or_observation_timestamp':{'known':36,'unknown':0,'denominator':36},'site_specificity':{'city_permit_sites_supported':23,'city_permit_sites_denominator':24,'el_paso_multifeature_site_ambiguous':1,'rrc_drilling_lease_well_identity_rows':6,'rrc_drilling_coordinate_verification':'UNKNOWN','flare_current_rows_with_district_only':2,'flare_retained_original_unavailable':4},'source_activity':{'application_or_permit_field_comparisons_supported':31,'ambiguous_feature_activity_link':1,'original_unavailable_activity':4,'el_paso_water_plant_scope_absent_from_row':1,'active_work_confirmed':0,'active_work_unknown':36,'activity_specific_power_load_or_rental_need_confirmed':0,'power_need_or_gap_unknown':36},'qualification_correctness':{'independently_decidable':0,'unknown':36,'denominator':36},'confirmed_incorrect_visible_signal_admission':{'count':0,'denominator':7},'proven_missed_qualified_power_need':{'count':0,'denominator':36},'potential_recall_investigations_not_proven_misses':{'count':2,'denominator':36,'sample_ids':['S2-04','S2-10']},'confirmed_fixed_sample_duplicate_grouping_error':{'count':0,'denominator':36,'ambiguous_identity_cases':1},'confirmed_buyer_authority_path':{'count':0,'denominator':36},'visible_signal_company_role_not_carried_into_title_projection':{'count':7,'denominator':7}},
 'pipeline_strata_counts':{'admitted':8,'rejected':28,'ambiguous':0,'denominator':36},
 'current_projection_counts':{'visible_signal':7,'excluded_below_floor':1,'not_admitted':28,'denominator':36},
 'confirmed_false_positive_visible_admissions':{'count':0,'denominator':7,'note':'No reviewed visible Signal was proven to claim unsupported identity/activity/current work/qualification. This is not a general precision estimate.'},
 'records':records,
 'limitations':['Original source comparison is not commercial correctness; source fidelity on 31 plus one ambiguous case does not establish active power demand.','Four retained flare originals unavailable; absent-versus-missed remains UNKNOWN.','All six source freshness values UNKNOWN; publication times UNKNOWN.','Stage2 mixed intake quality sample does not satisfy PRD39 independent-discovery Signal/Prospect sample or its 24-correct target.']
}
out=root/'docs/validation/stage2-review-sample-20261009.json'
out.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')




