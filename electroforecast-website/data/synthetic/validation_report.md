# Synthetic data validation report

Dataset version: `synth-v1-seed42`  
Years: 2020-2025

## Checks

| Status | Check | Actual | Tolerance |
|---|---|---|---|
| PASS | household energy vs sheet MWh, max relative error | 1.62235e-05 | 0.0001 |
| PASS | system hourly MWh vs sheet MWh, max relative error | 4.0113e-16 | 0.0001 |
| PASS | annual peak vs sheet 2020 (MW) | 1.77636e-15 | 0.01 |
| PASS | annual peak vs sheet 2021 (MW) | 1.77636e-15 | 0.01 |
| PASS | annual peak vs sheet 2022 (MW) | 1.77636e-15 | 0.01 |
| PASS | annual peak vs sheet 2023 (MW) | 1.77636e-15 | 0.01 |
| PASS | annual peak vs sheet 2024 (MW) | 1.77636e-15 | 0.01 |
| PASS | annual peak vs sheet 2025 (MW) | 3.55271e-15 | 0.01 |
| PASS | customer counts vs monthly_customers, mismatched months | 0 | 0 |
| PASS | feeder sum vs system, max hourly diff (MW) | 3.55271e-15 | 0.001 |
| PASS | negative or NaN numeric values, all tables | 0 | 0 |

## Per-year summary

| Year | Synthetic MWh | Peak MW | Load factor | kWh/customer/month | Min scale | Max scale |
|---|---|---|---|---|---|---|
| 2020 | 30296.0 | 8.44 | 0.409 | 78.5 | 0.703 | 0.841 |
| 2021 | 31930.0 | 9.09 | 0.401 | 80.0 | 0.728 | 0.865 |
| 2022 | 35205.0 | 11.06 | 0.363 | 85.3 | 0.769 | 0.915 |
| 2023 | 38689.0 | 11.02 | 0.401 | 89.8 | 0.754 | 0.968 |
| 2024 | 42855.0 | 12.89 | 0.378 | 95.6 | 0.874 | 1.017 |
| 2025 | 45433.0 | 12.93 | 0.401 | 97.5 | 0.853 | 1.045 |

## Scale-factor warnings

None.

## Limitations

- Household type mix: the sampled households' types are drawn from the final config year's mix and stay fixed for all years. Year-to-year growth in kWh/customer comes from the monthly scale factor, not from a changing mix of household types.
- Only monthly energy and the annual peak are real (the utility sheet); hourly, daily, feeder, transformer and household values are synthetic reconstructions.

## Notes

- Monthly sum 38689 differs from printed total 38369; monthly values used.
