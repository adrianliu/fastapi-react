import { useEffect, useState } from "react";

// Mirrors backend/hindcast/models.py.
export type Harness = "claude-code" | "codex";
export type Origin = "organic" | "benchmark";
export type ToolKind =
  "shell" | "read" | "edit" | "search" | "web" | "mcp" | "subagent" | "skill" | "other";
export type ReviewState = "pending" | "confirmed" | "rejected" | "edited";
export type SpanRole =
  "request" | "requirement" | "attempt" | "correction" | "outcome" | "solution_hint";
export type Readiness = "needs_review" | "blocked" | "ready_for_task_build";
export type Verdict = "better" | "worse" | "no_clear_difference" | "too_few_tasks";
export type TrialStatus = "queued" | "running" | "passed" | "failed";

export interface ToolCall {
  tool_call_id: string;
  function_name: string;
  tool_kind: ToolKind;
  summary: string;
  content: string | null;
  is_error: boolean;
  error_class: string | null;
  started_at: string;
  duration_ms: number;
  subagent_trajectory_id: string | null;
}

export interface Step {
  step_id: number;
  timestamp: string;
  source: "system" | "user" | "agent";
  message: string;
  reasoning_content: string | null;
  model_name: string | null;
  stop_reason: string | null;
  turn_index: number;
  prompt_tokens: number | null;
  cached_tokens: number | null;
  completion_tokens: number | null;
  cost_usd: number | null;
  duration_ms: number;
  is_compaction: boolean;
  tool_calls: ToolCall[];
}

export interface SubagentTrajectory {
  trajectory_id: string;
  parent_tool_call_id: string;
  subagent_kind: string;
  task: string;
  steps: Step[];
  total_cost_usd: number;
  tool_errors: number;
}

export interface Signal {
  name: string;
  count: number;
  weight: number;
  points: number;
}

export interface FrictionItem {
  type: string;
  severity: number;
  user_corrected: boolean;
  evidence_step_ids: number[];
  resolution_step_ids: number[];
  explanation: string;
  instruction_quote: string | null;
}

export interface Label {
  label_id: string;
  intent: string;
  task_type: string;
  outcome: string;
  outcome_reason: string;
  friction: FrictionItem[];
  review_state: ReviewState;
  model: string;
  prompt_version: string;
  condenser_version: string;
  input_sha256: string;
  input_chars: number;
  cost_usd: number;
}

export interface Episode {
  turn_index: number;
  first_step_id: number;
  last_step_id: number;
  reaction_step_id: number | null;
  prompt: string;
  score: number;
  signals: Signal[];
  cost_usd: number;
  tool_errors: number;
  label: Label | null;
}

export interface SessionSummary {
  trajectory_id: string;
  title: string;
  project_path: string;
  agent_name: Harness;
  agent_version: string;
  model_name: string;
  origin: Origin;
  git_branch: string | null;
  git_commit: string | null;
  git_dirty: boolean;
  started_at: string;
  ended_at: string;
  total_steps: number;
  subagent_count: number;
  total_prompt_tokens: number;
  total_cached_tokens: number;
  total_completion_tokens: number;
  total_cost_usd: number;
  tool_errors: number;
  turns: number;
  friction_score: number;
  friction_types: string[];
  has_friction_label: boolean;
  has_candidates: boolean;
}

export interface SessionDetail extends SessionSummary {
  steps: Step[];
  subagents: SubagentTrajectory[];
  episodes: Episode[];
}

export interface Meta {
  data_source: "demo";
  sessions: number;
  by_harness: Record<string, number>;
  projects: number;
  first_started_at: string;
  last_started_at: string;
}

export interface Span {
  role: SpanRole;
  trajectory_id: string;
  from_step: number;
  to_step: number;
  excerpt: string | null;
}

export interface TaskCandidate {
  candidate_id: string;
  revision: number;
  title: string;
  objective: string;
  readiness: Readiness;
  blocked_reasons: string[];
  criteria: { text: string; step_ids: number[] }[];
  spans: Span[];
  starting_state: { fact: string; status: "known" | "unknown"; step_ids: number[] }[];
  depends_on: { candidate_id: string; reason: string; step_ids: number[] }[];
  open_questions: string[];
  instruction: string;
}

export interface CandidateSet {
  trajectory_id: string;
  session_title: string;
  proposal_set: number;
  model: string;
  prompt_version: string;
  condenser_version: string;
  turns: { turn_index: number; first_step_id: number; last_step_id: number; prompt: string }[];
  candidates: TaskCandidate[];
}

export interface Trial {
  task: string;
  variant: string;
  repeat: number;
  status: TrialStatus;
  score: number | null;
  check_pass: boolean | null;
  diff_lines: number | null;
  note: string | null;
  items: Record<string, boolean>;
  fix_applied: boolean | null;
  tool_errors: number | null;
  tokens: number | null;
  duration_s: number | null;
  cost_usd: number | null;
  trajectory_id: string | null;
}

export interface VariantStats {
  variant: string;
  trials: number;
  check_pass: number;
  rubric_mean: number;
  median_diff_lines: number;
  new_config: number;
  item_trials: number;
  mean_tool_errors: number;
  mean_tokens: number;
  mean_duration_s: number;
  mean_cost_usd: number;
  fix_applied: number | null;
}

export interface ItemRate {
  key: string;
  label: string;
  bad: boolean;
  baseline: number;
  candidate: number;
  n: number;
}

export interface Bootstrap {
  verdict: Verdict;
  delta: number;
  ci_low: number;
  ci_high: number;
  margin: number;
  resamples: number;
  paired_tasks: number;
  histogram: number[];
  hist_min: number;
  hist_max: number;
}

export interface EvalRunSummary {
  run_id: string;
  title: string;
  dataset: string;
  status: "running" | "finished";
  started_at: string;
  trials_total: number;
  trials_done: number;
  verdict: Verdict | null;
}

export interface EvalRun extends EvalRunSummary {
  fix_name: string;
  fix_kind: "skill" | "rule" | "hook";
  harness: string;
  model: string;
  harbor_version: string;
  rewardkit_version: string;
  bench_commit: string;
  repeats: number;
  variants: string[];
  tasks: { name: string; source: string; control: boolean }[];
  rubric: { key: string; label: string; bad: boolean }[];
  trials: Trial[];
  stats: VariantStats[];
  items: ItemRate[];
  bootstrap: Bootstrap | null;
  duration_s: number | null;
  cost_usd: number;
}

export interface Dataset {
  key: string;
  name: string;
  version: string;
  tasks: number;
}

export interface LeaderboardEntry {
  rank: number;
  model: string;
  harness: string;
  harness_version: string;
  fixes: string[];
  resolved_pct: number;
  ci_low: number;
  ci_high: number;
  delta_vs_baseline: number | null;
  rubric_mean: number;
  cost_per_task: number;
  median_steps: number;
  trials: number;
  date: string;
  eval_run_id: string | null;
}

export interface FixImpact {
  name: string;
  kind: "skill" | "rule" | "hook";
  version: number;
  delta: number;
  verdict: Verdict;
  applied: string;
}

export interface Leaderboard {
  dataset: Dataset;
  datasets: Dataset[];
  entries: LeaderboardEntry[];
  fixes: FixImpact[];
}

declare const responseType: unique symbol;
/** A URL tagged with the JSON type its endpoint returns. */
export type Endpoint<T> = string & { readonly [responseType]?: T };

const q = encodeURIComponent;
export const endpoints = {
  meta: "/api/hindcast/meta" as Endpoint<Meta>,
  sessions: (params?: URLSearchParams) =>
    `/api/hindcast/sessions${params ? "?" + params.toString() : ""}` as Endpoint<SessionSummary[]>,
  session: (id: string) => `/api/hindcast/sessions/${q(id)}` as Endpoint<SessionDetail>,
  candidates: (id: string) =>
    `/api/hindcast/sessions/${q(id)}/candidates` as Endpoint<CandidateSet>,
  evals: "/api/hindcast/evals" as Endpoint<EvalRunSummary[]>,
  evalRun: (id: string) => `/api/hindcast/evals/${q(id)}` as Endpoint<EvalRun>,
  leaderboard: (dataset: string) =>
    `/api/hindcast/leaderboard?dataset=${q(dataset)}` as Endpoint<Leaderboard>,
};

export async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, options);
  if (!res.ok) throw new Error(`Request failed (${String(res.status)})`);
  return (await res.json()) as T;
}

export function reviewLabel(labelId: string, state: "pending" | "confirmed" | "rejected") {
  return request<{ state: ReviewState }>(
    `/api/hindcast/labels/${encodeURIComponent(labelId)}/review`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ state }),
    },
  );
}

interface FetchState<T> {
  url: string;
  data: T | null;
  error: string | null;
}

/** Fetch JSON for `url`; refetches when it changes. `loading` is true until this url resolves. */
export function useFetch<T>(url: Endpoint<T>) {
  const [state, setState] = useState<FetchState<T>>({ url: "", data: null, error: null });

  useEffect(() => {
    let live = true;
    request<T>(url)
      .then((data) => {
        if (live) setState({ url, data, error: null });
      })
      .catch((e: unknown) => {
        if (live) setState({ url, data: null, error: e instanceof Error ? e.message : "Error" });
      });
    return () => {
      live = false;
    };
  }, [url]);

  const current = state.url === url;
  return {
    data: current ? state.data : null,
    error: current ? state.error : null,
    loading: !current,
  };
}
