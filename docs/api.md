# Hindcast MVP API contract

All JSON. Prefix `/api`. Costs are API-price **estimates**.

## Core (owner: backend-core, `backend/hindcast/api_core.py`)
- `GET /api/home` → `{sessions: int, trajectories: int, steps: int, harnesses: {[agent_name]: int}, projects: int, first_at: str|null, last_at: str|null, weeks: int, unknown_records: {[agent_name]: int}, import_since: str|null}`
- `POST /api/import {since?: ISO datetime with offset, all?: bool}` → `{job_id: int}` (background; only files written to at or after `since`, default env `HINDCAST_IMPORT_SINCE`, else all; source: `~/.claude/projects`, `~/.session-hub/archive/*.jsonl.gz`, `~/.codex/sessions`)
- `GET /api/sessions?q=&harness=&project=&sort=started_at|cost|steps|friction&limit=50&offset=0` → `{total: int, items: SessionSummary[]}`
  - `SessionSummary = {trajectory_id, session_id, agent_name, project_path, model_name, started_at, ended_at, total_steps, total_prompt_tokens, total_completion_tokens, total_cost_usd, n_errors, n_subagents, friction_score: number|null, first_prompt: str}`
- `GET /api/sessions/{trajectory_id}` → `{summary: SessionSummary, steps: Step[], subagents: SessionSummary[]}`
  - `Step = {step_id, timestamp, source: "user"|"agent"|"system", message: str, reasoning_content: str|null, model_name: str|null, prompt_tokens: int|null, completion_tokens: int|null, cost_usd: number|null, turn_index: int, kind: str|null, tool_calls: ToolCall[]}`
  - `ToolCall = {tool_call_id, function_name, arguments: str, content: str, is_error: bool, error_class: str|null, duration_ms: int|null, subagent_trajectory_id: str|null}`
- `GET /api/jobs/{id}` → `Job = {id, kind, status: "queued"|"running"|"done"|"failed", progress: str, result: object|null, error: str|null, created_at, finished_at}`; `GET /api/jobs` → `Job[]` (latest 20)

## Friction and fixes (owner: friction-fixes, `backend/hindcast/api_fixes.py`)
- `POST /api/groups/build` → `{job_id}` (rule pass over episodes, theme grouping)
- `GET /api/groups` → `Group[]` ranked by `sessions * projects`
  - `Group = {id, name, lesson, n_items, sessions, projects, score, items: Correction[]}`
  - `Correction = {id, trajectory_id, step_id, project_path, timestamp, quote: str, agent_before: str, signals: {[name]: number}}`
- `GET /api/groups/{id}` → `Group`
- `POST /api/fixes/draft {group_id}` → `{job_id}` (live `claude -p`, result `{fix_id}`)
- `GET /api/fixes` → `Fix[]`; `GET /api/fixes/{id}` → `Fix`
  - `Fix = {id, group_id, fix_type: "rule"|"skill"|"hook", name, summary, versions: FixVersion[], rationale: {instruction: str, correction_ids: int[]}[]}`
  - `FixVersion = {version, content: str, author: "model"|"user", model: str|null, created_at}`
- `PUT /api/fixes/{id} {content}` → `Fix` (new version; validates rule ≤ 15 lines)
- `GET /api/fixes/{id}/install-preview?target=~/.claude/CLAUDE.md` → `{target, diff: str}`
- `POST /api/fixes/{id}/install {target, confirm: true}` → `{target, applied: bool}`

## Bench (owner: bench, `backend/hindcast/api_bench.py`)
- `GET /api/bench/tasks` → `Task[]`
  - `Task = {name, dataset, kind: "reconstructed"|"control", instruction: str, rubric: {id, text, kind, weight}[], checks: {nop: "pass"|"fail"|"unknown", oracle: ..., install: ...}}`
- `POST /api/bench/estimate {fix_id|null, variants: 2, tasks: int, repeats: int}` → `{trials, minutes, cost_usd}`
- `POST /api/bench/run {baseline_config, candidate_config}` → `{job_id}`
- `GET /api/bench/runs` → `{id, name, variants: str[], n_trials, started_at, status}[]`
- `GET /api/bench/comparison?run=<id>` → `Comparison`
  - `Comparison = {run, variants: VariantStats[], items: ItemRate[], tasks: TaskRow[], verdict: "better"|"worse"|"no clear difference"|"too few tasks", verdict_detail: str}`
  - `VariantStats = {name, n_trials, check_pass_rate, rubric_mean, metrics: {[name]: number}, median_diff_lines, cost_usd_mean, tokens_mean, duration_s_mean, rule_present: str}`
  - `ItemRate = {id, text, rates: {[variant]: {passed: int, n: int}}}`
  - `TaskRow = {task, cells: {variant, trial_id, reward: {[name]: number}, diff_lines: int}[]}`
- `GET /api/bench/trials/{trial_id}` → `{trial_id, variant, task, reward: {[k]: number}, diff: str, cost_usd, steps: {step_id, source, message, tool_calls: {function_name, arguments}[]}[]}`
