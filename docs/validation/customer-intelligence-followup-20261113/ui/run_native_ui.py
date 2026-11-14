from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import bcrypt
from sqlalchemy.engine import make_url
ROOT = Path(__file__).resolve().parents[4]
SEED = Path(__file__).with_name("seed_native.py")
CAPTURE = Path(__file__).with_name("capture_native_ui.cjs")
sys.path.insert(0, str(Path(__file__).parent))
from db_guard import validate_database_urls
PR202 = "26344b8b"
API_PORT = 18443
WEB_PORT = 15443
API_URL = f"http://127.0.0.1:{API_PORT}"
WEB_URL = f"http://127.0.0.1:{WEB_PORT}"


def assert_safe_base_urls():
    try:
        test_url = validate_database_urls(os.environ["TEST_DATABASE_URL"], os.environ["DATABASE_URL"])
    except (KeyError, ValueError) as error:
        raise SystemExit("Database URLs must be distinct, query-free, loopback PostgreSQL URLs with a disposable test database") from None
    if os.environ.get("OPENAI_API_KEY") or os.environ.get("FIRECRAWL_API_KEY") or os.environ.get("TYPESAFE_API_KEY"):
        raise SystemExit("Provider keys must be blank for this native UI follow-up")
    return test_url


def ensure_ports_free() -> None:
    for port in (API_PORT, WEB_PORT):
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError as error:
                raise SystemExit(f"Required local UI follow-up port {port} is occupied") from error


def wait_for(url: str, process: subprocess.Popen, *, api: bool) -> None:
    for _ in range(60):
        if process.poll() is not None:
            raise RuntimeError(f"Service exited before readiness: {url}")
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except urllib.error.HTTPError as error:
            if api and error.code in {401, 403}:
                return
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"Service did not become ready: {url}")


def terminate_owned(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def materialize_git_tree(revision: str, repository_path: str, destination: Path) -> None:
    listing = subprocess.check_output(
        ["git", "ls-tree", "-r", "-z", revision, "--", repository_path], cwd=ROOT
    )
    for entry in listing.split(b"\0"):
        if not entry:
            continue
        metadata, path_bytes = entry.split(b"\t", 1)
        mode, object_type, object_id = metadata.decode("ascii").split(" ")
        if object_type != "blob" or mode not in {"100644", "100755"}:
            continue
        path = Path(path_bytes.decode("utf-8")).relative_to(repository_path)
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(subprocess.check_output(["git", "cat-file", "blob", object_id], cwd=ROOT))


def launch_pair(mode: str, database: str, manifest: Path, output: Path, *, overlay: Path | None, password: str) -> dict:
    environment = os.environ.copy()
    environment.update(
        {
            "DATABASE_URL": make_url(os.environ["TEST_DATABASE_URL"])
            .set(database=database)
            .render_as_string(hide_password=False),
            "SAVED_BROWSE_ENABLED": "true",
            "COOKIE_SECURE": "false",
            "TRUSTED_ORIGINS": WEB_URL,
            "WORKER_AUTO_REFRESH": "false",
            "OPENAI_API_KEY": "",
            "FIRECRAWL_API_KEY": "",
            "TYPESAFE_API_KEY": "",
            "INTELLIGENCE_ENABLED": "false",
            "INTELLIGENCE_MODE": "disabled",
            "JEV_ENABLED": "false",
            "APP_PASSWORD_HASH": bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode(),
            "SESSION_SECRET": "disposable-audit-session-secret-20261113",
            "GRIDLENS_API_PORT": str(API_PORT),
            "GRID_UI_RUN_MANIFEST": str(manifest.resolve()),
            "GRID_UI_RUN_OUTPUT": str(output.resolve()),
            "GRID_TEST_PASSWORD": password,
            "PYTHONUTF8": "1",
            "PGCONNECT_TIMEOUT": "5",
        }
    )
    if overlay:
        environment["PYTHONPATH"] = str(overlay) + os.pathsep + str(ROOT / "backend" / "src")
    else:
        environment["PYTHONPATH"] = str(ROOT / "backend" / "src")
    logs = output / f"{mode}-logs"
    logs.mkdir(parents=True, exist_ok=False)
    api_log = (logs / "api.log").open("w", encoding="utf-8")
    web_log = (logs / "web.log").open("w", encoding="utf-8")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    api = web = None
    captured = False
    try:
        api = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "gridlens.api.app:app", "--host", "127.0.0.1", "--port", str(API_PORT), "--no-proxy-headers"],
            cwd=ROOT / "backend",
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=api_log,
            stderr=subprocess.STDOUT,
            creationflags=flags,
            start_new_session=os.name != "nt",
        )
        wait_for(f"{API_URL}/api/health", api, api=True)
        npm = shutil.which("npm.cmd" if os.name == "nt" else "npm") or shutil.which("npm")
        if not npm:
            raise RuntimeError("npm is required to launch the local UI")
        web_environment = environment.copy()
        web_environment["GRIDLENS_UI_FOLLOWUP_PORT"] = str(WEB_PORT)
        web = subprocess.Popen(
            [npm, "run", "dev", "--", "--host", "127.0.0.1", "--port", str(WEB_PORT), "--strictPort"],
            cwd=ROOT / "web",
            env=web_environment,
            stdin=subprocess.DEVNULL,
            stdout=web_log,
            stderr=subprocess.STDOUT,
            creationflags=flags,
            start_new_session=os.name != "nt",
        )
        wait_for(WEB_URL, web, api=False)
        capture_environment = web_environment.copy()
        capture_environment["GRID_UI_MODE"] = mode
        subprocess.run(["node", str(CAPTURE)], cwd=ROOT, env=capture_environment, check=True)
        captured = True
        return {
            "mode": mode,
            "database_name": database,
            "api_port": API_PORT,
            "web_port": WEB_PORT,
            "api_ready": True,
            "web_ready": True,
        }
    finally:
        terminate_owned(web)
        terminate_owned(api)
        api_log.close()
        web_log.close()
        if captured:
            shutil.rmtree(logs)


def main() -> None:
    test_base = assert_safe_base_urls()
    ensure_ports_free()
    output = Path(os.environ.get("GRID_UI_FOLLOWUP_OUTPUT", str(Path(__file__).parent / "run-native-ui"))).resolve()
    if output.exists():
        raise SystemExit(f"Refusing to overwrite a prior native UI run: {output}")
    output.mkdir(parents=True)
    before_name = f"gl3_ui_followup_before_{uuid.uuid4().hex[:8]}_test"
    after_name = f"gl3_ui_followup_after_{uuid.uuid4().hex[:8]}_test"
    before_manifest = output / "before-manifest.json"
    after_manifest = output / "after-manifest.json"
    password = secrets.token_urlsafe(24)
    seed_base_env = os.environ.copy()
    seed_base_env["PYTHONUTF8"] = "1"
    seed_base_env["PGCONNECT_TIMEOUT"] = "5"
    seed_base_env["APP_PASSWORD_HASH"] = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()
    seed_base_env["SESSION_SECRET"] = "disposable-audit-session-secret-20261113"
    seed_base_env["COOKIE_SECURE"] = "false"
    seed_base_env["WORKER_AUTO_REFRESH"] = "false"
    seed_base_env["OPENAI_API_KEY"] = ""
    seed_base_env["FIRECRAWL_API_KEY"] = ""
    seed_base_env["TYPESAFE_API_KEY"] = ""

    old_revision = subprocess.check_output(["git", "rev-parse", f"{PR202}^"], cwd=ROOT, text=True).strip()
    old_source = subprocess.check_output(
        ["git", "show", f"{old_revision}:backend/src/gridlens/intelligence/saved_browse.py"],
        cwd=ROOT,
    )
    with tempfile.TemporaryDirectory(prefix="gl3-ui-followup-pre-pr202-") as temporary:
        corpus = Path(temporary) / "retained-source-corpus"
        materialize_git_tree("HEAD", "eval/customer-commercial-v1", corpus)
        overlay = Path(temporary) / "backend" / "src"
        shutil.copytree(ROOT / "backend" / "src", overlay)
        shutil.copytree(ROOT / "config", Path(temporary) / "config")
        saved_browse_path = overlay / "gridlens" / "intelligence" / "saved_browse.py"
        saved_browse_path.write_bytes(old_source)
        before_env = seed_base_env.copy()
        before_env["PYTHONPATH"] = str(overlay) + os.pathsep + str(ROOT / "backend" / "src")
        before_env["GRID_SAVED_BROWSE_OVERLAY"] = str(overlay)
        subprocess.run(
            [sys.executable, str(SEED), "--mode", "before", "--database", before_name, "--manifest", str(before_manifest), "--corpus", str(corpus)],
            cwd=ROOT,
            env=before_env,
            check=True,
        )
        after_env = seed_base_env.copy()
        after_env["PYTHONPATH"] = str(ROOT / "backend" / "src")
        subprocess.run(
            [sys.executable, str(SEED), "--mode", "after", "--database", after_name, "--manifest", str(after_manifest), "--corpus", str(corpus)],
            cwd=ROOT,
            env=after_env,
            check=True,
        )
        before = json.loads(before_manifest.read_text(encoding="utf-8"))
        after = json.loads(after_manifest.read_text(encoding="utf-8"))
        if not any(account["recent_developments"] for account in before["accounts"]):
            raise AssertionError("Pre-PR202 native fixture did not reproduce its historical first-fact revision label")
        if any(account["recent_developments"] for account in after["accounts"]):
            raise AssertionError("Current native fixture still publishes a first-seen historical event as recent")
        if before["project_rows"] != after["project_rows"] or before["need_rows"] != after["need_rows"]:
            raise AssertionError("Before/after native fixtures did not retain the same project/need count")
        if before["source_artifact_sha256"] != after["source_artifact_sha256"]:
            raise AssertionError("Before/after native fixtures used different source artifacts")

        before_overlay_hash = hashlib.sha256(old_source).hexdigest()
        before_run = launch_pair("before", before_name, before_manifest, output, overlay=overlay, password=password)
        after_run = launch_pair("after", after_name, after_manifest, output, overlay=None, password=password)
    result = {
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "comparison": "Same retained source artifacts and parser; baseline uses pre-PR202 saved_browse.py, candidate uses current source.",
        "baseline_saved_browse_commit": old_revision,
        "baseline_saved_browse_sha256": before_overlay_hash,
        "candidate_saved_browse_sha256": hashlib.sha256((ROOT / "backend/src/gridlens/intelligence/saved_browse.py").read_bytes()).hexdigest(),
        "before_manifest": before,
        "after_manifest": after,
        "before_run": before_run,
        "after_run": after_run,
        "provider_calls": 0,
        "api_mocking": False,
        "reference_labels_used": False,
        "limitations": [
            "The before view is an intentionally stale pre-PR202 control, not current product behavior.",
            "Two retained public-source organizations are a technical readability fixture, not the required 20-organization evaluation.",
            "No salesperson or customer usability feedback was collected.",
            "No production deployment, retained-database access, paid provider call or live source activation occurred.",
        ],
    }
    (output / "receipt.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    screenshot_count = len(list(output.glob("*.png")))
    print(json.dumps({"output": str(output), "before_db": before_name, "after_db": after_name, "screenshots": screenshot_count, "receipt": str(output / "receipt.json")}))


if __name__ == "__main__":
    main()
