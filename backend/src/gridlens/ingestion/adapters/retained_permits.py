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
            ("applicant_full_name", "Permit-listed applicant name"),
            ("applicant_phone", "Applicant permit-listed phone (permit field)"),
        )
    },
    "row": "Source record",
    "project": "Permit / case",
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
}
GEORGIA = "georgia-air-draft-title-v"


def fields(source_id: str, text: str) -> dict[str, tuple[str, str]]:
    if source_id not in MAPS and source_id not in {GEORGIA, "houston-weekly-permits"}:
        return {}
    allowed = (
        set(MAPS[source_id])
        if source_id in MAPS
        else set(LABELS)
        if source_id == "houston-weekly-permits"
        else set(LABELS) - set(MAPS["chicago-building-permits"])
    )
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
    output = [
        {"label": label, "value": parsed[key][0], "quote": parsed[key][1]}
        for key, label in LABELS.items()
        if key in parsed
    ]
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
