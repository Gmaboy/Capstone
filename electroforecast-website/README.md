# ElectroForecast crowdsourcing platform

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

## Implemented workflow

1. **My Submissions** stores a household's appliance-rating contributions. A
   contribution remains in this history even when its household inventory item
   is removed.
2. **My Appliances** stores only the appliances the household currently wants
   in its load profile. Registered Appliances and Estimated Daily Load are
   calculated from this inventory only.
3. Selecting an administrator-approved rating reuses its technical details. The
   household personalizes only quantity and average hours per day, without
   another administrator review.
4. Entering a new appliance creates a pending contribution below the Household
   Appliance List. Pending contributions do not count toward inventory or load.
5. After an administrator approves a new contribution, the household decides
   whether to add it to My Appliances. Approval by itself does not add it.
6. **Monthly Consumption** has its own page and CRUD workflow, separate from the
   My Energy Portal summary.
7. Only approved contributions count toward forecast data readiness. Every
   create, update, delete, approval, rejection, and user-status change is
   written to the audit trail.

Database details are documented in `database/README.md`. `schema.sqlite.sql` is
the working local schema and `schema.sql` is the MySQL/MariaDB production
reference.
