import json
import sqlite3
from contextlib import closing

import pytest

from tools.model.forecast import CANDIDATES
from tools.model.train import MissingDataError, train


def _q(db, sql, *a):
    with closing(sqlite3.connect(db)) as con:
        return con.execute(sql, a).fetchall()


def test_train_writes_one_active_run_per_task(loaded_small_db, tmp_path):
    train(loaded_small_db, tmp_path / "m", tmp_path / "r")
    train(loaded_small_db, tmp_path / "m", tmp_path / "r")
    active = _q(loaded_small_db, "select task, count(*) from model_runs where is_active=1 group by task")
    assert dict(active) == {"monthly_energy": 1, "annual_peak": 1, "demand_class": 1}
    assert _q(loaded_small_db, "select count(*) from model_runs")[0][0] == 6
    assert _q(loaded_small_db, "select count(*) from forecast_monthly f join model_runs r using(run_id) where r.is_active=1")[0][0] == 24
    assert (tmp_path / "r" / "metrics.json").exists()


def test_run_contents_and_versions(loaded_small_db, tmp_path):
    ids = train(loaded_small_db, tmp_path / "m", tmp_path / "r")
    assert set(ids) == {"monthly_energy", "annual_peak", "demand_class"}
    versions = dict(_q(loaded_small_db, "select task, dataset_version from model_runs"))
    assert versions["monthly_energy"] == "real:guimelco_residential_2020_2025"
    assert versions["annual_peak"] == "real:guimelco_residential_2020_2025"
    assert versions["demand_class"] == "synth-v1-seed42"
    kinds = _q(loaded_small_db, "select kind, run_id, count(*), count(year) from feature_importance group by kind")
    by = {k: (r, n, ny) for k, r, n, ny in kinds}
    assert by["breakdown"] == (ids["monthly_energy"], 72, 72)
    assert by["permutation"][0] == ids["demand_class"] and by["permutation"][2] == 0
    assert _q(loaded_small_db, "select count(*) from forecast_annual_peak")[0][0] == 2
    assert _q(loaded_small_db, "select count(*) from demand_predictions")[0][0] == 365
    for t, rid in ids.items():
        assert (tmp_path / "m" / f"{t}-{rid}.joblib").exists()
    metrics = json.loads((tmp_path / "r" / "metrics.json").read_text())
    assert {"monthly_energy", "annual_peak", "demand_class", "backtest"} <= set(metrics)
    assert "beats_baseline" in metrics["monthly_energy"]
    nested = metrics["monthly_energy"]["nested"]
    assert nested["selected_on"] == "2024" and nested["model"] in CANDIDATES
    assert {"mape_2025", "rmse_2025", "baseline_mape_2025"} <= set(nested)
    assert metrics["demand_class"]["majority_macro_f1"] >= 0
    for png in ("forecast_backtest_2024", "forecast_backtest_2025", "demand_confusion_matrix", "feature_importance"):
        assert (tmp_path / "r" / f"{png}.png").exists()


def test_train_on_empty_db_raises_clear_error(tmp_path):
    with pytest.raises(MissingDataError, match="utility_monthly_energy"):
        train(tmp_path / "empty.db", tmp_path / "m", tmp_path / "r")
    assert not (tmp_path / "empty.db").exists()


def test_train_on_empty_existing_file_raises(tmp_path):
    (tmp_path / "e.db").write_bytes(b"")
    with pytest.raises(MissingDataError, match="python -m tools.synth.load"):
        train(tmp_path / "e.db", tmp_path / "m", tmp_path / "r")


def test_missing_synthetic_rows_raise(loaded_small_db, tmp_path):
    with pytest.raises(MissingDataError, match="synth_daily_peaks"):
        train(loaded_small_db, tmp_path / "m", tmp_path / "r", dataset_version="nope")


def test_nested_metric_selects_on_2024_only():
    import pandas as pd

    from tools.model.train import nested_metric

    bt = pd.DataFrame([
        ("seasonal_naive", "2024", 5.0, 50.0), ("seasonal_naive", "2025", 6.0, 60.0),
        ("a", "2024", 3.0, 30.0), ("a", "2025", 9.0, 90.0),
        ("b", "2024", 4.0, 40.0), ("b", "2025", 1.0, 10.0),
    ], columns=["model_name", "fold", "mape", "rmse"])
    n = nested_metric(bt)
    assert n == {"selected_on": "2024", "model": "a", "mape_2025": 9.0, "rmse_2025": 90.0, "baseline_mape_2025": 6.0}
