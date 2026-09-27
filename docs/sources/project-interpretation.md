# Retained RSS project interpretation

The worker retains each publisher item and evidence version before evaluating its title and short summary. It evaluates the same current version automatically during the ordinary RSS job. Failed decisions remain visible and are retryable on later refreshes. Identical semantic versions and evaluator versions reuse their durable decision without creating new observations, evidence or change events.

The deterministic `rss-project-v6` evaluator admits a Signal only when one event clause supports an identifiable project or site, a concrete physical facility action, and a US location tied to that event. It rejects policy, recall, aggregate, speculative, canceled, international and unrelated corporate activity. A company headquarters or contractor location does not establish a project location. Short summaries may omit facts, and those remain Unknown.

A Prospect additionally requires separate literal statements that bind the same named site and the same power activity to an actual MW requirement and an affirmative asserted predicate that supply is delayed, insufficient, or unavailable. That bound power activity takes precedence over an event-title phase when evaluating a resolved supply statement; a resolved statement blocks promotion only for the matching site and activity. Signals expose an activity only when their retained action explicitly maps to construction or operations; other actions remain unknown. Nameplate capacity, generation output, campus-wide totals, generic grid delay, another site's facts, negated or speculative claims, and secured adequate supply do not pass that gate. The stored MW value is the exact qualifier/number/unit phrase matched to the activity-specific requirement, never an earlier campus total in the same retained clause. A Prospect retains both exact quote spans, the stated MW text, the evidence version, and the facts still missing for a Lead. The pipeline never creates or promotes a Lead.

The offline review command is read-only by default and reports every retained RSS item in deterministic order:

```powershell
uv run --project backend python scripts/reinterpret_news.py --output .artifacts/GL3-007/dry-run.json
```

The report contains both accepted and rejected decisions. `--limit N` limits that report deterministically. `--apply` is a separate transaction mode that reads current RSS observations and matching retained evidence directly from `DATABASE_URL`; it does not trust an older snapshot file and performs no source retrieval. Apply only from the controller's authorized local run after inspecting the complete dry-run report. Repeating apply is idempotent.

Current limitations: this is a conservative rule parser over retained title/summary text, not full-article research or general entity resolution. Cross-publisher linking requires exact normalized title/summary plus the same supported subject, site/location, and action; publication date and publisher do not affect the match. Different text remains separate even when company and state match. The all-105 retained snapshot produced four Signals and no Prospects. That is a bounded sample result, not a coverage or completeness claim. Existing government/non-RSS interpretation behavior is unchanged.
