from gridlens.settings import settings


def test_omitted_registry_schedule_uses_seven_am_chicago():
    import gridlens.jobs.worker as worker

    config = worker._source_configuration({"cadence_hours": 24})
    assert config["timezone"] == "America/Chicago"
    assert config["schedule_anchor_time"] == "07:00:00"
    assert config["schedule_mode"] == "local_daily"


def test_schedule_settings_override_the_registry_default(monkeypatch):
    import gridlens.jobs.worker as worker

    monkeypatch.setattr(settings, "schedule_timezone", "America/Denver")
    monkeypatch.setattr(settings, "schedule_anchor_time", "06:30:00")
    config = worker._source_configuration({"cadence_hours": 24})
    assert config["timezone"] == "America/Denver"
    assert config["schedule_anchor_time"] == "06:30:00"
    explicit = worker._source_configuration(
        {"cadence_hours": 24, "timezone": "America/Chicago", "schedule_anchor_time": "03:00:00"}
    )
    assert explicit["timezone"] == "America/Chicago"
    assert explicit["schedule_anchor_time"] == "03:00:00"
