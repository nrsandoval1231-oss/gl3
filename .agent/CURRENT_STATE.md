# Current state — GL3 audit repair

Parent OPEN. Bounded A3/A9/A1/A2/A4/A5A/A5B and A6 backend remain separately independently accepted. PR43 exact accepted backend daedade06adc0dbe18fb09c46a5dcfc2444681f5 is published with successful CI. Main94c3acb and remote join5c038805 remain unchanged. No merge/deployment, paid activation or external sends authorized.

A6 UI/status candidate ce3a03bf8e7bef6f4a4edc212c8c77fd31e175ec/treecb8eaee9 was independently FIX/CORRECT despite full1471 backend and72 browser plus separate persisted1 PASS. Raw review SHA9c2d1290807cc01b702140ce998a27718b5b5d6c549580f407dd1d07697b5415 preserved in recovery dispatch. All278 source/Git hashes and223 final archive entries matched; original24 table fingerprints and dump checksum unchanged.

Findings: a status POST persisted with lost reply is idempotently replayed as its original event, but UI wrongly predicts a new version and never confirms; recent history shows oldest ten of latest100. Controller reconstructed exact server contract: GET omits client_id, so matching visible version/text alone cannot identify the pending key. Confirmation requires same-key POST event identity plus exact read-back; unresolved events remain UNKNOWN. No backend/admission redesign.

Sole READY node A6-UI-STATUS-RECOVERY, one Luna after dispatch commit. Ownership FactWorkflowPanel.tsx/call-facts.spec.ts plus new evidence only. Packet GL3-AUDIT-A6-UI-STATUS-RECOVERY.md SHA13c0f3a98347a00dd046a3444fe6e63ed471a1bd705e0bfe795f8324883678e9. Preserve earlier frozen source, failures and immutable original/saved evidence. Root reruns frozen gates and fresh Sol review after clean handoff.

A8A prepared packet remains DEPENDENT on exact UI PASS; A8B/authentic feeds/quality/seven-day/customer gates OPEN. A7 checksum-matching original PNG/HTML absent, video supplemental. Model/config/unmeasured tokens UNKNOWN. Direction CORRECT; no parent completion or UI publication.
