from pathlib import Path

from gridlens.api.app import app
from gridlens.persistence.models import Base


def test_editorial_endpoints_are_not_registered():
    assert not any(route.path.startswith("/api/editorial/") for route in app.routes)


def test_openapi_has_no_editorial_paths_or_request_models():
    schema = app.openapi()
    assert not any(path.startswith("/api/editorial/") for path in schema["paths"])
    assert "EditorialDecisionBody" not in schema["components"]["schemas"]


def test_historical_editorial_tables_and_migration_remain_intact():
    assert "editorial_decisions" in Base.metadata.tables
    assert "editorial_assessments" in Base.metadata.tables
    migration = Path(__file__).parents[2] / "migrations/versions/0019_editorial_decisions.py"
    assert migration.is_file()
    assert 'revision = "0019_editorial_decisions"' in migration.read_text(encoding="utf-8")
