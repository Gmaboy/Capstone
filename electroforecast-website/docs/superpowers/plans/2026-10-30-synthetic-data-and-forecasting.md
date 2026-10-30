# Synthetic Stand-in Data and Forecasting Models Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate five synthetic datasets anchored exactly to GUIMELCO's 2020–2025 residential sheet, train forecasting/classification models, and drive the Forecasting, Demand Classification, and Explainable AI pages from stored model results.

**Architecture:** An offline Python package `tools/` (generator → CSVs → SQLite loader → trainer) writes into new tables in the existing SQLite database. `app.py` gains read-only endpoints only. Three HTML pages replace hard-coded arrays with `ElectroAPI.request` calls.

**Tech Stack:** Python (project `.venv`), Flask 3.1.2, SQLite, numpy, pandas, statsmodels, scikit-learn, joblib, matplotlib, pytest; vanilla JS + `assets/js/chart-lite.js`.

**Spec:** `docs/superpowers/specs/2026-10-30-synthetic-data-and-forecasting-design.md`

All paths below are relative to `electroforecast-website/`. Run every command from that directory with the project venv (`.venv/Scripts/python`).

## Global Constraints

- `requirements.txt` stays `Flask==3.1.2` only. All other libraries go in `requirements-dev.txt`.
- The web app never generates, seeds, or trains at startup.
- Every synthetic table has a `dataset_version` column. The default version is `synth-v1-seed42` and the default seed is `42`.
- Every API payload includes `data_source` (`"real"` or `"synthetic"`).
- The monthly energy forecast trains and evaluates on **real** data only.
- 2023: monthly values are truth (sum 38,689). The printed total 38,369 is kept in `utility_annual_stats.total_mwh_reported`, with a note.
- Customer counts are year-end figures (config key `customer_count_convention: "year_end"`).
- Pages never fall back to fake numbers. With no active run, they show "No trained model yet".
- Existing crowdsourcing tables, routes, and pages are not modified.
- `.gitignore` adds `models/*.joblib` and `data/synthetic/*.csv`. `data/real/`, `reports/`, and `data/synthetic/validation_report.md` are committed.
- Test helpers named `build_small_*`, and the constants `ANCHORS`, `CFG`, `SMALL_CFG`, `TYPES`, `REAL_CSV`, live in `tests/conftest.py`. Each task adds its helper there by composing the earlier tasks' public functions with `tests/fixtures/config_small.json` and `rng = numpy.random.default_rng(cfg.seed)`. `CFG` in Task 2 is the full config; from Task 3 on, test `CFG` means the small config.
- Validation tolerances (spec §4.8):
  - monthly energy: ≤ 0.01%
  - annual peak: ≤ 0.01 MW
  - customer counts: exact
  - feeders vs system: ≤ 0.001 MW every hour
  - negative or NaN values: none

## Review Focus

1. **Leap years (2020, 2024):** hourly tables have 8,784 rows for those years, Feb 29 exists, and peak calibration still hits the sheet peak → tested in Task 4.
2. **Re-running `load` or `train`:** no duplicate rows. Re-loading the same `dataset_version` replaces it. Re-training leaves exactly one active run per task, and older runs stay inactive → tested in Tasks 6 and 9.
3. **Running `train` on a database with no loaded data:** exits with a clear message naming the missing table, not a traceback → tested in Task 9.
4. **Look-ahead leakage in demand features:** previous-day peak and 7-day mean use only days strictly before the predicted day → tested in Task 8.
5. **Bad `/api/demand/daily` queries:** non-ISO dates or `from` > `to` → `400`. Missing params default to the last 30 days of data → tested in Task 10.

---

### Task 1: Project tooling and real anchor data

**Files:**
- Create: `requirements-dev.txt`, `pytest.ini`, `tools/__init__.py`, `tools/common/__init__.py`, `tools/common/anchors.py`
- Create: `data/real/guimelco_residential_2020_2025.csv`
- Create: `tests/__init__.py`, `tests/test_anchors.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces:
  - `Anchors` (frozen dataclass) with fields:
    - `monthly_mwh: dict[tuple[int, int], float]`, keyed (year, month)
    - `annual_reported_mwh: dict[int, float]`
    - `customers: dict[int, int]`
    - `peak_mw: dict[int, float]`
    - `notes: dict[int, str]`
  - `Anchors.years -> list[int]`
  - `load_anchors(path: Path = DEFAULT_REAL_CSV) -> Anchors`
  - `DEFAULT_REAL_CSV`, the `Path` to the CSV.

- [ ] **Step 1: Set up dev tooling.**
  - `requirements-dev.txt` contents: `-r requirements.txt`, `numpy`, `pandas`, `statsmodels`, `scikit-learn`, `joblib`, `matplotlib`, `pytest`.
  - `pytest.ini` contents: `[pytest]`, `pythonpath = .`, `testpaths = tests`.
  - Append `models/*.joblib` and `data/synthetic/*.csv` to `.gitignore`.
  - Run: `.venv/Scripts/python -m pip install -r requirements-dev.txt`
  - Expected: installs without error.

- [ ] **Step 2: Write `data/real/guimelco_residential_2020_2025.csv`.**
  - Header comment lines:
    - `# Source: GUIMELCO, Residential.pdf, "Historical Residential Electricity Consumption and Peak Demand", received 2026-10-30`
    - `# Monthly values in MWh. 2023 printed total (38369) disagrees with monthly sum (38689); monthly values treated as truth.`
  - Columns: `year,jan,feb,mar,apr,may,jun,jul,aug,sep,oct,nov,dec,total_mwh_reported,customers,coincident_peak_mw`
  - Rows: copy all values verbatim from spec §2.

- [ ] **Step 3: Write the failing tests in `tests/test_anchors.py`.**

```python
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
```

- [ ] **Step 4: Run the tests to confirm they fail.**
  - Run: `.venv/Scripts/python -m pytest tests/test_anchors.py -v`
  - Expected: FAIL with `ModuleNotFoundError: tools.common.anchors`.

- [ ] **Step 5: Implement `load_anchors` in `tools/common/anchors.py`.**
  - Skip `#` lines and parse with the `csv` module.
  - `notes[year]` is filled when |Σ months − reported| > 2. Text: `"Monthly sum {sum:.0f} differs from printed total {reported:.0f}; monthly values used."`

- [ ] **Step 6: Run the tests to confirm they pass.**
  - Run: `.venv/Scripts/python -m pytest tests/test_anchors.py -v`
  - Expected: 3 passed.

- [ ] **Step 7: Commit.**

```bash
git add requirements-dev.txt pytest.ini .gitignore tools data/real tests
git commit -m "feat: add real GUIMELCO anchor data loader and test tooling"
```

### Task 2: Generator config and customer counts by barangay (spec §4.1)

**Files:**
- Create: `tools/synth/__init__.py`, `tools/synth/config.json`, `tools/synth/config.py`, `tools/synth/customers.py`
- Create: `tests/fixtures/config_small.json`, `tests/test_customers.py`

**Interfaces:**
- Consumes: `Anchors`, `load_anchors` (Task 1)
- Produces:
  - `SynthConfig` dataclass, created with `load_config(path: Path) -> SynthConfig`. Fields mirror the JSON keys below; `years` defaults to all anchor years.
  - `BARANGAYS: dict[str, tuple[str, ...]]`, imported from `app.GUIMARAS_BARANGAYS` without starting Flask. Move the dict to `tools/common/locations.py`; `app.py` then imports it from there.
  - `monthly_customers(anchors, cfg) -> dict[tuple[int, int], int]`
  - `customer_counts(anchors, cfg) -> pandas.DataFrame` with columns `year, month, municipality, barangay, customers, dataset_version`.
  - `largest_remainder(total: int, weights: Sequence[float]) -> list[int]`

- [ ] **Step 1: Write `tools/synth/config.json` with these keys and values.**
  - `"seed": 42`
  - `"dataset_version": "synth-v1-seed42"`
  - `"customer_count_convention": "year_end"`
  - `"household_sample_size": 2000`
  - `"years": null`
  - `"municipality_shares"`: PSA 2020 Census of Population and Housing populations for the 5 Guimaras municipalities, normalized. Add a `"municipality_shares_source"` string with the PSA citation/URL. **Look the figures up; do not estimate.**
  - `"barangay_weighting": "equal"`. Use `"population"` instead only if PSA barangay populations are entered under `"barangay_populations"`.
  - `"feeders"`: `{"Buenavista": 3, "Jordan": 3, "Nueva Valencia": 2, "San Lorenzo": 2, "Sibunag": 2}`
  - `"transformers_total": 100`
  - `"transformer_sizes_kva": [10, 15, 25, 37.5, 50, 75, 100, 167]`
  - `"power_factor": 0.9`
  - `"transformer_util_normal": [0.5, 0.9]`
  - `"transformer_util_stressed": [0.9, 1.1]`
  - `"transformer_stressed_share": 0.05`
  - `"weekend_factor": 1.05`
  - `"holiday_factor": 1.08`
  - `"daily_noise_sigma": 0.04`
  - `"daily_noise_clip": 0.10`
  - `"household_noise_sigma": 0.15`
  - `"demand_thresholds": {"high": 0.90, "medium": 0.75}`
  - `"fixed_holidays"`, as MM-DD: `01-01, 04-09, 05-01, 06-12, 08-21, 11-01, 11-02, 11-30, 12-08, 12-24, 12-25, 12-30, 12-31`
  - `"holy_week": true`

  `tests/fixtures/config_small.json`: identical except `"household_sample_size": 200`, `"years": [2024, 2025]`, `"transformers_total": 20`.

- [ ] **Step 2: Write the failing tests in `tests/test_customers.py`.**

```python
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
    assert df.barangay.nunique() == 98 and df.municipality.nunique() == 5

def test_municipality_shares_sum_to_one_and_cite_source():
    cfg = load_config(CFG)
    assert abs(sum(cfg.municipality_shares.values()) - 1) < 1e-9
    assert set(cfg.municipality_shares) == set(BARANGAYS)
    assert cfg.municipality_shares_source
```

  `CFG` is `Path("tools/synth/config.json")`.

- [ ] **Step 3: Run the tests to confirm they fail.**
  - Run: `.venv/Scripts/python -m pytest tests/test_customers.py -v`
  - Expected: FAIL (import errors).

- [ ] **Step 4: Implement `tools/common/locations.py`, `config.py`, and `customers.py`.**
  - Move `GUIMARAS_BARANGAYS` from `app.py` to `tools/common/locations.py` as `BARANGAYS`. `app.py` does `from tools.common.locations import BARANGAYS as GUIMARAS_BARANGAYS`.
  - Monthly interpolation: month m of year y = C[y−1] + (C[y] − C[y−1]) × m/12, rounded to int.
  - C[2019] = C[2020] − (C[2021] − C[2020]).

- [ ] **Step 5: Run these tests plus the existing app import check.**
  - Run: `.venv/Scripts/python -m pytest tests/test_customers.py -v`
  - Run: `.venv/Scripts/python -c "import app; print(len(app.GUIMARAS_BARANGAYS))"`
  - Expected: 4 passed, then `5`.

- [ ] **Step 6: Commit.**

```bash
git add tools tests app.py
git commit -m "feat: add synth config and exact customer counts by barangay"
```

### Task 3: Household types, sample, and monthly consumption (spec §4.2–4.3)

**Files:**
- Create: `tools/synth/household_types.json`, `tools/synth/households.py`
- Create: `tests/test_households.py`

**Interfaces:**
- Consumes: `SynthConfig`, `customer_counts`, `Anchors`
- Produces:
  - `HouseholdType` dataclass with fields:
    - `name: str`
    - `appliances: list[dict]`
    - `mix_start: float`, `mix_end: float`
    - `peak_window: str` (`"evening"` | `"afternoon_evening"` | `"flat"`)
  - `load_household_types(path) -> list[HouseholdType]`
  - `HouseholdType.base_kwh_month -> float` = Σ watts × qty × hours × 30.4 / 1000
  - `sample_households(anchors, cfg, types, rng) -> DataFrame` with columns `synth_household_id, municipality, barangay, household_type, household_size, dataset_version`. Transformer assignment is added in Task 5.
  - `household_monthly(anchors, cfg, types, households, counts, rng) -> DataFrame` with columns `synth_household_id, year, month, kwh, weight, dataset_version`
  - `scale_factors(...)`, recorded in the frame attribute `attrs["scale_factors"]: dict[(y, m), float]`

- [ ] **Step 1: Write `tools/synth/household_types.json`.**
  - Five types, in this order: `basic`, `standard`, `aircon`, `home_business`, `low_occupancy`.
  - Appliances per type follow spec §4.2.
  - Every appliance has `name, watts, quantity, hours_per_day, source`.
  - Sources: DOE Philippines energy labels/guides for wattage; PSA Household Energy Consumption Survey for ownership; utility appliance calculators for hours. Use `"estimate"` where unverified.
  - `mix_start` (2020) and `mix_end` (2025) shares: each set sums to 1, and `aircon` + `standard` grow from start to end.
  - `peak_window`: `aircon` → `afternoon_evening`; `home_business` → `flat`; others → `evening`.

- [ ] **Step 2: Write the failing tests in `tests/test_households.py`, using `tests/fixtures/config_small.json`.**

```python
def test_types_file_is_well_formed():
    types = load_household_types(TYPES)
    assert [t.name for t in types] == ["basic", "standard", "aircon", "home_business", "low_occupancy"]
    for t in types:
        for a in t.appliances:
            assert a["watts"] > 0 and 0 <= a["hours_per_day"] <= 24 and a["source"]
    assert abs(sum(t.mix_start for t in types) - 1) < 1e-9
    assert abs(sum(t.mix_end for t in types) - 1) < 1e-9

def test_weighted_total_matches_sheet_each_month():
    hm = build_small()  # helper: anchors+cfg+types+sample+counts → household_monthly
    for (y, m), group in hm.groupby(["year", "month"]):
        total_mwh = (group.kwh * group.weight).sum() / 1000
        assert abs(total_mwh - ANCHORS.monthly_mwh[(y, m)]) / ANCHORS.monthly_mwh[(y, m)] <= 1e-4

def test_weights_reproduce_customer_counts():
    hm = build_small()
    for (y, m), group in hm.groupby(["year", "month"]):
        assert round(group.weight.sum()) == monthly_customers(ANCHORS, CFG)[(y, m)]

def test_sample_size_and_no_negatives():
    hm = build_small()
    assert hm.synth_household_id.nunique() == 200
    assert (hm.kwh >= 0).all() and hm.kwh.notna().all()
```

- [ ] **Step 3: Run the tests to confirm they fail.**
  - Run: `.venv/Scripts/python -m pytest tests/test_households.py -v`
  - Expected: FAIL (import errors).

- [ ] **Step 4: Implement `tools/synth/households.py`.**
  - **Sampling:** stratified by barangay. Allocate `household_sample_size` across barangays with `largest_remainder` on final-year customer counts, with at least 1 per barangay.
  - **Types:** drawn from the mix linearly interpolated at the final config year.
  - **Household size:** integer drawn from 1–8, centered on 4.
  - **Weight:** barangay customers(y, m) ÷ sampled households in that barangay.
  - **Raw kWh:** `base_kwh_month × seasonal(type, month) × (0.7 + 0.075 × size) × lognormal(0, household_noise_sigma)`.
    - Seasonal factor for `aircon`: 1.35 for Apr–Jun, 1.1 for Mar and Jul–Aug, 0.85 otherwise.
    - Other types: 1.0 ± 0.08 following the sheet's monthly shape (month MWh ÷ year mean).
  - **Scaling:** one factor per (y, m) makes Σ weight × kWh = MWh × 1000. Store kWh rounded to 0.1.
  - **RNG:** `numpy.random.default_rng(cfg.seed)` passed in from the caller.

- [ ] **Step 5: Run the tests to confirm they pass.**
  - Run: `.venv/Scripts/python -m pytest tests/test_households.py -v`
  - Expected: 4 passed.

- [ ] **Step 6: Commit.**

```bash
git add tools/synth tests
git commit -m "feat: add household types, weighted sample, and monthly consumption"
```

### Task 4: Load profiles and system hourly load with peak calibration (spec §4.4–4.5)

**Files:**
- Create: `tools/synth/calendar.py`, `tools/synth/profiles.py`, `tools/synth/system_load.py`
- Create: `tests/test_system_load.py`

**Interfaces:**
- Consumes: `SynthConfig`, `HouseholdType`, `Anchors`, the type mix from Task 3.
- Produces:
  - `easter(year: int) -> date`
  - `holidays(year: int, cfg) -> set[date]`: fixed holidays, plus Maundy Thursday and Good Friday when `holy_week` is set.
  - `load_profiles(types, cfg) -> DataFrame` with columns `household_type, month, daytype ("weekday" | "weekend"), hour (0–23), share, dataset_version`. Shares sum to 1 per (type, month, daytype).
  - `system_hourly(anchors, cfg, types, profiles, rng) -> DataFrame` with columns `ts (naive local datetime, Asia/Manila), year, month, load_mw, dataset_version`.
  - `calibrate_peak(day_energy: np.ndarray, day_shapes: np.ndarray, target_mw: float) -> np.ndarray`
    - `day_energy` has shape (days,), in MWh; `day_shapes` has shape (days, 24) and sums to 1.
    - Returns hourly MW with shape (days, 24).

- [ ] **Step 1: Write the failing tests in `tests/test_system_load.py`.**

```python
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
```

- [ ] **Step 2: Run the tests to confirm they fail.**
  - Run: `.venv/Scripts/python -m pytest tests/test_system_load.py -v`
  - Expected: FAIL (import errors).

- [ ] **Step 3: Implement `calendar.py`.**
  - `easter` uses the anonymous Gregorian algorithm (Meeus/Jones/Butcher).

- [ ] **Step 4: Implement `profiles.py`.**
  - Each shape is a base of 0.025 plus Gaussian bumps in hours:
    - `evening`: a bump at 19:00 (σ = 1.5 h) and a small one at 06:00.
    - `afternoon_evening`: bumps at 14:00 and 20:00. Their amplitude is ×1.4 in Apr–Jun.
    - `flat`: a single wide bump at 12:00.
  - Weekends shift the morning bump +1 h and raise midday by 10%.
  - Normalize each shape to sum to 1.

- [ ] **Step 5: Implement `system_load.py`.**
  - **Daily energy:** month MWh × normalized day weights. Weight = 1, × `weekend_factor` on Sat/Sun, × `holiday_factor` on holidays, × (1 + clipped normal noise).
  - **Day shape:** the type-mix-weighted blend of profiles for that month and daytype.
  - **Peak calibration** (`calibrate_peak`):

```python
def calibrate_peak(day_energy, day_shapes, target_mw):
    def hourly(k):
        s = day_shapes ** k
        return day_energy[:, None] * s / s.sum(1, keepdims=True)
    lo, hi = 0.2, 8.0
    if not (hourly(lo).max() <= target_mw <= hourly(hi).max()):
        raise ValueError(f"Peak {target_mw} MW unreachable for this energy/shape")
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if hourly(mid).max() < target_mw else (lo, mid)
    return hourly((lo + hi) / 2)
```

  - Call `calibrate_peak` once per year, on all of that year's days together.

- [ ] **Step 6: Run the tests to confirm they pass.**
  - Run: `.venv/Scripts/python -m pytest tests/test_system_load.py -v`
  - Expected: 6 passed.

- [ ] **Step 7: Commit.**

```bash
git add tools/synth tests
git commit -m "feat: add load profiles and peak-calibrated system hourly load"
```

### Task 5: Feeders, transformers, and daily peak labels (spec §4.6–4.7)

**Files:**
- Create: `tools/synth/network.py`, `tools/synth/daily.py`
- Create: `tests/test_network.py`

**Interfaces:**
- Consumes: the household sample (Task 3), `household_monthly`, `system_hourly`, `load_profiles`, `SynthConfig`.
- Produces:
  - `build_network(cfg, households, counts, rng) -> tuple[DataFrame, DataFrame, DataFrame]`, returning (feeders, transformers, households-with-`transformer_id`).
    - feeders columns: `feeder_id, feeder_code ("SYN-BUE-F1"…), substation_zone, barangays (";"-joined), dataset_version`
    - transformers columns: `transformer_id, transformer_code ("SYN-T001"…), feeder_id, barangays, rating_kva, dataset_version`
  - `feeder_hourly(feeders, households, household_monthly, profiles, system) -> DataFrame` with columns `ts, feeder_id, load_mw, dataset_version`
  - `transformer_monthly_peak(transformers, households, household_monthly, feeder_hourly, cfg, rng) -> DataFrame` with columns `transformer_id, year, month, peak_kva, utilization, dataset_version`. Ratings are filled here and written back into `transformers.rating_kva`.
  - `daily_peaks(system, cfg) -> DataFrame` with columns `date, year, peak_mw, pct_of_annual_peak, demand_level ("High" | "Medium" | "Low"), dataset_version`

- [ ] **Step 1: Write the failing tests in `tests/test_network.py`.**

```python
def test_feeder_layout():
    f, t, h = build_small_network()
    assert len(f) == 12
    assert f.groupby("substation_zone").size().to_dict() == {
        "Buenavista": 3, "Jordan": 3, "Nueva Valencia": 2, "San Lorenzo": 2, "Sibunag": 2}
    assert h.transformer_id.notna().all() and len(t) == 20

def test_feeders_sum_to_system_every_hour():
    fh, system = build_small_feeder_hourly()
    merged = fh.groupby("ts").load_mw.sum().reindex(system.set_index("ts").index)
    assert np.abs(merged.values - system.load_mw.values).max() <= 0.001

def test_transformer_ratings_and_stress_share():
    tm, t = build_small_transformer_peaks()
    assert set(t.rating_kva) <= {10, 15, 25, 37.5, 50, 75, 100, 167}
    final = tm[tm.year == tm.year.max()].groupby("transformer_id").utilization.max()
    assert (final <= 1.1 + 1e-9).all() and (final >= 0.5 - 1e-9).all()

def test_daily_labels_use_thresholds():
    d = daily_peaks(build_small_system(), CFG)
    assert d.loc[d.pct_of_annual_peak >= 0.90, "demand_level"].eq("High").all()
    assert d.loc[d.pct_of_annual_peak < 0.75, "demand_level"].eq("Low").all()
    assert (d.groupby("year").pct_of_annual_peak.max() == 1.0).all()
```

- [ ] **Step 2: Run the tests to confirm they fail.**
  - Run: `.venv/Scripts/python -m pytest tests/test_network.py -v`
  - Expected: FAIL (import errors).

- [ ] **Step 3: Implement `network.py` and `daily.py`.**
  - **Feeders:** each municipality's barangays are split across its feeders in contiguous registry order, balanced by customers.
  - **Transformers:** `transformers_total` are allocated across feeders by customer share (at least 1 each). Each feeder's barangays are clustered across its transformers.
  - **Feeder hourly:** raw = Σ over the feeder's households of weight × kWh(month) × profile(type, month, daytype, hour) ÷ days-in-month energy. Then rescale each hour so Σ feeders = system.
  - **Transformer peak kW:** the feeder's hourly load × the transformer's share of feeder energy that month, maximized over the month. kVA = kW ÷ `power_factor`.
  - **Ratings:** per transformer, draw a target utilization from `transformer_util_stressed` with probability `transformer_stressed_share`, otherwise from `transformer_util_normal`. Pick the standard size closest to final-year peak kVA ÷ target, then clamp so final-year max utilization stays within [0.5, 1.1] by choosing the adjacent size if needed.

- [ ] **Step 4: Run the tests to confirm they pass.**
  - Run: `.venv/Scripts/python -m pytest tests/test_network.py -v`
  - Expected: 4 passed.

- [ ] **Step 5: Commit.**

```bash
git add tools/synth tests
git commit -m "feat: add synthetic feeders, transformers, and daily demand labels"
```

### Task 6: Generator CLI, validation report, schema, and loader (spec §3, §4.8)

**Files:**
- Create: `tools/synth/validate.py`, `tools/synth/generate.py`, `tools/synth/load.py`
- Modify: `database/schema.sqlite.sql` (append tables), `database/schema.sql` (MySQL mirror)
- Create: `tests/test_generate_and_load.py`
- Create, generated and committed: `data/synthetic/validation_report.md`

**Interfaces:**
- Consumes: everything from Tasks 1–5.
- Produces:
  - `validate(anchors, cfg, tables: dict[str, DataFrame]) -> list[Check]`. `Check` is a dataclass with fields `name, actual, tolerance, passed`.
  - `ValidationError(Exception)`
  - `generate(config_path: Path, out_dir: Path) -> dict[str, DataFrame]`
    - writes one CSV per synth table (file name = table name);
    - writes `validation_report.md`;
    - raises `ValidationError` if any check fails.
  - `load(db_path: Path, real_csv: Path, synthetic_dir: Path) -> None`
  - CLIs:
    - `python -m tools.synth.generate --config tools/synth/config.json --out data/synthetic`
    - `python -m tools.synth.load --db database/electroforecast.db --real data/real/guimelco_residential_2020_2025.csv --synthetic data/synthetic`
  - Tables:
    - `utility_monthly_energy(year, month, energy_mwh, source, PRIMARY KEY(year, month))`
    - `utility_annual_stats(year PRIMARY KEY, total_mwh_reported, customers, coincident_peak_mw, notes)`
    - the 10 `synth_*` tables from spec §3.3, with the columns defined in Tasks 2–5 plus `dataset_version TEXT NOT NULL`
    - indexes on `synth_system_hourly(ts)`, `synth_feeder_hourly(feeder_id, ts)`, `synth_daily_peaks(date)`

- [ ] **Step 1: Write the failing tests in `tests/test_generate_and_load.py`.**

```python
def test_small_generation_passes_all_checks(tmp_path):
    tables = generate(SMALL_CFG, tmp_path)
    report = (tmp_path / "validation_report.md").read_text()
    assert "FAIL" not in report and "38689" not in report  # 2023 not in small config years
    assert (tmp_path / "synth_system_hourly.csv").exists()

def test_generation_is_deterministic(tmp_path):
    generate(SMALL_CFG, tmp_path / "a")
    generate(SMALL_CFG, tmp_path / "b")
    for f in (tmp_path / "a").glob("*.csv"):
        assert f.read_bytes() == (tmp_path / "b" / f.name).read_bytes()

def test_validation_fails_on_tampered_totals(tmp_path):
    tables = generate(SMALL_CFG, tmp_path)
    tables["synth_system_hourly"].loc[0, "load_mw"] += 5
    assert not all(c.passed for c in validate(ANCHORS, load_config(SMALL_CFG), tables))

def test_load_is_idempotent(tmp_path):
    db = tmp_path / "t.db"
    generate(SMALL_CFG, tmp_path / "out")
    load(db, REAL_CSV, tmp_path / "out")
    load(db, REAL_CSV, tmp_path / "out")
    con = sqlite3.connect(db)
    assert con.execute("select count(*) from synth_households").fetchone()[0] == 200
    assert con.execute("select count(*) from utility_monthly_energy").fetchone()[0] == 72
    assert con.execute("select notes from utility_annual_stats where year=2023").fetchone()[0]
```

- [ ] **Step 2: Run the tests to confirm they fail.**
  - Run: `.venv/Scripts/python -m pytest tests/test_generate_and_load.py -v`
  - Expected: FAIL (import errors).

- [ ] **Step 3: Implement `validate.py` with the spec §4.8 checks and tolerances.**
  - The report lists every check with its actual value.
  - Per year it shows load factor = annual MWh ÷ (peak MW × hours-in-year), plus kWh/customer/month and min/max monthly scale factors.
  - Scale factors outside [0.7, 1.3] are listed as **WARN**, not FAIL.
  - The 2023 note is included when 2023 is in scope.

- [ ] **Step 4: Implement `generate.py`.**
  - CSV formatting: `float_format="%.6f"`, sorted by primary key, `lineterminator="\n"`. This keeps output byte-identical between runs.

- [ ] **Step 5: Implement the schema and `load.py`.**
  - Append the DDL to `schema.sqlite.sql` with `CREATE TABLE IF NOT EXISTS`, and mirror it in `schema.sql` with MySQL types.
  - `load` runs in one transaction:
    1. Execute the schema.
    2. `DELETE FROM <table> WHERE dataset_version=?` for each synth table.
    3. Insert with `pandas.to_sql(..., if_exists="append", chunksize=10000)`.
    4. Replace both utility tables entirely.

- [ ] **Step 6: Run the tests to confirm they pass, then run the full generation and load.**
  - Run: `.venv/Scripts/python -m pytest tests/test_generate_and_load.py -v`
    - Expected: 4 passed.
  - Run: `.venv/Scripts/python -m tools.synth.generate --config tools/synth/config.json --out data/synthetic`
    - Expected: exits 0; `data/synthetic/validation_report.md` shows no FAIL.
  - Run: `.venv/Scripts/python -m tools.synth.load --db database/electroforecast.db --real data/real/guimelco_residential_2020_2025.csv --synthetic data/synthetic`
    - Expected: exits 0.
  - Run: `.venv/Scripts/python -m pytest -q`
    - Expected: all tests pass, including Tasks 1–5.

- [ ] **Step 7: Commit (the CSVs are git-ignored).**

```bash
git add tools/synth database/schema.sqlite.sql database/schema.sql data/synthetic/validation_report.md tests
git commit -m "feat: add synth generator CLI, validation report, schema, and loader"
```

### Task 7: Monthly energy forecast and annual peak models (spec §5.1–5.2)

**Files:**
- Create: `tools/model/__init__.py`, `tools/model/forecast.py`
- Create: `tests/test_forecast.py`

**Interfaces:**
- Consumes: `Anchors`, `monthly_customers` (Tasks 1–2).
- Produces:
  - `CANDIDATES: dict[str, Callable[[pd.Series, pd.Series], FittedModel]]`, with keys `seasonal_naive, holt_winters_add, holt_winters_mul, sarima, regression`.
  - `FittedModel` protocol: `.predict(steps: int, exog_future: pd.Series | None) -> pd.DataFrame` with columns `forecast_mwh, lo80, hi80, lo95, hi95`.
  - `backtest(series: pd.Series, customers: pd.Series) -> pd.DataFrame` with columns `model_name, fold ("2024" | "2025"), mape, rmse`.
  - `select_model(bt: pd.DataFrame) -> tuple[str, bool]`, returning (model_name, beats_baseline).
  - `forecast_monthly(series, customers, model_name, start=(2026, 1), months=24) -> pd.DataFrame` with columns `year, month, forecast_mwh, lo80, hi80, lo95, hi95`.
  - `forecast_peak(anchors, monthly_fc: pd.DataFrame) -> pd.DataFrame` with columns `year, peak_mw, lo, hi`.

- [ ] **Step 1: Write the failing tests in `tests/test_forecast.py`.**

```python
def test_backtest_has_two_folds_per_model():
    bt = backtest(SERIES, CUSTOMERS)
    assert set(bt.fold) == {"2024", "2025"}
    assert set(bt.model_name) == set(CANDIDATES)
    assert (bt.mape > 0).all()

def test_select_model_falls_back_to_baseline():
    bt = pd.DataFrame({"model_name": ["seasonal_naive", "x"], "fold": ["2024", "2024"], "mape": [5.0, 6.0], "rmse": [1, 1]})
    assert select_model(bt) == ("seasonal_naive", False)

def test_forecast_shape_and_interval_order():
    fc = forecast_monthly(SERIES, CUSTOMERS, "holt_winters_add")
    assert len(fc) == 24 and (fc.year.iloc[0], fc.month.iloc[0]) == (2026, 1)
    assert (fc.lo95 <= fc.lo80).all() and (fc.lo80 <= fc.forecast_mwh).all()
    assert (fc.forecast_mwh <= fc.hi80).all() and (fc.hi80 <= fc.hi95).all()

def test_peak_formula():
    fc = pd.DataFrame({"year": [2026] * 12, "month": range(1, 13), "forecast_mwh": [4000.0] * 12,
                       "lo80": 0, "hi80": 0, "lo95": 0, "hi95": 0})
    p = forecast_peak(ANCHORS, fc).iloc[0]
    lfs = [sum(ANCHORS.monthly_mwh[(y, m)] for m in range(1, 13)) / (ANCHORS.peak_mw[y] * 8760) for y in ANCHORS.years]
    assert abs(p.peak_mw - 48000 / (np.mean(lfs) * 8760)) < 1e-6
    assert p.lo < p.peak_mw < p.hi
```

  `SERIES` is the 72 real months as a monthly `pd.Series` with a `PeriodIndex`. `CUSTOMERS` is aligned and comes from `monthly_customers`.

- [ ] **Step 2: Run the tests to confirm they fail.**
  - Run: `.venv/Scripts/python -m pytest tests/test_forecast.py -v`
  - Expected: FAIL (import errors).

- [ ] **Step 3: Implement `forecast.py`.**
  - **Holt-Winters:** `statsmodels.tsa.holtwinters.ExponentialSmoothing` with `trend="add"`, `seasonal="add"` or `"mul"`, `seasonal_periods=12`. Intervals come from `simulate(repetitions=1000)` quantiles with a fixed `random_state=42`.
  - **SARIMA:** fixed grid (p, d, q) ∈ {(1,1,0), (0,1,1)} × seasonal (0,1,1,12); keep the lowest-AIC order.
  - **Regression:** OLS with trend + month dummies + customers. Future customers are extrapolated linearly from the 2024→2025 growth.
  - **Seasonal naive:** the same month last year. Intervals use ± z × the std of residuals from the seasonal differences.
  - **Selection:** pick the lowest mean MAPE. If the winner is not `seasonal_naive` but does not beat `seasonal_naive`'s mean MAPE, return `("seasonal_naive", False)`. `beats_baseline` is True only when the selected model is not the baseline.
  - **Peak:** LF uses hours-in-year, so leap years are handled. The central value uses the mean LF; `lo` uses the max LF and `hi` uses the min LF.

- [ ] **Step 4: Run the tests to confirm they pass.**
  - Run: `.venv/Scripts/python -m pytest tests/test_forecast.py -v`
  - Expected: 4 passed.

- [ ] **Step 5: Commit.**

```bash
git add tools/model tests
git commit -m "feat: add monthly energy forecast backtest and annual peak model"
```

### Task 8: Demand classifier and explainability (spec §5.3–5.4)

**Files:**
- Create: `tools/model/demand.py`, `tools/model/explain.py`
- Create: `tests/test_demand.py`

**Interfaces:**
- Consumes: the `synth_daily_peaks` frame (Task 5 columns), `holidays` (Task 4), and the forecast functions (Task 7).
- Produces:
  - `FEATURES = ["month", "day_of_week", "is_holiday", "prev_day_peak", "mean_7d_peak"]`
  - `build_features(daily: DataFrame, cfg) -> DataFrame`: the feature columns, plus `date` and `demand_level`. The first 7 days are dropped.
  - `train_demand(features, test_year=2025) -> DemandResult`. `DemandResult` is a dataclass with fields:
    - `model_name: str`
    - `model`
    - `metrics: dict` (keys `accuracy, macro_f1, confusion_matrix, labels, baseline_accuracy, baseline_macro_f1`)
    - `predictions: DataFrame` (`date, predicted_level, p_high, p_medium, p_low, actual_level`; test year only)
  - `permutation_importance_table(result, features) -> DataFrame` with columns `feature, importance`
  - `forecast_breakdown(series, customers, model_name) -> DataFrame` with columns `year, month, trend, seasonality, customer_growth`

- [ ] **Step 1: Write the failing tests in `tests/test_demand.py`.**

```python
def test_features_have_no_lookahead():
    daily = pd.DataFrame({"date": pd.date_range("2025-01-01", periods=10), "peak_mw": range(10),
                          "demand_level": ["Low"] * 10, "year": 2025, "pct_of_annual_peak": 0.5})
    f = build_features(daily, CFG)
    row = f[f.date == pd.Timestamp("2025-01-09")].iloc[0]
    assert row.prev_day_peak == 7
    assert row.mean_7d_peak == np.mean([1, 2, 3, 4, 5, 6, 7])

def test_train_demand_reports_metrics_on_test_year_only():
    r = train_demand(build_features(SMALL_DAILY, CFG), test_year=2025)
    assert set(r.predictions.date.dt.year) == {2025}
    assert 0 <= r.metrics["macro_f1"] <= 1
    assert r.model_name in {"logistic_regression", "random_forest"}
    p = r.predictions[["p_high", "p_medium", "p_low"]].sum(1)
    assert np.allclose(p, 1)

def test_importance_covers_all_features():
    r = train_demand(build_features(SMALL_DAILY, CFG), test_year=2025)
    imp = permutation_importance_table(r, build_features(SMALL_DAILY, CFG))
    assert list(imp.sort_values("feature").feature) == sorted(FEATURES)
```

  `SMALL_DAILY` is the output of `daily_peaks` for the small config.

- [ ] **Step 2: Run the tests to confirm they fail.**
  - Run: `.venv/Scripts/python -m pytest tests/test_demand.py -v`
  - Expected: FAIL (import errors).

- [ ] **Step 3: Implement `demand.py` and `explain.py`.**
  - **Features:** `prev_day_peak = peak.shift(1)`; `mean_7d_peak = peak.shift(1).rolling(7).mean()`.
  - **Models:**
    - `LogisticRegression(max_iter=1000)` in a pipeline with `StandardScaler`.
    - `RandomForestClassifier(n_estimators=300, random_state=42)`.
  - **Selection:** keep the model with the higher macro-F1 on the test year. Report the logistic model's scores as `baseline_*`.
  - **Importance:** `sklearn.inspection.permutation_importance(n_repeats=10, random_state=42)` on the test year.
  - **Breakdown:** Holt-Winters components (level+trend → `trend`, season → `seasonality`, `customer_growth` = 0) or regression term contributions, depending on `model_name`. For `seasonal_naive`, use `statsmodels.tsa.seasonal.STL` on the history to split trend and seasonality.

- [ ] **Step 4: Run the tests to confirm they pass.**
  - Run: `.venv/Scripts/python -m pytest tests/test_demand.py -v`
  - Expected: 3 passed.

- [ ] **Step 5: Commit.**

```bash
git add tools/model tests
git commit -m "feat: add demand classifier, permutation importance, forecast breakdown"
```

### Task 9: Training CLI and result storage (spec §5.5)

**Files:**
- Create: `tools/model/train.py`, `tools/model/store.py`
- Modify: `database/schema.sqlite.sql`, `database/schema.sql` (model tables)
- Create: `tests/test_train.py`
- Create, generated and committed: `reports/metrics.json`, `reports/*.png`

**Interfaces:**
- Consumes: the Task 6 tables in the DB and the Task 7–8 functions.
- Produces:
  - Tables:
    - `model_runs(run_id INTEGER PK AUTOINCREMENT, task TEXT CHECK(task IN ('monthly_energy','annual_peak','demand_class')), model_name, dataset_version, trained_at, metrics TEXT (JSON), is_active INTEGER)`
    - `forecast_monthly`, `forecast_annual_peak`, `demand_predictions`, `feature_importance`, with columns per spec §5.5, each keyed by `run_id`.
    - `feature_importance` adds `kind TEXT ('permutation' | 'breakdown')`, plus nullable `year, month` for breakdown rows: the `trend`, `seasonality`, and `customer_growth` values for each forecast month.
  - `train(db_path: Path, models_dir: Path, reports_dir: Path, dataset_version: str = "synth-v1-seed42") -> dict[str, int]`, which returns `{task: run_id}`.
  - `MissingDataError(Exception)`
  - CLI: `python -m tools.model.train --db database/electroforecast.db --models-dir models --reports-dir reports`

- [ ] **Step 1: Write the failing tests in `tests/test_train.py`.**

```python
def test_train_writes_one_active_run_per_task(loaded_small_db, tmp_path):
    train(loaded_small_db, tmp_path / "m", tmp_path / "r")
    train(loaded_small_db, tmp_path / "m", tmp_path / "r")
    con = sqlite3.connect(loaded_small_db)
    active = con.execute("select task, count(*) from model_runs where is_active=1 group by task").fetchall()
    assert dict(active) == {"monthly_energy": 1, "annual_peak": 1, "demand_class": 1}
    assert con.execute("select count(*) from model_runs").fetchone()[0] == 6
    assert con.execute("select count(*) from forecast_monthly f join model_runs r using(run_id) where r.is_active=1").fetchone()[0] == 24
    assert (tmp_path / "r" / "metrics.json").exists()

def test_train_on_empty_db_raises_clear_error(tmp_path):
    with pytest.raises(MissingDataError, match="utility_monthly_energy"):
        train(tmp_path / "empty.db", tmp_path / "m", tmp_path / "r")
```

  The fixture `loaded_small_db` goes in `tests/conftest.py`: it runs `generate(SMALL_CFG)` and `load()` into `tmp_path`. Real utility tables always contain all 72 months.

- [ ] **Step 2: Run the tests to confirm they fail.**
  - Run: `.venv/Scripts/python -m pytest tests/test_train.py -v`
  - Expected: FAIL (import errors).

- [ ] **Step 3: Implement `store.py` and `train.py`.**
  - **Before training:** check that `utility_monthly_energy` has 72 rows and `synth_daily_peaks` has rows for `dataset_version`. Otherwise raise `MissingDataError` naming the table and the command that fills it.
  - **Storage:** each task's insert plus the activation (`UPDATE model_runs SET is_active=0 WHERE task=?`, then set the new run to 1) runs in one transaction.
  - **Files:**
    - `models/<task>-<run_id>.joblib`
    - `reports/metrics.json` (all three tasks + backtest table + `beats_baseline`)
    - `reports/forecast_backtest_2024.png`, `reports/forecast_backtest_2025.png`, `reports/demand_confusion_matrix.png`, `reports/feature_importance.png` (matplotlib, Agg backend)
  - **CLI:** on `MissingDataError`, print the message and exit 2. On success, print a results table: task, model, key metric, beats baseline.

- [ ] **Step 4: Run the tests, then the real training.**
  - Run: `.venv/Scripts/python -m pytest tests/test_train.py -v`
    - Expected: 2 passed.
  - Run: `.venv/Scripts/python -m tools.model.train --db database/electroforecast.db --models-dir models --reports-dir reports`
    - Expected: exits 0, prints 3 rows, writes the `reports/` files.

- [ ] **Step 5: Commit.**

```bash
git add tools/model database/schema.sqlite.sql database/schema.sql reports tests
git commit -m "feat: add training CLI with model run storage and reports"
```

### Task 10: Read-only API endpoints (spec §6)

**Files:**
- Modify: `app.py` (`DATABASE_PATH` env override near line 20; new routes placed before the `@app.get("/")` root route at ~line 2186)
- Create: `tests/test_api.py`; extend `tests/conftest.py`

**Interfaces:**
- Consumes: the Task 9 tables. Response shapes are fixed here and consumed by Task 11.
- Produces:
  - **DB override:** `DATABASE_PATH = Path(os.environ.get("ELECTROFORECAST_DB", ROOT / "database" / "electroforecast.db"))`
  - **Routes**, all `@require_auth()`:
    - `GET /api/models/active` →
      `{"runs": [{"task", "run_id", "model_name", "dataset_version", "trained_at", "metrics", "data_source"}]}`
    - `GET /api/forecast/monthly` →
      `{"data_source": "real", "model": run, "history": [{"year", "month", "energy_mwh"}], "forecast": [{"year", "month", "forecast_mwh", "lo80", "hi80", "lo95", "hi95"}]}`
    - `GET /api/forecast/peak` →
      `{"data_source": "real", "model": run, "history": [{"year", "peak_mw"}], "forecast": [{"year", "peak_mw", "lo", "hi"}]}`
    - `GET /api/demand/daily?from=YYYY-MM-DD&to=YYYY-MM-DD` →
      `{"data_source": "synthetic", "dataset_version", "model": run, "days": [{"date", "peak_mw", "actual_level", "predicted_level", "p_high", "p_medium", "p_low"}]}`
      - Days come from `synth_daily_peaks`, left-joined to the active run's predictions; prediction fields are `null` when absent.
      - Defaults: the last 30 days of available data.
    - `GET /api/explain` →
      `{"classifier": {"data_source": "synthetic", "model": run, "importance": [{"feature", "importance"}]}, "forecast": {"data_source": "real", "model": run, "breakdown": [{"year", "month", "trend", "seasonality", "customer_growth"}]}}`
  - **Errors:**
    - No active run for the task → `404 {"error": "No trained model yet"}`.
    - Bad date format or `from` > `to` → `400`.

- [ ] **Step 1: Write the failing tests in `tests/test_api.py`.**

```python
def test_requires_login(client):
    assert client.get("/api/forecast/monthly").status_code == 401

def test_no_model_returns_404(client_logged_in_empty):
    r = client_logged_in_empty.get("/api/forecast/monthly")
    assert r.status_code == 404 and r.json["error"] == "No trained model yet"

def test_monthly_forecast_shape(client_logged_in_trained):
    j = client_logged_in_trained.get("/api/forecast/monthly").json
    assert j["data_source"] == "real" and len(j["history"]) == 72 and len(j["forecast"]) == 24

def test_demand_daily_defaults_and_validation(client_logged_in_trained):
    j = client_logged_in_trained.get("/api/demand/daily").json
    assert j["data_source"] == "synthetic" and len(j["days"]) == 30 and j["dataset_version"]
    assert client_logged_in_trained.get("/api/demand/daily?from=2025-02-01&to=2025-01-01").status_code == 400
    assert client_logged_in_trained.get("/api/demand/daily?from=yesterday").status_code == 400

def test_explain_has_both_sources(client_logged_in_trained):
    j = client_logged_in_trained.get("/api/explain").json
    assert j["classifier"]["data_source"] == "synthetic" and j["forecast"]["data_source"] == "real"
```

  **Fixtures (conftest):**
  - Set `ELECTROFORECAST_DB` to a temp path *before* importing `app`; use `importlib` and pop `sys.modules["app"]`.
  - Log in with the demo household credentials from `README.md` via `/api/auth/login`.
  - The `_trained` variant runs `load` + `train` into that same DB first.

- [ ] **Step 2: Run the tests to confirm they fail.**
  - Run: `.venv/Scripts/python -m pytest tests/test_api.py -v`
  - Expected: FAIL (404s on the new routes).

- [ ] **Step 3: Implement the override and routes in `app.py`.**
  - Follow the existing style: `with get_db() as db:`, `jsonify(...)`, parameterized SQL.
  - Add one helper, `active_run(db, task) -> dict | None`, which parses `metrics` JSON.
  - `initialize_database()` must not fail when the new tables are absent: the schema is executed there already, so the new DDL creates them empty.

- [ ] **Step 4: Run the full suite.**
  - Run: `.venv/Scripts/python -m pytest -q`
  - Expected: all pass.

- [ ] **Step 5: Commit.**

```bash
git add app.py tests
git commit -m "feat: add read-only forecast, demand, explain, and model APIs"
```

### Task 11: Wire the three pages to the API (spec §7) and document the workflow

**Files:**
- Create: `assets/js/analytics.js`
- Modify: `forecasting.html` (inline script lines ~99–114 and the summary table ~60–75), `demand-classification.html` (~117–137), `explainable-ai.html` (static bars and the inline mount at ~76)
- Modify: `assets/css/style.css` (badge/model-card classes), `README.md`

**Interfaces:**
- Consumes: the Task 10 response shapes, `ElectroAPI.request`, `ElectroAPI.escapeHTML`, `ElectroAPI.formatDate`, `ElectroShell.mount`, and `window.Chart` (ChartLite: `line`/`bar`/`doughnut`, plus a `fill:'+1'` band between datasets).
- Produces (on `window.ElectroAnalytics`):
  - `dataBadge(source: "real" | "synthetic") -> string` (HTML). Copy: `"Real GUIMELCO data"` / `"Synthetic"`.
  - `modelCard(run, metricLabel: string, metricValue: string) -> string` (HTML): model name, trained date, metric.
  - `emptyState(container: Element) -> void`: renders `"No trained model yet"` and a hint to run `python -m tools.model.train`.

- [ ] **Step 1: Implement `assets/js/analytics.js`.**
  - Escape every dynamic string with `ElectroAPI.escapeHTML`.
  - Add CSS classes `.data-badge.real`, `.data-badge.synthetic`, and `.model-card` in `style.css`, following existing badge colors.

- [ ] **Step 2: Rewrite the `forecasting.html` script.**
  - Fetch `/api/forecast/monthly` and `/api/forecast/peak`.
  - Chart: the last 24 history months as Actual; 24 forecast months as Forecast with an Upper/Lower 80% band.
  - The summary table shows the first 12 forecast months with columns `Month, Forecast (MWh), Lower 80%, Upper 80%`.
  - A model card shows mean backtest MAPE; a badge says Real.
  - A peak card shows the 2026 and 2027 peak MW with ranges.
  - On a 404 → `emptyState`.
  - Remove all hard-coded arrays and rows.

- [ ] **Step 3: Rewrite the `demand-classification.html` script.**
  - Fetch `/api/demand/daily` with default range plus `/api/models/active`.
  - Bar chart of daily peak MW, colored by `predicted_level` (`actual_level` when the prediction is null).
  - Doughnut of predicted-level shares over the range.
  - The table shows date, level, top probability %, and a recommendation chosen by level:
    - High: "Shift heavy appliance use outside 13:00–21:00"
    - Medium: "Monitor usage during evening hours"
    - Low: "Normal usage"
  - A model card shows macro-F1; a badge says Synthetic.
  - On a 404 → `emptyState`.

- [ ] **Step 4: Rewrite the `explainable-ai.html` content.**
  - Fetch `/api/explain`.
  - Bars: classifier importance sorted descending, with width = importance ÷ max × 100%.
  - A line or stacked view of the forecast breakdown (trend / seasonality / customer growth) for the forecast months.
  - Separate badges per section. On a 404 → `emptyState`.

- [ ] **Step 5: Verify in the browser.**
  - Run: `powershell -ExecutionPolicy Bypass -File .\start-app.ps1`
  - Sign in at `http://127.0.0.1:4173/login.html` as the demo household. Open the three pages.
  - Expected:
    - charts render from API data;
    - badges and model cards are visible;
    - no console errors;
    - each page's Network tab shows the new `/api/...` calls returning 200.
  - Then temporarily point `ELECTROFORECAST_DB` at an empty DB and reload. Expected: "No trained model yet" on all three pages.

- [ ] **Step 6: Document the workflow in `README.md`.**
  - Add a **Forecasting data and models** section with:
    - the three commands (generate, load, train);
    - that synthetic data is anchored to `Residential.pdf`;
    - where `validation_report.md` and `reports/` live;
    - the 2023 discrepancy and the open items from spec §10.

- [ ] **Step 7: Commit.**

```bash
git add assets forecasting.html demand-classification.html explainable-ai.html README.md
git commit -m "feat: drive forecasting, demand, and XAI pages from trained model APIs"
```
