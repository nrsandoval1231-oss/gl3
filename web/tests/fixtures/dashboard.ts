const source = {
  reference: 'evidence:approved-fixture', title: 'Retained site development notice', url: 'https://example.test/notice',
  source_date: '2026-10-20', retained_evidence_id: 'retained-a', content_hash: 'a'.repeat(64),
  passage: 'The notice identifies a site project and its electrical contractor.', extraction_method: 'Official notice',
  verification_status: 'Current retained support',
}
const card = {
  policy_version: 'opportunity-intelligence-v1', need_id: 'need-a', project_id: 'project-a',
  input_fingerprint: 'b'.repeat(64), qualification: 'Signal', disposition: 'RESEARCH',
  fields: [
    { key: 'customer', label: 'Customer / end user', section: 'identity', value: 'A very long customer organization name that should wrap without widening the dashboard', status: 'Reported', basis: 'Identified in retained source.', sources: [source] },
    { key: 'project', label: 'Project', section: 'identity', value: 'A long facility name that should remain readable on phone screens', status: 'Reported', basis: 'Source title.', sources: [source] },
    { key: 'power', label: 'Power activity', section: 'power', value: 'Construction', status: 'Reported', basis: 'Permit scope.', sources: [source] },
  ],
  contacts: [{ claim_id: 'contact-a', company: 'A very long customer organization name that should wrap without widening the dashboard', name: 'Alexandra Longname-Sample', title: 'Director, Infrastructure Programs', role: 'Owner developer', responsibility: 'Source-supported project involvement', purchasing_authority: 'Requires confirmation for this power package', methods: [{ kind: 'phone', value: '+1 512 555 0100', href: 'tel:+15125550100', source_url: source.url }], sources: [source] }],
  next_contact_path: 'Confirm who owns power procurement for this specific project.',
  next_action: 'Verify the activity-specific power window with the source-listed organization.',
  research_gaps: [{ key: 'start', label: 'Power needed by', section: 'power', value: null, status: 'Research in progress', basis: 'No supported date is available yet.', research_category: 'timing', research_status: 'NOT_SCHEDULED', sources: [] }],
  completeness: { supported: 3, total: 8, percent: 38, basis: 'Independent of qualification' },
  last_intelligence_update: '2026-10-20T10:00:00Z', power_gap: null, evidence: [source], research_enabled: true,
}
export const needA = {
  id: 'need-a', project_id: 'project-a', name: 'A long facility name that should remain readable on phone screens',
  browse_title: 'A long facility name that should remain readable on phone screens', location: 'Austin, TX', tier: 'Signal',
  workflow_status: 'New', activity: 'construction', rationale: 'A retained project filing supports investigation.',
  signal_evidence_state: 'active', conflict_state: 'Not assessed', required_mw: null, supply: 'Unknown', start_window: null, duration: null,
  evidence: [{ source_id: 'city-permit', document_number: 'P-1', title: 'Retained site development notice', url: source.url, published_at: null, retrieved_at: '2026-10-20T10:00:00Z', event_date: '2026-10-19', event_date_label: 'Event date', source_origin: 'City permits', extraction_location: 'Page 1', abstract: 'The notice identifies a site project and its electrical contractor.', content_hash: 'a'.repeat(64), assessment_current: true }],
  missing_facts: ['Activity-specific load', 'Suitable utility supply'], project_identity_key: 'project-a',
  commercial_disposition: 'RESEARCH', commercial_reason: 'The retained filing supports project investigation while load and suitable supply remain unknown.',
  commercial_next_question: 'Who owns the electrical scope?', commercial_next_action: 'Confirm the power package and expected timing.', commercial_organization: 'A very long customer organization name that should wrap without widening the dashboard',
  intelligence_card: card,
}
export const needB = { ...needA, id: 'need-b', project_id: 'project-b', name: 'Second supported power need', browse_title: 'Second supported power need', intelligence_card: { ...card, need_id: 'need-b', project_id: 'project-b', fields: card.fields.map(field => field.key === 'customer' ? { ...field, value: 'Example Customer' } : field.key === 'project' ? { ...field, value: 'Second supported power need' } : field), contacts: [], evidence: [] }, evidence: needA.evidence }
