import hashlib
import hmac
import time
from collections import defaultdict, deque

import bcrypt
from fastapi import HTTPException, Request

from gridlens.settings import settings

_failures: dict[str, deque[float]] = defaultdict(deque)


def check_password(password: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), settings.app_password_hash.encode())
    except ValueError:
        return False


def login_allowed(key: str) -> bool:
    now = time.time()
    attempts = _failures[key]
    while attempts and attempts[0] < now - 60:
        attempts.popleft()
    return len(attempts) < 5


def record_login_failure(key: str) -> None:
    _failures[key].append(time.time())


def token_for(expires: int) -> str:
    signature = hmac.new(
        settings.session_secret.encode(), str(expires).encode(), hashlib.sha256
    ).hexdigest()
    return f"{expires}.{signature}"


def valid_token(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    expires_raw, signature = token.split(".", 1)
    if not expires_raw.isdigit() or int(expires_raw) <= int(time.time()):
        return False
    expected = token_for(int(expires_raw)).split(".", 1)[1]
    return hmac.compare_digest(expected, signature)


def require_session(request: Request) -> None:
    if not valid_token(request.cookies.get("gridlens_session")):
        raise HTTPException(status_code=401, detail="Authentication required")


def require_same_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    configured = {
        item.strip().rstrip("/") for item in settings.trusted_origins.split(",") if item.strip()
    }
    same_origin = f"{request.url.scheme}://{request.url.netloc}"
    if origin and origin.rstrip("/") not in configured | {same_origin}:
        raise HTTPException(status_code=403, detail="Origin check failed")
