from pathlib import Path

from tools.common.anchors import load_anchors

CFG = Path("tools/synth/config.json")
CFG_SMALL = Path("tests/fixtures/config_small.json")
TYPES = Path("tools/synth/household_types.json")
ANCHORS = load_anchors()


def build_small():
    """Anchors + small config -> household_monthly, using one seeded RNG."""
    import numpy as np

    from tools.synth.config import load_config
    from tools.synth.customers import customer_counts
    from tools.synth.households import (
        household_monthly,
        load_household_types,
        sample_households,
    )

    cfg = load_config(CFG_SMALL)
    types = load_household_types(TYPES)
    rng = np.random.default_rng(cfg.seed)
    counts = customer_counts(ANCHORS, cfg)
    hh = sample_households(ANCHORS, cfg, types, rng, counts)
    return household_monthly(ANCHORS, cfg, types, hh, counts, rng)


def build_small_system():
    """Small config -> system_hourly, using one seeded RNG."""
    import numpy as np

    from tools.synth.config import load_config
    from tools.synth.households import load_household_types
    from tools.synth.profiles import load_profiles
    from tools.synth.system_load import system_hourly

    cfg = load_config(CFG_SMALL)
    types = load_household_types(TYPES)
    profiles = load_profiles(types, cfg)
    rng = np.random.default_rng(cfg.seed)
    return system_hourly(ANCHORS, cfg, types, profiles, rng)


_NET_CACHE: dict = {}


def _network_pipeline():
    """Small-config pipeline through transformer peaks, one RNG, generator order."""
    if "p" in _NET_CACHE:
        return _NET_CACHE["p"]
    import numpy as np

    from tools.synth.config import load_config
    from tools.synth.customers import customer_counts
    from tools.synth.households import (
        household_monthly,
        load_household_types,
        sample_households,
    )
    from tools.synth.network import build_network, feeder_hourly, transformer_monthly_peak
    from tools.synth.profiles import load_profiles
    from tools.synth.system_load import system_hourly

    cfg = load_config(CFG_SMALL)
    types = load_household_types(TYPES)
    rng = np.random.default_rng(cfg.seed)
    counts = customer_counts(ANCHORS, cfg)
    hh = sample_households(ANCHORS, cfg, types, rng, counts)
    hm = household_monthly(ANCHORS, cfg, types, hh, counts, rng)
    profiles = load_profiles(types, cfg)
    system = system_hourly(ANCHORS, cfg, types, profiles, rng)
    feeders, transformers, hh_net = build_network(cfg, hh, counts, rng)
    fh = feeder_hourly(feeders, hh_net, hm, profiles, system)
    tm = transformer_monthly_peak(transformers, hh_net, hm, fh, cfg, rng)
    _NET_CACHE["p"] = {
        "network": (feeders, transformers, hh_net),
        "feeder_hourly": (fh, system),
        "peaks": (tm, transformers),
    }
    return _NET_CACHE["p"]


def build_small_network():
    return _network_pipeline()["network"]


def build_small_feeder_hourly():
    return _network_pipeline()["feeder_hourly"]


def build_small_transformer_peaks():
    return _network_pipeline()["peaks"]


def _real_series():
    from tools.model.forecast import real_series
    from tools.synth.config import load_config

    return real_series(ANCHORS, load_config(CFG))


SERIES, CUSTOMERS = _real_series()


_DAILY_CACHE: dict = {}


def small_daily():
    """Daily peaks for the small config (built once, lazily)."""
    if "d" not in _DAILY_CACHE:
        from tools.synth.config import load_config
        from tools.synth.daily import daily_peaks

        _DAILY_CACHE["d"] = daily_peaks(build_small_system(), load_config(CFG_SMALL))
    return _DAILY_CACHE["d"]


import pytest  # noqa: E402


@pytest.fixture
def loaded_small_db(tmp_path):
    """SQLite DB holding the real utility tables plus the small synthetic dataset."""
    from tools.common.anchors import DEFAULT_REAL_CSV
    from tools.synth.generate import generate
    from tools.synth.load import load

    out = tmp_path / "synth"
    generate(CFG_SMALL, out)
    db = tmp_path / "small.db"
    load(db, DEFAULT_REAL_CSV, out)
    return db


# ---- API fixtures -------------------------------------------------------

DEMO_LOGIN = {"email": "household@electroforecast.local", "password": "Household123!"}


@pytest.fixture(scope="module")
def trained_db_template(tmp_path_factory):
    """Small synthetic data loaded and trained once per module (read-only template)."""
    from tools.common.anchors import DEFAULT_REAL_CSV
    from tools.model.train import train
    from tools.synth.generate import generate
    from tools.synth.load import load

    base = tmp_path_factory.mktemp("api_trained")
    out = base / "synth"
    generate(CFG_SMALL, out)
    db = base / "trained.db"
    load(db, DEFAULT_REAL_CSV, out)
    train(db, base / "models", base / "reports")
    return db


def _import_app(monkeypatch, db_path):
    import sys

    monkeypatch.setenv("ELECTROFORECAST_DB", str(db_path))
    sys.modules.pop("app", None)
    import importlib

    return importlib.import_module("app")


def _login(app_module):
    client = app_module.app.test_client()
    resp = client.post("/api/auth/login", json=DEMO_LOGIN)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return client


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Flask test client on an empty temp DB, not logged in."""
    import sys

    mod = _import_app(monkeypatch, tmp_path / "empty.db")
    try:
        yield mod.app.test_client()
    finally:
        sys.modules.pop("app", None)


@pytest.fixture
def client_logged_in_empty(tmp_path, monkeypatch):
    import sys

    mod = _import_app(monkeypatch, tmp_path / "empty.db")
    try:
        yield _login(mod)
    finally:
        sys.modules.pop("app", None)


@pytest.fixture
def client_logged_in_trained(trained_db_template, tmp_path, monkeypatch):
    import shutil
    import sys

    db = tmp_path / "trained_copy.db"
    shutil.copyfile(trained_db_template, db)
    mod = _import_app(monkeypatch, db)
    try:
        yield _login(mod)
    finally:
        sys.modules.pop("app", None)
