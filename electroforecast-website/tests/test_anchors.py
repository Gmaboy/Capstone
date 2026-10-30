from tools.common.anchors import load_anchors

def test_monthly_values_match_sheet():
    a = load_anchors()
    assert a.years == [2020, 2021, 2022, 2023, 2024, 2025]
    assert a.monthly_mwh[(2020, 1)] == 2367
    assert a.monthly_mwh[(2025, 12)] == 3786
    assert sum(a.monthly_mwh[(2020, m)] for m in range(1, 13)) == 30296

def test_2023_discrepancy_is_preserved_and_noted():
    a = load_anchors()
    assert sum(a.monthly_mwh[(2023, m)] for m in range(1, 13)) == 38689
    assert a.annual_reported_mwh[2023] == 38369
    assert "38689" in a.notes[2023]

def test_customers_and_peaks():
    a = load_anchors()
    assert a.customers[2025] == 39618
    assert a.peak_mw[2022] == 11.06
