-- RouteMind initial schema (SQLite dialect).
-- Timestamps are epoch seconds stored as REAL, identical to the Postgres dialect,
-- so repository code is shared. Geometry lives in geom_json (GeoJSON text) with
-- bbox columns for cheap spatial pre-filtering.

CREATE TABLE IF NOT EXISTS users (
  id             TEXT PRIMARY KEY,
  username       TEXT NOT NULL UNIQUE,
  full_name      TEXT NOT NULL,
  email          TEXT,
  role           TEXT NOT NULL CHECK (role IN ('admin','dispatcher','field_officer','logistics_manager')),
  password_hash  TEXT,
  password_salt  TEXT,
  login_enabled  INTEGER NOT NULL DEFAULT 0,
  active         INTEGER NOT NULL DEFAULT 1,
  created_at     REAL NOT NULL,
  updated_at     REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
  token_hash  TEXT PRIMARY KEY,
  user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at  REAL NOT NULL,
  expires_at  REAL NOT NULL,
  user_agent  TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS districts (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  state       TEXT NOT NULL,
  geom_json   TEXT,
  min_lng REAL, min_lat REAL, max_lng REAL, max_lat REAL,
  created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS roads (
  id              TEXT PRIMARY KEY,
  name            TEXT NOT NULL,
  ref             TEXT,
  classification  TEXT,
  from_city       TEXT,
  to_city         TEXT,
  length_km       REAL,
  free_flow_kmh   REAL,
  condition       TEXT,
  data_class      TEXT NOT NULL DEFAULT 'REAL' CHECK (data_class IN ('REAL','SIMULATED','DERIVED','PREDICTED')),
  source          TEXT,
  created_at      REAL NOT NULL,
  updated_at      REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS road_segments (
  id             TEXT PRIMARY KEY,
  road_id        TEXT NOT NULL REFERENCES roads(id) ON DELETE CASCADE,
  seq            INTEGER NOT NULL DEFAULT 0,
  name           TEXT,
  length_km      REAL,
  free_flow_kmh  REAL,
  condition      TEXT,
  district_id    TEXT REFERENCES districts(id),
  geom_json      TEXT,
  min_lng REAL, min_lat REAL, max_lng REAL, max_lat REAL,
  data_class     TEXT NOT NULL DEFAULT 'REAL' CHECK (data_class IN ('REAL','SIMULATED','DERIVED','PREDICTED')),
  source         TEXT,
  created_at     REAL NOT NULL,
  updated_at     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_segments_road ON road_segments(road_id);
CREATE INDEX IF NOT EXISTS idx_segments_bbox ON road_segments(min_lng, min_lat, max_lng, max_lat);

CREATE TABLE IF NOT EXISTS depots (
  id           TEXT PRIMARY KEY,
  name         TEXT NOT NULL,
  district_id  TEXT REFERENCES districts(id),
  lng          REAL NOT NULL,
  lat          REAL NOT NULL,
  geom_json    TEXT,
  capacity_pct REAL,
  data_class   TEXT NOT NULL DEFAULT 'SIMULATED' CHECK (data_class IN ('REAL','SIMULATED','DERIVED','PREDICTED')),
  created_at   REAL NOT NULL,
  updated_at   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS inventory_items (
  id                 TEXT PRIMARY KEY,
  depot_id           TEXT NOT NULL REFERENCES depots(id) ON DELETE CASCADE,
  item               TEXT NOT NULL,
  category           TEXT,
  stock_units        REAL,
  daily_consumption  REAL,
  stock_days         REAL,
  status             TEXT CHECK (status IN ('shortage','watch','ok','surplus')),
  data_class         TEXT NOT NULL DEFAULT 'SIMULATED' CHECK (data_class IN ('REAL','SIMULATED','DERIVED','PREDICTED')),
  updated_at         REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_inventory_depot ON inventory_items(depot_id);

CREATE TABLE IF NOT EXISTS vehicles (
  id               TEXT PRIMARY KEY,
  plate            TEXT,
  driver           TEXT,
  phone            TEXT,
  cargo            TEXT,
  cargo_category   TEXT,
  capacity_tonnes  REAL,
  cold_chain       INTEGER NOT NULL DEFAULT 0,
  priority         TEXT CHECK (priority IN ('critical','high','standard')),
  status           TEXT,
  corridor_id      TEXT,
  lng              REAL,
  lat              REAL,
  eta_min          INTEGER,
  rerouted         INTEGER NOT NULL DEFAULT 0,
  data_class       TEXT NOT NULL DEFAULT 'SIMULATED' CHECK (data_class IN ('REAL','SIMULATED','DERIVED','PREDICTED')),
  updated_at       REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS deliveries (
  id                TEXT PRIMARY KEY,
  vehicle_id        TEXT REFERENCES vehicles(id),
  cargo             TEXT,
  category          TEXT,
  origin            TEXT,
  destination       TEXT,
  consignee         TEXT,
  priority          TEXT CHECK (priority IN ('critical','high','standard')),
  sla_hours         REAL,
  status            TEXT,
  eta_min           INTEGER,
  delay_min         INTEGER,
  reliability       REAL,
  risk_probability  REAL,
  data_class        TEXT NOT NULL DEFAULT 'SIMULATED' CHECK (data_class IN ('REAL','SIMULATED','DERIVED','PREDICTED')),
  created_at        REAL NOT NULL,
  updated_at        REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_deliveries_vehicle ON deliveries(vehicle_id);

CREATE TABLE IF NOT EXISTS incidents (
  id            TEXT PRIMARY KEY,
  corridor_id   TEXT,
  segment_id    TEXT REFERENCES road_segments(id),
  type          TEXT NOT NULL,
  severity      TEXT NOT NULL CHECK (severity IN ('critical','high','moderate','low')),
  title         TEXT NOT NULL,
  description   TEXT,
  lng           REAL,
  lat           REAL,
  geom_json     TEXT,
  blocks_road   INTEGER NOT NULL DEFAULT 0,
  status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','acknowledged','resolved')),
  verified      INTEGER NOT NULL DEFAULT 0,
  source        TEXT,
  source_label  TEXT,
  data_class    TEXT NOT NULL DEFAULT 'REAL' CHECK (data_class IN ('REAL','SIMULATED','DERIVED','PREDICTED')),
  external_url  TEXT,
  reported_by   TEXT REFERENCES users(id),
  reported_at   REAL,
  observed_at   REAL,
  ingested_at   REAL,
  resolved_at   REAL,
  updated_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_incidents_corridor ON incidents(corridor_id);
CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status);

CREATE TABLE IF NOT EXISTS field_reports (
  id            TEXT PRIMARY KEY,
  client_uuid   TEXT UNIQUE,
  incident_id   TEXT REFERENCES incidents(id) ON DELETE SET NULL,
  reporter_id   TEXT REFERENCES users(id),
  corridor_id   TEXT,
  type          TEXT NOT NULL,
  severity      TEXT NOT NULL,
  description   TEXT,
  lng           REAL,
  lat           REAL,
  accuracy_m    REAL,
  photo_path    TEXT,
  photo_sha256  TEXT,
  captured_at   REAL,
  synced_at     REAL,
  sync_state    TEXT NOT NULL DEFAULT 'synced' CHECK (sync_state IN ('pending','synced','failed','duplicate')),
  data_class    TEXT NOT NULL DEFAULT 'REAL' CHECK (data_class IN ('REAL','SIMULATED','DERIVED','PREDICTED')),
  created_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_field_reports_state ON field_reports(sync_state);

CREATE TABLE IF NOT EXISTS route_plans (
  id                   TEXT PRIMARY KEY,
  vehicle_id           TEXT REFERENCES vehicles(id),
  delivery_id          TEXT REFERENCES deliveries(id),
  requested_by         TEXT REFERENCES users(id),
  priority             TEXT,
  provenance           TEXT,
  routing_provenance   TEXT,
  created_at           REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS route_options (
  id                TEXT PRIMARY KEY,
  plan_id           TEXT NOT NULL REFERENCES route_plans(id) ON DELETE CASCADE,
  label             TEXT,
  source            TEXT,
  distance_km       REAL,
  eta_min           INTEGER,
  risk_probability  REAL,
  reliability       REAL,
  blocked           INTEGER NOT NULL DEFAULT 0,
  recommended       INTEGER NOT NULL DEFAULT 0,
  score_time        REAL,
  score_risk        REAL,
  score_reliability REAL,
  score_priority    REAL,
  score_total       REAL,
  explanation       TEXT,
  geom_json         TEXT,
  created_at        REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_route_options_plan ON route_options(plan_id);

CREATE TABLE IF NOT EXISTS risk_predictions (
  id            TEXT PRIMARY KEY,
  corridor_id   TEXT NOT NULL,
  segment_id    TEXT REFERENCES road_segments(id),
  probability   REAL NOT NULL,
  band          TEXT NOT NULL,
  window_hours  INTEGER NOT NULL,
  model_version TEXT NOT NULL,
  model_kind    TEXT NOT NULL,
  factors_json  TEXT,
  data_class    TEXT NOT NULL DEFAULT 'PREDICTED' CHECK (data_class IN ('REAL','SIMULATED','DERIVED','PREDICTED')),
  predicted_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_predictions_corridor ON risk_predictions(corridor_id, predicted_at);

CREATE TABLE IF NOT EXISTS simulation_runs (
  id                TEXT PRIMARY KEY,
  scenario_id       TEXT NOT NULL,
  name              TEXT,
  phase             TEXT NOT NULL,
  committed         INTEGER NOT NULL DEFAULT 0,
  created_by        TEXT REFERENCES users(id),
  started_at        REAL NOT NULL,
  decided_at        REAL,
  accepted_route_id TEXT,
  impact_json       TEXT,
  log_json          TEXT
);

CREATE TABLE IF NOT EXISTS alerts (
  id              TEXT PRIMARY KEY,
  alert_key       TEXT NOT NULL,
  severity        TEXT NOT NULL CHECK (severity IN ('critical','high','moderate','low')),
  status          TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new','acknowledged','assigned','escalated','resolved')),
  title           TEXT NOT NULL,
  body            TEXT,
  entity_type     TEXT,
  entity_id       TEXT,
  corridor_id     TEXT,
  assignee_id     TEXT REFERENCES users(id),
  assignee_name   TEXT,
  source          TEXT,
  data_class      TEXT NOT NULL DEFAULT 'DERIVED' CHECK (data_class IN ('REAL','SIMULATED','DERIVED','PREDICTED')),
  created_at      REAL NOT NULL,
  updated_at      REAL NOT NULL,
  acknowledged_at REAL,
  resolved_at     REAL
);
CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status, severity);

CREATE TABLE IF NOT EXISTS notifications (
  id         TEXT PRIMARY KEY,
  user_id    TEXT REFERENCES users(id) ON DELETE CASCADE,
  alert_id   TEXT REFERENCES alerts(id) ON DELETE CASCADE,
  channel    TEXT NOT NULL DEFAULT 'in_app' CHECK (channel IN ('in_app','push','email','sms')),
  status     TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','sent','failed','read')),
  created_at REAL NOT NULL,
  sent_at    REAL
);
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, status);

CREATE TABLE IF NOT EXISTS audit_log (
  id          TEXT PRIMARY KEY,
  at          REAL NOT NULL,
  actor_id    TEXT,
  actor_role  TEXT,
  action      TEXT NOT NULL,
  entity_type TEXT,
  entity_id   TEXT,
  detail_json TEXT,
  allowed     INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_audit_at ON audit_log(at);
