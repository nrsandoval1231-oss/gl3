"""Source-reviewed regional context; never a project permit or power-gap decision."""

import re
from datetime import date
from typing import Any

EFFECTIVE_ON = date(2026, 9, 21)
VERIFIED_ON = date(2026, 10, 7)
_TEXAS_SITE_END = re.compile(r"(?:^|[\s,])(?:TX|Texas)(?:\s+\d{5}(?:-\d{4})?)?\s*$", re.I)


def texas_permitting_context(
    *, asset_type: str, site: dict[str, Any], as_of: date
) -> list[dict[str, Any]]:
    """Return a dated policy snapshot separately from evidence-supported project state.

    A scope match only identifies a question to investigate. It does not attest
    that a particular permit is required, pending, halted, denied, or revoked.
    The review date bounds currency; the reporting deadline never ends the pause.
    """
    if as_of < EFFECTIVE_ON or asset_type not in {"data_center", "unknown"}:
        return []
    location = site.get("value")
    scope_match = (
        asset_type == "data_center"
        and site.get("status") == "SUPPORTED"
        and isinstance(location, str)
        and bool(_TEXAS_SITE_END.search(location))
    )
    return [
        {
            "id": "tx-tceq-data-center-permitting-pause-2026-09-21",
            "policy_kind": "state_environmental_permitting_pause",
            "status": "directed_pause",
            "issuing_authority": "Governor of Texas",
            "implementing_agency": "TCEQ",
            "effective_on": EFFECTIVE_ON.isoformat(),
            "geographic_scope": "Texas statewide",
            "asset_scope": "data_center",
            "minimum_mw": None,
            "completion_condition": (
                "ERCOT completes its audit/review; necessary audit information is acquired "
                "before state agencies advance data-center regulatory approvals."
            ),
            "agency_implementation": (
                "TCEQ's construction-stormwater notice halts data-center-associated permit "
                "applications, including TPDES Construction General Permit coverage, until "
                "further notice from the Office of the Texas Governor."
            ),
            "reporting_deadline": "2026-10-19",
            "reporting_deadline_kind": "TCEQ compliance update to Governor",
            "expires_on": None,
            "verified_on": VERIFIED_ON.isoformat(),
            "current_status_verification": (
                "verified_snapshot" if as_of == VERIFIED_ON else "requires_refresh"
            ),
            "project_applicability": (
                "regional_scope_match" if scope_match else "requires_verification"
            ),
            "project_permit_status": "UNKNOWN",
            "limitations": (
                "Regional policy context, not a project denial or cancellation. No verified "
                "project-specific hold, permit revocation, power gap, MW, timing or duration "
                "is inferred. ERCOT interconnection restrictions and 16 TAC §25.194 are "
                "separate mechanisms. No automatic release at the reporting deadline or "
                "upon an assumed audit completion. Recheck current agency guidance and "
                "the project's permit record; no official rescission found in sources "
                "checked on the verification date."
            ),
            "sources": [
                {
                    "publisher": "Office of the Texas Governor",
                    "url": "https://gov.texas.gov/news/post/"
                    "governor-abbott-directs-tceq-to-halt-data-center-permits",
                    "source_date": "2026-09-21",
                    "verified_on": VERIFIED_ON.isoformat(),
                    "extraction_location": "announcement: directive and compliance update",
                },
                {
                    "publisher": "Office of the Texas Governor",
                    "url": "https://gov.texas.gov/uploads/files/press/TCEQ_Data_Center.pdf",
                    "source_date": "2026-09-21",
                    "verified_on": VERIFIED_ON.isoformat(),
                    "extraction_location": "letter to Kelly Keel, pages 1-2",
                },
                {
                    "publisher": "TCEQ",
                    "url": "https://www.tceq.texas.gov/permitting/stormwater/construction",
                    "source_date": None,
                    "verified_on": VERIFIED_ON.isoformat(),
                    "extraction_location": "Special Notice: Directive from Office of Governor",
                },
            ],
        }
    ]
