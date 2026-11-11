import { useState } from "react";
import { api } from "../api/client.ts";
import type { Comparison, TaskCell } from "../api/types.ts";
import { fmtCost, fmtDate, fmtNum, fmtPct } from "../format.ts";
import { useApi } from "../hooks.ts";
import { go } from "../router.ts";
import { Bar, DiffView, Status } from "../ui.tsx";

function cellScore(c: TaskCell): number | null {
  const vals = Object.values(c.reward);
  if (vals.length === 0) return null;
  return vals.reduce((a, b) => a + b, 0) / vals.length;
}

function TrialDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const state = useApi(() => api.trial(id), [id]);
  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside
        className="drawer"
        onClick={(e) => {
          e.stopPropagation();
        }}
      >
        <div className="row">
          <h2>Trial {id}</h2>
          <span className="spacer" />
          <button onClick={onClose}>Close</button>
        </div>
        <Status state={state}>
          {(t) => (
            <>
              <div className="meta-row">
                <span className="chip">{t.variant}</span>
                <span>{t.task}</span>
                <span>{fmtCost(t.cost_usd)}</span>
                {Object.entries(t.reward).map(([k, v]) => (
                  <span key={k}>
                    {k}: <b>{v.toFixed(2)}</b>
                  </span>
                ))}
              </div>
              <h3>Diff</h3>
              <DiffView diff={t.diff} />
              <h3>Trajectory</h3>
              <div className="timeline compact">
                {t.steps.map((s) => (
                  <div key={String(s.step_id)} className={"step src-" + s.source}>
                    <span className={"src-tag " + s.source}>{s.source}</span>{" "}
                    {s.message && <span className="step-msg">{s.message}</span>}
                    {s.tool_calls.map((tc, i) => (
                      <div key={i} className="tool-line">
                        <code>{tc.function_name}</code>{" "}
                        <span className="muted small">{tc.arguments}</span>
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            </>
          )}
        </Status>
      </aside>
    </div>
  );
}

function ComparisonView({ c }: { c: Comparison }) {
  const [trial, setTrial] = useState<string | null>(null);
  const names = c.variants.map((v) => v.name);
  const verdictClass = c.verdict.replace(/ /g, "-");
  return (
    <>
      <div className={"verdict " + verdictClass}>
        <div className="verdict-title">Verdict: {c.verdict}</div>
        <div>{c.verdict_detail}</div>
      </div>
      <table className="table stats">
        <thead>
          <tr>
            <th />
            {c.variants.map((v) => (
              <th key={v.name}>{v.name}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Trials</td>
            {c.variants.map((v) => (
              <td key={v.name}>{v.n_trials}</td>
            ))}
          </tr>
          <tr>
            <td>Check pass rate</td>
            {c.variants.map((v) => (
              <td key={v.name}>
                {fmtPct(v.check_pass_rate)} <Bar value={v.check_pass_rate} />
              </td>
            ))}
          </tr>
          <tr>
            <td>Rubric mean</td>
            {c.variants.map((v) => (
              <td key={v.name}>
                {v.rubric_mean.toFixed(2)} <Bar value={v.rubric_mean} />
              </td>
            ))}
          </tr>
          <tr>
            <td>Median diff lines</td>
            {c.variants.map((v) => (
              <td key={v.name}>{fmtNum(v.median_diff_lines)}</td>
            ))}
          </tr>
          <tr>
            <td>Mean est. cost</td>
            {c.variants.map((v) => (
              <td key={v.name}>{fmtCost(v.cost_usd_mean)}</td>
            ))}
          </tr>
          <tr>
            <td>Mean tokens</td>
            {c.variants.map((v) => (
              <td key={v.name}>{fmtNum(Math.round(v.tokens_mean))}</td>
            ))}
          </tr>
          <tr>
            <td>Mean duration</td>
            {c.variants.map((v) => (
              <td key={v.name}>{v.duration_s_mean.toFixed(0)} s</td>
            ))}
          </tr>
          <tr>
            <td>Rule present</td>
            {c.variants.map((v) => (
              <td key={v.name}>{v.rule_present}</td>
            ))}
          </tr>
        </tbody>
      </table>

      <h2>Rubric items</h2>
      {c.items.length === 0 && <div className="empty">No rubric items.</div>}
      <table className="table">
        <tbody>
          {c.items.map((it) => (
            <tr key={it.id}>
              <td>{it.text}</td>
              <td className="rates">
                {names.map((n, i) => {
                  const r = it.rates[n];
                  return (
                    <span key={n} className="rate">
                      {i > 0 && <span className="arrow">→</span>}
                      <span className="muted small">{n}</span>{" "}
                      <b>{r ? String(r.passed) + "/" + String(r.n) : "—"}</b>{" "}
                      <Bar
                        value={r && r.n > 0 ? r.passed / r.n : 0}
                        tone={i === 0 ? "base" : "cand"}
                      />
                    </span>
                  );
                })}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>Per task</h2>
      <table className="table grid">
        <thead>
          <tr>
            <th>Task</th>
            {names.map((n) => (
              <th key={n}>{n}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {c.tasks.map((row) => (
            <tr key={row.task}>
              <td>{row.task}</td>
              {names.map((n) => (
                <td key={n}>
                  <div className="cells">
                    {row.cells
                      .filter((cell) => cell.variant === n)
                      .map((cell) => {
                        const s = cellScore(cell);
                        const tone =
                          s === null ? "" : s >= 0.75 ? "good" : s >= 0.4 ? "mid" : "bad";
                        return (
                          <button
                            key={cell.trial_id}
                            className={"cell " + tone}
                            title={Object.entries(cell.reward)
                              .map(([k, v]) => k + "=" + v.toFixed(2))
                              .join(" ")}
                            onClick={() => {
                              setTrial(cell.trial_id);
                            }}
                          >
                            {s === null ? "?" : s.toFixed(2)}
                            <span className="small"> ±{cell.diff_lines}</span>
                          </button>
                        );
                      })}
                  </div>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {trial && (
        <TrialDrawer
          id={trial}
          onClose={() => {
            setTrial(null);
          }}
        />
      )}
    </>
  );
}

export default function ComparisonPage({ run }: { run?: string }) {
  const runs = useApi(() => api.runs(), []);
  const selected = run ?? (runs.data?.[0] ? String(runs.data[0].id) : undefined);
  return (
    <div>
      <header className="page-head">
        <h1>Comparison</h1>
        <select
          value={selected ?? ""}
          onChange={(e) => {
            go("comparison/" + e.target.value);
          }}
        >
          {selected === undefined && <option value="">No runs</option>}
          {(runs.data ?? []).map((r) => (
            <option key={String(r.id)} value={String(r.id)}>
              {r.name} · {r.n_trials} trials · {r.status} · {fmtDate(r.started_at)}
            </option>
          ))}
        </select>
      </header>
      {runs.error && <div className="error-box">Runs: {runs.error}</div>}
      {selected === undefined ? (
        runs.loading ? (
          <div className="muted pad">Loading…</div>
        ) : (
          <div className="empty">
            No bench runs yet. <a href="#/run">Start one</a>.
          </div>
        )
      ) : (
        <ComparisonLoader run={selected} />
      )}
    </div>
  );
}

function ComparisonLoader({ run }: { run: string }) {
  const state = useApi(() => api.comparison(run), [run]);
  return <Status state={state}>{(c) => <ComparisonView c={c} />}</Status>;
}
