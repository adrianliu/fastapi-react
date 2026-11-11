// Mirrors docs/api.md. Costs are API-price estimates.

export interface Home {
  sessions: number;
  trajectories: number;
  steps: number;
  harnesses: Record<string, number>;
  projects: number;
  first_at: string | null;
  last_at: string | null;
  weeks: number;
  unknown_records: Record<string, number>;
  /** ISO start of the import window (HINDCAST_IMPORT_SINCE), or null for all sessions. */
  import_since: string | null;
}

export interface JobRef {
  job_id: number;
}

export interface SessionSummary {
  trajectory_id: string;
  session_id: string;
  agent_name: string;
  project_path: string;
  model_name: string | null;
  started_at: string | null;
  ended_at: string | null;
  total_steps: number;
  total_prompt_tokens: number | null;
  total_completion_tokens: number | null;
  total_cost_usd: number | null;
  n_errors: number;
  n_subagents: number;
  friction_score: number | null;
  first_prompt: string;
}

export interface SessionList {
  total: number;
  items: SessionSummary[];
}

export interface ToolCall {
  tool_call_id: string;
  function_name: string;
  arguments: string;
  content: string;
  is_error: boolean;
  error_class: string | null;
  duration_ms: number | null;
  subagent_trajectory_id: string | null;
}

export interface Step {
  step_id: number | string;
  timestamp: string | null;
  source: "user" | "agent" | "system";
  message: string;
  reasoning_content: string | null;
  model_name: string | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  cost_usd: number | null;
  turn_index: number;
  kind: string | null;
  tool_calls: ToolCall[];
}

export interface SessionDetail {
  summary: SessionSummary;
  steps: Step[];
  subagents: SessionSummary[];
}

export type JobStatus = "queued" | "running" | "done" | "failed";

export interface Job {
  id: number;
  kind: string;
  status: JobStatus;
  progress: string;
  result: Record<string, unknown> | null;
  error: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface Correction {
  id: number;
  trajectory_id: string;
  step_id: number | string;
  project_path: string;
  timestamp: string | null;
  quote: string;
  agent_before: string;
  signals: Record<string, number>;
}

export interface Group {
  id: number;
  name: string;
  lesson: string;
  n_items: number;
  sessions: number;
  projects: number;
  score: number;
  items: Correction[];
}

export interface FixVersion {
  version: number;
  content: string;
  author: "model" | "user";
  model: string | null;
  created_at: string;
}

export interface Rationale {
  instruction: string;
  correction_ids: number[];
}

export interface Fix {
  id: number;
  group_id: number;
  fix_type: "rule" | "skill" | "hook";
  name: string;
  summary: string;
  versions: FixVersion[];
  rationale: Rationale[];
}

export interface InstallPreview {
  target: string;
  diff: string;
}

export interface InstallResult {
  target: string;
  applied: boolean;
}

export type CheckStatus = "pass" | "fail" | "unknown";

export interface RubricItem {
  id: string;
  text: string;
  kind: string;
  weight: number;
}

export interface Task {
  name: string;
  dataset: string;
  kind: "reconstructed" | "control";
  instruction: string;
  rubric: RubricItem[];
  checks: { nop: CheckStatus; oracle: CheckStatus; install: CheckStatus };
}

export interface EstimateRequest {
  fix_id: number | null;
  variants: number;
  tasks: number;
  repeats: number;
}

export interface Estimate {
  trials: number;
  minutes: number;
  cost_usd: number;
}

export interface RunRequest {
  baseline_config: Record<string, unknown>;
  candidate_config: Record<string, unknown>;
}

export interface BenchRun {
  id: number | string;
  name: string;
  variants: string[];
  n_trials: number;
  started_at: string | null;
  status: string;
}

export interface VariantStats {
  name: string;
  n_trials: number;
  check_pass_rate: number;
  rubric_mean: number;
  metrics: Record<string, number>;
  median_diff_lines: number;
  cost_usd_mean: number;
  tokens_mean: number;
  duration_s_mean: number;
  rule_present: string;
}

export interface ItemRate {
  id: string;
  text: string;
  rates: Record<string, { passed: number; n: number }>;
}

export interface TaskCell {
  variant: string;
  trial_id: string;
  reward: Record<string, number>;
  diff_lines: number;
}

export interface TaskRow {
  task: string;
  cells: TaskCell[];
}

export type Verdict = "better" | "worse" | "no clear difference" | "too few tasks";

export interface Comparison {
  run: number | string;
  variants: VariantStats[];
  items: ItemRate[];
  tasks: TaskRow[];
  verdict: Verdict;
  verdict_detail: string;
}

export interface TrialStep {
  step_id: number | string;
  source: string;
  message: string;
  tool_calls: { function_name: string; arguments: string }[];
}

export interface Trial {
  trial_id: string;
  variant: string;
  task: string;
  reward: Record<string, number>;
  diff: string;
  cost_usd: number | null;
  steps: TrialStep[];
}
