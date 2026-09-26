import argparse
import secrets
from pathlib import Path

import bcrypt

root = Path(__file__).resolve().parents[1]
target = root / ".env.compose"
auth_path = root / ".artifacts" / "compose-auth.txt"
parser = argparse.ArgumentParser(description="Create ignored Compose credentials")
parser.add_argument("--force", action="store_true", help="rotate existing ignored credentials")
args = parser.parse_args()
if not args.force and (target.exists() or auth_path.exists()):
    raise SystemExit(
        "Compose credentials exist; edit .env.compose or pass --force to rotate"
    )
password = secrets.token_urlsafe(32)
session_secret = secrets.token_hex(32)
app_password = secrets.token_urlsafe(24)
password_hash = bcrypt.hashpw(app_password.encode(), bcrypt.gensalt(rounds=12)).decode()
url = f"postgresql+psycopg://gridlens:{password}@db:5432"


def dotenv(value: str) -> str:
    """Single-quote values so Compose keeps secret dollar signs literal."""
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


target.write_text(
    "\n".join(
        (
            f"POSTGRES_PASSWORD={dotenv(password)}",
            f"COMPOSE_DATABASE_URL={dotenv(url + '/gridlens')}",
            f"DATABASE_URL={dotenv(url + '/gridlens')}",
            f"TEST_DATABASE_URL={dotenv(url + '/gridlens_test')}",
            f"APP_PASSWORD_HASH={dotenv(password_hash)}",
            f"SESSION_SECRET={dotenv(session_secret)}",
            "COOKIE_SECURE=false",
            "SESSION_HOURS=12",
            "WORKER_AUTO_REFRESH=true",
            "TRUSTED_ORIGINS=http://127.0.0.1:8080,http://localhost:8080",
            "",
        )
    ),
    encoding="utf-8",
)
(root / ".artifacts").mkdir(exist_ok=True)
auth_path.write_text(
    "Compose development password (keep private):\n" + app_password + "\n", encoding="utf-8"
)
print(
    "Created ignored .env.compose and .artifacts/compose-auth.txt. "
    "Set TRUSTED_ORIGINS before starting."
)
