# GUIMPOWERCORE crowdsourcing platform

This project now runs as a Flask application with a persistent SQLite database,
role-based access, a household crowdsourcing portal, and an administrator
validation dashboard.

## Start the application

From PowerShell:

```powershell
cd "C:\Users\Greence Mark\Capstone\electroforecast-website"
powershell -ExecutionPolicy Bypass -File .\start-app.ps1
```

Open `http://127.0.0.1:4173/login.html`.

The first launch creates `database/electroforecast.db` automatically and seeds
representative capstone data.

## Demo accounts

- Household: `household@electroforecast.local` / `Household123!`
- Administrator: `admin@electroforecast.local` / `Admin123!`

New households can create their own account from `signup.html` or the
**Create a household account** link on the sign-in page. Registration creates
both the role-restricted user account and its Guimaras household profile, then
signs the household in automatically.

The registration form loads the five Guimaras municipalities and their 98
barangays from the built-in PSA PSGC-aligned location registry. Selecting a
municipality filters the Barangay field to that municipality, and the API
rejects municipality/barangay combinations that do not match.

## Implemented workflow

1. **My Submissions** stores a household's appliance-rating contributions. A
   contribution remains in this history even when its household inventory item
   is removed.
2. **My Appliances** stores only the appliances the household currently wants
   in its load profile. Registered Appliances and Estimated Daily Load are
   calculated from this inventory only.
3. Removing an inventory item moves it to **Recently Deleted**. It is excluded
   from the household load and does not return to Submitted Appliances. The
   household can restore it later, or select one or multiple deleted items and
   delete them permanently.
4. Selecting an administrator-approved rating reuses its technical details. The
   household personalizes only quantity and average hours per day, without
   another administrator review.
5. Entering a new appliance creates a pending contribution below the Household
   Appliance List. Pending contributions do not count toward inventory or load.
6. After an administrator approves a new contribution, the household decides
   whether to add it to My Appliances. Approval by itself does not add it.
7. **Monthly Consumption** has its own page and CRUD workflow, separate from the
   My Energy Portal summary. Removed records first move to **Recently Deleted**,
   where one or multiple records can be restored or deleted permanently. New
   and resubmitted records require a private JPG, PNG, or WebP bill picture.
8. **Reviewer Notes** appear in My Submissions through a message icon beside
   the status. New administrator feedback is highlighted until the household
   opens it, and the read state is stored in the database.
9. Only approved contributions count toward forecast data readiness. Every
   create, update, delete, approval, rejection, and user-status change is
   written to the audit trail.

Database details are documented in `database/README.md`. `schema.sqlite.sql` is
the working local schema and `schema.sql` is the MySQL/MariaDB production
reference.

## Forecasting data and models

The Forecasting, Demand Classification, and Explainable AI pages read trained
model results from the database. Install the development dependencies first:

```powershell
pip install -r requirements-dev.txt
```

Then generate the synthetic data, load it, and train the models:

```powershell
python -m tools.synth.generate --config tools/synth/config.json --out data/synthetic
python -m tools.synth.load --db database/electroforecast.db --real data/real/guimelco_residential_2020_2025.csv --synthetic data/synthetic
python -m tools.model.train --db database/electroforecast.db --models-dir models --reports-dir reports
```

Until `tools.model.train` has run, the three pages show "No trained model yet".

- The synthetic data is anchored to GUIMELCO's `Residential.pdf`. The monthly
  energy and annual peak forecasts use real GUIMELCO data; the demand
  classifier is trained on synthetic data and is labelled "Synthetic" in the UI.
- The synthetic data validation report is `data/synthetic/validation_report.md`.
  Model reports and charts are written to `reports/`.
- Known discrepancy: the 2023 monthly values sum to 38,689 while the printed
  2023 total is 38,369. The monthly values are used.

Open items to confirm:

1. The correct 2023 total (38,689 from the months versus 38,369 printed).
2. Whether the customer counts are year-end or average counts.
3. Household appliance values are mostly estimates.

