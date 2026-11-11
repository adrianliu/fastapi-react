import { useEffect } from "react";
import { api } from "../api/client.ts";
import type { Step } from "../api/types.ts";
import { fmtCost, fmtDate, fmtNum, shortPath, truncate } from "../format.ts";
import { useApi } from "../hooks.ts";
import { Status } from "../ui.tsx";

function StepView({ step, focus }: { step: Step; focus: boolean }) {
  const hasError = step.tool_calls.some((t) => t.is_error);
  const tokens = (step.prompt_tokens ?? 0) + (step.completion_tokens ?? 0);
  return (
    <div
      id={"step-" + String(step.step_id)}
      className={
        "step src-" + step.source + (hasError ? " has-error" : "") + (focus ? " focus" : "")
      }
    >
      <div className="step-meta">
        <span className={"src-tag " + step.source}>{step.source}</span>
        <span className="muted small">#{String(step.step_id)}</span>
        {step.kind && <span className="chip small">{step.kind}</span>}
        <span className="muted small">{fmtDate(step.timestamp)}</span>
        <span className="spacer" />
        {tokens > 0 && <span className="muted small">{fmtNum(tokens)} tok</span>}
        {step.cost_usd !== null && <span className="muted small">{fmtCost(step.cost_usd)}</span>}
      </div>
      {step.reasoning_content && (
        <details className="reasoning">
          <summary>reasoning</summary>
          <pre>{step.reasoning_content}</pre>
        </details>
      )}
      {step.message && <div className="step-msg">{step.message}</div>}
      {step.tool_calls.map((t) => (
        <details key={t.tool_call_id} className={"tool" + (t.is_error ? " tool-error" : "")}>
          <summary>
            <code>{t.function_name}</code>{" "}
            <span className="muted small">{truncate(t.arguments, 100)}</span>
            {t.is_error && <span className="err small"> {t.error_class ?? "error"}</span>}
            {t.duration_ms !== null && <span className="muted small"> · {t.duration_ms} ms</span>}
            {t.subagent_trajectory_id && (
              <a className="small" href={"#/sessions/" + t.subagent_trajectory_id}>
                {" "}
                → subagent
              </a>
            )}
          </summary>
          <div className="tool-body">
            <div className="label">arguments</div>
            <pre>{t.arguments}</pre>
            <div className="label">result</div>
            <pre className={t.is_error ? "err" : ""}>{t.content}</pre>
          </div>
        </details>
      ))}
    </div>
  );
}

export default function SessionPage({ id, focusStep }: { id: string; focusStep?: string }) {
  const state = useApi(() => api.session(id), [id]);
  const loaded = state.data !== null;

  useEffect(() => {
    if (loaded && focusStep) {
      document.getElementById("step-" + focusStep)?.scrollIntoView({ block: "center" });
    }
  }, [loaded, focusStep]);

  return (
    <div>
      <a href="#/sessions" className="back">
        ← Sessions
      </a>
      <Status state={state}>
        {(d) => {
          const s = d.summary;
          return (
            <>
              <header className="page-head">
                <h1>{truncate(s.first_prompt || s.session_id, 80)}</h1>
              </header>
              <div className="meta-row">
                <span className="chip">{s.agent_name}</span>
                <span title={s.project_path}>{shortPath(s.project_path)}</span>
                <span>{s.model_name ?? "—"}</span>
                <span>{fmtDate(s.started_at)}</span>
                <span>{fmtNum(s.total_steps)} steps</span>
                <span>
                  {fmtNum((s.total_prompt_tokens ?? 0) + (s.total_completion_tokens ?? 0))} tokens
                </span>
                <span>{fmtCost(s.total_cost_usd)}</span>
                {s.n_errors > 0 && <span className="err">{s.n_errors} errors</span>}
              </div>
              {d.subagents.length > 0 && (
                <div className="card">
                  <h3>Subagents</h3>
                  <ul className="plain">
                    {d.subagents.map((sa) => (
                      <li key={sa.trajectory_id}>
                        <a href={"#/sessions/" + sa.trajectory_id}>
                          {truncate(sa.first_prompt || sa.trajectory_id, 100)}
                        </a>{" "}
                        <span className="muted small">
                          {sa.total_steps} steps · {fmtCost(sa.total_cost_usd)}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              <div className="timeline">
                {d.steps.map((st) => (
                  <StepView
                    key={String(st.step_id)}
                    step={st}
                    focus={String(st.step_id) === focusStep}
                  />
                ))}
              </div>
            </>
          );
        }}
      </Status>
    </div>
  );
}
