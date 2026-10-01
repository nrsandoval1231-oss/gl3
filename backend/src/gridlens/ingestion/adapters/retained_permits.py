"""Decode the reviewed adapters' retained field format, without network research.

Only official source identities opt into these mappings. Quotes remain byte-exact
in the original Evidence abstract; no reconstructed JSON is treated as evidence.
"""

from __future__ import annotations

import re

from gridlens.ingestion.adapters.socrata_permits import MAPS

LABELS = {
    **{
        key: label
        for key, label in (
            ("contractor_trade", "Permit contractor trade"),
            ("contractor_company_name", "Permit contractor organization"),
            ("contractor_full_name", "Permit-listed contractor name"),
            ("contractor_phone", "Contractor permit-listed phone (permit field)"),
            ("applicant_org", "Applicant-associated organization on permit"),
            ("lp_business_name", "Permit-listed LP Business Name (role unverified)"),
            ("applicant_full_name", "Permit-listed applicant name"),
            ("applicant_phone", "Applicant permit-listed phone (permit field)"),
        )
    },
    "operator": "Permit-listed operator",
    "applicant_org": "CCC-listed cultivation applicant organization",
    "applicant_role": "Applicant role on CCC cultivation application",
    "business_email": "CCC-listed applicant business email (source field; authority unknown)",
    "business_phone": "CCC-listed applicant business phone (source field; authority unknown)",
    "application_number": "CCC application number",
    "license_number": "CCC license number",
    "application_stage": "CCC application stage",
    "original_submitted_date": "CCC original submitted date",
    "application_created_date": "CCC application created date",
    "application_approved_date": "CCC application approval date",
    "application_denied_date": "CCC application denial date",
    "license_status": "CCC license status",
    "commence_operations_date": "CCC commence operations date",
    "final_licensure_date": "CCC final licensure date",
    "license_start_date": "CCC license start date",
    "license_original_start_date": "CCC original license start date",
    "license_expiration_date": "CCC license expiration date",
    "license_revocation_date": "CCC license revocation date",
    "license_surrendered_date": "CCC license surrender date",
    "license_suspended_start_date": "CCC license suspension start date",
    "license_suspended_end_date": "CCC license suspension end date",
    "snapshot_updated": "CCC snapshot update date",
    "operator_number": "RRC operator number",
    "lease": "Lease",
    "well": "Well number",
    "county_code": "RRC county code",
    "amendment_sequence": "RRC amendment sequence (decreases on amendment)",
    "amended_date": "Reported amendment date",
    "application_received": "Application received date",
    "application_type": "RRC application type code",
    "row": "Source record",
    "project": "Permit / case",
    "object_id": "ArcGIS row ID (raw provenance)",
    "address": "Site address",
    "type": "Permit type",
    "work": "Work type",
    "description": "Permit scope",
    "date": "Permit issue date",
    "application_start": "Application start date",
    "status": "Permit status",
    "milestone": "Permit milestone",
    "parcel": "Parcel",
    "Facility": "Facility",
    "Location": "Location",
    "Application number": "Application number",
    "Application received date": "Application received date",
    "Application date": "Application date",
    "Public comment deadline": "Public comment deadline",
    "event": "Reported permit event",
    "contact_type": "Contact type",
    "district": "Council district",
    "area": "Gross building area",
    "cost": "Reported job value",
    "units": "Proposed dwelling units",
    "zoning": "Base zoning",
    "application_status": "Permit application status",
    "geocode_status": "Geocoding status (not permit lifecycle)",
    "owner_name": "Permit-listed owner",
    "report_start": "Weekly report period start",
    "report_end": "Weekly report period end (exclusive)",
    "layer_feature_count": "El Paso layer feature count (metadata)",
    "window_feature_count": "El Paso issue-window feature count",
    "window_unique_permit_count": "El Paso unique permit count in issue window",
    "source_as_of": "El Paso source query date",
    "detail_project": "Houston exact permit project number",
    "detail_date": "Houston sold permit detail date",
    "detail_use": "Permit use / work description",
    "detail_owner_occupant": "Permit-listed owner / occupant",
    "detail_site_address": "Permit job address",
    "detail_valuation": "Permit valuation",
    "detail_permit_type": "Permit type code",
    "detail_fcc_group": "Houston permit FCC group",
    "detail_buyer": "Permit-listed Buyer (entity type unknown)",
    "detail_buyer_address": "Permit-listed buyer address",
    "detail_buyer_phone": "Permit-listed buyer phone",
    "zip": "Reported ZIP code",
}
GEORGIA = "georgia-air-draft-title-v"
CITY_MAPS = {
    "dallas-monthly-permits": {
        "row": "Permit / case",
        "project": "Permit / case",
        "date": "Permit issue date",
        "event": "Reported permit event",
        "status": "Permit status",
        "applicant_full_name": "Permit-listed applicant name",
        "lp_business_name": "Permit-listed LP Business Name (role unverified)",
        "contact_type": "Contact type",
        "type": "Permit type",
        "work": "Work type",
        "proposed_land_use": "Proposed land use",
        "description": "Permit scope",
        "address": "Site address",
        "district": "Council district",
        "area": "Gross building area",
        "cost": "Reported job value",
        "units": "Proposed dwelling units",
        "zoning": "Base zoning",
    },
    "el-paso-new-commercial-permits": {
        "row": "B1_ALT_ID permit ID",
        "object_id": "OBJECTID GIS row ID",
        "project": "Permit / case",
        "date": "Permit issue date",
        "event": "Reported permit event",
        "status": "Permit application status",
        "geocode_status": "Geocoding status (not permit lifecycle)",
        "owner_name": "Permit-listed owner",
        "type": "Permit type",
        "work": "Permit work label",
        "description": "Permit scope",
        "address": "Site address",
        "cost": "Reported job value",
    },
}
CULTIVATION_FIELDS = {
    "applicant_org": "Applicant organization (CCC cultivation application)",
    "applicant_role": "Applicant role on CCC cultivation application",
    "business_email": "CCC-listed applicant business email (source field; authority unknown)",
    "business_phone": "CCC-listed applicant business phone (source field; authority unknown)",
    "application_number": "CCC application number",
    "license_number": "CCC license number",
    "license_type": "CCC license type",
    "application_status": "CCC application status",
    "application_stage": "CCC application stage",
    "event_date": "CCC application event date",
    "event_date_label": "CCC application event date type",
    "original_submitted_date": "CCC original submitted date",
    "application_created_date": "CCC application created date",
    "application_updated_date": "CCC application updated date",
    "establishment_address": "CCC establishment street address",
    "city": "CCC establishment city",
    "state": "CCC establishment state",
    "zip": "CCC establishment ZIP",
    "license_status": "CCC license status",
    "commence_operations_date": "CCC commence operations date",
    "license_start_date": "CCC license start date",
    "license_expiration_date": "CCC license expiration date",
    "snapshot_updated": "CCC snapshot update date",
}


def fields(source_id: str, text: str) -> dict[str, tuple[str, str]]:
    if source_id not in MAPS and source_id not in CITY_MAPS and source_id not in {
        GEORGIA,
        "houston-weekly-permits",
        "texas-rrc-drilling-permits",
        "ma-ccc-cultivation-applications",
    }:
        return {}
    allowed = (
        set(MAPS[source_id])
        if source_id in MAPS
        else set(CITY_MAPS[source_id])
        if source_id in CITY_MAPS
        else set(LABELS)
        if source_id in {"houston-weekly-permits", "texas-rrc-drilling-permits"}
        else set(LABELS) - set(MAPS["chicago-building-permits"])
    )
    if source_id == "ma-ccc-cultivation-applications":
        allowed = set(CULTIVATION_FIELDS)
    result: dict[str, tuple[str, str]] = {}
    duplicates: set[str] = set()
    for line in text.splitlines():
        key, separator, value = line.partition(": ")
        if separator and key in allowed and value.strip():
            if key in result:
                duplicates.add(key)
            result[key] = (value, line)
    # Ambiguous repeated field labels never manufacture a relationship.
    return {key: value for key, value in result.items() if key not in duplicates}


def facts(source_id: str, text: str) -> list[dict[str, str]]:
    parsed = fields(source_id, text)
    selected_labels = (
        CULTIVATION_FIELDS.items()
        if source_id == "ma-ccc-cultivation-applications"
        else LABELS.items()
    )
    output = [
        {"label": label, "value": parsed[key][0], "quote": parsed[key][1]}
        for key, label in selected_labels
        if key in parsed
    ]
    if source_id == "houston-weekly-permits":
        for item in output:
            if item["label"] == "Permit issue date":
                item["label"] = "Permit sale event date (weekly report)"
    if source_id == "el-paso-new-commercial-permits":
        for item in output:
            if item["label"] == "Permit issue date":
                item["label"] = "ISSUEDATE (official issue-event date)"
    if source_id == "chicago-building-permits":
        if "address" in parsed and parsed["address"][0].isdigit():
            # Historical GL3-018 abstracts stored the street number separately.
            for item in output:
                if item["label"] == "Site address":
                    item["label"] = "Site street number"
            for key, label in (
                ("street_direction", "Street direction"),
                ("street_name", "Street name"),
            ):
                if key in parsed:
                    output.append(
                        {"label": label, "value": parsed[key][0], "quote": parsed[key][1]}
                    )
        for number in range(1, 16):
            name = parsed.get(f"contact_{number}_name")
            role = parsed.get(f"contact_{number}_type")
            if name and role:
                output.append(
                    {
                        "label": f"Permit-listed party · {role[0]}",
                        "value": name[0],
                        "quote": name[1],
                        "role_quote": role[1],
                    }
                )
    if source_id == GEORGIA:
        proponent = georgia_proponent(text)
        if proponent:
            output.append(
                {
                    "label": "Named construction proponent",
                    "value": proponent[0],
                    "quote": proponent[1],
                }
            )
        link = re.search(
            r"draft permit URL: (https://epd\.georgia\.gov/document/document/[A-Za-z0-9_-]+-draft/download)",
            text,
        )
        if link and georgia_identity(text):
            output.append(
                {
                    "label": "Draft permit document · page 1",
                    "value": link.group(1),
                    "quote": link.group(0),
                }
            )
        for label, value, quote in georgia_identity(text):
            output.append({"label": label, "value": value, "quote": quote})
    return output


def chicago_contacts(text: str) -> list[tuple[str, str, str, str]]:
    parsed = fields("chicago-building-permits", text)
    return [
        (
            parsed[f"contact_{n}_name"][0],
            parsed[f"contact_{n}_type"][0],
            parsed[f"contact_{n}_name"][1],
            parsed[f"contact_{n}_type"][1],
        )
        for n in range(1, 16)
        if f"contact_{n}_name" in parsed
        and f"contact_{n}_type" in parsed
        # A person formatted LAST, FIRST is kept in the permit facts only. The
        # permit does not tell us their employer or current organization role.
        and not re.fullmatch(r"[A-Z'-]+,\s*[A-Z .'-]+", parsed[f"contact_{n}_name"][0])
    ]


def georgia_identity(text: str) -> list[tuple[str, str, str]]:
    lines = [line for line in text.splitlines() if line.startswith("Draft identity (page 1): ")]
    if len(lines) != 1:
        return []
    patterns = (
        ("Draft permit entity", r"Facility Name: (?P<value>.{1,200}?) (?=Facility Address:)"),
        (
            "Draft facility site",
            r"Facility Address: (?P<value>.{1,500}?) (?=Mailing Address:|Facility AIRS Number:)",
        ),
        ("Draft permit scope", r"is issued a Permit for the following: (?P<value>.{1,800})$"),
    )
    return [
        (label, match.group("value"), match.group(0))
        for label, pattern in patterns
        if (match := re.search(pattern, lines[0]))
    ]


def georgia_proponent(text: str) -> tuple[str, str] | None:
    match = re.search(
        r"Background Information (?P<name>[A-Za-z0-9&, .'-]{2,120}\b(?:LLC|Inc\.?)) "
        r"proposes to construct a new data center[^.]{0,240}\.",
        text,
    )
    return (match.group("name"), match.group(0)) if match else None
