# Container security completion evidence

## Candidate

- Repository: `gl3-readiness-containers-20261024`
- Branch: `audit/container-security-20261024`
- Base: `fae481db749b2e71dfb41ee63547c3fa1f6b1170`
- Scope: `deploy/Dockerfile.backend`, `deploy/Dockerfile.web`, and this evidence file only.
- Backend image: `gridlens-container-security-api:20261024`, image ID `sha256:0e8bc3baea7a5c0e4c9bf9911ade8415291fdc039c36eaa369d0c11e92cbf675`.
- Web image: `gridlens-container-security-web:20261024`, image ID `sha256:9c5d717bc43a220be2845dbe620d1dd3df9f9504cf378e302ee65d101f1713aa`.

## Changes

Both Dockerfiles upgrade supported base-image OS packages during build. The backend removes only the global base-image setuptools after locked application dependencies are installed; the application runs from its uv environment. This removes vulnerable vendored `jaraco.context 5.3.0` and `wheel 0.45.1` bootstrap copies without changing Python, the backend lock, or application dependencies.

The web image removes unused version-pinned nginx optional modules, unpins the nginx package, and upgrades the remaining nginx package to Alpine's available `1.28.3-r7`. The runtime config only uses core proxy/static directives. Alpine's upgraded package uses `/etc/nginx/http.d/` for virtual hosts and expects `/run/nginx` for its PID, so the Dockerfile installs the existing server config at the package's virtual-host path and creates the PID directory. The nginx configuration contents and runtime behavior are unchanged.

## Deterministic build and scan

Build commands (each exited 0):

```powershell
docker build --pull --no-cache -f deploy/Dockerfile.backend -t gridlens-container-security-api:20261024 .
docker build --pull --no-cache -f deploy/Dockerfile.web -t gridlens-container-security-web:20261024 .
```

Scans used the controller's checksum-verified Trivy executable at `.artifacts/readiness-20261024/trivy/trivy.exe`, version `0.76.1`. Its vulnerability DB reported `UpdatedAt=2026-10-24T13:07:23Z`, bundle digest `sha256:b591e9190cff4aa4e385b1a25bccfd9ecf178d3c77fd194e1410b7ce7e1df058`. Both scans exited 0:

```powershell
& $trivy image --format json --output "$env:TEMP\trivy-container-security-api-20261024.json" gridlens-container-security-api:20261024
& $trivy image --format json --output "$env:TEMP\trivy-container-security-web-20261024.json" gridlens-container-security-web:20261024
```

The controller's baseline reports were API 174 findings, including 46 HIGH (two fixable), and web 216 findings, including 2 CRITICAL and 62 HIGH (64 fixable). The rebuilt API reports 170 findings: 44 HIGH, 62 LOW, 63 MEDIUM, 1 UNKNOWN; zero CRITICAL and zero fixable HIGH/CRITICAL. The two fixable Python bootstrap findings are gone. The rebuilt web reports zero vulnerabilities at all severities. Build output confirmed Alpine updates including Brotli `1.2.1-r0`, OpenSSL libraries `3.5.9-r0`, and nginx `1.28.3-r7`.

The remaining 44 API HIGH findings are Debian system packages (`bsdutils`, `libacl1`, `libblkid1`, `liblastlog2-2`, `libmount1`, `libncursesw6`, `libsmartcols1`, `libsystemd0`, `libtinfo6`, `libudev1`, `libuuid1`, `login`, `mount`, `ncurses-base`, `ncurses-bin`, `perl-base`, `util-linux`). Trivy returned no `FixedVersion` for these findings in the scanned Debian image; `apt-get upgrade` updated the available `tzdata` package but did not change these versions. No distro or Python runtime migration was attempted. These findings remain open for a future base-image update with published Debian fixes.

## Runtime smoke

A disposable local `postgres:18.6` container with trust auth, no volume, and a private Docker network was used only for this smoke; migrations ran against that ephemeral database. No production database, provider, or production service was accessed. The test API and web containers were bound only to `127.0.0.1:55512` and `127.0.0.1:55513`. The temporary containers and network were removed after the run.

Passed checks: API `/health/live` 200; API `/health/ready` 200; web `/` 200 and served the application mount; anonymous `/api/auth/session` returned `authenticated=false`; dummy test-password login set a valid session cookie; session then returned `authenticated=true`; authenticated `/openapi.json` proxy returned 200. The smoke also established that the API starts and serves requests after removing global setuptools and that nginx starts with the upgraded Alpine package.

Commands, exits, and scope above are local evidence only. No push, merge, deployment, production mutation, or external communication occurred. Trivy JSON receipts were kept under `%TEMP%`, outside the repository. CI, platform Linux host, and deployment remain outside this packet's validation.
