import pytest

from gridlens.settings import settings


@pytest.fixture(autouse=True)
def disable_real_model_keys(monkeypatch):
    """Keep test runs isolated from locally configured paid model credentials."""
    monkeypatch.setattr(settings, "openai_api_key", None)
    monkeypatch.setattr(settings, "typesafe_api_key", None)
