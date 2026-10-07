-- Skema PostgreSQL untuk Supabase (dihasilkan oleh `python main.py db-schema`).
-- Opsional: jalankan di Supabase SQL Editor. `python main.py setup` juga membuatnya otomatis.

CREATE TABLE IF NOT EXISTS stocks (
  id BIGSERIAL PRIMARY KEY,
  ticker TEXT NOT NULL,
  name TEXT,
  sector TEXT,
  subsector TEXT,
  board TEXT,
  listing_date DATE,
  delisting_date DATE,
  is_active BOOLEAN NOT NULL,
  previous_ticker TEXT,
  listed_shares DOUBLE PRECISION,
  first_seen TIMESTAMPTZ,
  last_seen TIMESTAMPTZ,
  updated_at TIMESTAMPTZ,
  UNIQUE (ticker)
);

CREATE TABLE IF NOT EXISTS price_history (
  id BIGSERIAL PRIMARY KEY,
  stock_id BIGINT NOT NULL REFERENCES stocks(id),
  date DATE NOT NULL,
  open DOUBLE PRECISION,
  high DOUBLE PRECISION,
  low DOUBLE PRECISION,
  close DOUBLE PRECISION,
  volume DOUBLE PRECISION,
  value DOUBLE PRECISION,
  frequency DOUBLE PRECISION,
  is_adjusted BOOLEAN,
  source TEXT,
  ingested_at TIMESTAMPTZ,
  UNIQUE (stock_id, date)
);

CREATE TABLE IF NOT EXISTS corporate_actions (
  id BIGSERIAL PRIMARY KEY,
  stock_id BIGINT NOT NULL REFERENCES stocks(id),
  ex_date DATE NOT NULL,
  action TEXT NOT NULL,
  ratio DOUBLE PRECISION,
  amount DOUBLE PRECISION,
  source TEXT,
  processed_at TIMESTAMPTZ,
  UNIQUE (stock_id, ex_date, action)
);

CREATE TABLE IF NOT EXISTS market_index (
  id BIGSERIAL PRIMARY KEY,
  symbol TEXT NOT NULL,
  date DATE NOT NULL,
  open DOUBLE PRECISION,
  high DOUBLE PRECISION,
  low DOUBLE PRECISION,
  close DOUBLE PRECISION,
  volume DOUBLE PRECISION,
  source TEXT,
  ingested_at TIMESTAMPTZ,
  UNIQUE (symbol, date)
);

CREATE TABLE IF NOT EXISTS sector_data (
  id BIGSERIAL PRIMARY KEY,
  date DATE NOT NULL,
  sector TEXT NOT NULL,
  ret5 DOUBLE PRECISION,
  ret20 DOUBLE PRECISION,
  ret60 DOUBLE PRECISION,
  breadth DOUBLE PRECISION,
  volume_mom DOUBLE PRECISION,
  rs20 DOUBLE PRECISION,
  score DOUBLE PRECISION,
  rank BIGINT,
  n_stocks BIGINT,
  UNIQUE (date, sector)
);

CREATE TABLE IF NOT EXISTS features (
  id BIGSERIAL PRIMARY KEY,
  stock_id BIGINT NOT NULL REFERENCES stocks(id),
  date DATE NOT NULL,
  feature_version TEXT NOT NULL,
  payload TEXT,
  UNIQUE (stock_id, date, feature_version)
);

CREATE TABLE IF NOT EXISTS predictions (
  id BIGSERIAL PRIMARY KEY,
  prediction_date DATE NOT NULL,
  stock_id BIGINT NOT NULL REFERENCES stocks(id),
  ticker TEXT NOT NULL,
  model_version TEXT NOT NULL,
  horizon BIGINT,
  decision TEXT,
  setup TEXT,
  score DOUBLE PRECISION,
  market_regime TEXT,
  prob_bearish DOUBLE PRECISION,
  prob_neutral DOUBLE PRECISION,
  prob_bullish DOUBLE PRECISION,
  expected_return DOUBLE PRECISION,
  prob_hit_tp DOUBLE PRECISION,
  entry_low DOUBLE PRECISION,
  entry_ideal DOUBLE PRECISION,
  entry_high DOUBLE PRECISION,
  stop_loss DOUBLE PRECISION,
  tp1 DOUBLE PRECISION,
  tp2 DOUBLE PRECISION,
  risk_reward DOUBLE PRECISION,
  position_size BIGINT,
  lots BIGINT,
  capital_required DOUBLE PRECISION,
  estimated_loss DOUBLE PRECISION,
  confidence TEXT,
  close_price DOUBLE PRECISION,
  data_status TEXT,
  reasons TEXT,
  risks TEXT,
  reject_reasons TEXT,
  run_id TEXT,
  created_at TIMESTAMPTZ,
  UNIQUE (prediction_date, stock_id, model_version)
);

CREATE TABLE IF NOT EXISTS prediction_evaluations (
  id BIGSERIAL PRIMARY KEY,
  prediction_id BIGINT NOT NULL REFERENCES predictions(id),
  evaluated_at TIMESTAMPTZ,
  actual_return_3d DOUBLE PRECISION,
  actual_return_5d DOUBLE PRECISION,
  actual_return_10d DOUBLE PRECISION,
  mfe DOUBLE PRECISION,
  mae DOUBLE PRECISION,
  entry_filled BOOLEAN,
  hit_stop BOOLEAN,
  hit_tp1 BOOLEAN,
  hit_tp2 BOOLEAN,
  actual_class BIGINT,
  prediction_correct BOOLEAN,
  outcome TEXT,
  UNIQUE (prediction_id)
);

CREATE TABLE IF NOT EXISTS trading_signals (
  id BIGSERIAL PRIMARY KEY,
  signal_date DATE NOT NULL,
  stock_id BIGINT NOT NULL REFERENCES stocks(id),
  ticker TEXT NOT NULL,
  rank BIGINT,
  decision TEXT,
  setup TEXT,
  score DOUBLE PRECISION,
  prob_bullish DOUBLE PRECISION,
  expected_return DOUBLE PRECISION,
  entry_low DOUBLE PRECISION,
  entry_ideal DOUBLE PRECISION,
  entry_high DOUBLE PRECISION,
  stop_loss DOUBLE PRECISION,
  tp1 DOUBLE PRECISION,
  tp2 DOUBLE PRECISION,
  risk_reward DOUBLE PRECISION,
  lots BIGINT,
  confidence TEXT,
  model_version TEXT,
  run_id TEXT,
  UNIQUE (signal_date, stock_id)
);

CREATE TABLE IF NOT EXISTS backtest_runs (
  id BIGSERIAL PRIMARY KEY,
  run_id TEXT NOT NULL,
  created_at TIMESTAMPTZ,
  kind TEXT,
  period_start DATE,
  period_end DATE,
  model_version TEXT,
  config_hash TEXT,
  metrics TEXT,
  benchmark TEXT,
  status TEXT,
  UNIQUE (run_id)
);

CREATE TABLE IF NOT EXISTS backtest_trades (
  id BIGSERIAL PRIMARY KEY,
  backtest_run_id TEXT NOT NULL,
  ticker TEXT,
  setup TEXT,
  entry_date DATE,
  exit_date DATE,
  entry_price DOUBLE PRECISION,
  exit_price DOUBLE PRECISION,
  shares BIGINT,
  net_pnl DOUBLE PRECISION,
  net_return DOUBLE PRECISION,
  r_multiple DOUBLE PRECISION,
  exit_reason TEXT,
  fees DOUBLE PRECISION,
  UNIQUE (backtest_run_id, ticker, entry_date)
);

CREATE TABLE IF NOT EXISTS model_versions (
  id BIGSERIAL PRIMARY KEY,
  version TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TIMESTAMPTZ,
  promoted_at TIMESTAMPTZ,
  train_start DATE,
  train_end DATE,
  feature_version TEXT,
  config_hash TEXT,
  classifiers TEXT,
  metrics TEXT,
  storage_backend TEXT,
  storage_uri TEXT,
  artifact BYTEA,
  artifact_sha256 TEXT,
  artifact_bytes BIGINT,
  notes TEXT,
  UNIQUE (version)
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
  id BIGSERIAL PRIMARY KEY,
  run_id TEXT NOT NULL,
  run_type TEXT NOT NULL,
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  status TEXT,
  stocks_processed BIGINT,
  stocks_failed BIGINT,
  rows_inserted BIGINT,
  rows_updated BIGINT,
  model_version TEXT,
  data_status TEXT,
  market_date DATE,
  trigger TEXT,
  summary TEXT,
  error_message TEXT,
  created_at TIMESTAMPTZ,
  UNIQUE (run_id)
);

CREATE TABLE IF NOT EXISTS data_sources (
  id BIGSERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  type TEXT,
  priority BIGINT,
  enabled BOOLEAN,
  last_success_at TIMESTAMPTZ,
  last_error_at TIMESTAMPTZ,
  last_error TEXT,
  rows_fetched_total BIGINT,
  UNIQUE (name)
);

CREATE TABLE IF NOT EXISTS system_logs (
  id BIGSERIAL PRIMARY KEY,
  run_id TEXT,
  ts TIMESTAMPTZ,
  level TEXT,
  logger TEXT,
  message TEXT
);

CREATE TABLE IF NOT EXISTS reports (
  id BIGSERIAL PRIMARY KEY,
  report_date DATE NOT NULL,
  kind TEXT NOT NULL,
  filename TEXT NOT NULL,
  content BYTEA,
  content_type TEXT,
  storage_backend TEXT,
  storage_uri TEXT,
  run_id TEXT,
  created_at TIMESTAMPTZ,
  UNIQUE (report_date, kind, filename)
);

CREATE TABLE IF NOT EXISTS schema_migrations (
  version BIGINT PRIMARY KEY,
  applied_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_stocks_is_active ON stocks (is_active);

CREATE INDEX IF NOT EXISTS ix_stocks_sector ON stocks (sector);

CREATE INDEX IF NOT EXISTS ix_price_history_date ON price_history (date);

CREATE INDEX IF NOT EXISTS ix_corporate_actions_ex_date ON corporate_actions (ex_date);

CREATE INDEX IF NOT EXISTS ix_market_index_date ON market_index (date);

CREATE INDEX IF NOT EXISTS ix_sector_data_date ON sector_data (date);

CREATE INDEX IF NOT EXISTS ix_features_date ON features (date);

CREATE INDEX IF NOT EXISTS ix_predictions_ticker ON predictions (ticker);

CREATE INDEX IF NOT EXISTS ix_predictions_decision ON predictions (decision);

CREATE INDEX IF NOT EXISTS ix_predictions_model_version ON predictions (model_version);

CREATE INDEX IF NOT EXISTS ix_trading_signals_signal_date ON trading_signals (signal_date);

CREATE INDEX IF NOT EXISTS ix_backtest_runs_created_at ON backtest_runs (created_at);

CREATE INDEX IF NOT EXISTS ix_backtest_trades_backtest_run_id ON backtest_trades (backtest_run_id);

CREATE INDEX IF NOT EXISTS ix_model_versions_status ON model_versions (status);

CREATE INDEX IF NOT EXISTS ix_pipeline_runs_run_type_started_at ON pipeline_runs (run_type, started_at);

CREATE INDEX IF NOT EXISTS ix_system_logs_run_id ON system_logs (run_id);

CREATE INDEX IF NOT EXISTS ix_system_logs_ts ON system_logs (ts);

CREATE INDEX IF NOT EXISTS ix_reports_report_date ON reports (report_date);
