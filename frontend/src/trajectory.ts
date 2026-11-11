import type { Episode, Label, SessionDetail, Step, ToolCall, ToolKind } from "./api";

export const KIND_COLOR: Record<ToolKind | "model" | "user", string> = {
  user: "var(--blue)",
  model: "var(--k-model)",
  read: "var(--k-read)",
  search: "var(--k-read)",
  edit: "var(--k-edit)",
  shell: "var(--k-shell)",
  web: "var(--k-web)",
  subagent: "var(--sub)",
  mcp: "var(--k-web)",
  skill: "var(--k-web)",
  other: "var(--k-web)",
};

export interface Bar {
  key: string;
  left: number;
  width: number;
  color: string;
  error: boolean;
  title: string;
  stepId: number;
}

export interface Lane {
  name: string;
  bars: Bar[];
}

const LANES: { name: string; kinds: ToolKind[] }[] = [
  { name: "read / search", kinds: ["read", "search"] },
  { name: "edit", kinds: ["edit"] },
  { name: "shell", kinds: ["shell"] },
  { name: "web / other", kinds: ["web", "mcp", "skill", "other"] },
  { name: "subagents", kinds: ["subagent"] },
];

export interface TurnBand {
  turn: number;
  left: number;
  width: number;
  score: number;
}

export interface MapModel {
  turns: TurnBand[];
  lanes: Lane[];
  context: { left: number; height: number; stepId: number; turn: number; tokens: number }[];
  compactions: number[];
  ticks: { left: number; label: string }[];
  maxContext: number;
}

export function timeScale(start: string, end: string) {
  const t0 = Date.parse(start);
  const span = Math.max(1, Date.parse(end) - t0);
  return {
    at: (iso: string) => ((Date.parse(iso) - t0) / span) * 100,
    len: (ms: number) => (ms / span) * 100,
  };
}

export function buildMap(s: SessionDetail): MapModel {
  const { at, len } = timeScale(s.started_at, s.ended_at);
  const byStep = new Map(s.steps.map((st) => [st.step_id, st]));
  const stepTime = (id: number) => byStep.get(id)?.timestamp ?? s.ended_at;

  const turns = s.episodes.map((e, i) => {
    const next = s.episodes[i + 1];
    const left = at(stepTime(e.first_step_id));
    const right = next ? at(stepTime(next.first_step_id)) : 100;
    return { turn: e.turn_index, left, width: Math.max(0.4, right - left), score: e.score };
  });

  const user: Bar[] = [];
  const model: Bar[] = [];
  const tool = new Map<string, Bar[]>(LANES.map((l) => [l.name, []]));
  for (const st of s.steps) {
    if (st.source === "user") {
      user.push({
        key: `u${String(st.step_id)}`,
        left: at(st.timestamp),
        width: 0.35,
        color: KIND_COLOR.user,
        error: false,
        title: `s${String(st.step_id)} user: ${st.message.slice(0, 80)}`,
        stepId: st.step_id,
      });
    }
    if (st.source !== "agent") continue;
    model.push({
      key: `m${String(st.step_id)}`,
      left: at(st.timestamp),
      width: len(st.duration_ms),
      color: KIND_COLOR.model,
      error: false,
      title: `s${String(st.step_id)} model call`,
      stepId: st.step_id,
    });
    for (const c of st.tool_calls) {
      const lane = LANES.find((l) => l.kinds.includes(c.tool_kind)) ?? LANES[3];
      if (!lane) continue;
      tool.get(lane.name)?.push({
        key: c.tool_call_id,
        left: at(c.started_at),
        width: len(c.duration_ms),
        color: KIND_COLOR[c.tool_kind],
        error: c.is_error,
        title: `s${String(st.step_id)} ${c.summary}${c.is_error ? ` (${c.error_class ?? "error"})` : ""}`,
        stepId: st.step_id,
      });
    }
  }

  const agentSteps = s.steps.filter((st) => st.source === "agent");
  const maxContext = Math.max(1, ...agentSteps.map((st) => st.prompt_tokens ?? 0));
  const context = agentSteps.map((st) => ({
    left: at(st.timestamp),
    height: ((st.prompt_tokens ?? 0) / maxContext) * 100,
    stepId: st.step_id,
    turn: st.turn_index,
    tokens: st.prompt_tokens ?? 0,
  }));

  const total = Date.parse(s.ended_at) - Date.parse(s.started_at);
  const stepMs = [60_000, 300_000, 600_000, 900_000, 1_800_000, 3_600_000].find(
    (m) => total / m <= 7,
  );
  const ticks: { left: number; label: string }[] = [];
  const start = Date.parse(s.started_at);
  const every = stepMs ?? 3_600_000;
  for (let t = Math.ceil(start / every) * every; t < start + total; t += every) {
    ticks.push({
      left: ((t - start) / total) * 100,
      label: new Date(t).toISOString().slice(11, 16),
    });
  }

  return {
    turns,
    lanes: [
      { name: "user", bars: user },
      { name: "model calls", bars: model },
      ...LANES.map((l) => ({ name: l.name, bars: tool.get(l.name) ?? [] })),
    ],
    context,
    compactions: s.steps.filter((st) => st.is_compaction).map((st) => at(st.timestamp)),
    ticks,
    maxContext,
  };
}

export interface WaterfallRow {
  key: string;
  id: string;
  label: string;
  color: string;
  left: number;
  width: number;
  duration: number;
  flag: boolean;
  stepId: number;
}

export function buildWaterfall(s: SessionDetail, ep: Episode): WaterfallRow[] {
  const steps = s.steps.filter(
    (st) => st.step_id >= ep.first_step_id && st.step_id <= ep.last_step_id,
  );
  const reaction = s.steps.find((st) => st.step_id === ep.reaction_step_id);
  const first = steps[0];
  if (!first) return [];
  const last = steps[steps.length - 1] ?? first;
  const endOf = (st: Step) =>
    Math.max(
      Date.parse(st.timestamp) + st.duration_ms,
      ...st.tool_calls.map((c) => Date.parse(c.started_at) + c.duration_ms),
    );
  const t0 = Date.parse(first.timestamp);
  const t1 = reaction ? Date.parse(reaction.timestamp) + 2000 : endOf(last);
  const span = Math.max(1, t1 - t0);
  const pos = (iso: string) => ((Date.parse(iso) - t0) / span) * 100;
  const evidence = new Set(ep.label?.friction.flatMap((f) => f.evidence_step_ids) ?? []);

  const rows: WaterfallRow[] = [];
  const all = reaction ? [...steps, reaction] : steps;
  for (const st of all) {
    const id = `s${String(st.step_id)}`;
    const flag = evidence.has(st.step_id);
    if (st.source === "user" || st.source === "system") {
      rows.push({
        key: id,
        id,
        label:
          st === reaction ? "user reaction" : st.source === "user" ? "user prompt" : "compaction",
        color:
          st === reaction ? "var(--hot)" : st.source === "user" ? "var(--blue)" : "var(--warn-ink)",
        left: pos(st.timestamp),
        width: (Math.max(st.duration_ms, 1500) / span) * 100,
        duration: st.duration_ms,
        flag,
        stepId: st.step_id,
      });
      continue;
    }
    rows.push({
      key: id + "m",
      id,
      label: st.message ? `model · “${st.message.slice(0, 40)}”` : "model call",
      color: KIND_COLOR.model,
      left: pos(st.timestamp),
      width: (st.duration_ms / span) * 100,
      duration: st.duration_ms,
      flag: flag && st.tool_calls.length === 0,
      stepId: st.step_id,
    });
    st.tool_calls.forEach((c: ToolCall) => {
      rows.push({
        key: c.tool_call_id,
        id,
        label: c.summary,
        color: c.is_error ? "var(--err)" : KIND_COLOR[c.tool_kind],
        left: pos(c.started_at),
        width: (c.duration_ms / span) * 100,
        duration: c.duration_ms,
        flag,
        stepId: st.step_id,
      });
    });
  }
  return rows;
}

export function evidenceIds(label: Label | null): Set<number> {
  return new Set(label?.friction.flatMap((f) => f.evidence_step_ids) ?? []);
}

/** Group a turn's steps: runs of >=3 quiet steps (no message, no errors, not evidence) collapse. */
export type Block = { kind: "step"; step: Step } | { kind: "run"; steps: Step[] };

export function blocks(steps: Step[], keep: Set<number>): Block[] {
  const out: Block[] = [];
  let run: Step[] = [];
  const quiet = (st: Step) =>
    st.source === "agent" &&
    !st.message &&
    !st.reasoning_content &&
    !keep.has(st.step_id) &&
    st.tool_calls.every((c) => !c.is_error && c.tool_kind !== "subagent");
  const flush = () => {
    if (run.length >= 3) out.push({ kind: "run", steps: run });
    else run.forEach((st) => out.push({ kind: "step", step: st }));
    run = [];
  };
  for (const st of steps) {
    if (quiet(st)) {
      run.push(st);
    } else {
      flush();
      out.push({ kind: "step", step: st });
    }
  }
  flush();
  return out;
}
