import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

from gridlens.ingestion.adapters.buying_chain_public import (
    PublicAccessRestricted,
    _fetch_robots_direct,
    check_public_site_access,
    retrieve,
)
from gridlens.ingestion.adapters.public_site_policy import (
    HostApproval,
    evaluate_host_approval,
    evaluate_robots_policy,
    load_host_approval,
)

NOW = datetime(2026, 11, 8, 12, tzinfo=UTC)
ORIGINAL_HTTPX_CLIENT = httpx.Client


def _approval(host="example.test", *, modes=None, expires=None, revoked=None):
    return HostApproval(
        hostname=host,
        terms_review_ref="fixture:review-1",
        reviewed_at=NOW - timedelta(days=1),
        expires_at=expires or NOW + timedelta(days=30),
        modes=frozenset(modes or {"direct"}),
        revoked_at=revoked,
    )


def test_host_approval_is_exact_host_mode_scoped_expiring_and_revocable(monkeypatch):
    approval = _approval()
    assert evaluate_host_approval(
        "https://example.test/team", approval, mode="direct", now=NOW
    ).allowed
    assert not evaluate_host_approval(
        "https://sub.example.test/team", approval, mode="direct", now=NOW
    ).allowed
    assert not evaluate_host_approval(
        "https://example.test/team", approval, mode="firecrawl", now=NOW
    ).allowed
    assert not evaluate_host_approval(
        "https://example.test/team", _approval(expires=NOW), mode="direct", now=NOW
    ).allowed
    assert not evaluate_host_approval(
        "https://example.test/team", _approval(revoked=NOW), mode="direct", now=NOW
    ).allowed
    assert not evaluate_host_approval(
        "https://example.test/team",
        HostApproval("example.test", "", NOW, NOW + timedelta(days=1), frozenset({"direct"})),
        mode="direct",
        now=NOW,
    ).allowed
    assert not evaluate_host_approval(
        "https://example.test/team",
        HostApproval(
            "example.test", "fixture:review", NOW, NOW + timedelta(days=1), frozenset({"*"})
        ),
        mode="direct",
        now=NOW,
    ).allowed
    assert not evaluate_host_approval(
        "https://*.example.test/", approval, mode="direct", now=NOW
    ).allowed

    settings_data = [{
        "hostname": "example.test",
        "terms_review_ref": "fixture:review-1",
        "reviewed_at": (NOW - timedelta(days=1)).isoformat(),
        "expires_at": (NOW + timedelta(days=30)).isoformat(),
        "modes": ["direct"],
    }]
    import gridlens.ingestion.adapters.public_site_policy as policy

    config_value = json.dumps(settings_data)
    monkeypatch.setattr(
        policy, "settings", SimpleNamespace(public_research_site_permissions=config_value)
    )
    assert load_host_approval("https://example.test/a", mode="direct", now=NOW) == approval
    settings_data.append(dict(settings_data[0]))
    config_value = json.dumps(settings_data)
    monkeypatch.setattr(
        policy, "settings", SimpleNamespace(public_research_site_permissions=config_value)
    )
    assert load_host_approval("https://example.test/a", mode="direct", now=NOW) is None
    invalid_data = [{
        "hostname": "example.test",
        "terms_review_ref": "fixture:review-1",
        "reviewed_at": (NOW - timedelta(days=1)).isoformat(),
        "expires_at": (NOW + timedelta(days=30)).isoformat(),
        "modes": [{}],
    }]
    monkeypatch.setattr(
        policy,
        "settings",
        SimpleNamespace(public_research_site_permissions=json.dumps(invalid_data)),
    )
    assert load_host_approval("https://example.test/a", mode="direct", now=NOW) is None
    assert not evaluate_host_approval(
        "https://user:password@example.test/a", approval, mode="direct", now=NOW
    ).allowed


def test_robots_prefix_rules_are_conservative_and_fail_closed():
    policy = "User-agent: *\nDisallow: /private\nAllow: /private/public\n"
    assert evaluate_robots_policy(policy, "https://example.test/public").allowed
    assert not evaluate_robots_policy(policy, "https://example.test/private/x").allowed
    assert evaluate_robots_policy(policy, "https://example.test/private/public/a").allowed
    assert not evaluate_robots_policy(
        "User-agent: *\nDisallow: /private*\n", "https://example.test/private/x"
    ).allowed
    assert not evaluate_robots_policy(
        "User-agent: *\nCrawl-delay: 1\n", "https://example.test/"
    ).allowed
    for status in (301, 401, 403, 429, 500):
        assert not evaluate_robots_policy(
            None, "https://example.test/", robots_status=status
        ).allowed
    assert evaluate_robots_policy(None, "https://example.test/", robots_status=404).allowed
    assert evaluate_robots_policy(None, "https://example.test/", robots_status=410).allowed
    assert not evaluate_robots_policy(policy, "https://example.test/%70rivate/x").allowed
    assert not evaluate_robots_policy(policy, "https://example.test/private/../public").allowed
    assert not evaluate_robots_policy(policy, "https://example.test/private?next=/public").allowed


def test_robots_exact_user_agent_group_precedes_wildcard_and_allow_wins_equal_prefix():
    groups = (
        "User-agent: *\nDisallow: /\n"
        "User-agent: GridLens\nDisallow: /private\nAllow: /private\n"
    )
    assert evaluate_robots_policy(groups, "https://example.test/public").allowed
    assert evaluate_robots_policy(groups, "https://example.test/private/x").allowed
    grouped = "User-agent: *\nDisallow: /\n\nUser-agent: otherbot\nAllow: /\n"
    assert not evaluate_robots_policy(grouped, "https://example.test/public").allowed
    partial_match = "User-agent: *\nAllow: /\n\nUser-agent: Grid\nDisallow: /blocked\n"
    assert not evaluate_robots_policy(
        partial_match, "https://example.test/blocked/contact"
    ).allowed


@pytest.mark.parametrize("status", [302, 401, 403, 429, 503])
def test_robots_transport_denies_redirect_and_error_statuses(monkeypatch, status):
    requested = []
    monkeypatch.setattr(
        "gridlens.ingestion.adapters.buying_chain_public._public_ip", lambda _host: "93.184.216.34"
    )
    original_client = httpx.Client
    monkeypatch.setattr(
        "gridlens.ingestion.adapters.buying_chain_public.httpx.Client",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(
                lambda request: requested.append(request) or httpx.Response(status)
            ),
            **kwargs,
        ),
    )
    observed_status, body, pinned_ip = _fetch_robots_direct(
        "https://example.test/robots.txt"
    )
    assert observed_status == status
    assert body == b""
    assert pinned_ip == "93.184.216.34"
    assert len(requested) == 1
    assert requested[0].headers["host"] == "example.test"


def test_public_site_preflight_reserves_robots_and_reuses_pinned_address(monkeypatch):
    import gridlens.ingestion.adapters.buying_chain_public as public

    approval = _approval()
    requests = []
    monkeypatch.setattr(
        public,
        "run_isolated",
        lambda *_args, **_kwargs: (200, b"User-agent: *\nDisallow: /private\n", "93.184.216.34"),
    )
    decision = check_public_site_access(
        "https://example.test/public",
        approval=approval,
        before_request=requests.append,
    )
    assert decision.allowed and decision.resolved_ip == "93.184.216.34"
    assert requests == ["https://example.test/robots.txt"]
    blocked = check_public_site_access(
        "https://example.test/private/card",
        approval=approval,
        before_request=requests.append,
    )
    assert not blocked.allowed and blocked.reason == "robots_disallowed"
    with pytest.raises(PublicAccessRestricted, match="request_budget_callback_required"):
        retrieve("https://example.test/public", approval=approval)


def test_retrieve_preflights_approval_and_reuses_robots_pinned_ip(monkeypatch):
    import gridlens.ingestion.adapters.buying_chain_public as public

    calls = []

    def isolated(function_path, args, kwargs, *, deadline):
        calls.append((function_path, args, kwargs))
        if function_path.endswith(":_fetch_robots_direct"):
            return 200, b"User-agent: *\n", "93.184.216.34"
        return public.PublicDocument(args[0], "Fixture", "fixture")

    monkeypatch.setattr(public, "run_isolated", isolated)
    requests = []
    approval = _approval()
    result = retrieve(
        "https://example.test/contact",
        approval=approval,
        before_request=requests.append,
    )
    assert result.title == "Fixture"
    assert requests == ["https://example.test/robots.txt", "https://example.test/contact"]
    assert calls[1][2]["pinned_ip"] == "93.184.216.34"


def test_unapproved_host_denies_before_any_request_or_transport(monkeypatch):
    import gridlens.ingestion.adapters.buying_chain_public as public

    monkeypatch.setattr(
        public, "run_isolated", lambda *_args, **_kwargs: pytest.fail("unexpected network")
    )
    requests = []
    with pytest.raises(PublicAccessRestricted, match="host_not_approved"):
        retrieve("https://example.test/contact", before_request=requests.append)
    assert requests == []


def _mock_isolated_public_transport(monkeypatch, *, robots_body):
    import gridlens.ingestion.adapters.buying_chain_public as public

    requested = []
    resolved = []
    addresses = iter(("93.184.216.34", "1.1.1.1"))
    def resolve(_host):
        address = next(addresses)
        resolved.append(address)
        return address

    monkeypatch.setattr(public, "_public_ip", resolve)
    def client_factory(**kwargs):
        def response(request):
            requested.append(request)
            if request.url.path == "/robots.txt":
                return httpx.Response(
                    200, headers={"content-type": "text/plain"}, content=robots_body
                )
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                content=(
                    b"<html><title>Fixture page</title><body>"
                    b"This is a sufficiently long fixture public body for retrieval."
                    b"</body></html>"
                ),
            )

        return ORIGINAL_HTTPX_CLIENT(transport=httpx.MockTransport(response), **kwargs)

    monkeypatch.setattr(public.httpx, "Client", client_factory)

    def isolated(function_path, args, kwargs, *, deadline):
        function_name = function_path.rsplit(":", 1)[1]
        return getattr(public, function_name)(*args, **kwargs)

    monkeypatch.setattr(public, "run_isolated", isolated)
    return public, requested, resolved


def test_robots_denial_prevents_target_fetch_and_alternating_dns_rebind(monkeypatch):
    public, requested, resolved = _mock_isolated_public_transport(
        monkeypatch, robots_body=b"User-agent: *\nDisallow: /private\n"
    )
    callbacks = []
    with pytest.raises(PublicAccessRestricted, match="robots_disallowed"):
        public.retrieve(
            "https://example.test/private/contact",
            approval=_approval(),
            before_request=callbacks.append,
        )
    assert len(requested) == 1
    assert requested[0].url.path == "/robots.txt"
    assert resolved == ["93.184.216.34"]
    assert callbacks == [
        "https://example.test/robots.txt",
    ]


def test_target_get_reuses_robots_ip_and_callback_exhaustion_prevents_fetch(monkeypatch):
    public, requested, resolved = _mock_isolated_public_transport(
        monkeypatch, robots_body=b"User-agent: *\n"
    )
    callbacks = []

    def reserve(url):
        callbacks.append(url)
        if len(callbacks) == 2:
            raise PublicAccessRestricted("request_budget_exhausted")

    with pytest.raises(PublicAccessRestricted, match="request_budget_exhausted"):
        public.retrieve(
            "https://example.test/contact",
            approval=_approval(),
            before_request=reserve,
        )
    assert len(requested) == 1
    assert requested[0].url.path == "/robots.txt"
    assert resolved == ["93.184.216.34"]
    assert callbacks == ["https://example.test/robots.txt", "https://example.test/contact"]

    public, requested, resolved = _mock_isolated_public_transport(
        monkeypatch, robots_body=b"User-agent: *\n"
    )
    result = public.retrieve(
        "https://example.test/contact",
        approval=_approval(),
        before_request=lambda _url: None,
    )
    assert result.title == "Fixture page"
    assert [request.url.path for request in requested] == ["/robots.txt", "/contact"]
    assert [request.url.host for request in requested] == ["93.184.216.34"] * 2
    assert [request.headers["host"] for request in requested] == ["example.test"] * 2
    assert resolved == ["93.184.216.34"]


def test_private_explicit_pin_is_rejected_and_default_deadline_is_shared(monkeypatch):
    import gridlens.ingestion.adapters.buying_chain_public as public

    monkeypatch.setattr(public, "_public_ip", lambda _host: pytest.fail("unexpected DNS"))
    with pytest.raises(ValueError, match="Private destinations"):
        public._retrieve_direct("https://example.test/contact", pinned_ip="127.0.0.1")

    approvals = _approval()
    deadlines = []

    def isolated(_function_path, _args, kwargs, *, deadline):
        deadlines.append(deadline)
        if len(deadlines) == 1:
            return 200, b"User-agent: *\n", "93.184.216.34"
        return public.PublicDocument(
            "https://example.test/contact", "Fixture", "body text long enough"
        )

    monkeypatch.setattr(public, "run_isolated", isolated)
    public.retrieve(
        "https://example.test/contact",
        approval=approvals,
        before_request=lambda _url: None,
    )
    assert len(deadlines) == 2
    assert deadlines[0] == deadlines[1]
