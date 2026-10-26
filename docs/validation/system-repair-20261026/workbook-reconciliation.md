# Actual workbook parse and reconciliation

Run date: 2026-10-26. Four user-supplied workbooks were parsed from the provided temporary attachment directory. The report records file hashes, headers/mappings and aggregate counts only; it contains no workbook cell values, raw contact details, or source files.

The run used the existing `config/import-mappings/project-tracker.json` mapping (`Developer` → `company_name`). The tracker also has an `Owner` column; that field remains a separate original source field and does not replace Developer as the company assertion.

| Workbook | SHA-256 | Sheets / parsed rows | Parsed row classes | Parser errors | In-workbook duplicate hints |
| --- | --- | ---: | --- | --- | --- |
| `1-DC-Leads.xlsx` | `8ab4a2abe5a7a03186cb1b6ca7b397c92694d486c10f01070410112a8d688210` | 40 / 2,077 | 2,077 project rows | 0 | 2 exact groups, 80 row references |
| `2-US_Data_Center_Project_Tracker_August_2026.xlsx` | `27494d7a42e070112f8bc18793073cdb3c14e1db940d2de3a02fbb01c5834040` | 4 / 1,072 | 1,011 mixed project/contact rows; 52 summary rows; 9 metadata rows | 2 Power Capacity cells | 1 exact group, 2 row references |
| `3-texas-dc-leads.xlsx` | `b4b52671e3148f212fab479438a89c9c26eca4ccf623479630d5477d73cdf30f` | 8 / 486 | 484 project rows; 2 repeated header rows classified as metadata | 0 | 3 exact groups, 20 row references; 1 probable group, 5 row references |
| `4-Cleanview.xlsx` | `535e762cfdd91208e30cb8a61d2bf4cf5cc4b1e64f20d652d79bbcd99cbd40cf` | 17 / 885 | 885 project rows | 0 | 2 exact groups, 34 row references |

All four source previews were complete and below parser row limits. The reconciliation report returns up to 500 row details per file while computing counts over all parsed rows. Its detail sample included 500 of 2,077, 500 of 1,072, 486 of 486, and 500 of 885 rows, respectively. The omitted detail rows are report sampling, not skipped parsing or matching. Duplicate counts in the table are within each workbook.

The three lead-list workbooks use one repeated 17-column source layout across their sheets. Five of those columns map to Project Name, Developer, Facility Power (MW), IT Capacity (MW), and State; the other 12 source columns are retained but not normalized. The tracker has four distinct sheets: All Projects (1,011 rows), State Summary (46), Status Summary (6), and Read Me (9). Its 22-column main sheet maps project name, address, city, state, Developer, Power Capacity, Project Email, and Project Phone. Summary and Read Me rows remain non-project data.

The Texas workbook contained two exact echoes of its 17-column project header within the project sheet. The parser previously treated them as projects and emitted invalid power errors. They are now retained with their original sheet, row number, and header fields as metadata, with no normalized assertions. A regression test covers this row shape.

The tracker has two Power Capacity cells with unsupported non-scalar text. They remain parse errors and do not become numeric facility capacity, demand, or temporary need. The original workbook remains the source for those cells; their contents are intentionally omitted here.

Across the four workbooks, no mapped field or source header explicitly identifies activity-specific temporary demand. Facility Power, Power Capacity, and IT Capacity are kept as capacity claims. No rows map to committed supply, required-power date, or duration. The tracker’s Completion Date and Date Added remain unmapped; neither becomes a power need date. Imported email and phone fields occur in two rows each and remain unverified business-contact assertions.

The row state labels include 696 TX/OK/NM rows in total: 61 in 1-DC Leads, 178 in the tracker, 457 in Texas DC Leads, and 0 in Cleanview. These are source-row geography counts, not verified territory eligibility or qualified projects. Cleanview’s state-labelled rows are outside TX/OK/NM; other rows have missing state labels.

## Cross-workbook duplicate candidates

The analysis grouped normalized project/mixed rows by exact normalized claims and by weaker name/state keys. Unit-source metadata fields were excluded from exact normalized claim equality; no names, addresses, contacts, or cell values are included in this report.

One exact normalized row group contains 66 row references across 1-DC Leads (40), Texas DC Leads (9), and Cleanview (17). That normalized row contains only `project_name`; it has no normalized company, state, address, city, or power assertion. It is an identical text hint, not evidence of one physical project and not a deduplication decision.

Across the 4,455 project/mixed rows with a project name, 233 normalized project-name/state groups span multiple workbooks (467 row references). Of those, 186 groups also share a normalized company name (372 row references). Project name, state, and company-name agreement still do not establish that rows refer to the same physical site; the source workbooks generally lack a site address in the lead-list layouts.

In 67 of the project-name/state groups, source rows disagree on at least one normalized value across files. Company name differs in 51 groups and facility capacity differs in 24 groups. These source conflicts remain unresolved. No rows were merged or automatically adopted as canonical projects.

## Canonical matching boundary

The repaired read-only reconciliation command was run with the four actual files against the isolated local fixture database `gridlens_repair_workbook_test`. At the time of the run it contained 0 projects, 0 company identities, and 0 power needs. The fixture therefore returned 4,454 unmatched rows, 2 invalid rows, 64 ignored rows, and no exact, probable, or ambiguous canonical matches. Those are fixture results only and say nothing about matches in the production corpus.

A separate local Austin verifier database exists at migration revision `0041_evidence_packages` with 6 projects, 171 evidence rows, 6 power needs, and 0 company identities. It is a limited verifier corpus, not the current production canonical snapshot, and was not used as the four-workbook matching baseline. No current production canonical snapshot was available; production matching remains unmeasured.

The operation used a database transaction enforced read-only at connection level. It did not stage imports, activate rows, promote claims, or write to production. No paid source or enrichment call was used.

Count-only machine-readable results are in [workbook-reconciliation-counts.json](workbook-reconciliation-counts.json). The parser and focused reconciliation tests passed: 35 tests; Ruff and module Mypy checks passed.
