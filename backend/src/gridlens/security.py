import hashlib
import hmac
import ipaddress
import secrets
from datetime import UTC, datetime, timedelta

import bcrypt
from fastapi import HTTPException, Request
from sqlalchemy import delete, func, select, text

from gridlens.persistence.models import AuthLoginBucket, AuthSession
from gridlens.settings import settings

OVERFLOW_BUCKET = "client:overflow"


def check_password(password: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), settings.app_password_hash.encode())
    except ValueError:
        return False


def credential_fingerprint() -> str:
    return hashlib.sha256(
        (settings.app_password_hash + "\0" + settings.session_secret).encode()
    ).hexdigest()


def _auth_sessions():
    # The API module owns the app session factory; tests replace it with their
    # isolated database factory, and every auth operation follows that choice.
    from gridlens.api import app as api_module

    return api_module.SessionLocal


def _bucket_id(scope: str, identity: str = "") -> str:
    if scope == "global":
        return "global"
    digest = hmac.new(
        settings.session_secret.encode(), identity.encode(), hashlib.sha256
    ).hexdigest()
    return f"client:{digest}"


def consume_login_attempt(client_ip: str) -> bool:
    """Atomically consume global and client capacity across every API process."""
    now = datetime.now(UTC)
    client_id = _bucket_id("client", client_ip)
    with _auth_sessions().begin() as session:
        # All limit decisions, pruning and capacity checks share one transaction lock.
        session.execute(text("SELECT pg_advisory_xact_lock(728104, 1)"))
        session.execute(
            delete(AuthLoginBucket).where(
                AuthLoginBucket.window_started_at
                <= now - timedelta(seconds=settings.login_window_seconds)
            )
        )
        count = (
            session.scalar(
                select(func.count())
                .select_from(AuthLoginBucket)
                .where(AuthLoginBucket.scope == "client")
            )
            or 0
        )
        if (
            session.get(AuthLoginBucket, client_id) is None
            and count >= settings.login_client_bucket_cap
        ):
            client_id = OVERFLOW_BUCKET
        ids = ("global", client_id)
        buckets = {
            bucket.id: bucket
            for bucket in session.scalars(
                select(AuthLoginBucket).where(AuthLoginBucket.id.in_(ids))
            ).all()
        }
        limits = {
            "global": settings.login_global_limit,
            client_id: settings.login_client_limit,
        }
        # A rejected client must not consume otherwise available global budget.
        for bucket_id in ids:
            scope = "global" if bucket_id == "global" else "client"
            bucket = buckets.get(bucket_id)
            if bucket is None:
                bucket = AuthLoginBucket(
                    id=bucket_id, scope=scope, window_started_at=now, attempts=0
                )
                session.add(bucket)
                buckets[bucket_id] = bucket
        if any(buckets[bucket_id].attempts >= limits[bucket_id] for bucket_id in ids):
            return False
        for bucket_id in ids:
            buckets[bucket_id].attempts += 1
        return True


def create_session(expires_timestamp: int | None = None) -> tuple[str, int]:
    now = datetime.now(UTC)
    expires_at = (
        datetime.fromtimestamp(expires_timestamp, UTC)
        if expires_timestamp is not None
        else now + timedelta(hours=settings.session_hours)
    )
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode()).hexdigest()
    with _auth_sessions().begin() as session:
        session.execute(delete(AuthSession).where(AuthSession.expires_at < now - timedelta(days=7)))
        session.add(
            AuthSession(
                token_digest=digest,
                created_at=now,
                expires_at=expires_at,
                credential_fingerprint=credential_fingerprint(),
            )
        )
    return token, int(expires_at.timestamp())


def token_for(expires: int) -> str:
    """Compatibility helper for tests; issue an opaque persisted session."""
    return create_session(expires)[0]


def valid_token(token: str | None) -> bool:
    if not token or len(token) > 128:
        return False
    digest = hashlib.sha256(token.encode()).hexdigest()
    now = datetime.now(UTC)
    with _auth_sessions().begin() as session:
        session.execute(delete(AuthSession).where(AuthSession.expires_at < now - timedelta(days=7)))
        row = session.get(AuthSession, digest)
        return bool(
            row
            and row.revoked_at is None
            and row.expires_at > now
            and hmac.compare_digest(row.credential_fingerprint, credential_fingerprint())
        )


def revoke_token(token: str | None) -> None:
    if not token or len(token) > 128:
        return
    digest = hashlib.sha256(token.encode()).hexdigest()
    now = datetime.now(UTC)
    with _auth_sessions().begin() as session:
        row = session.get(AuthSession, digest)
        if row is not None and row.revoked_at is None:
            row.revoked_at = now


def _trusted_proxies():
    networks = []
    for entry in settings.trusted_proxy_cidrs.split(","):
        entry = entry.strip()
        if entry:
            networks.append(ipaddress.ip_network(entry, strict=False))
    return networks


def _canonical_ip(value: str):
    address = ipaddress.ip_address(value)
    if isinstance(address, ipaddress.IPv6Address):
        if address.scope_id:
            raise ValueError("Scoped IPv6 addresses are not valid client identities")
        return address.ipv4_mapped or address
    return address


def client_ip(request: Request) -> str:
    peer_text = request.client.host if request.client else ""
    try:
        peer = _canonical_ip(peer_text)
    except ValueError:
        return "unknown"
    try:
        trusted = _trusted_proxies()
    except ValueError:
        return str(peer)
    if not any(peer in network for network in trusted):
        return str(peer)
    forwarded = request.headers.get("x-forwarded-for", "")
    if len(forwarded) > 2048:
        return str(peer)
    values = forwarded.split(",")
    if not values or len(values) > 32:
        return str(peer)
    try:
        chain = [_canonical_ip(value.strip()) for value in values]
    except ValueError:
        return str(peer)
    # Walk from the socket peer through trusted hops; first untrusted is client.
    for address in reversed(chain):
        if not any(address in network for network in trusted):
            return str(address)
    return str(chain[0])


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
