import argparse
import os
import secrets
from pathlib import Path

import bcrypt

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description="Create ignored native-development credentials")
parser.add_argument("--force", action="store_true", help="rotate existing ignored credentials")
parser.add_argument(
    "--use-environment", action="store_true", help="read database URLs from the process environment"
)
args = parser.parse_args()
env_path = root / ".env"
auth_path = root / ".artifacts" / "local-auth.txt"
if not args.force and (env_path.exists() or auth_path.exists()):
    raise SystemExit("Local credentials already exist; pass --force only to rotate them")
connection_path = root / ".artifacts" / "local-postgres" / "connection.env"
if connection_path.exists() and not args.use_environment:
    connections = {}
    for line in connection_path.read_text(encoding="utf-8").splitlines():
        key, value = line.split("=", 1)
        connections[key] = value
else:
    connections = {
        "DATABASE_URL": os.environ.get("DATABASE_URL", ""),
        "TEST_DATABASE_URL": os.environ.get("TEST_DATABASE_URL", ""),
    }
if not all(connections.get(key) for key in ("DATABASE_URL", "TEST_DATABASE_URL")):
    raise SystemExit(
        "Provide DATABASE_URL and TEST_DATABASE_URL in the environment or local connection file"
    )
password = secrets.token_urlsafe(24)
session_secret = secrets.token_hex(32)
compose_password = secrets.token_hex(32)
encoded_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()
env_path.write_text(
    f"DATABASE_URL={connections['DATABASE_URL']}\nTEST_DATABASE_URL={connections['TEST_DATABASE_URL']}\n"
    f"POSTGRES_PASSWORD={compose_password}\nCOMPOSE_DATABASE_URL=postgresql+psycopg://gridlens:{compose_password}@db:5432/gridlens\n"
    f"APP_PASSWORD_HASH={encoded_hash}\nSESSION_SECRET={session_secret}\nCOOKIE_SECURE=false\nSESSION_HOURS=12\n"
    "WORKER_AUTO_REFRESH=true\n"
    "TRUSTED_ORIGINS=http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:8080,http://localhost:8080\n",
    encoding="utf-8",
)
auth_path.parent.mkdir(exist_ok=True)
auth_path.write_text(
    "Local development password (set a new password before sharing this machine):\n"
    + password
    + "\n",
    encoding="utf-8",
)
print("Created ignored local .env and .artifacts/local-auth.txt.")
