# Customer intelligence UI captures

These screenshots use one explicitly synthetic browser fixture: Synthetic Northstar Compute (2 projects) and Synthetic Cedar Infrastructure (1 unrelated project), including Mesa campus, a partial upper-bound IT capacity claim on the Northstar account, 1 of 2 Northstar projects carrying capacity, construction-start timing only, insufficient commissioning inputs, and one verified name-only project contact and one distinct Cedar account with no capacity claims. They are layout and behavior evidence, not production data.

`before-main-*` and `before-main-account-detail.png` were rendered from a temporary archive of source HEAD `f8b4caa6` with the earlier bounded mock fixture. Its web subtree is byte-identical to audited main `bf75d327` (both Git tree `8cfdd5336114e7d4598c08b0202f2e394eb99d96`). `after-*` and `after-account-detail.png` were rendered from the working candidate after the customer intelligence UI changes. The later after fixture also adds capacity/timeline conflicts, a commercial brief and a 12.5MW engineering scenario to exercise review repairs; the retained before images lack those later additions. These are illustrative layout states, **not a strictly matched same-input before/after performance or usability comparison**.

Viewport captures: desktop wide (1440×1000), desktop compact (1280×800), tablet landscape (1024×768), tablet portrait (768×1024), and mobile (390×844). Account detail was captured at 1440×1000 after opening its progressive disclosure.

The [delivery checkpoint](DELIVERY.md) records PRs, evaluation results, independent review and release blockers.

## Fresh read-performance repair evidence

[Source-pinned repair measurements](performance/read-repair/README.md) compare backend `1de298af` with `bf75d327`: sampled service SQL counts return to baseline and card payloads shrink versus the earlier candidate. Latency remains above baseline under shared live test/PostgreSQL load; the unchanged service harness and separate actual API-setup supplement retain their distinct limits. No latency regression pass or production-readiness claim follows.

Dated dependency boundary: the later [Soup Sieve security correction](../security-soupsieve-20261113/README.md) changes the runtime lock to 4.0/Python 3.11.5+. Existing performance manifests and receipts remain byte-exact historical measurements with 2.10; they are not a final updated-runtime performance pass.
