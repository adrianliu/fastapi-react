import type { Episode, Step, SubagentTrajectory, ToolCall } from "../api";
import { clock, ms, plural, stepRange, tokens, usd } from "../format";
import { blocks } from "../trajectory";

export interface ViewOptions {
  reasoning: boolean;
  subagents: boolean;
  onlyErrors: boolean;
  system: boolean;
}

interface StepProps {
  step: Step;
  evidence: Set<number>;
  subagents: Map<string, SubagentTrajectory>;
  options: ViewOptions;
  reactionOf?: boolean;
  flash: boolean;
}

function Call({ call }: { call: ToolCall }) {
  return (
    <details className={call.is_error ? "call err" : "call"} open={call.is_error}>
      <summary>
        <span
          className={call.is_error ? "dot err" : "dot"}
          aria-label={call.is_error ? "error" : "ok"}
        />
        <span className="muted">{call.tool_kind}</span>
        <span className="ellipsis" title={call.summary}>
          {call.summary}
        </span>
        <span style={{ color: call.is_error ? "var(--err-ink)" : "var(--muted)" }}>
          {ms(call.duration_ms)}
        </span>
      </summary>
      <pre>
        {call.is_error && (
          <strong style={{ color: "var(--err-ink)" }}>
            ERROR {call.error_class ?? ""}
            {"\n"}
          </strong>
        )}
        {call.content ?? `${call.function_name} · no result text recorded`}
      </pre>
    </details>
  );
}

function Subagent({ call, sub }: { call: ToolCall; sub: SubagentTrajectory }) {
  const answer = sub.steps.filter((s) => s.message).at(-1);
  return (
    <details className="subagent" open>
      <summary>
        <span style={{ fontWeight: 600, color: "var(--sub-ink)" }}>
          Subagent · {sub.subagent_kind}
        </span>
        <span className="grow" style={{ color: "var(--ink-2)", flexBasis: 200 }}>
          “{sub.task}”
        </span>
        <span className="mono small" style={{ color: "var(--sub-ink)" }}>
          {sub.trajectory_id} · {plural(sub.steps.length, "step")} ·{" "}
          {plural(sub.tool_errors, "error")} · {usd(sub.total_cost_usd)} · {ms(call.duration_ms)}
        </span>
      </summary>
      <div className="inner">
        {sub.steps.flatMap((s) =>
          s.tool_calls.map((c) => (
            <div
              key={c.tool_call_id}
              className="row mono"
              style={{ fontSize: 12.5, flexWrap: "nowrap" }}
            >
              <span className="muted" style={{ width: 28 }}>
                s{s.step_id}
              </span>
              <span className={c.is_error ? "dot err" : "dot"} />
              <span className="muted" style={{ width: 56 }}>
                {c.tool_kind}
              </span>
              <span className="ellipsis grow">{c.summary}</span>
              <span className="muted">{ms(c.duration_ms)}</span>
            </div>
          )),
        )}
        {answer && (
          <div
            className="row"
            style={{ fontSize: 13, flexWrap: "nowrap", alignItems: "flex-start" }}
          >
            <span className="mono muted" style={{ width: 28, fontSize: 12.5 }}>
              s{answer.step_id}
            </span>
            <span style={{ color: "var(--ink-2)" }}>{answer.message}</span>
          </div>
        )}
      </div>
    </details>
  );
}

export function StepView({ step, evidence, subagents, options, reactionOf, flash }: StepProps) {
  const isEvidence = evidence.has(step.step_id);
  const cls = [
    "step",
    step.source === "agent" ? "" : step.source,
    isEvidence ? "evidence" : "",
    flash ? "flash" : "",
  ]
    .filter(Boolean)
    .join(" ");
  const calls = options.onlyErrors ? step.tool_calls.filter((c) => c.is_error) : step.tool_calls;
  return (
    <article id={`${reactionOf ? "reaction" : "step"}-${String(step.step_id)}`} className={cls}>
      <span
        className="step-id"
        style={isEvidence ? { color: "var(--hot-score)", fontWeight: 600 } : undefined}
      >
        s{step.step_id}
      </span>
      <div style={{ minWidth: 0 }}>
        <div
          className="step-who"
          style={step.source === "user" ? { color: "var(--blue-ink)" } : undefined}
        >
          {step.source === "user"
            ? reactionOf
              ? "USER · reaction"
              : "USER · prompt"
            : step.source.toUpperCase()}
          {step.stop_reason && (
            <span className="mono muted" style={{ fontWeight: 400 }}>
              stop {step.stop_reason}
            </span>
          )}
          {isEvidence && <span className="chip hot">evidence</span>}
          {step.is_compaction && <span className="chip warn">compaction</span>}
        </div>
        {options.reasoning && step.reasoning_content && (
          <details className="reasoning">
            <summary>Reasoning</summary>
            <p>{step.reasoning_content}</p>
          </details>
        )}
        {step.message && (
          <p style={step.source === "user" ? { fontSize: 15 } : undefined}>{step.message}</p>
        )}
        {calls.map((c) => {
          const sub = c.subagent_trajectory_id
            ? subagents.get(c.subagent_trajectory_id)
            : undefined;
          return sub && options.subagents ? (
            <Subagent key={c.tool_call_id} call={c} sub={sub} />
          ) : (
            <Call key={c.tool_call_id} call={c} />
          );
        })}
      </div>
      <div className="step-meta">
        {clock(step.timestamp)}
        {step.prompt_tokens !== null && (
          <>
            <br />
            {tokens(step.prompt_tokens)} in · {tokens(step.cached_tokens ?? 0)} cached
            <br />
            {tokens(step.completion_tokens ?? 0)} out · {usd(step.cost_usd ?? 0, 3)}
          </>
        )}
      </div>
    </article>
  );
}

interface EpisodeProps {
  episode: Episode;
  steps: Step[];
  reaction: Step | undefined;
  open: boolean;
  selected: boolean;
  onToggle: () => void;
  evidence: Set<number>;
  subagents: Map<string, SubagentTrajectory>;
  options: ViewOptions;
  flashStep: number | null;
}

export function EpisodeView(p: EpisodeProps) {
  const { episode: ep } = p;
  const hot = ep.score >= 4;
  const visible = p.steps.filter(
    (s) =>
      (p.options.system || s.source !== "system" || s.is_compaction) &&
      (!p.options.onlyErrors || s.source === "user" || s.tool_calls.some((c) => c.is_error)),
  );
  const keep = new Set([...p.evidence, ...(p.flashStep !== null ? [p.flashStep] : [])]);
  const reactionStep = p.reaction;
  return (
    <section
      id={`turn-${String(ep.turn_index)}`}
      className={["episode", hot ? "hot" : "", p.open ? "open" : ""].join(" ")}
      aria-label={`Turn ${String(ep.turn_index)}`}
    >
      <button type="button" className="episode-head" aria-expanded={p.open} onClick={p.onToggle}>
        <span className="mono" style={{ fontWeight: 700 }}>
          T{ep.turn_index}
        </span>
        <span className="grow ellipsis" style={{ flexBasis: 240, color: "var(--ink-2)" }}>
          {p.open ? (hot ? "Episode · turn + reaction" : "Turn") : `“${ep.prompt}”`}
        </span>
        {p.open &&
          ep.signals.map((s) => (
            <span key={s.name} className="chip outline">
              {s.name}{" "}
              {s.count > 1 ? `${String(s.count)} × ${String(s.weight)}` : `+${String(s.points)}`}
            </span>
          ))}
        <span className="mono small muted">
          {stepRange(ep.first_step_id, ep.last_step_id)} · {plural(ep.tool_errors, "error")} ·{" "}
          {usd(ep.cost_usd)}
        </span>
        <span
          className="mono"
          style={{ fontWeight: 700, color: hot ? "var(--hot-score)" : "var(--muted)" }}
        >
          score {ep.score.toFixed(1)}
        </span>
        {ep.label && <span className="chip hot">labelled</span>}
      </button>
      {p.open && (
        <div>
          {blocks(visible, keep).map((b) =>
            b.kind === "step" ? (
              <StepView
                key={b.step.step_id}
                step={b.step}
                evidence={p.evidence}
                subagents={p.subagents}
                options={p.options}
                flash={p.flashStep === b.step.step_id}
              />
            ) : (
              <details key={`run-${String(b.steps[0]?.step_id ?? 0)}`} className="collapsed">
                <summary>
                  {stepRange(b.steps[0]?.step_id ?? 0, b.steps.at(-1)?.step_id ?? 0)} ·{" "}
                  {plural(
                    b.steps.reduce((n, s) => n + s.tool_calls.length, 0),
                    "call",
                  )}{" "}
                  ({summarizeKinds(b.steps)}) · 0 errors ·{" "}
                  {usd(b.steps.reduce((n, s) => n + (s.cost_usd ?? 0), 0))}
                </summary>
                {b.steps.map((s) => (
                  <StepView
                    key={s.step_id}
                    step={s}
                    evidence={p.evidence}
                    subagents={p.subagents}
                    options={p.options}
                    flash={false}
                  />
                ))}
              </details>
            ),
          )}
          {reactionStep && (
            <StepView
              step={reactionStep}
              evidence={p.evidence}
              subagents={p.subagents}
              options={p.options}
              reactionOf
              flash={p.flashStep === reactionStep.step_id}
            />
          )}
        </div>
      )}
    </section>
  );
}

function summarizeKinds(steps: Step[]): string {
  const counts = new Map<string, number>();
  for (const s of steps)
    for (const c of s.tool_calls)
      counts.set(c.function_name, (counts.get(c.function_name) ?? 0) + 1);
  return [...counts].map(([k, n]) => `${k}×${String(n)}`).join(", ");
}
