import hashlib
import importlib.util
import json
from decimal import Decimal
from pathlib import Path

import pytest

from gridlens.settings import settings

ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts" / "compare_acquisition.py"
SPEC = importlib.util.spec_from_file_location("compare_acquisition_cli", SCRIPT_PATH)
cli = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(cli)


def test_dispatch_caps_fail_closed_before_scrape(monkeypatch):
    monkeypatch.setattr(
        settings, "database_url", "postgresql://u:p@127.0.0.1:55443/pipeline_m2_app"
    )
    monkeypatch.setattr(settings, "firecrawl_api_key", None)
    monkeypatch.setattr(settings, "firecrawl_scrape_cost_usd", Decimal("0.01"))
    args = type("Args", (), {"max_calls": 1, "max_credits": 1, "max_cost_usd": Decimal("0.01")})()
    with pytest.raises(ValueError, match="credentials"):
        cli._validate_dispatch_caps(args, 1)
    monkeypatch.setattr(settings, "firecrawl_api_key", object())
    for invalid in (Decimal("NaN"), Decimal("Infinity")):
        args.max_cost_usd = invalid
        with pytest.raises(ValueError, match="finite"):
            cli._validate_dispatch_caps(args, 1)
    args.max_cost_usd = Decimal("0.01")
    args.max_calls = 2
    args.max_credits = 2
    with pytest.raises(ValueError, match="eligible"):
        cli._validate_dispatch_caps(args, 1)


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://u:p@db.internal:55443/pipeline_m2_app",
        "postgresql://u:p@127.0.0.1:5432/pipeline_m2_app",
        "postgresql://u:p@127.0.0.1:55443/other",
        "postgresql://u:p@127.0.0.1:55443/pipeline_m2_app?host=elsewhere",
    ],
)
def test_isolated_database_guard_rejects_endpoint_overrides(monkeypatch, dsn):
    monkeypatch.setattr(settings, "database_url", dsn)
    with pytest.raises(ValueError, match="exact isolated"):
        cli._require_isolated_database()


@pytest.mark.parametrize(
    "field,value",
    [
        ("raw_path", "../raw"),
        ("extracted_text_path", "../text"),
        ("extracted_text_path", "C:/outside.txt"),
    ],
)
def test_capture_receipt_rejects_path_escape(tmp_path, field, value):
    capture_dir = tmp_path / "captures"
    capture_dir.mkdir()
    receipt = {
        "case_id": "x",
        "source_id": "s",
        "exact_url": "https://example.gov/x",
        "observed_utc": "2026-10-23T00:00:00Z",
        "capture_id": "c",
        "scope": "complete_document",
        "content_type": "text/html",
        "text": "some text",
        "text_sha256": hashlib.sha256(b"some text").hexdigest(),
    }
    receipt[field] = value
    (capture_dir / "x.json").write_text(json.dumps(receipt), encoding="utf-8")
    cases = [
        {
            "case_id": "x",
            "source_id": "s",
            "external_id": None,
            "url": receipt["exact_url"],
            "media_type": "text/html",
            "max_bytes": 1000,
        }
    ]
    with pytest.raises(ValueError, match="path"):
        cli._load_captures(capture_dir, cases)


def test_missing_native_capture_never_enters_scrape(tmp_path, monkeypatch):
    manifest = {"version": "v", "max_cases": 5, "cases": []}
    for i in range(5):
        manifest["cases"].append(
            {
                "case_id": f"case-{i}",
                "source_id": "s",
                "external_id": None,
                "identity_kind": "capture_label",
                "url": f"https://example.gov/{i}",
                "media_type": "text/html",
                "max_bytes": 1000,
                "recovery_terms": [],
            }
        )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    capture_dir = tmp_path / "empty"
    capture_dir.mkdir()
    monkeypatch.setattr(
        settings, "database_url", "postgresql://u:p@127.0.0.1:55443/pipeline_m2_app"
    )
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "firecrawl_api_key", SecretStr("fixture"))
    monkeypatch.setattr(settings, "firecrawl_scrape_cost_usd", Decimal("0.01"))
    monkeypatch.setattr(
        cli,
        "scrape_html",
        lambda *_a, **_k: pytest.fail("must not dispatch without native capture"),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            str(SCRIPT_PATH),
            "--manifest",
            str(manifest_path),
            "--captures",
            str(capture_dir),
            "--dispatch",
            "--max-calls",
            "1",
            "--max-credits",
            "1",
            "--max-cost-usd",
            "0.01",
            "--output",
            str(tmp_path / "report.json"),
        ],
    )
    assert cli.main() == 2
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert all(row["native"]["error_code"] == "NATIVE_CAPTURE_MISSING" for row in report["cases"])


def test_all_native_receipts_validate_before_first_dispatch(tmp_path, monkeypatch):
    manifest = {"version": "v", "max_cases": 5, "cases": []}
    receipts = tmp_path / "captures"
    receipts.mkdir()
    for i in range(5):
        url = f"https://example.gov/{i}"
        manifest["cases"].append(
            {
                "case_id": f"case-{i}",
                "source_id": "s",
                "external_id": None,
                "identity_kind": "capture_label",
                "url": url,
                "media_type": "text/html",
                "max_bytes": 1000,
                "recovery_terms": [],
            }
        )
        text = f"text {i}"
        (receipts / f"case-{i}.json").write_text(
            json.dumps(
                {
                    "case_id": f"case-{i}",
                    "source_id": "s",
                    "external_id": None,
                    "exact_url": url,
                    "observed_utc": "2026-10-23T00:00:00Z",
                    "capture_id": f"capture-{i}",
                    "scope": "complete_document",
                    "content_type": "application/pdf" if i == 4 else "text/html",
                    "text": text,
                    "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                }
            ),
            encoding="utf-8",
        )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(
        settings, "database_url", "postgresql://u:p@127.0.0.1:55443/pipeline_m2_app"
    )
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "firecrawl_api_key", SecretStr("fixture"))
    monkeypatch.setattr(settings, "firecrawl_scrape_cost_usd", Decimal("0.01"))
    monkeypatch.setattr(
        cli,
        "scrape_html",
        lambda *_a, **_k: pytest.fail("no case may dispatch before all receipts validate"),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            str(SCRIPT_PATH),
            "--manifest",
            str(manifest_path),
            "--captures",
            str(receipts),
            "--dispatch",
            "--max-calls",
            "1",
            "--max-credits",
            "1",
            "--max-cost-usd",
            "0.01",
        ],
    )
    with pytest.raises(ValueError, match="media type"):
        cli.main()
