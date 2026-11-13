# Independent contact-refresh evidence review

Review date: 2026-11-13. Scope: the retained [contact refresh](../../../../eval/customer-commercial-v1/contact-refresh/README.md), its source manifest and SEC identity evidence. This reviewer changed only this report, ran independent read-only Python checks, and inspected the complete retained source context around the selected roles. No network retrieval, database operation, product/test edit or outreach was performed.

**Final scoped disposition: accepted as a source-backed research dataset after the corrections and independent recheck recorded below.** The three positive SEC issuer/domain proofs pass the bounded source review. This is not acceptance of application contacts, native identities, project assignment, buying authority or commercial completeness. The initial findings remain below as dated review history.

## Independently verified evidence

- All 20 reference organizations are represented; 36 named-role records and 17 organizational channels were checked. Every selected person quotation occurs literally in its cited retained Markdown. Every organizational contact URL/shared inbox occurs in its cited page. No individual contact method was invented or inferred.
- All 34 manifest source entries were checked. The 32 complete rendered texts match their declared SHA-256 and character counts, and byte counts where provided. The two excerpt-only SEC captures (Amazon and Digital Realty) are explicitly identified as excerpts; their hashes and manifest excerpt lengths match. Supplemental excerpt text in complete SEC captures occurs in the corresponding full Markdown.
- All 12 SEC identity quotation byte ranges reproduce the exact UTF-8 quote bytes; all quote hashes and referenced full-source hashes match. Manifest URLs match the capture URL and retained source URL metadata where supplied.
- All five recorded SEC filing dates, primary-document paths, CIKs and EINs were checked against the retained index. Applied Digital, Equinix, Microsoft and Meta indexes explicitly identify Form 10-K. Dominion's index explicitly identifies **ARS**, not 10-K.
- Both unchanged gold files retain SHA-256 `dd061c52a85b0ba05b59aab4229f5dd886bced31145fe6ab315c5ad1cda0b922`.

| Positive issuer proof | EIN | Index filing date | Filing website / relevant host |
| --- | --- | --- | --- |
| APPLIED DIGITAL CORPORATION | 95-4863690 | 2026-07-29 | `www.applieddigital.com` / `ir.applieddigital.com` |
| EQUINIX, INC. | 77-0487526 | 2026-02-11 | `www.equinix.com` / `newsroom.equinix.com` |
| MICROSOFT CORPORATION | 91-1144442 | 2026-07-29 | `www.microsoft.com` / `blogs.microsoft.com` |

Each positive combines the exact issuer, EIN and website statement in the same retained filing, with its document listed in the matching SEC index. The stated root domains support the recorded domain-family comparison; this does not identify a physical project, assign a person to it, establish a GridLens UUID or independently establish a subsidiary's legal identity.

Meta remains correctly held: the cited statements identify `investor.atmeta.com` and `meta.com/news`, without the proposed project-host binding. Digital Realty remains held because its joint filing includes separate Inc. and L.P. entities/EINs. Amazon.com, Inc. does not establish an AWS legal identity or the `aboutamazon.com` host. Dominion's ARS/index pair remains supporting evidence, outside the three complete same-10-K proofs.

## Required corrections found in the initial snapshot

1. **Vantage role history is incomplete.** The selected Jeff Tench quotation calls him President, North America, and the dataset flags conflict with Dana Adams. The same retained page also states `Jeff TenchExecutive Vice President, Global` and explicitly says this expands on his **previous position as president, North America**. Preserve this materially relevant newer-role/history statement and the residual page contradiction. Do not count the old president fragment as a verified current North American buyer. Samuel Huckaby appears in the older page section; observation establishes that the page contains his name, not independently that this role is current. No effective date should be invented.
2. **Dominion association needs its stated division.** Emil Avram's title is immediately followed by `Dominion Energy Virginia`. The selected quote and generic “Corporate construction/development roles” description omit that association. Retain the division explicitly; the parent's leadership page cannot establish employment by the exact parent legal issuer. The Dominion contact row also references nonexistent evidence ID `dominion-sec-annual-report-domain`; the actual record is `dominion-sec-annual-report-domain-support`.
3. **Publication metadata loses captured dates.** The source manifest labels the AWS and Microsoft Pecos publication dates as not stated, although the retained pages explicitly show January 25, 2024 and June 22, 2026 respectively. The person rows already use those dates. Normalize these consistently, preserving publication versus observation. The Dominion manifest's February 23, 2026 date comes from unverified search metadata, whereas the retained index establishes the ARS filing on March 19, 2026. Do not silently treat search metadata as verified publication/filing chronology; preserve the distinction or leave unsupported publication date null. The Dominion PDF capture also must not be described as an HTML scrape.

These findings were sent to the coordinator and researcher. A later correction does not retroactively change the initial checked snapshot; a follow-up disposition must identify new hashes.

## Relevance and currentness limits

The selected functions generally concern development, construction, operations, engineering, energy or delivery. These are plausible research leads, not demonstrated equipment procurement authority. AWS's Roger Wehner is explicitly historical-only and must remain outside current buyer coverage. Microsoft supports Noelle Walsh's role as of June 22, 2026, approximately five months before observation; a 365-day rule is a product freshness policy, not proof of continued employment. Undated rosters establish a role statement observed on November 13, not a start date or guaranteed current employment.

STACK's Omar Muhialdin is expressly APAC; he cannot support SVY01/San Jose project relevance or an Americas contact count merely because the corporate roster lists him. Current QTS page branding/footer says QTS Realty Trust, LLC; the research association must not silently bind to a historical Inc. issuer. Most rows explicitly withhold project assignment. TerraPower's two roles are tied to the Natrium program; that alone does not establish specific purchasing rights. Google and Meta have no full relevant named-person assertion in this dataset. No quoted role effective date used by the person records is later than observation; future-looking language in a biography does not establish a future effective appointment date.

The dataset contains useful source-backed research, but **36 named records is not 36 verified current project buyers**. Three legal-issuer/domain proofs are not three verified project-owner bindings. Neither this review nor the retained research executes contact acquisition, native attribution, suppression/history guards or the browse publication path. The separate runtime work currently reports only two eligible Texas sources; held/out-of-region sources and company helper work remain separate. This report makes no native identity accuracy or application contact-coverage claim.

## Initial snapshot receipts

| Artifact | SHA-256 |
| --- | --- |
| `contact-refresh.json` | `9f6d0faf03f02eb88560262e766e23e168aa7de2973d474440d51846758eb00f` |
| `source-manifest.json` | `61e403b7a488426d7a9a666cec402e9b6e90a04e0a21c1456d61be1016883a23` |
| `company-identity-evidence.json` | `427bb57df9e50c173bbc34857ab2012a75e537c0fa9e449b26b99b7153489024` |
| All 39 retained raw files, aggregate described below | `9c68a884f9814a208500505176d6611fcc170bdfd86d4a954234f5caf09c852e` |

The raw aggregate is SHA-256 over UTF-8 lines `file_sha256 + "  " + relative_path + "\n"`, ordered by raw filename; paths are relative to `contact-refresh/`. Checks used Python standard-library `hashlib`, `json`, `re` and `pathlib`, independently of the dataset builder scripts. Raw contact offsets were checked by exact quotation search; explicit byte offsets are supplied and verified for SEC quotations. Full upstream HTML/PDF bytes and independent server timestamps were not retained by this dataset, so these hashes bind the rendered captures, not original publisher bytes.

## Corrected snapshot recheck and disposition

On 2026-11-13, this reviewer independently rechecked the corrected frozen package. Result: **20 unique reference IDs matching gold; 36 literal person-role quotations; one literal role-history quotation; 34 manifest sources; 32 complete-text hash checks; 16 excerpt hash/length checks; 17 literal organizational channels; 12 exact SEC byte-range/hash checks; five matching SEC index filing dates/document paths/CIKs/EINs; zero integrity errors or dangling identity-evidence references.** Publisher-date quotations and the QTS legal-form footer quotation were also checked against retained text. The unchanged gold hashes remain as recorded above.

The corrections close the initial findings:

- Vantage now records Jeff Tench's explicit global EVP biography, its EMEA/APAC remit and the prior North America role, while preserving the page's older fragment and unspecified effective dates. Dana's North America responsibilities remain source-backed; Samuel's current employment is expressly unverified. Neither is assigned to Frontier by this dataset.
- Emil Avram's exact quote and role now retain Dominion Energy Virginia, without parent-employment inference. The generic assignment text now says “Listed construction/development roles,” and the referenced Dominion evidence ID resolves.
- AWS publication is January 25, 2024; Microsoft Pecos publication is June 22, 2026; the Fairwater announcement is September 18, 2025. These match explicit captured publisher text. SEC index filing dates occupy separate fields. Dominion is correctly described as a PDF annual report filed as ARS on March 19, 2026, with publication date unknown; the earlier search-derived February date is not promoted.
- QTS remains a brand-level association with the LLC footer recorded, without historical-Inc. legal binding. STACK's APAC role is explicitly out of region for SVY01. Meta, Digital Realty and AWS identity holds remain intact.

**No material factual or provenance defect remains in this bounded corrected research package.** All currentness, project-assignment, buyer-authority and application-publication limitations above still apply. No application contact-coverage denominator, native identity accuracy or live pipeline acceptance is established by this disposition.

| Final artifact | SHA-256 |
| --- | --- |
| `contact-refresh.json` | `88e64460f65fc52f334eea3782f06f32e804f4293f85ea2a447c1cd94d588ad0` |
| `source-manifest.json` | `3a8cdc16535cc178f48f21bc1082d691e418d1ae9f9ce4d82aa4d8299ba6add5` |
| `company-identity-evidence.json` | `da49605ec56d5527d7bf99fb7d548a8124176d2a20c7bc61b2bb2621d8cecf2a` |
| `README.md` | `1f0e80075f220612cc92e0ae023c161da87d1d85253025f8eed9353e0c6564d6` |
| `build_manifest.py` | `eb997fda976612c5791b7a2e7b6cb53ef4fde15a9723dae2987b3dad459dba34` |
| `build_identity_evidence.py` | `a19d39155b3ed27475e5209d77e03c06a06f82e37d0d3bae486b846992305173` |
| All 39 retained raw files, same aggregate algorithm | `dc89c4c2730f730a3d8213753fba392816226a126e087761c5f98699af537064` |

The raw-file aggregate changed with capture metadata/path corrections, including the Dominion annual-report filename; the checked source-text hashes and exact SEC quote content remain valid. Final independent assertion-based recheck exited zero with `FINAL_RECHECK_PASS`. The prior initial snapshot receipts remain historical and are not overwritten.
