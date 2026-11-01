from datetime import date

import numpy as np

from tests.conftest import ANCHORS, CFG_SMALL, build_small_system
from tests.conftest import TYPES as TYPES_PATH
from tools.synth.calendar import easter
from tools.synth.config import load_config
from tools.synth.households import load_household_types
from tools.synth.profiles import load_profiles
from tools.synth.system_load import calibrate_peak

CFG = load_config(CFG_SMALL)
TYPES = load_household_types(TYPES_PATH)


def test_easter_known_dates():
    assert easter(2024) == date(2024, 3, 31) and easter(2025) == date(2025, 4, 20)


def test_profiles_sum_to_one():
    p = load_profiles(TYPES, CFG)
    assert np.allclose(p.groupby(["household_type", "month", "daytype"]).share.sum(), 1)


def test_hour_counts_include_leap_year():
    s = build_small_system()  # years 2024, 2025
    assert (s.year == 2024).sum() == 8784 and (s.year == 2025).sum() == 8760


def test_monthly_energy_matches_sheet():
    s = build_small_system()
    for (y, m), g in s.groupby(["year", "month"]):
        assert abs(g.load_mw.sum() - ANCHORS.monthly_mwh[(y, m)]) / ANCHORS.monthly_mwh[(y, m)] <= 1e-4


def test_annual_peak_matches_sheet():
    s = build_small_system()
    for y, g in s.groupby("year"):
        assert abs(g.load_mw.max() - ANCHORS.peak_mw[y]) <= 0.01


def test_calibrate_peak_preserves_daily_energy():
    e = np.array([100.0, 120.0])
    shapes = np.full((2, 24), 1 / 24)
    shapes[:, 19] += 0.02
    shapes /= shapes.sum(1, keepdims=True)
    out = calibrate_peak(e, shapes, target_mw=9.0)
    assert np.allclose(out.sum(1), e) and abs(out.max() - 9.0) <= 0.01
