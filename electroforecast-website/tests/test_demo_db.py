"""The Vercel demo starts from deploy/demo.db; it must still serve every page's data with the demo accounts."""
import shutil
import sys
from pathlib import Path

import pytest

from tests.conftest import _import_app
from tests.test_validated_data import ADMIN_LOGIN, HOUSEHOLD_LOGIN

DEMO_DB = Path(__file__).resolve().parent.parent / "deploy" / "demo.db"


@pytest.fixture
def demo_app(tmp_path, monkeypatch):
    if not DEMO_DB.exists():
        pytest.skip("deploy/demo.db not built")
    db = tmp_path / "demo.db"
    shutil.copyfile(DEMO_DB, db)
    monkeypatch.setenv("ELECTROFORECAST_UPLOADS", str(tmp_path / "uploads"))
    mod = _import_app(monkeypatch, db)
    try:
        yield mod
    finally:
        sys.modules.pop("app", None)


def _login(mod, creds):
    client = mod.app.test_client()
    assert client.post("/api/auth/login", json=creds).status_code == 200
    return client


def test_demo_accounts_see_real_data(demo_app):
    admin = _login(demo_app, ADMIN_LOGIN)
    for url in ("/api/forecast/monthly", "/api/forecast/peak", "/api/demand/daily", "/api/explain",
                "/api/models/active", "/api/validated-data", "/api/contributors", "/api/admin/submissions?status=all"):
        assert admin.get(url).status_code == 200, url
    assert admin.get("/api/forecast/monthly").json["history"], "forecast history should not be empty"
    household = _login(demo_app, HOUSEHOLD_LOGIN)
    assert household.get("/api/portal/summary").status_code == 200


def test_demo_has_only_demo_accounts_and_serves_pages(demo_app):
    admin = _login(demo_app, ADMIN_LOGIN)
    emails = {u["email"] for u in admin.get("/api/admin/users").json["users"]}
    assert emails <= {"admin@electroforecast.local", "household@electroforecast.local", "maria@electroforecast.local"}
    client = demo_app.app.test_client()
    for page in ("/index.html", "/login.html", "/assets/css/style.css", "/reports/forecast_backtest_2024.png"):
        assert client.get(page).status_code == 200, page
    for secret in ("/deploy/demo.db", "/app.py", "/api/index.py"):
        assert client.get(secret).status_code == 404, secret
