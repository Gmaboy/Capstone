PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS roles (
  role_id INTEGER PRIMARY KEY AUTOINCREMENT,
  role_name TEXT NOT NULL UNIQUE CHECK (role_name IN ('admin','guimelco','researcher','household')),
  description TEXT
);

CREATE TABLE IF NOT EXISTS users (
  user_id INTEGER PRIMARY KEY AUTOINCREMENT,
  role_id INTEGER NOT NULL,
  full_name TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE COLLATE NOCASE,
  password_hash TEXT NOT NULL,
  contact_no TEXT,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','inactive')),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (role_id) REFERENCES roles(role_id)
);

CREATE TABLE IF NOT EXISTS user_settings (
  user_id INTEGER PRIMARY KEY,
  notify_high_demand INTEGER NOT NULL DEFAULT 1 CHECK (notify_high_demand IN (0, 1)),
  notify_rating_updates INTEGER NOT NULL DEFAULT 1 CHECK (notify_rating_updates IN (0, 1)),
  notify_weekly_summary INTEGER NOT NULL DEFAULT 0 CHECK (notify_weekly_summary IN (0, 1)),
  forecast_horizon TEXT NOT NULL DEFAULT '7_days' CHECK (forecast_horizon IN ('7_days', '14_days', '30_days')),
  forecast_granularity TEXT NOT NULL DEFAULT 'daily' CHECK (forecast_granularity IN ('daily', 'weekly', 'monthly')),
  measurement_unit TEXT NOT NULL DEFAULT 'kwh' CHECK (measurement_unit IN ('kwh', 'mwh')),
  landing_page TEXT NOT NULL DEFAULT 'role_default' CHECK (landing_page IN ('role_default', 'forecasting', 'demand_classification')),
  show_confidence_intervals INTEGER NOT NULL DEFAULT 1 CHECK (show_confidence_intervals IN (0, 1)),
  show_demand_gauge INTEGER NOT NULL DEFAULT 1 CHECK (show_demand_gauge IN (0, 1)),
  compact_table_view INTEGER NOT NULL DEFAULT 0 CHECK (compact_table_view IN (0, 1)),
  data_refresh_frequency TEXT NOT NULL DEFAULT 'daily' CHECK (data_refresh_frequency IN ('daily', 'weekly', 'manual')),
  default_file_format TEXT NOT NULL DEFAULT 'csv' CHECK (default_file_format IN ('csv', 'xlsx', 'json')),
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS households (
  household_id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL UNIQUE,
  barangay TEXT,
  municipality TEXT NOT NULL DEFAULT 'Jordan',
  province TEXT NOT NULL DEFAULT 'Guimaras',
  household_size INTEGER CHECK (household_size IS NULL OR household_size BETWEEN 1 AND 30),
  meter_number TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS appliance_categories (
  category_id INTEGER PRIMARY KEY AUTOINCREMENT,
  category_name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS appliances (
  appliance_id INTEGER PRIMARY KEY AUTOINCREMENT,
  household_id INTEGER NOT NULL,
  category_id INTEGER NOT NULL,
  appliance_name TEXT NOT NULL,
  brand TEXT,
  model TEXT,
  power_rating_watts REAL NOT NULL CHECK (power_rating_watts > 0 AND power_rating_watts <= 50000),
  quantity INTEGER NOT NULL DEFAULT 1 CHECK (quantity BETWEEN 1 AND 50),
  avg_daily_usage_hours REAL NOT NULL DEFAULT 0 CHECK (avg_daily_usage_hours >= 0 AND avg_daily_usage_hours <= 24),
  source_of_info TEXT NOT NULL DEFAULT 'nameplate_label'
    CHECK (source_of_info IN ('nameplate_label','user_manual','manual_estimate','retailer_specs')),
  copied_from_appliance_id INTEGER,
  verification_status TEXT NOT NULL DEFAULT 'pending'
    CHECK (verification_status IN ('pending','approved','rejected')),
  reviewer_notes TEXT,
  reviewer_notes_read_at TEXT,
  reviewed_by INTEGER,
  reviewed_at TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (household_id) REFERENCES households(household_id) ON DELETE CASCADE,
  FOREIGN KEY (category_id) REFERENCES appliance_categories(category_id),
  FOREIGN KEY (copied_from_appliance_id) REFERENCES appliances(appliance_id) ON DELETE SET NULL,
  FOREIGN KEY (reviewed_by) REFERENCES users(user_id)
);

CREATE INDEX IF NOT EXISTS idx_appliances_household ON appliances(household_id);
CREATE INDEX IF NOT EXISTS idx_appliances_status ON appliances(verification_status);

CREATE TABLE IF NOT EXISTS household_appliances (
  inventory_id INTEGER PRIMARY KEY AUTOINCREMENT,
  household_id INTEGER NOT NULL,
  source_appliance_id INTEGER,
  category_id INTEGER NOT NULL,
  appliance_name TEXT NOT NULL,
  brand TEXT,
  model TEXT,
  power_rating_watts REAL NOT NULL CHECK (power_rating_watts > 0 AND power_rating_watts <= 50000),
  quantity INTEGER NOT NULL DEFAULT 1 CHECK (quantity BETWEEN 1 AND 50),
  avg_daily_usage_hours REAL NOT NULL DEFAULT 0 CHECK (avg_daily_usage_hours >= 0 AND avg_daily_usage_hours <= 24),
  source_of_info TEXT NOT NULL,
  deleted_at TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (household_id) REFERENCES households(household_id) ON DELETE CASCADE,
  FOREIGN KEY (source_appliance_id) REFERENCES appliances(appliance_id) ON DELETE SET NULL,
  FOREIGN KEY (category_id) REFERENCES appliance_categories(category_id),
  UNIQUE (household_id, source_appliance_id)
);

CREATE INDEX IF NOT EXISTS idx_household_appliances_household
  ON household_appliances(household_id);

CREATE TABLE IF NOT EXISTS monthly_consumption (
  consumption_id INTEGER PRIMARY KEY AUTOINCREMENT,
  household_id INTEGER NOT NULL,
  billing_month TEXT NOT NULL,
  consumption_kwh REAL NOT NULL CHECK (consumption_kwh > 0 AND consumption_kwh <= 100000),
  bill_amount_php REAL CHECK (bill_amount_php IS NULL OR bill_amount_php >= 0),
  meter_reading REAL CHECK (meter_reading IS NULL OR meter_reading >= 0),
  source_of_info TEXT NOT NULL DEFAULT 'electric_bill'
    CHECK (source_of_info IN ('electric_bill','meter_reading','utility_portal','manual_entry')),
  verification_status TEXT NOT NULL DEFAULT 'pending'
    CHECK (verification_status IN ('pending','approved','rejected')),
  reviewer_notes TEXT,
  reviewer_notes_read_at TEXT,
  reviewed_by INTEGER,
  reviewed_at TEXT,
  deleted_at TEXT,
  bill_image_filename TEXT,
  bill_image_original_name TEXT,
  bill_image_mime TEXT,
  bill_image_size_bytes INTEGER,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (household_id) REFERENCES households(household_id) ON DELETE CASCADE,
  FOREIGN KEY (reviewed_by) REFERENCES users(user_id),
  UNIQUE (household_id, billing_month)
);

CREATE INDEX IF NOT EXISTS idx_consumption_household ON monthly_consumption(household_id);
CREATE INDEX IF NOT EXISTS idx_consumption_status ON monthly_consumption(verification_status);

CREATE TABLE IF NOT EXISTS notifications (
  notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  title TEXT NOT NULL,
  message TEXT NOT NULL,
  type TEXT NOT NULL CHECK (type IN ('demand_alert','submission_update','forecast_update','report_ready','system')),
  is_read INTEGER NOT NULL DEFAULT 0 CHECK (is_read IN (0,1)),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS audit_logs (
  audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
  actor_user_id INTEGER,
  action TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id INTEGER,
  details TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (actor_user_id) REFERENCES users(user_id)
);

CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at DESC);
