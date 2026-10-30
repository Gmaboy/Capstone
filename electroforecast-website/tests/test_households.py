from tests.conftest import ANCHORS, CFG_SMALL, TYPES, build_small
from tools.synth.config import load_config
from tools.synth.customers import monthly_customers
from tools.synth.households import load_household_types, type_mix

CFG = load_config(CFG_SMALL)


def test_types_file_is_well_formed():
    types = load_household_types(TYPES)
    assert [t.name for t in types] == ["basic", "standard", "aircon", "home_business", "low_occupancy"]
    for t in types:
        for a in t.appliances:
            assert a["watts"] > 0 and 0 <= a["hours_per_day"] <= 24 and a["source"]
    assert abs(sum(t.mix_start for t in types) - 1) < 1e-9
    assert abs(sum(t.mix_end for t in types) - 1) < 1e-9


def test_weighted_total_matches_sheet_each_month():
    hm = build_small()
    for (y, m), group in hm.groupby(["year", "month"]):
        total_mwh = (group.kwh * group.weight).sum() / 1000
        assert abs(total_mwh - ANCHORS.monthly_mwh[(y, m)]) / ANCHORS.monthly_mwh[(y, m)] <= 1e-4


def test_weights_reproduce_customer_counts():
    hm = build_small()
    expected = monthly_customers(ANCHORS, CFG)
    for (y, m), group in hm.groupby(["year", "month"]):
        assert round(group.weight.sum()) == expected[(y, m)]


def test_sample_size_and_no_negatives():
    hm = build_small()
    assert hm.synth_household_id.nunique() == 200
    assert (hm.kwh >= 0).all() and hm.kwh.notna().all()


def test_type_mix_interpolates_and_sums_to_one():
    types = load_household_types(TYPES)
    for y in (2020, 2023, 2025):
        assert abs(sum(type_mix(types, y).values()) - 1) < 1e-9
    assert type_mix(types, 2020)["aircon"] == types[2].mix_start
    assert abs(type_mix(types, 2025)["aircon"] - types[2].mix_end) < 1e-12
