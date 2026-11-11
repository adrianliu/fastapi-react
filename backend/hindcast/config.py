"""Filesystem locations. Every path can be overridden by an environment variable for tests."""

import os
from pathlib import Path


def _path(env: str, default: Path) -> Path:
    value = os.environ.get(env)
    return Path(value).expanduser() if value else default


def hindcast_home() -> Path:
    """`~/.hindcast` (env `HINDCAST_HOME`)."""
    return _path("HINDCAST_HOME", Path.home() / ".hindcast")


def llm_cwd() -> Path:
    """Working directory for `claude -p` calls (spec 7). The importer skips its project slug."""
    return hindcast_home() / "llm-cwd"


def bench_repo() -> Path:
    """The private benchmark repo, `hindcast-bench` (spec 6.6). Env `HINDCAST_BENCH`."""
    return _path("HINDCAST_BENCH", hindcast_home() / "bench")


def claude_projects_dir() -> Path:
    """Claude Code sessions: `~/.claude/projects` (env `HINDCAST_CLAUDE_PROJECTS`)."""
    return _path("HINDCAST_CLAUDE_PROJECTS", Path.home() / ".claude" / "projects")


def codex_home() -> Path:
    """Codex home with `sessions/` and `archived_sessions/` (env `CODEX_HOME`)."""
    return _path("CODEX_HOME", Path.home() / ".codex")


def session_hub_archive() -> Path:
    """Optional import source: `~/.session-hub/archive` (env `HINDCAST_ARCHIVE`)."""
    return _path("HINDCAST_ARCHIVE", Path.home() / ".session-hub" / "archive")
