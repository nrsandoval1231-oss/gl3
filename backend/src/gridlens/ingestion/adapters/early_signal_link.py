"""Deterministic docket-to-project links: PUCT certificate dockets to ERCOT RPG projects.

A link exists only when both sides state the same key, and the key is exact after a fixed
normalisation of the *stated* names (never fuzzy matching):

* ``substation_county``  each side states exactly one distinct substation name and one distinct
  county, and both values are equal after normalisation (case, accents, punctuation, the words
  station, substation, switch, switching, new, proposed, future, tap and a voltage token removed);
* ``rpg_id``            the docket's own text cites an RPG project ID that is an ERCOT project we
  hold (an exact identifier).

Evidence from both sides (value, page, verbatim quote, document hash, URL) travels with the link.
No candidate, more than one candidate project, or keys that point to different projects means no
link (unknown), with the reason; a link is never guessed from similar names, nearby places or an
agreeing cost or MW. A link says the two documents describe the same facility, not who the
customer is.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterable
from typing import Any

VERSION = "early-signal-link-v1"
KEY_TYPES = ("substation_county", "rpg_id")
_COMPASS = frozenset(
    {
        "north",
        "south",
        "east",
        "west",
        "northeast",
        "northwest",
        "southeast",
        "southwest",
        "central",
    }
)
_DROP = frozenset(
    {
        "substation",
        "station",
        "switching",
        "switch",
        "sub",
        "new",
        "proposed",
        "future",
        "tap",
        "the",
        "kv",
    }
)
_VOLTAGE = re.compile(r"^\d{2,3}(?:/\d{2,3})?(?:kv)?$")


def norm_substation(name: Any) -> str | None:
    if not isinstance(name, str):
        return None
    text = unicodedata.normalize("NFKC", name).casefold()
    text = "".join(
        c if c.isalnum() else " "
        for c in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(c)
    )
    tokens = [t for t in text.split() if t not in _DROP and not _VOLTAGE.match(t)]
    joined = " ".join(tokens)
    if len(tokens) == 1 and tokens[0] in _COMPASS:
        return None  # a bare compass name ("North", "West") is not a place
    return joined if len(joined.replace(" ", "")) >= 3 else None


def norm_county(name: Any) -> str | None:
    if not isinstance(name, str):
        return None
    text = unicodedata.normalize("NFKC", name).casefold()
    text = "".join(c if c.isalnum() else " " for c in text)
    tokens = [t for t in text.split() if t not in {"county", "counties"}]
    joined = " ".join(tokens)
    return joined or None


def _list(value: Any) -> list[dict[str, Any]]:
    return [e for e in value if isinstance(e, dict)] if isinstance(value, list) else []


def _keys(fields: dict[str, Any]) -> dict[tuple[str, str], tuple[dict[str, Any], dict[str, Any]]]:
    # Extractors retain substations and counties independently. Pairing multiple values here
    # would invent associations (for example, two sites across two counties produce four pairs).
    # Until extraction preserves an explicit association, only one distinct value of each kind
    # can support a substation/county key.
    substations: dict[str, dict[str, Any]] = {}
    counties: dict[str, dict[str, Any]] = {}
    for sub in _list(fields.get("substations")):
        s = norm_substation(sub.get("value"))
        if s:
            substations.setdefault(s, sub)
    for county in _list(fields.get("counties")):
        c = norm_county(county.get("value"))
        if c:
            counties.setdefault(c, county)
    if len(substations) != 1 or len(counties) != 1:
        return {}
    ((substation, sub),) = substations.items()
    ((county_name, county),) = counties.items()
    return {(substation, county_name): (sub, county)}


def peers_from_states(states: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """RPG project summaries (union across documents) from stored ``rpg_pdf`` states."""
    merged: dict[str, dict[str, Any]] = {}
    for state in states:
        if state.get("kind") != "rpg_pdf":
            continue
        document = state.get("document") or {}
        extraction = document.get("extraction") or {}
        for project in extraction.get("projects") or []:
            pid = project.get("project_id")
            if not isinstance(pid, str):
                continue
            entry = merged.setdefault(
                pid,
                {
                    "project_id": pid,
                    "project_id_evidence": [],
                    "counties": [],
                    "substations": [],
                    "utility": None,
                },
            )
            fields = project.get("fields") or {}
            for ev in _list(project.get("project_id_evidence")):
                tagged = {
                    **ev,
                    "document_sha256": document.get("sha256"),
                    "url": state.get("url"),
                }
                if all(
                    (e.get("document_sha256"), e.get("page"), e.get("quote"))
                    != (tagged.get("document_sha256"), tagged.get("page"), tagged.get("quote"))
                    for e in entry["project_id_evidence"]
                ):
                    entry["project_id_evidence"].append(tagged)
            for name in ("counties", "substations"):
                for ev in _list(fields.get(name)):
                    tagged = {
                        **ev,
                        "document_sha256": document.get("sha256"),
                        "url": state.get("url"),
                    }
                    if all(
                        str(e.get("value")).casefold() != str(ev.get("value")).casefold()
                        for e in entry[name]
                    ):
                        entry[name].append(tagged)
            utility = fields.get("utility") or {}
            if entry["utility"] is None and utility.get("value"):
                entry["utility"] = utility["value"]
    return [merged[k] for k in sorted(merged)]


def _side(ev: dict[str, Any], default_url: Any = None) -> dict[str, Any]:
    """One side's evidence with the identity the value itself carries.

    A value read from a filing keeps that filing's own hash; a value read from the case style has
    no document hash and keeps the docket record's hash. A combined docket hash is never used.
    """
    return {
        "value": ev.get("value"),
        "basis": ev.get("basis"),
        "page": ev.get("page"),
        "quote": ev.get("quote"),
        "location": ev.get("location"),
        "role": ev.get("role"),
        "item": ev.get("item"),
        "document_sha256": ev.get("document_sha256"),
        "record_source_hash": ev.get("record_source_hash"),
        "url": ev.get("url") or default_url,
    }


def link_docket(docket: dict[str, Any], peers: list[dict[str, Any]]) -> dict[str, Any]:
    """Decide the link for one docket summary against the held RPG projects."""
    fields = docket.get("fields") or {}
    docket_keys = _keys(fields)
    cited = {
        str(e.get("value")): e
        for e in _list(fields.get("rpg_ids"))
        if isinstance(e.get("value"), str)
    }
    held = {p["project_id"]: p for p in peers if _list(p.get("project_id_evidence"))}
    candidates: dict[str, list[dict[str, Any]]] = {}
    for project in peers:
        shared = set(docket_keys) & set(_keys(project))
        if not shared:
            continue
        project_keys = _keys(project)
        for key in sorted(shared):
            d_sub, d_county = docket_keys[key]
            p_sub, p_county = project_keys[key]
            candidates.setdefault(project["project_id"], []).append(
                {
                    "type": "substation_county",
                    "substation_norm": key[0],
                    "county_norm": key[1],
                    "docket": {
                        "substation": _side(d_sub, docket.get("url")),
                        "county": _side(d_county, docket.get("url")),
                    },
                    "project": {
                        "substation": _side(p_sub),
                        "county": _side(p_county),
                    },
                }
            )
    for pid, evidence in cited.items():
        if pid in held:
            candidates.setdefault(pid, []).append(
                {
                    "type": "rpg_id",
                    "project_id": pid,
                    "docket": {"rpg_id": _side(evidence, docket.get("url"))},
                    "project": {"rpg_id": _side(held[pid]["project_id_evidence"][0])},
                }
            )
    if not candidates:
        has_key_fields = bool(
            cited or (_list(fields.get("substations")) and _list(fields.get("counties")))
        )
        reason = "no_deterministic_key" if has_key_fields else "docket_has_no_key_fields"
        return {"status": "unknown", "reason": reason, "candidates": []}
    if len(candidates) > 1:
        return {
            "status": "unknown",
            "reason": "ambiguous_candidates",
            "candidates": sorted(candidates),
        }
    ((project_id, keys),) = candidates.items()
    return {
        "status": "linked",
        "reason": None,
        "project_id": project_id,
        "link_basis": "deterministic_exact_key",
        "keys": keys,
    }


def link_record(docket: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    control = docket["control"]
    pid = decision["project_id"]
    key_names = sorted(
        {
            k["substation_norm"] + "|" + k["county_norm"]
            if k["type"] == "substation_county"
            else "rpg_id:" + k["project_id"]
            for k in decision["keys"]
        }
    )
    identities: list[str] = []
    for key in decision["keys"]:
        for side in ("docket", "project"):
            for item in key[side].values():
                identities.append(f"{item.get('document_sha256')}/{item.get('record_source_hash')}")
    digest_source = "|".join([control, pid, *key_names, *sorted(identities)])
    return {
        "document_number": f"ERCOT-PUCT-LINK-{control}-{pid}",
        "title": f"Link: PUCT docket {control} and ERCOT RPG project {pid}",
        "abstract": "\n".join(
            [
                f"PUCT docket {control} and ERCOT RPG project {pid} describe the same facility "
                "by an exact stated key.",
                "Key: " + "; ".join(key_names),
                "Basis: deterministic exact key; not a fuzzy or proximity match.",
                "This link does not identify a customer and states no load.",
            ]
        ),
        "publication_date": None,
        "event_date": None,
        "html_url": docket["url"],
        "extraction_location": "docket and RPG evidence key match",
        "source_hash": hashlib.sha256(digest_source.encode()).hexdigest(),
        "early_signal": {
            "version": VERSION,
            "kind": "link",
            "key": f"link:{control}:{pid}",
            "stateful": False,
            "docket": control,
            "project_id": pid,
            "link_basis": decision["link_basis"],
            "keys": decision["keys"],
        },
    }
