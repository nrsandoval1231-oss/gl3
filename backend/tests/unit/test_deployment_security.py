"""Guard the web security headers and the proxy-trust wiring of the deployment."""

import ipaddress
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "deploy" / "nginx.conf"
COMPOSE = ROOT / "deploy" / "digitalocean" / "compose.prod.yaml"
ENV_EXAMPLE = ROOT / "deploy" / "digitalocean" / "env.prod.example"


def test_all_web_response_locations_inherit_always_on_security_headers():
    config = re.sub(r"#.*", "", CONFIG.read_text())
    depth = 0
    headers = {}
    for line in config.splitlines():
        stripped = line.strip()
        if stripped.startswith("add_header "):
            # A location-level add_header silently disables server inheritance.
            assert depth == 1, "Security headers must be inherited from the server scope"
            match = re.fullmatch(r'add_header (\S+) ("[^"]+"|\$\w+) always;', stripped)
            assert match, "Security headers must also cover non-success responses"
            headers[match[1]] = match[2].strip('"')
        depth += line.count("{") - line.count("}")
    csp = headers["Content-Security-Policy"]
    for directive in (
        "default-src 'self'",
        "img-src 'self' data:",
        "frame-ancestors 'none'",
        "base-uri 'none'",
        "form-action 'self'",
    ):
        assert directive in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    # Cache-Control is a map variable that is non-empty only under /api/.
    assert headers["Cache-Control"] == "$gridlens_api_cache_control"
    assert re.search(r'~\^/api/\s+"private, no-store";', config)


def test_nginx_appends_peer_to_forwarded_for_chain_for_api():
    config = CONFIG.read_text()
    assert "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;" in config


def test_api_trusts_forwarded_for_only_from_the_fixed_compose_subnet():
    compose = yaml.safe_load(COMPOSE.read_text())
    subnets = compose["networks"]["default"]["ipam"]["config"]
    assert len(subnets) == 1
    subnet = ipaddress.ip_network(subnets[0]["subnet"])
    wiring = compose["services"]["api"]["environment"]["TRUSTED_PROXY_CIDRS"]
    default = re.fullmatch(r"\$\{TRUSTED_PROXY_CIDRS:-([^}]+)\}", wiring)
    assert default and ipaddress.ip_network(default[1]) == subnet
    example = re.search(r"^TRUSTED_PROXY_CIDRS=(\S+)$", ENV_EXAMPLE.read_text(), re.M)
    assert example and ipaddress.ip_network(example[1]) == subnet


def test_backend_services_are_hardened_and_migrate_has_no_provider_keys():
    services = yaml.safe_load(COMPOSE.read_text())["services"]
    for name in ("migrate", "api", "worker", "browse"):
        assert "no-new-privileges:true" in services[name]["security_opt"], name
        assert services[name]["cap_drop"] == ["ALL"], name
    for key in ("TYPESAFE_API_KEY", "OPENAI_API_KEY", "FIRECRAWL_API_KEY"):
        assert services["migrate"]["environment"][key] == ""


def test_backend_image_runs_unprivileged():
    lines = (ROOT / "deploy" / "Dockerfile.backend").read_text().splitlines()
    users = [line for line in lines if line.startswith("USER ")]
    assert users == ["USER app"]
