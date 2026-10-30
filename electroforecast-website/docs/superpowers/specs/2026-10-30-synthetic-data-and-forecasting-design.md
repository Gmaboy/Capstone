# Synthetic Stand-in Data and Forecasting Models — Design

- **Date:** 2026-10-30
- **Status:** Draft for review
- **Branch:** `feature/synthetic-data-forecasting`

## 1. Purpose and context

GUIMELCO provided one signed sheet, *Historical Residential Electricity
Consumption and Peak Demand* (`Residential.pdf`), with residential-class
aggregates for 2020–2025. It did not provide the granular data a forecasting
system needs:

1. household-level consumption records
2. peak demand below annual resolution
3. consumer counts by area
4. transformer / feeder load data
5. anonymized load profiles

The Forecasting, Demand Classification, and Explainable AI pages currently
show hard-coded numbers (e.g. `forecasting.html` chart arrays). No model
exists.

This design:

- builds **temporary synthetic stand-ins** for all five missing datasets,
  anchored so that every aggregate reproduces the real sheet;
- trains real models whose results drive the three pages.

### Success criteria

- Every synthetic dataset, when aggregated, matches the sheet within the
  tolerances in §4.8. The generator fails loudly otherwise.
- The monthly energy forecast is trained and evaluated on **real** data and
  beats a seasonal-naive baseline on held-out years.
- Every page and table clearly distinguishes **Real GUIMELCO data** from
  **Synthetic** data.
- The pages show model output from the database, not hard-coded arrays.
- Regeneration is deterministic: same config + seed → identical output.

### Non-goals

- Replacing synthetic data with real utility data (future; the table shapes
  are designed so this is a data swap, not a redesign).
- Recalibrating household types from crowdsourced approvals (future work;
  see §4.2).
- Supabase / Vercel migration.
- Touching the existing crowdsourcing tables or flows.

## 2. Real anchor data

Transcribed from the sheet (MWh per month; customers; coincident peak MW).

| Year | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec | Total (printed) | Customers | Peak MW |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2020 | 2,367 | 2,175 | 2,197 | 2,796 | 2,757 | 2,794 | 2,554 | 2,571 | 2,630 | 2,479 | 2,504 | 2,472 | 30,296 | 32,667 | 8.44 |
| 2021 | 2,513 | 2,386 | 2,407 | 2,805 | 2,858 | 2,873 | 2,656 | 2,825 | 2,663 | 2,633 | 2,825 | 2,486 | 31,931 | 33,745 | 9.09 |
| 2022 | 2,514 | 2,755 | 2,616 | 2,981 | 3,262 | 3,237 | 2,953 | 3,000 | 3,099 | 2,891 | 2,976 | 2,921 | 35,205 | 34,930 | 11.06 |
| 2023 | 2,897 | 2,757 | 2,619 | 3,447 | 3,521 | 3,407 | 3,222 | 3,366 | 3,323 | 3,271 | 3,486 | 3,373 | 38,369 | 36,712 | 11.02 |
| 2024 | 3,432 | 3,161 | 3,172 | 4,089 | 4,292 | 3,844 | 3,401 | 3,683 | 3,353 | 3,403 | 3,544 | 3,481 | 42,856 | 37,916 | 12.89 |
| 2025 | 3,683 | 3,534 | 3,217 | 4,137 | 4,186 | 4,115 | 3,749 | 3,906 | 3,743 | 3,719 | 3,658 | 3,786 | 45,431 | 39,618 | 12.93 |

### Known discrepancy

2023 monthly values sum to **38,689 MWh**; the printed total is **38,369**
(−320). Other years differ by 0–2 MWh (rounding). Until GUIMELCO confirms:

- **monthly values are the source of truth**;
- the printed total is kept in `utility_annual_stats.total_mwh_reported`;
- the discrepancy is recorded in its `notes` column.

### Assumptions

- Monthly values are in MWh (confirmed: 2020 months sum to the printed
  30,296 MWh).
- Customer counts are **year-end** figures. Monthly counts are linearly
  interpolated from the previous year-end. January 2020 is back-extrapolated
  from the 2020→2021 growth. This is a config value.
- Coincident peak is the annual maximum hourly residential load.

## 3. Architecture

Three layers.

### 3.1 Real layer (never modified by code)

- `data/real/guimelco_residential_2020_2025.csv`: transcription of the sheet,
  with source file name and received date in a header comment.
- `utility_monthly_energy` (year, month, energy_mwh, source) — 72 rows.
- `utility_annual_stats` (year, total_mwh_reported, customers,
  coincident_peak_mw, notes) — 6 rows.

### 3.2 Generator (offline tool, not part of the web app)

- `tools/synth/generate.py`:
  - reads the real CSV and `tools/synth/config.json`;
  - writes CSVs to `data/synthetic/`;
  - writes `data/synthetic/validation_report.md`.
- `tools/synth/config.json`: seed, customer-count convention, municipality
  shares, feeder layout, demand-label thresholds, noise levels.
- `tools/synth/household_types.json`: household types and appliance
  definitions (§4.2).
- `tools/synth/load.py`: loads the CSVs into SQLite, replacing rows with the
  same `dataset_version`.
- Dev-only dependencies go in `requirements-dev.txt`. `requirements.txt`
  stays Flask-only.
- The web app never generates or seeds synthetic data at startup.

### 3.3 Synthetic tables

Every table has `dataset_version` (e.g. `synth-v1-seed42`).

| Table | Stand-in for | Approx. rows |
|---|---|---|
| `synth_feeders` | feeder layout | 12 |
| `synth_transformers` | distribution transformers | ~100 |
| `synth_households` | 2,000-household weighted sample | 2,000 |
| `synth_household_monthly` | consumption records (incl. weight) | ~144,000 |
| `synth_customer_counts` | customers by month × barangay | ~7,000 |
| `synth_load_profiles` | anonymized profiles: type × month × daytype × hour | ~2,900 |
| `synth_system_hourly` | system load, MW | 52,560 |
| `synth_feeder_hourly` | feeder load, MW | ~630,000 |
| `synth_transformer_monthly_peak` | transformer monthly peak kVA and utilization | ~7,200 |
| `synth_daily_peaks` | daily peak MW and demand label | ~2,190 |

Table DDL is added to `database/schema.sqlite.sql` and mirrored in
`database/schema.sql` (MySQL reference).

## 4. Generation method (hybrid top-down)

Totals come top-down from the sheet. Household types decide how those totals
are distributed between households and across hours.

### 4.1 Customer counts by barangay

1. Monthly customers come from the year-end counts (§2 assumptions).
2. Split across the 5 municipalities using PSA 2020 Census population
   shares, stored in config with source citation.
3. Split within each municipality across its barangays, using the same
   98-barangay registry as `app.py`. Barangay weights are population-based
   where PSA barangay data is available; otherwise they are equal, with the
   choice recorded in config.
4. Integer rounding uses the largest-remainder method so every month's total
   is exact.

### 4.2 Household types

Defined in `tools/synth/household_types.json`, **not** from the app's
appliance catalog (which currently holds demo data). Initial types:

- **Basic:** lighting, fan, TV, phone charging
- **Standard:** Basic plus refrigerator and rice cooker
- **Aircon:** Standard plus one aircon unit
- **Home business:** Standard plus chest freezer (sari-sari store)
- **Low-occupancy:** vacant / OFW homes

Each appliance entry has wattage, quantity, hours/day, and a `source` field.
Sources are published references, each checked before use:

- DOE Philippines appliance energy labels and guides (wattage)
- PSA Household Energy Consumption Survey (ownership rates)
- utility appliance calculators (usage hours)

Values that cannot be verified are marked `"source": "estimate"`.

The type mix shifts year by year, toward more Standard and Aircon homes. The
mix is calibrated so the weighted mean kWh/customer/month matches the sheet:
77.3 (2020) → 95.6 (2025).

**Future work (out of scope):** a script that recalibrates this file from
administrator-approved crowdsourced appliances.

### 4.3 Household sample and monthly consumption

- 2,000 households, stratified by barangay in proportion to customer counts.
- Each household is assigned a type, a household size, and a transformer.
- Weight per household-month = barangay customers that month ÷ sampled
  households in that barangay.
- Raw kWh = type baseline × type seasonal factor(month) × size factor ×
  lognormal noise (σ from config).
- One scale factor per month makes Σ(weight × kWh) equal the sheet's monthly
  MWh × 1000.
- Values are stored to 0.1 kWh.

### 4.4 Load profiles

- A normalized 24-hour shape per type × month × daytype (weekday / weekend).
  Each day's shape sums to 1.
- Examples:
  - Aircon homes peak in the afternoon and early evening, strongest April–June.
  - Basic homes peak 18:00–21:00.
- These shapes are published as `synth_load_profiles`, the anonymized load
  profiles.

### 4.5 System hourly load

1. Split monthly energy into days using:
   - weekday/weekend factors;
   - Philippine holidays (fixed list in config, incl. Holy Week and Christmas);
   - bounded day-to-day noise.
2. Split each day into hours with the customer-weighted blend of type shapes
   for that month.
3. **Peak calibration:** for each year, apply a within-day power transform to
   the hourly shape (sharpen or flatten while preserving daily energy). The
   exponent is found by bisection so the annual maximum hour equals the
   sheet's peak MW.
4. With energy and peak both fixed, load factor (≈0.36–0.41) follows
   automatically.

### 4.6 Feeders and transformers

- **Layout:** 5 substation zones (one per municipality). Feeders: Buenavista
  3, Jordan 3, Nueva Valencia 2, San Lorenzo 2, Sibunag 2 (12 total). Each
  feeder serves a set of barangays; ~100 transformers serve barangay clusters.
- All names are synthetic and marked as such; real names can replace them
  later.
- **Feeder hourly load** = Σ over its households of weight × monthly kWh ×
  type shape. It is rescaled every hour so Σ feeders = system load.
- **Transformer kVA ratings** are chosen so most run at 50–90% utilization at
  peak, with a few at 90–110% to exercise overload warnings.
- Only the monthly peak is stored per transformer.

### 4.7 Daily peaks and demand labels

- Daily peak MW comes from system hourly load.
- Labels are relative to that year's peak (thresholds in config):
  - **High:** ≥ 90%
  - **Medium:** 75–90%
  - **Low:** < 75%

### 4.8 Validation (generator fails if any check fails)

| Check | Tolerance |
|---|---|
| Σ weighted household kWh per month vs sheet monthly MWh | ≤ 0.01% |
| Σ system hourly MWh per month vs sheet monthly MWh | ≤ 0.01% |
| Annual max system hour vs sheet peak MW | ≤ 0.01 MW |
| Σ customer counts per month vs interpolated total | exact |
| Σ feeder load vs system load, every hour | ≤ 0.001 MW |
| Any negative or NaN value | none allowed |

`validation_report.md` lists:

- every check with its actual value;
- derived load factor and kWh/customer/month per year;
- the 2023 discrepancy note.

## 5. Models

Training is offline. The web app only reads stored results.

### 5.1 Monthly residential energy forecast (real data)

- **Data:** 72 real monthly values plus monthly customer counts.
- **Candidates** (`statsmodels`):
  - seasonal naive (baseline)
  - Holt-Winters (additive and multiplicative)
  - SARIMA (small, fixed grid)
  - linear regression on trend + month dummies + customers
- **Evaluation:** rolling origin.
  - Fold 1: train 2020–2023, test 2024.
  - Fold 2: train 2020–2024, test 2025.
  - Metrics: MAPE and RMSE per fold, plus the mean.
- **Selection:** lowest mean MAPE. The selected model must beat seasonal
  naive; if none does, the baseline is reported as selected and the report
  says so.
- **Output:** monthly forecast for 2026–2027 with 80% and 95% intervals,
  refit on all 72 months.
- **Reported caveat:** 2020–2021 includes COVID-19 effects.

### 5.2 Annual peak forecast

Six real annual points are too few to train a model.

- Peak MW = forecast annual MWh ÷ (LF × 8.76).
- Central LF = mean of 2020–2025 real load factors.
- The interval spans the min–max real LF (0.363–0.410).

### 5.3 Daily demand classification (synthetic data)

- **Inputs:** month, day of week, holiday flag, previous-day peak, 7-day mean
  peak.
- **Models** (`scikit-learn`): logistic regression (baseline) and random
  forest.
- **Split:** train on synthetic 2020–2024, test on synthetic 2025.
- **Metrics:** accuracy, macro-F1, confusion matrix.
- Labeled **"trained on synthetic data"** wherever shown.

### 5.4 Explainability

- **Classifier:** permutation importance on the 2025 test set.
- **Monthly forecast:** additive breakdown of the forecast into trend,
  seasonality, and customer-growth contributions (from the selected model's
  components or regression terms).

### 5.5 Storage

**Tables:**

- `model_runs`: run_id, model_name, task, dataset_version, trained_at,
  metrics (JSON), is_active
- `forecast_monthly`: run_id, year, month, forecast_mwh, lo80, hi80, lo95,
  hi95
- `forecast_annual_peak`: run_id, year, peak_mw, lo, hi
- `demand_predictions`: run_id, date, predicted_level, p_high, p_medium,
  p_low, actual_level
- `feature_importance`: run_id, feature, importance

**Files:**

- `models/*.joblib`
- `reports/metrics.json`
- `reports/*.png` (actual vs predicted per fold, confusion matrix,
  importance)

**Command:** `python tools/model/train.py`

- trains all models;
- prints a results table;
- writes the tables and files above;
- marks the new runs active.

## 6. API (read-only)

Same authentication model as the existing pages: any signed-in active user,
matching the roles in `shell.js`.

| Endpoint | Returns |
|---|---|
| `GET /api/forecast/monthly` | real history + active forecast with intervals |
| `GET /api/forecast/peak` | real annual peaks + forecast peaks |
| `GET /api/demand/daily?from=&to=` | synthetic daily peaks, labels, predictions |
| `GET /api/explain` | feature importance + forecast breakdown |
| `GET /api/models/active` | active run metadata and metrics |

Error handling:

- No active run → `404` with `{"error": "No trained model yet"}`.
- Bad dates → `400`.

Every payload includes `data_source`: `"real"` or `"synthetic"`, plus
`dataset_version`.

## 7. Pages

- `forecasting.html`, `demand-classification.html`, and `explainable-ai.html`
  fetch the APIs above. All hard-coded arrays are removed.
- Each page shows:
  - a **model card**: model name, trained date, test MAPE or accuracy;
  - a **data badge**: "Real GUIMELCO data" or "Synthetic".
- If no model exists, the page shows an empty state ("No trained model yet").
  It never falls back to fake numbers.
- User-supplied strings are rendered with the existing
  `ElectroAPI.escapeHTML`.

## 8. Testing (`pytest`)

- **Generator invariants:** all §4.8 checks, run on a reduced config
  (200 households, 1 year).
- **Determinism:** two runs with the same seed produce byte-identical CSVs.
- **Training:** `train.py` runs end-to-end on the reduced dataset and writes
  one active run per task.
- **API:** response shape, `data_source` present, `401` when signed out,
  `404` when no active run.
- **Real-data integrity:** the transcribed CSV's monthly values match §2.

## 9. Files touched

**New:**

- `data/real/`, `data/synthetic/`
- `tools/synth/`, `tools/model/`
- `models/`, `reports/`
- `tests/`
- `requirements-dev.txt`

**Modified:**

- `database/schema.sqlite.sql`, `database/schema.sql`
- `app.py` (new read-only endpoints only)
- the three page HTML files
- `README.md` (how to regenerate and retrain)

**Not modified:** crowdsourcing tables, routes, and pages.

**`.gitignore`:**

- `models/*.joblib` and `data/synthetic/*.csv` are regenerated, not
  committed.
- `data/real/` and `reports/` are committed.

## 10. Open items

- GUIMELCO to confirm the correct 2023 annual total.
- GUIMELCO to confirm whether customer counts are year-end or annual average.
- PSA 2020 municipality and barangay population figures to be entered in
  config with citations during implementation.
