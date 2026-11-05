"""Deterministic PUCT docket to ERCOT RPG project links: exact key, evidence, ambiguity, unknown."""

from __future__ import annotations

import pytest

import gridlens.ingestion.adapters.early_signal_link as link


def ev(value, quote="q", page=1, sha="a" * 64, url="https://example.invalid/x"):
    return {
        "value": value,
        "basis": "documented",
        "page": page,
        "quote": quote,
        "document_sha256": sha,
        "url": url,
    }


def project(pid, subs, counties):
    return {
        "project_id": pid,
        "project_id_evidence": [ev(pid, f"RPG project {pid}")],
        "utility": "U",
        "substations": [ev(s) for s in subs],
        "counties": [ev(c) for c in counties],
    }


def docket(control="59549", subs=(), counties=(), rpg=()):
    return {
        "control": control,
        "url": f"https://interchange.puc.texas.gov/Search/Filings?ControlNumber={control}",
        "document_sha256": "b" * 64,
        "fields": {
            "substations": [ev(s, f"new substation {s}", sha="b" * 64) for s in subs],
            "counties": [ev(c, sha="b" * 64) for c in counties],
            "rpg_ids": [ev(r, sha="b" * 64) for r in rpg],
        },
    }


# --------------------------------------------------------------------------- normalisation


@pytest.mark.parametrize(
    "a,b",
    [
        ("Legend Falls", "LEGEND FALLS Substation"),
        ("New Castroville 345/138-kV station", "castroville"),
        ("Rogers Road", "Rogers Rd".replace("Rd", "Road")),
        ("Mangana-Hein", "mangana hein"),
        ("San Geronimo  Substation", "San Geronimo"),
    ],
)
def test_substation_names_equal_after_fixed_normalisation(a, b):
    assert link.norm_substation(a) == link.norm_substation(b) is not None


@pytest.mark.parametrize(
    "a,b", [("Rogers Road", "Rogers Rd"), ("Legend Falls", "Legend Fall"), ("Howard", "Howard 2")]
)
def test_near_names_are_not_equal_never_fuzzy(a, b):
    assert link.norm_substation(a) != link.norm_substation(b)


def test_empty_or_too_short_names_have_no_key():
    assert link.norm_substation("Substation") is None
    assert link.norm_substation("AB") is None
    assert link.norm_substation(None) is None
    assert link.norm_county("Medina County") == "medina" == link.norm_county("MEDINA")


# --------------------------------------------------------------------------- decisions


def test_link_on_exact_substation_and_county_with_evidence_on_both_sides():
    peers = [
        project("25RPG099", ["Legend Falls"], ["Medina"]),
        project("25RPG020", ["Castroville"], ["Bexar"]),
    ]
    decision = link.link_docket(docket(subs=["LEGEND FALLS"], counties=["Medina"]), peers)
    assert decision["status"] == "linked" and decision["project_id"] == "25RPG099"
    (key,) = decision["keys"]
    assert (key["substation_norm"], key["county_norm"]) == ("legend falls", "medina")
    assert key["docket"]["substation"]["quote"] == "new substation LEGEND FALLS"
    assert key["docket"]["substation"]["document_sha256"] == "b" * 64
    assert key["project"]["substation"]["document_sha256"] == "a" * 64
    record = link.link_record(docket(subs=["LEGEND FALLS"], counties=["Medina"]), decision)
    assert record["document_number"] == "ERCOT-PUCT-LINK-59549-25RPG099"
    assert record["early_signal"]["kind"] == "link" and record["early_signal"]["stateful"] is False
    assert record["early_signal"]["link_basis"] == "deterministic_exact_key"
    assert "does not identify a customer" in record["abstract"]


def test_multiple_unassociated_substations_and_counties_do_not_form_cross_pairs():
    # The source documents list these names independently. The matching A/Y values are not
    # evidence that substation A is in county Y, so they cannot create a link.
    peers = [project("25RPG099", ["Alpha Station"], ["Medina"])]
    decision = link.link_docket(
        docket(
            subs=["Alpha Station", "Beta Station"],
            counties=["Travis", "Medina"],
        ),
        peers,
    )
    assert decision == {
        "status": "unknown",
        "reason": "no_deterministic_key",
        "candidates": [],
    }


def test_same_substation_name_in_a_different_county_is_no_link():
    peers = [project("25RPG099", ["Legend Falls"], ["Bexar"])]
    decision = link.link_docket(docket(subs=["Legend Falls"], counties=["Medina"]), peers)
    assert decision == {"status": "unknown", "reason": "no_deterministic_key", "candidates": []}


def test_multiple_project_substations_and_counties_are_not_cross_paired():
    peer = project(
        "25RPG099",
        ["Alpha Station", "Beta Station"],
        ["Travis", "Medina"],
    )
    decision = link.link_docket(
        docket(subs=["Alpha Station"], counties=["Medina"]),
        [peer],
    )
    assert decision == {
        "status": "unknown",
        "reason": "no_deterministic_key",
        "candidates": [],
    }


def test_county_alone_is_never_a_key():
    peers = [project("25RPG099", ["Castroville"], ["Medina"])]
    decision = link.link_docket(docket(subs=[], counties=["Medina"]), peers)
    assert decision["status"] == "unknown" and decision["reason"] == "docket_has_no_key_fields"


def test_two_projects_sharing_the_key_is_ambiguous_and_unlinked():
    peers = [
        project("25RPG020", ["Castroville"], ["Medina"]),
        project("25RPG046", ["Castroville"], ["Medina"]),
    ]
    decision = link.link_docket(docket(subs=["Castroville"], counties=["Medina"]), peers)
    assert decision == {
        "status": "unknown",
        "reason": "ambiguous_candidates",
        "candidates": ["25RPG020", "25RPG046"],
    }


def test_a_cited_project_id_is_an_exact_key():
    peers = [project("25RPG020", [], []), project("25RPG046", [], [])]
    decision = link.link_docket(docket(rpg=["25RPG046"]), peers)
    assert decision["status"] == "linked" and decision["project_id"] == "25RPG046"
    assert decision["keys"][0]["type"] == "rpg_id"
    assert decision["keys"][0]["docket"]["rpg_id"]["document_sha256"] == "b" * 64
    assert decision["keys"][0]["project"]["rpg_id"]["document_sha256"] == "a" * 64


def test_a_cited_id_we_do_not_hold_is_not_a_link():
    decision = link.link_docket(docket(rpg=["25RPG777"]), [project("25RPG020", [], [])])
    assert decision["status"] == "unknown"


def test_conflicting_keys_pointing_to_different_projects_are_unknown():
    peers = [project("25RPG020", ["Legend Falls"], ["Medina"]), project("25RPG046", [], [])]
    decision = link.link_docket(
        docket(subs=["Legend Falls"], counties=["Medina"], rpg=["25RPG046"]), peers
    )
    assert decision["status"] == "unknown" and decision["reason"] == "ambiguous_candidates"


def test_both_keys_agreeing_on_one_project_link_once():
    peers = [project("25RPG020", ["Legend Falls"], ["Medina"])]
    decision = link.link_docket(
        docket(subs=["Legend Falls"], counties=["Medina"], rpg=["25RPG020"]), peers
    )
    assert decision["status"] == "linked" and {k["type"] for k in decision["keys"]} == {
        "substation_county",
        "rpg_id",
    }


def test_no_peers_and_no_fields_are_unknown():
    assert link.link_docket(docket(), [])["status"] == "unknown"
    assert (
        link.link_docket({"control": "1", "fields": {}, "url": "u"}, [])["reason"]
        == "docket_has_no_key_fields"
    )


def test_link_digest_changes_when_either_document_changes():
    peers = [project("25RPG099", ["Legend Falls"], ["Medina"])]
    d = docket(subs=["Legend Falls"], counties=["Medina"])
    one = link.link_record(d, link.link_docket(d, peers))
    peers2 = [
        {
            **peers[0],
            "substations": [ev("Legend Falls", sha="c" * 64)],
            "counties": peers[0]["counties"],
        }
    ]
    two = link.link_record(d, link.link_docket(d, peers2))
    again = link.link_record(d, link.link_docket(d, peers))
    assert one["source_hash"] == again["source_hash"] != two["source_hash"]


def test_project_id_only_link_has_two_sided_citations_and_hashes_ercot_evidence():
    d = docket(rpg=["25RPG046"])
    peer = project("25RPG046", [], [])
    one = link.link_record(d, link.link_docket(d, [peer]))
    revised = {
        **peer,
        "project_id_evidence": [ev("25RPG046", "RPG project 25RPG046", sha="c" * 64)],
    }
    two = link.link_record(d, link.link_docket(d, [revised]))
    (key,) = one["early_signal"]["keys"]
    assert key["docket"]["rpg_id"]["document_sha256"] == "b" * 64
    assert key["project"]["rpg_id"]["document_sha256"] == "a" * 64
    assert one["source_hash"] != two["source_hash"]


# --------------------------------------------------------------------------- peers from states


def test_peers_are_built_from_stored_states_with_document_hashes():
    def state(url, sha, projects):
        return {
            "kind": "rpg_pdf",
            "url": url,
            "document": {"sha256": sha, "extraction": {"projects": projects}},
        }

    fields = lambda subs, counties: {  # noqa: E731
        "substations": [ev(s) for s in subs],
        "counties": [ev(c) for c in counties],
        "utility": {"value": "AEN", "basis": "documented"},
    }
    states = [
        state(
            "https://www.ercot.com/files/docs/2026/01/01/a.pdf",
            "1" * 64,
            [
                {
                    "project_id": "26RPG022",
                    "project_id_evidence": [ev("26RPG022", "Project 26RPG022")],
                    "fields": fields(["Whitetail"], ["Travis"]),
                }
            ],
        ),
        state(
            "https://www.ercot.com/files/docs/2026/02/01/b.pdf",
            "2" * 64,
            [
                {
                    "project_id": "26RPG022",
                    "project_id_evidence": [ev("26RPG022", "Updated 26RPG022")],
                    "fields": fields(["Whitetail", "Dunlap"], ["Travis"]),
                }
            ],
        ),
        {"kind": "tpit", "url": "u", "document": {}},
    ]
    (peer,) = link.peers_from_states(states)
    assert peer["project_id"] == "26RPG022" and peer["utility"] == "AEN"
    assert [s["value"] for s in peer["substations"]] == ["Whitetail", "Dunlap"]
    assert peer["substations"][0]["document_sha256"] == "1" * 64
    assert peer["substations"][1]["document_sha256"] == "2" * 64
    assert peer["counties"][0]["url"].endswith("a.pdf")
    assert peer["project_id_evidence"][0]["document_sha256"] == "1" * 64
    assert peer["project_id_evidence"][1]["document_sha256"] == "2" * 64
