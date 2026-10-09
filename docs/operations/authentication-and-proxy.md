# Authentication and reverse proxies

GridLens stores only SHA-256 digests of 256-bit random session cookies. Each
request checks the session row, expiry, revocation time, and a fingerprint of
the current password hash and session secret. Rotating either credential
invalidates existing sessions. Logout revokes the server-side row before
clearing the browser cookie. Expired session rows are pruned at session issue;
revoked rows are retained until they expire plus seven days.

Login attempts use one PostgreSQL transaction lock and persisted fixed-window
buckets. Every attempt consumes the global bucket (500 per 60 seconds by
default) and a client bucket (5 per 60 seconds). The first 10,000 distinct
client buckets are retained; additional identities share an overflow bucket,
so key growth stays bounded and the global limit remains active. The per-client
limit means many users behind one shared egress may need a higher configured
client limit. The global limit is intentionally generous and protects the
single-password workspace from distributed guessing. Expired buckets are
deleted during attempts, and limits apply across API workers and restarts.

Uvicorn proxy-header rewriting is disabled in the supplied Compose and image
launchers. With an empty `TRUSTED_PROXY_CIDRS`, the socket peer is the login
identity and forwarding headers are ignored. When a proxy is required, list
only the exact proxy peer addresses/CIDRs in `TRUSTED_PROXY_CIDRS`. The app
accepts a bounded `X-Forwarded-For` chain only from such a peer and walks it
right-to-left across trusted hops to find the first untrusted client address.
Malformed, oversized, or overlong chains fall back to the socket peer. The
`Forwarded` header is not used.

The bundled Nginx proxy appends its observed peer using
`proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for`. When an outer TLS
proxy precedes Nginx, that outer edge must strip client-supplied forwarding
headers and safely set the observed client address; Nginx then appends the
outer proxy's observed peer. If Nginx itself is the Internet-facing edge, it
must overwrite incoming `X-Forwarded-For` with `$remote_addr` instead of
preserving client values. Configure every actual proxy peer in the app's
trusted CIDR setting. Do not trust a broad container or private network when
exact proxy addresses are available. Set `TRUSTED_ORIGINS` to the public HTTPS
origin and keep `COOKIE_SECURE=true` for HTTPS access. Origin checks remain
enforced for login and logout. Downgrading migration 0015 drops session and
limiter state, logging out every session and resetting active login windows.
