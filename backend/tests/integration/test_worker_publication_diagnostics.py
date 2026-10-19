"""Keep the initiating publication outcome without exposing canonical inputs."""

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker

from gridlens.intelligence import saved_browse
from gridlens.intelligence.worker_browse import install_worker_publication
from gridlens.persistence.models import PowerNeed
from gridlens.settings import settings
from tests.integration.test_saved_browse import saved_db, seed  # noqa: F401


def test_refresh_outcome_survives_savepoint_and_excludes_private_error(
    saved_db, monkeypatch,  # noqa: F811
):
    ids = seed(saved_db, histories=1)
    assert saved_browse.rebuild(saved_db)["status"] == "published"
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    factory = sessionmaker(saved_db.kw["bind"], expire_on_commit=False)
    install_worker_publication(factory)
    with factory() as writer:
        writer.get(PowerNeed, ids[0]).rationale = "Synthetic updated rationale"
        writer.commit()
        assert writer.info["worker_browse_outcome"]["status"] == "published"

    original = saved_browse._write_rows

    def fail(*args, **kwargs):
        raise RuntimeError("PRIVATE-SYNTHETIC-INPUT must not enter diagnostics")

    monkeypatch.setattr(saved_browse, "_write_rows", fail)
    with factory() as writer:
        writer.get(PowerNeed, ids[0]).rationale = "Canonical change survives"
        writer.commit()
        assert writer.info["worker_browse_outcome"] == {
            "status": "pending", "reason": "RuntimeError", "sqlstate": None,
        }
    with saved_db() as reader:
        assert reader.get(PowerNeed, ids[0]).rationale == "Canonical change survives"
        with pytest.raises(HTTPException) as failure:
            saved_browse.current_generation(reader)
        assert failure.value.status_code == 503
    monkeypatch.setattr(saved_browse, "_write_rows", original)
    saved_db.kw["bind"].dispose()
    restarted = sessionmaker(saved_db.kw["bind"], expire_on_commit=False)
    assert saved_browse.maintain_once(restarted)["status"] == "published"
    with restarted() as reader:
        saved_browse.current_generation(reader)
