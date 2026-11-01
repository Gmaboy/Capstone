import numpy as np

from tests.conftest import (
    CFG_SMALL as CFG,
    build_small_feeder_hourly,
    build_small_network,
    build_small_system,
    build_small_transformer_peaks,
)
from tools.synth.config import load_config
from tools.synth.daily import daily_peaks


def test_feeder_layout():
    f, t, h = build_small_network()
    assert len(f) == 12
    assert f.groupby("substation_zone").size().to_dict() == {
        "Buenavista": 3, "Jordan": 3, "Nueva Valencia": 2, "San Lorenzo": 2, "Sibunag": 2}
    assert h.transformer_id.notna().all() and len(t) == 100


def test_feeders_sum_to_system_every_hour():
    fh, system = build_small_feeder_hourly()
    merged = fh.groupby("ts").load_mw.sum().reindex(system.set_index("ts").index)
    assert np.abs(merged.values - system.load_mw.values).max() <= 0.001


def test_transformer_ratings_and_stress_share():
    tm, t = build_small_transformer_peaks()
    assert set(t.rating_kva) <= {10, 15, 25, 37.5, 50, 75, 100, 167, 250, 333, 500}
    final = tm[tm.year == tm.year.max()].groupby("transformer_id").utilization.max()
    assert (final <= 1.1 + 1e-9).all() and (final >= 0.5 - 1e-9).all()


def test_daily_labels_use_thresholds():
    d = daily_peaks(build_small_system(), load_config(CFG))
    assert d.loc[d.pct_of_annual_peak >= 0.90, "demand_level"].eq("High").all()
    assert d.loc[d.pct_of_annual_peak < 0.75, "demand_level"].eq("Low").all()
    assert (d.groupby("year").pct_of_annual_peak.max() == 1.0).all()
