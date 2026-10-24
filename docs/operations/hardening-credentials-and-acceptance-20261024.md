# Credential and commercial acceptance boundaries — October 24, 2026

This continuation keeps Gate A production security/reliability separate from Gate B commercial completion. Missing original QA evidence or an unrepeatable provider outcome does not by itself prohibit a bounded application security/reliability release. Credential disposition and deployment authority remain actual Gate A requirements.

## Historical Google Maps key

[Secret-scanning alert 1](https://github.com/nrsandoval1231-oss/gl3/security/secret-scanning/1) remains OPEN, publicly leaked, validity UNKNOWN. Its source is historical HTML downloaded from the Taylor municipal publisher, not a demonstrated GridLens-issued credential. Publisher provenance does **not** establish the Google Cloud project owner or prove appropriate restrictions. Both current Taylor fixtures were curated before PR119; that PR added a regression guard. Historical exposure remains.

A metadata-only probe compared the alerted value in process memory with every running GridLens container's environment. It found **zero matching values**, and no Google/GCP/Maps environment-variable names across web, API, worker, browse, ingress or PostgreSQL. Current application source does not implement a Google Maps integration. This establishes no configured runtime dependency through those surfaces, rather than proving absence of every possible external dependency. The value was not printed, logged, persisted, hashed, submitted to a Google service, or used to test activity. No credential was rotated or revoked, no history rewritten, and no alert dismissed.

Available tools provide no authenticated administrative access to the key's Google Cloud project; local `gcloud` was unavailable. Project identity, active/revoked state, API/application restrictions and usage therefore remain **UNKNOWN**. Google documents that [lookupKey requires permission on the parent project](https://docs.cloud.google.com/api-keys/docs/reference/rest/v2/keys/lookupKey). The browser origin of a Maps key does not prove whether it is safe: [Google's guidance](https://developers.google.com/maps/api-security-best-practices) calls for both application and API restrictions appropriate to the service.

The owner answered **"Ownership is unknown"** during this continuation. That is not risk acceptance or authority to change the credential. The alert stays open.

Smallest owner/provider action:

1. An authorized project administrator privately identifies the credential associated with alert 1 in Google Cloud and records only project ID, key resource ID, active/revoked state, permitted APIs, permitted application origins/IPs, and recent usage evidence. Do not paste the key into chat, commands, reports or issues.
2. If active and unrestricted or abused, establish actual consumers and a restricted replacement before revoking the old credential. If unused, revoke it. If intentionally public and appropriately restricted, retain evidence supporting that disposition; public HTML alone is insufficient.
3. The authorized repository owner records acceptance or verified remediation against the alert. Close it only with that supported disposition. Until then Gate A has an external decision blocker, not a successful remediation claim.

If the repository owner has no provider access, the key's publisher/project administrator must supply the metadata or the authorized owner must explicitly accept the documented residual exposure. This engineering run does not communicate externally on the owner's behalf.

## Original QA corpus

The original acceptance input is the 446-record Grok `/workspace/gl3-qa` export associated with `QA Build Review`. It remains unavailable. This continuation searched connected Google Drive and Dropbox for `gl3-qa` and `QA Build Review` with no matching result; targeted local filename searches across Downloads, Nucleus and Codex attachments found no identifiable original export. These bounded searches do not prove that the export does not exist elsewhere or under another name.

Required dependency: recover the original records plus their source/export context, export time/version, record identity and a manifest/checksum sufficient to bind acceptance to those exact records. Preserve the original bytes and run acceptance on an isolated copy. The 578-observation M6 corpus, older RRC data and synthetic fixtures are not substitutes. No original-corpus pass count is claimed.

## Provider and Finish Contract

Albuquerque's retained M6 outcome remains `SENT_OUTCOME_UNKNOWN`; the audit does not retry it, release its reservation, reconcile/reset its ledger, increase budgets or infer a successful outcome from a different production call. Saved permit-acquisition success and the unresolved Sol assessment are separate evidence.

The six outstanding live-acceptance tests, five-chain/contradiction requirements, M6/source-provider coverage and parent Finish Contract remain open where their original evidence or provider authority is missing. Safe fixture and isolated retained-data checks are reported separately. Gate B remains INCOMPLETE until those gates are actually evidenced.
