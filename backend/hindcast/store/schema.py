"""Core tables (trajectories, steps, tool_calls, source_files, raw_record_counts, jobs, steps_fts).

Other areas read these columns, so names are fixed. `connect()` opens the Hindcast DB in WAL mode
without running the numbered migrations in store/migrations (their draft schema differs).
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from hindcast.store.db import db_path

CORE_SCHEMA = """
CREATE TABLE IF NOT EXISTS trajectories (
  trajectory_id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  parent_trajectory_id TEXT,
  parent_tool_call_id TEXT,
  agent_name TEXT NOT NULL,
  agent_version TEXT,
  model_name TEXT,
  origin TEXT NOT NULL DEFAULT 'organic',
  project_path TEXT,
  git_branch TEXT,
  started_at TEXT,
  ended_at TEXT,
  total_prompt_tokens INTEGER,
  total_completion_tokens INTEGER,
  total_cached_tokens INTEGER,
  total_cost_usd REAL,
  total_steps INTEGER,
  extra TEXT
);
CREATE INDEX IF NOT EXISTS trajectories_parent ON trajectories(parent_trajectory_id);
CREATE INDEX IF NOT EXISTS trajectories_started ON trajectories(started_at);
CREATE TABLE IF NOT EXISTS steps (
  trajectory_id TEXT NOT NULL,
  step_id INTEGER NOT NULL,
  timestamp TEXT,
  source TEXT NOT NULL,
  message TEXT NOT NULL,
  reasoning_content TEXT,
  model_name TEXT,
  prompt_tokens INTEGER,
  completion_tokens INTEGER,
  cached_tokens INTEGER,
  cost_usd REAL,
  stop_reason TEXT,
  turn_index INTEGER NOT NULL DEFAULT 0,
  extra TEXT,
  PRIMARY KEY (trajectory_id, step_id)
);
CREATE TABLE IF NOT EXISTS tool_calls (
  trajectory_id TEXT NOT NULL,
  step_id INTEGER NOT NULL,
  tool_call_id TEXT NOT NULL,
  function_name TEXT NOT NULL,
  arguments TEXT NOT NULL,
  content TEXT,
  is_error INTEGER NOT NULL DEFAULT 0,
  error_class TEXT,
  tool_kind TEXT,
  duration_ms INTEGER,
  extra TEXT
);
CREATE INDEX IF NOT EXISTS tool_calls_step ON tool_calls(trajectory_id, step_id);
CREATE TABLE IF NOT EXISTS source_files (
  path TEXT PRIMARY KEY,
  size INTEGER NOT NULL,
  prefix_hash TEXT,
  cursor INTEGER NOT NULL DEFAULT 0,
  parser_version TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS raw_record_counts (
  agent_name TEXT NOT NULL,
  record_type TEXT NOT NULL,
  n INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (agent_name, record_type)
);
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',
  progress TEXT NOT NULL DEFAULT '',
  result TEXT,
  error TEXT,
  created_at TEXT NOT NULL,
  finished_at TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS steps_fts USING fts5(
  message, trajectory_id UNINDEXED, step_id UNINDEXED
);
"""


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


@contextmanager
def core_db() -> Iterator[sqlite3.Connection]:
    """A connection whose `with` block is one transaction."""
    conn = connect()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def ensure_core_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(CORE_SCHEMA)
