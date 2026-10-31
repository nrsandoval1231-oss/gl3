"""Guard the framing policy shared by static, proxied and error responses."""

import re
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[3] / "deploy" / "nginx.conf"


def test_all_web_response_locations_inherit_always_on_framing_headers():
    config = re.sub(r"#.*", "", CONFIG.read_text())
    depth = 0
    headers = {}
    for line in config.splitlines():
        stripped = line.strip()
        if stripped.startswith("add_header "):
            # A location-level add_header silently disables server inheritance.
            assert depth == 1, "Framing headers must be inherited from the server scope"
            match = re.fullmatch(r'add_header (\S+) "([^"]+)" always;', stripped)
            assert match, "Security headers must also cover non-success responses"
            headers[match[1]] = match[2]
        depth += line.count("{") - line.count("}")
    assert headers.get("Content-Security-Policy") == "frame-ancestors 'none'"
    assert headers.get("X-Frame-Options") == "DENY"
