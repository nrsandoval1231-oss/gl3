#!/usr/bin/env python3
"""Build quoted, offset-addressed issuer/domain evidence from saved sources."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw"
OUT = ROOT / "company-identity-evidence.json"


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def quote(path_name: str, label: str, text: str) -> dict[str, object]:
    raw = (RAW / path_name).read_bytes()
    raw_text = raw.decode("utf-8")
    raw_quote = text.encode("utf-8")
    start = raw.find(raw_quote)
    if start < 0:
        raise SystemExit(f"quote not found in captured source: {path_name}:{label}")
    return {
        "label": label,
        "text": text,
        "byte_start": start,
        "byte_end": start + len(raw_quote),
        "sha256_utf8": digest(text),
        "raw_file": f"raw/{path_name}",
        "raw_source_sha256_utf8": hashlib.sha256(raw).hexdigest(),
    }


def main() -> None:
    applied = "sec-apld-10k.md"
    equinix = "sec-equinix-10k.md"
    microsoft = "sec-microsoft-10k.md"
    meta = "sec-meta-10k.md"
    dominion = "sec-dominion-annual-report.md"
    items = [
        {
            "evidence_id": "applied-digital-sec-domain-proof",
            "customer_reference_id": "applied-ellendale",
            "status": "supported_exact_issuer_and_registered_domain",
            "issuer_name": "APPLIED DIGITAL CORPORATION",
            "ein": "95-4863690",
            "cik": "0001144879",
            "sec_filing_type": "10-K",
            "filing_date": "2026-07-29",
            "sec_filing_url": "https://www.sec.gov/Archives/edgar/data/1144879/000114487926000048/apld-20260531.htm",
            "sec_index_source_id": "sec-apld-index",
            "official_domain_statement": "www.applieddigital.com",
            "reference_source_host": "ir.applieddigital.com",
            "host_comparison": "same registered domain: applieddigital.com",
            "quotes": [
                quote(applied, "exact_registrant_name", "| APPLIED DIGITAL CORPORATION |\n\n(Exact name of registrant as specified in its charter)"),
                quote(applied, "issuer_ein", "| Nevada | 95-4863690 |\n| (State or other jurisdiction of incorporation or organization) | (I.R.S. Employer Identification No.) |"),
                quote(applied, "issuer_website", "Our principal website address is www.applieddigital.com."),
            ],
            "limits": "Current leadership page is separately captured. No project-specific assignment is inferred from the issuer/domain proof.",
        },
        {
            "evidence_id": "equinix-sec-domain-proof",
            "customer_reference_id": "equinix-jh2",
            "status": "supported_exact_issuer_and_registered_domain",
            "issuer_name": "EQUINIX, INC.",
            "ein": "77-0487526",
            "cik": "0001101239",
            "sec_filing_type": "10-K",
            "filing_date": "2026-02-11",
            "sec_filing_url": "https://www.sec.gov/Archives/edgar/data/1101239/000110123926000032/eqix-20251231.htm",
            "sec_index_source_id": "sec-equinix-index",
            "official_domain_statement": "www.equinix.com",
            "reference_source_host": "newsroom.equinix.com",
            "host_comparison": "same registered domain: equinix.com",
            "quotes": [
                quote(equinix, "exact_registrant_name", "EQUINIX, INC.\n\n(Exact name of registrant as specified in its charter)"),
                quote(equinix, "issuer_ein", "| Delaware |  | 77-0487526 |\n| (State of incorporation) |  | (I.R.S. Employer Identification No.) |"),
                quote(equinix, "issuer_website", "You may also obtain copies of our annual reports on Form 10-K, our quarterly reports on Form 10-Q and our current reports on Form 8-K, including exhibits, and any amendments to such reports, free of charge by visiting the Investor Relations page on our website, www.equinix.com."),
            ],
            "limits": "Current leadership page separately names Raouf Abdel; no JH2 project assignment is inferred.",
        },
        {
            "evidence_id": "microsoft-sec-domain-proof",
            "customer_reference_id": "microsoft-fairwater",
            "status": "supported_exact_issuer_and_registered_domain",
            "issuer_name": "MICROSOFT CORPORATION",
            "ein": "91-1144442",
            "cik": "0000789019",
            "sec_filing_type": "10-K",
            "filing_date": "2026-07-29",
            "sec_filing_url": "https://www.sec.gov/Archives/edgar/data/789019/000119312526323660/msft-20260630.htm",
            "sec_index_source_id": "sec-microsoft-index",
            "official_domain_statement": "www.microsoft.com",
            "reference_source_host": "blogs.microsoft.com",
            "host_comparison": "same registered domain: microsoft.com",
            "quotes": [
                quote(microsoft, "exact_issuer_name_and_ein", "Commission File Number 001-37845\n\nMICROSOFT CORPORATION\n\n|     |     |     |\n| --- | --- | --- |\n|  |  |  |\n| Washington |  | 91-1144442 |\n| (STATE OF INCORPORATION) |  | (I.R.S. ID) |"),
                quote(microsoft, "issuer_website", "Our Internet address is www.microsoft.com."),
            ],
            "limits": "The current Noelle Walsh source is company-wide Cloud Operations + Innovation leadership; it does not assign her to Fairwater.",
        },
        {
            "evidence_id": "meta-sec-domain-review",
            "customer_reference_id": "meta-richland",
            "status": "hold_project_host_not_explicitly_bound",
            "issuer_name": "Meta Platforms, Inc.",
            "ein": "20-1665019",
            "cik": "0001326801",
            "sec_filing_type": "10-K",
            "filing_date": "2026-01-29",
            "sec_filing_url": "https://www.sec.gov/Archives/edgar/data/1326801/000162828026003942/meta-20251231.htm",
            "sec_index_source_id": "sec-meta-index",
            "official_domains_stated_in_filing": ["investor.atmeta.com", "meta.com/news"],
            "reference_source_host": "datacenters.atmeta.com",
            "host_comparison": "not established by the captured statement; do not broaden from investor.atmeta.com or meta.com/news to datacenters.atmeta.com",
            "quotes": [
                quote(meta, "issuer_ein", "| Delaware | 20-1665019 |\n| (State or other jurisdiction of incorporation or organization) | (I.R.S. Employer Identification Number) |"),
                quote(meta, "filing_website_statement", "Such reports and other information filed by us with the SEC are available free of charge on our website at investor.atmeta.com when such reports are available on the SEC's website. We use our investor.atmeta.com and meta.com/news websites as well as Mark Zuckerberg's Facebook profile (www.facebook.com/zuck), Instagram account (www.instagram.com/zuck), and Threads profile (www.threads.net/zuck) as means of disclosing material non-public information and for complying with our disclosure obligations under Regulation FD."),
            ],
            "limits": "Meta's official project page is retained separately. The SEC text does not make a direct project-host binding.",
        },
        {
            "evidence_id": "dominion-sec-annual-report-domain-support",
            "customer_reference_id": "dominion-cvow",
            "status": "supporting_annual_report_and_sec_index_pair_not_10k_proof",
            "issuer_name": "Dominion Energy, Inc.",
            "ein": "54-1229715",
            "cik": "0000715957",
            "sec_filing_type": "ARS (annual report); the SEC index is not a 10-K filing",
            "filing_date": "2026-03-19",
            "sec_filing_url": "https://www.sec.gov/Archives/edgar/data/715957/000119312526115192/dei-ars-12312025.pdf",
            "sec_index_source_id": "sec-dominion-index",
            "official_domain_statement": "https://www.dominionenergy.com",
            "reference_source_host": "www.dominionenergy.com",
            "host_comparison": "same stated host family in issuer annual report",
            "quotes": [
                quote(dominion, "issuer_name", "Dominion Energy, Inc."),
                quote(dominion, "issuer_website", "available, free of charge, through Dominion Energy’s website,\nhttps://www.dominionenergy.com, as soon as reasonably\npracticable after filing or furnishing the material to the SEC."),
            ],
            "limits": "This is supporting identity evidence from an annual report and SEC index, not a completed same-10-K parser proof.",
        },
    ]
    OUT.write_text(
        json.dumps({"schema_version": "gridlens-company-domain-evidence-v1", "observed_at": "2026-11-13", "records": items}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {OUT.name}: {len(items)} records")


if __name__ == "__main__":
    main()
