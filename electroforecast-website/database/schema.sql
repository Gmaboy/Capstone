-- ============================================================
-- ElectroForecast (GECAST) — Hybrid BLSTM–SARIMA Crowdsourcing
-- Platform for Electricity Consumption Forecasting and
-- Demand Level Classification
--
-- Reference schema aligned with the capstone's Definition of
-- Terms and system description. Engine: MySQL / MariaDB.
-- This is illustrative — adjust to match the production schema
-- once the GUIMELCO dataset and final ERD are finalized.
-- ============================================================

CREATE DATABASE IF NOT EXISTS electroforecast
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE electroforecast;

-- ---------------------------------------------------------------
-- Roles & Users
-- ---------------------------------------------------------------
CREATE TABLE roles (
  role_id       INT AUTO_INCREMENT PRIMARY KEY,
  role_name     ENUM('admin','guimelco','researcher','household') NOT NULL UNIQUE,
  description   VARCHAR(255)
);

CREATE TABLE users (
  user_id       INT AUTO_INCREMENT PRIMARY KEY,
  role_id       INT NOT NULL,
  full_name     VARCHAR(120) NOT NULL,
  email         VARCHAR(150) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  contact_no    VARCHAR(30),
  status        ENUM('active','inactive') NOT NULL DEFAULT 'active',
  created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  FOREIGN KEY (role_id) REFERENCES roles(role_id)
);

CREATE TABLE user_settings (
  user_id INT PRIMARY KEY,
  notify_high_demand TINYINT(1) NOT NULL DEFAULT 1,
  notify_rating_updates TINYINT(1) NOT NULL DEFAULT 1,
  notify_weekly_summary TINYINT(1) NOT NULL DEFAULT 0,
  forecast_horizon ENUM('7_days','14_days','30_days') NOT NULL DEFAULT '7_days',
  forecast_granularity ENUM('daily','weekly','monthly') NOT NULL DEFAULT 'daily',
  measurement_unit ENUM('kwh','mwh') NOT NULL DEFAULT 'kwh',
  landing_page ENUM('role_default','forecasting','demand_classification') NOT NULL DEFAULT 'role_default',
  show_confidence_intervals TINYINT(1) NOT NULL DEFAULT 1,
  show_demand_gauge TINYINT(1) NOT NULL DEFAULT 1,
  compact_table_view TINYINT(1) NOT NULL DEFAULT 0,
  data_refresh_frequency ENUM('daily','weekly','manual') NOT NULL DEFAULT 'daily',
  default_file_format ENUM('csv','xlsx','json') NOT NULL DEFAULT 'csv',
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- ---------------------------------------------------------------
-- Households (Crowdsourcing Platform participants)
-- ---------------------------------------------------------------
CREATE TABLE households (
  household_id  INT AUTO_INCREMENT PRIMARY KEY,
  user_id       INT NOT NULL,
  barangay      VARCHAR(120),
  municipality  VARCHAR(120),
  household_size INT,
  meter_number  VARCHAR(50),
  created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(user_id)
);

-- ---------------------------------------------------------------
-- Household Appliance Information
-- ---------------------------------------------------------------
CREATE TABLE appliance_categories (
  category_id   INT AUTO_INCREMENT PRIMARY KEY,
  category_name VARCHAR(100) NOT NULL UNIQUE
);

CREATE TABLE appliances (
  appliance_id  INT AUTO_INCREMENT PRIMARY KEY,
  household_id  INT NOT NULL,
  category_id   INT,
  appliance_name VARCHAR(120) NOT NULL,
  brand         VARCHAR(100),
  model         VARCHAR(100),
  power_rating_watts DECIMAL(10,2) NOT NULL,
  quantity      INT NOT NULL DEFAULT 1,
  avg_daily_usage_hours DECIMAL(5,2) DEFAULT 0,
  source_of_info ENUM('nameplate_label','user_manual','manual_estimate','retailer_specs') NOT NULL DEFAULT 'nameplate_label',
  copied_from_appliance_id INT NULL,
  verification_status ENUM('pending','approved','rejected') NOT NULL DEFAULT 'pending',
  reviewer_notes VARCHAR(500),
  reviewer_notes_read_at DATETIME NULL,
  reviewed_by   INT NULL,
  reviewed_at   DATETIME NULL,
  image_path    VARCHAR(255),
  created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  FOREIGN KEY (household_id) REFERENCES households(household_id),
  FOREIGN KEY (category_id) REFERENCES appliance_categories(category_id),
  FOREIGN KEY (copied_from_appliance_id) REFERENCES appliances(appliance_id) ON DELETE SET NULL,
  FOREIGN KEY (reviewed_by) REFERENCES users(user_id)
);

CREATE TABLE household_appliances (
  inventory_id INT AUTO_INCREMENT PRIMARY KEY,
  household_id INT NOT NULL,
  source_appliance_id INT NULL,
  category_id INT NOT NULL,
  appliance_name VARCHAR(120) NOT NULL,
  brand VARCHAR(100),
  model VARCHAR(100),
  power_rating_watts DECIMAL(10,2) NOT NULL,
  quantity INT NOT NULL DEFAULT 1,
  avg_daily_usage_hours DECIMAL(5,2) NOT NULL DEFAULT 0,
  source_of_info ENUM('nameplate_label','user_manual','manual_estimate','retailer_specs') NOT NULL,
  deleted_at DATETIME NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  FOREIGN KEY (household_id) REFERENCES households(household_id) ON DELETE CASCADE,
  FOREIGN KEY (source_appliance_id) REFERENCES appliances(appliance_id) ON DELETE SET NULL,
  FOREIGN KEY (category_id) REFERENCES appliance_categories(category_id),
  UNIQUE KEY uq_household_source_appliance (household_id, source_appliance_id)
);

CREATE INDEX idx_household_appliances_deleted
  ON household_appliances(household_id, deleted_at);

-- ---------------------------------------------------------------
-- Crowdsourced Appliance Ratings (power-rating submissions)
-- ---------------------------------------------------------------
CREATE TABLE crowdsourced_ratings (
  rating_id     INT AUTO_INCREMENT PRIMARY KEY,
  submitted_by  INT NOT NULL,
  appliance_name VARCHAR(120) NOT NULL,
  category_id   INT,
  brand         VARCHAR(100),
  model         VARCHAR(100),
  power_rating_watts DECIMAL(10,2) NOT NULL,
  source_of_info ENUM('nameplate_label','user_manual','manual_estimate','retailer_specs') NOT NULL,
  image_path    VARCHAR(255),
  status        ENUM('pending','verified','rejected') NOT NULL DEFAULT 'pending',
  reviewed_by   INT NULL,
  reviewed_at   DATETIME NULL,
  submitted_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (submitted_by) REFERENCES users(user_id),
  FOREIGN KEY (reviewed_by) REFERENCES users(user_id),
  FOREIGN KEY (category_id) REFERENCES appliance_categories(category_id)
);

-- ---------------------------------------------------------------
-- Historical Electricity Consumption Records
-- ---------------------------------------------------------------
CREATE TABLE consumption_records (
  record_id     INT AUTO_INCREMENT PRIMARY KEY,
  household_id  INT NOT NULL,
  record_date   DATE NOT NULL,
  consumption_kwh DECIMAL(10,3) NOT NULL,
  avg_temperature_c DECIMAL(5,2),
  day_of_week   VARCHAR(10),
  is_holiday    TINYINT(1) DEFAULT 0,
  created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (household_id) REFERENCES households(household_id),
  UNIQUE KEY uq_household_date (household_id, record_date)
);

-- ---------------------------------------------------------------
-- Crowdsourced Monthly Electricity Consumption
-- ---------------------------------------------------------------
CREATE TABLE monthly_consumption (
  consumption_id INT AUTO_INCREMENT PRIMARY KEY,
  household_id  INT NOT NULL,
  billing_month CHAR(7) NOT NULL COMMENT 'YYYY-MM',
  consumption_kwh DECIMAL(10,3) NOT NULL,
  bill_amount_php DECIMAL(12,2),
  meter_reading DECIMAL(12,2),
  source_of_info ENUM('electric_bill','meter_reading','utility_portal','manual_entry') NOT NULL DEFAULT 'electric_bill',
  verification_status ENUM('pending','approved','rejected') NOT NULL DEFAULT 'pending',
  reviewer_notes VARCHAR(500),
  reviewer_notes_read_at DATETIME NULL,
  reviewed_by   INT NULL,
  reviewed_at   DATETIME NULL,
  deleted_at    DATETIME NULL,
  bill_image_filename VARCHAR(100),
  bill_image_original_name VARCHAR(255),
  bill_image_mime VARCHAR(50),
  bill_image_size_bytes INT,
  created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  FOREIGN KEY (household_id) REFERENCES households(household_id),
  FOREIGN KEY (reviewed_by) REFERENCES users(user_id),
  UNIQUE KEY uq_household_billing_month (household_id, billing_month)
);

-- Persistent trace of CRUD and validation actions
CREATE TABLE audit_logs (
  audit_id      INT AUTO_INCREMENT PRIMARY KEY,
  actor_user_id INT NULL,
  action        VARCHAR(40) NOT NULL,
  entity_type   VARCHAR(60) NOT NULL,
  entity_id     INT NULL,
  details       JSON,
  created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (actor_user_id) REFERENCES users(user_id)
);

-- ---------------------------------------------------------------
-- Forecasts (Hybrid BLSTM-SARIMA output)
-- ---------------------------------------------------------------
CREATE TABLE forecasts (
  forecast_id   INT AUTO_INCREMENT PRIMARY KEY,
  household_id  INT NOT NULL,
  forecast_date DATE NOT NULL,
  model_used    ENUM('hybrid_blstm_sarima','blstm_only','sarima_only') NOT NULL DEFAULT 'hybrid_blstm_sarima',
  granularity   ENUM('daily','weekly','monthly') NOT NULL DEFAULT 'daily',
  predicted_kwh DECIMAL(10,3) NOT NULL,
  lower_bound_kwh DECIMAL(10,3),
  upper_bound_kwh DECIMAL(10,3),
  mae           DECIMAL(10,4),
  rmse          DECIMAL(10,4),
  mape          DECIMAL(6,3),
  generated_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (household_id) REFERENCES households(household_id)
);

-- ---------------------------------------------------------------
-- Demand Level Classification
-- ---------------------------------------------------------------
CREATE TABLE demand_classifications (
  classification_id INT AUTO_INCREMENT PRIMARY KEY,
  forecast_id   INT NOT NULL,
  household_id  INT NOT NULL,
  classification_date DATE NOT NULL,
  demand_level  ENUM('low','normal','high','peak') NOT NULL,
  probability_pct DECIMAL(5,2) NOT NULL,
  description   VARCHAR(255),
  recommendation VARCHAR(255),
  created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (forecast_id) REFERENCES forecasts(forecast_id),
  FOREIGN KEY (household_id) REFERENCES households(household_id)
);

-- ---------------------------------------------------------------
-- Explainable AI (XAI) results — SHAP / LIME
-- ---------------------------------------------------------------
CREATE TABLE xai_explanations (
  explanation_id INT AUTO_INCREMENT PRIMARY KEY,
  forecast_id   INT NOT NULL,
  method        ENUM('shap','lime') NOT NULL,
  feature_name  VARCHAR(100) NOT NULL,
  contribution_score DECIMAL(6,4) NOT NULL,
  generated_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (forecast_id) REFERENCES forecasts(forecast_id)
);

-- ---------------------------------------------------------------
-- Reports
-- ---------------------------------------------------------------
CREATE TABLE reports (
  report_id     INT AUTO_INCREMENT PRIMARY KEY,
  generated_by  INT NOT NULL,
  report_type   ENUM('consumption_summary','forecast_accuracy','demand_classification','appliance_contribution') NOT NULL,
  period_start  DATE,
  period_end    DATE,
  file_format   ENUM('pdf','csv') NOT NULL DEFAULT 'pdf',
  file_path     VARCHAR(255),
  generated_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (generated_by) REFERENCES users(user_id)
);

-- ---------------------------------------------------------------
-- Notifications
-- ---------------------------------------------------------------
CREATE TABLE notifications (
  notification_id INT AUTO_INCREMENT PRIMARY KEY,
  user_id       INT NOT NULL,
  title         VARCHAR(150) NOT NULL,
  message       VARCHAR(255) NOT NULL,
  type          ENUM('demand_alert','rating_update','forecast_update','report_ready','system') NOT NULL,
  is_read       TINYINT(1) NOT NULL DEFAULT 0,
  created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(user_id)
);

-- ---------------------------------------------------------------
-- Seed reference data
-- ---------------------------------------------------------------
INSERT INTO roles (role_name, description) VALUES
  ('admin','Full system access and user management'),
  ('guimelco','Utility company staff reviewing forecasts and reports'),
  ('researcher','Read access for analysis and model evaluation'),
  ('household','Crowdsourcing contributor submitting appliance data');

INSERT INTO appliance_categories (category_name) VALUES
  ('Cooling'),('Kitchen Appliances'),('Laundry'),('Entertainment'),('Lighting'),('Other');
