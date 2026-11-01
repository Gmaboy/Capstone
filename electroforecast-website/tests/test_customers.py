from pathlib import Path

from tools.common.anchors import load_anchors
from tools.common.locations import BARANGAYS
from tools.synth.config import load_config
from tools.synth.customers import customer_counts, largest_remainder, monthly_customers

CFG = Path("tools/synth/config.json")


def test_largest_remainder_is_exact():
    assert sum(largest_remainder(1001, [1, 1, 1])) == 1001


def test_year_end_convention():
    m = monthly_customers(load_anchors(), load_config(CFG))
    assert m[(2025, 12)] == 39618 and m[(2024, 12)] == 37916
    assert 37916 < m[(2025, 6)] < 39618


def test_counts_sum_exactly_every_month():
    df = customer_counts(load_anchors(), load_config(CFG))
    sums = df.groupby(["year", "month"]).customers.sum()
    m = monthly_customers(load_anchors(), load_config(CFG))
    assert all(sums[k] == m[k] for k in m)
    assert len(df[["municipality", "barangay"]].drop_duplicates()) == 98 and df.municipality.nunique() == 5


def test_municipality_shares_sum_to_one_and_cite_source():
    cfg = load_config(CFG)
    assert abs(sum(cfg.municipality_shares.values()) - 1) < 1e-9
    assert set(cfg.municipality_shares) == set(BARANGAYS)
    assert cfg.municipality_shares_source
