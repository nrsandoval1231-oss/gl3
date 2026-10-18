from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.intelligence.intelligence_operations import operations_view
from gridlens.persistence.database import Base
from gridlens.persistence.models import LogicalCall, LogicalCallBudget
from gridlens.settings import settings


@pytest.fixture
def factory():
    target = make_url(settings.test_database_url)
    application = make_url(settings.database_url)
    assert target.database and target.database.endswith("_test")
    assert (target.host, target.port, target.database) != (
        application.host,
        application.port,
        application.database,
    )
    engine = create_engine(settings.test_database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine, expire_on_commit=False)
    yield session_factory
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_all_time_exposure_includes_terminal_null_cost_after_detail_cap(factory):
    now = datetime.now(UTC)
    with factory.begin() as session:
        session.add_all(
            [
                LogicalCall(
                    id=uuid4(),
                    fingerprint=f"{i:064x}",
                    task_type="TEST",
                    task_key=str(i),
                    evidence_digest="e" * 64,
                    context_digest="c" * 64,
                    prompt_contract="test",
                    provider="test-provider",
                    model="test-model",
                    policy_version="test",
                    lease_authority="job",
                    status="COMPLETED",
                    fence_token=1,
                    estimated_cost_usd=0.1,
                    max_cost_usd=0.2,
                    actual_cost_usd=None,
                    created_at=now,
                    budget_scopes=[],
                )
                for i in range(5001)
            ]
        )
        session.add(
            LogicalCallBudget(
                scope="global:all",
                period="daily",
                period_key=now.date().isoformat(),
                call_count=5001,
                cost_usd=1000,
                active_count=0,
            )
        )
    with factory() as session:
        result = operations_view(session)["providers"]
    assert result["detail_truncated"] is True
    assert result["detail_rows_30d"] == 5000
    assert result["reserved_cost_usd"] == 1000.2
    assert result["reserved_known_subtotal_usd"] == 1000.2
    assert result["total_cost_status"] == "UNKNOWN"
    assert result["utc_day"]["timezone"] == "UTC"
