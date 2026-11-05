from __future__ import annotations

from datetime import date

from gridlens.ingestion.adapters import regulatory_events

FILING = {
    "state": "TX",
    "agency": "TCEQ",
    "instrument": "permits",
    "data_center_explicit": True,
    "pending": True,
}


def test_later_pause_directive_does_not_clear_screening_until_lift() -> None:
    events = regulatory_events.load_events()
    screening = next(event for event in events if event["effect"] == "pause_screening")
    directive = next(event for event in events if event["effect"] == "pause_directed")
    later_directive = {
        **directive,
        "id": "tx-gov-later-directive",
        "date": "2026-11-01",
    }

    current = regulatory_events.status_for(FILING, [*events, later_directive], date(2026, 11, 2))

    assert current is not None
    assert current["event_id"] == screening["id"]
    assert current["label"] == "pending — pause may apply (TCEQ screening)"

    lift = {
        **directive,
        "id": "tx-gov-later-lift",
        "date": "2026-11-03",
        "effect": "lift_pause",
    }
    assert (
        regulatory_events.status_for(FILING, [*events, later_directive, lift], date(2026, 11, 3))
        is None
    )
