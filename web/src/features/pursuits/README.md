# Pursuits presentation

Displays persisted, backend-ranked daily power pursuits and their source evidence. The API owns screening, research, identity, action status, ranking, and tier rules. This view does not calculate demand or promote evidence tiers.

Manual refresh queues the existing worker job and polls saved results. Call notes are attributed owner entries appended through an idempotent API request, distinct from public-source findings.
