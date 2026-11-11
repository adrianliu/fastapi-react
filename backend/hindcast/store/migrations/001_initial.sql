-- Core tables live in hindcast/store/schema.py (ensure_core_schema); area tables in their modules' ensure_schema.
-- This migration holds only what no module creates itself.
CREATE TABLE IF NOT EXISTS llm_calls (
  llm_call_id            INTEGER PRIMARY KEY,
  purpose                TEXT NOT NULL,             -- label | group | distill | extract | task_write | judge | other
  job_id                 INTEGER,
  model_requested        TEXT NOT NULL,
  model_used             TEXT,                      -- key of modelUsage
  prompt_version         TEXT,
  schema_name            TEXT NOT NULL,             -- Pydantic model name
  schema_version         TEXT,
  input_sha256           TEXT NOT NULL,
  input_chars            INTEGER NOT NULL,
  status                 TEXT NOT NULL CHECK (status IN ('ok', 'error')),
  attempts               INTEGER NOT NULL DEFAULT 1,
  error                  TEXT,
  duration_ms            INTEGER,
  input_tokens           INTEGER,
  output_tokens          INTEGER,
  cache_read_tokens      INTEGER,
  cache_creation_tokens  INTEGER,
  total_cost_usd         REAL,                      -- API list-price equivalent
  created_at             TEXT NOT NULL
);
