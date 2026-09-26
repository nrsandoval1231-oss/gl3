import json
import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "backend" / "src"))
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://unavailable:unavailable@127.0.0.1/unavailable")
os.environ.setdefault(
    "APP_PASSWORD_HASH", "$2b$12$C6UzMDM.H6dfI/f/IKcEe.3J8rsfS8XgF8N6yLQK9PfdO4.pToZui"
)
os.environ.setdefault("SESSION_SECRET", "local-contract-generation-only-32-bytes")
from gridlens.api.app import app  # noqa: E402

openapi_path = root / "web" / "src" / "api" / "openapi.json"
openapi_path.write_text(
    json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8"
)
