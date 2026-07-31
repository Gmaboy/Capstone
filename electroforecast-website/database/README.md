# ElectroForecast database

The working local application uses `electroforecast.db`, created automatically
from `schema.sqlite.sql` when `app.py` starts. SQLite keeps the capstone demo
self-contained and requires no database service.

`schema.sql` remains the MySQL/MariaDB production reference required by the
paper. Both schemas model:

- role-based users and participating households;
- appliance-rating contributions (`appliances`);
- household load-profile inventory (`household_appliances`);
- reusable administrator-approved appliance catalog records;
- monthly electricity consumption;
- administrator validation and reviewer notes;
- notifications and an audit trail.

Only approved appliance and consumption contributions are considered
forecast-ready. Appliance contributions are independent from household
inventory: deleting an inventory row never deletes its source contribution.

`household_appliances` contains the records counted by Registered Appliances
and Estimated Daily Load. A manually entered appliance is first stored as a
pending contribution and is excluded from this table. After approval, the
household can explicitly add it to My Appliances. The approved name, brand,
model, category, wattage, and evidence source are copied as a snapshot, while
quantity and average hours per day remain household-specific and can be edited
without another administrator review.

Demo accounts:

- Administrator: `admin@electroforecast.local` / `Admin123!`
- Household: `household@electroforecast.local` / `Household123!`
