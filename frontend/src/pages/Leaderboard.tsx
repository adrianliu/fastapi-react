import { useState } from "react";
import { endpoints, useFetch, type LeaderboardEntry, type Verdict } from "../api";
import { href } from "../router";

const VERDICT_TEXT: Record<Verdict, string> = {
  better: "better",
  worse: "worse",
  no_clear_difference: "no clear difference",
  too_few_tasks: "too few tasks",
};

function setupKey(e: LeaderboardEntry) {
  return `${e.model}|${e.harness}`;
}

export default function LeaderboardPage() {
  const [dataset, setDataset] = useState("all");
  const [harness, setHarness] = useState("");
  const [showBase, setShowBase] = useState(true);
  const [showFixed, setShowFixed] = useState(true);
  const { data, error } = useFetch(endpoints.leaderboard(dataset));

  const entries = (data?.entries ?? []).filter(
    (e) => (!harness || e.harness === harness) && (e.fixes.length ? showFixed : showBase),
  );
  const pairs = [...new Set((data?.entries ?? []).map(setupKey))]
    .map((key) => {
      const rows = (data?.entries ?? []).filter((e) => setupKey(e) === key);
      return {
        key,
        base: rows.find((e) => !e.fixes.length),
        fixed: rows.find((e) => e.fixes.length),
      };
    })
    .filter((p) => !harness || p.key.endsWith(`|${harness}`))
    .sort((a, b) => (b.fixed?.resolved_pct ?? 0) - (a.fixed?.resolved_pct ?? 0));

  return (
    <div className="page narrow">
      <div className="row between" style={{ alignItems: "flex-end" }}>
        <div>
          <h1 style={{ fontSize: 24 }}>Leaderboard</h1>
          <p className="muted" style={{ marginTop: 4, maxWidth: 760 }}>
            Agent setups ranked on your private benchmark: tasks rebuilt from your own sessions. A
            setup is a harness, a model and the fixes installed. Canary-tagged and never published.
          </p>
        </div>
      </div>

      <div className="tabs" role="tablist" aria-label="Dataset">
        {(data?.datasets ?? []).map((d) => (
          <button
            key={d.key}
            type="button"
            role="tab"
            aria-selected={d.key === dataset}
            onClick={() => {
              setDataset(d.key);
            }}
          >
            {d.name}{" "}
            <span className="mono" style={{ fontWeight: 400 }}>
              {d.key === "all" ? `${d.version} · ` : ""}
              {d.tasks}
            </span>
          </button>
        ))}
      </div>
      {error && <p className="alert">Could not load the leaderboard ({error}).</p>}

      {data && (
        <>
          <div className="cols" style={{ gap: 16, alignItems: "stretch" }}>
            <section
              className="panel pad stack"
              style={{ flex: "2 1 640px", minWidth: 0, gap: 10 }}
            >
              <div className="row between">
                <h2>% resolved · baseline vs with your fixes</h2>
                <span className="small muted">
                  3 repeats per task · whisker = bootstrap 95 % CI
                </span>
              </div>
              {pairs.map((p) => (
                <div key={p.key} className="pairbar">
                  <span style={{ fontSize: 13, fontWeight: 500 }}>{p.key.replace("|", " · ")}</span>
                  <div className="stack" style={{ gap: 3 }}>
                    {p.base && (
                      <div className="hbar" title={`baseline ${p.base.resolved_pct.toFixed(1)}%`}>
                        <div
                          className="fill"
                          style={{
                            width: `${String(p.base.resolved_pct)}%`,
                            background: "#b8bdc6",
                          }}
                        />
                        <span
                          className="lbl"
                          style={{ left: `calc(${String(p.base.resolved_pct)}% + 6px)` }}
                        >
                          {p.base.resolved_pct.toFixed(1)}
                        </span>
                      </div>
                    )}
                    {p.fixed && (
                      <div
                        className="hbar"
                        title={`with fixes ${p.fixed.resolved_pct.toFixed(1)}%`}
                      >
                        <div
                          className="fill"
                          style={{
                            width: `${String(p.fixed.resolved_pct)}%`,
                            background: "var(--blue)",
                          }}
                        />
                        <div
                          className="ci"
                          style={{
                            left: `${String(p.fixed.ci_low)}%`,
                            width: `${String(p.fixed.ci_high - p.fixed.ci_low)}%`,
                          }}
                        />
                        <span
                          className="lbl"
                          style={{ left: `calc(${String(p.fixed.ci_high)}% + 6px)` }}
                        >
                          {p.fixed.resolved_pct.toFixed(1)}
                        </span>
                      </div>
                    )}
                  </div>
                </div>
              ))}
              <div className="legend">
                <span>
                  <span className="swatch" style={{ background: "#b8bdc6" }} />
                  baseline
                </span>
                <span>
                  <span className="swatch" style={{ background: "var(--blue)" }} />+ installed fixes
                </span>
              </div>
            </section>
            <section className="panel pad stack" style={{ flex: "1 1 320px", minWidth: 0 }}>
              <h2>Fixes in the top setup</h2>
              {data.fixes.map((f) => (
                <div
                  key={f.name}
                  className="kv"
                  style={{
                    fontFamily: "inherit",
                    fontSize: 13,
                    borderBottom: "1px solid var(--line-soft)",
                    paddingBottom: 10,
                  }}
                >
                  <span style={{ fontWeight: 500 }}>{f.name}</span>
                  <span
                    className="mono"
                    style={{
                      textAlign: "right",
                      fontWeight: 600,
                      color: f.verdict === "better" ? "var(--ok-ink)" : "var(--muted)",
                    }}
                  >
                    {f.delta >= 0 ? "+" : "−"}
                    {Math.abs(f.delta).toFixed(2)}
                  </span>
                  <span className="small muted">
                    {f.kind} · {f.applied} · v{f.version}
                  </span>
                  <span className="mono small muted" style={{ textAlign: "right" }}>
                    {VERDICT_TEXT[f.verdict]}
                  </span>
                </div>
              ))}
              <a href={href("evals")} style={{ fontSize: 13 }}>
                Open the eval runs →
              </a>
            </section>
          </div>

          <div className="row" style={{ gap: 14, fontSize: 13 }}>
            <label className="row">
              Harness
              <select
                className="input"
                value={harness}
                onChange={(e) => {
                  setHarness(e.target.value);
                }}
              >
                <option value="">All</option>
                <option value="claude-code">claude-code</option>
                <option value="codex">codex</option>
              </select>
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={showBase}
                onChange={(e) => {
                  setShowBase(e.target.checked);
                }}
              />
              Baselines
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={showFixed}
                onChange={(e) => {
                  setShowFixed(e.target.checked);
                }}
              />
              With fixes
            </label>
          </div>

          <div className="panel tablewrap">
            <table className="data" style={{ minWidth: 1100 }}>
              <thead>
                <tr>
                  <th style={{ width: 44 }}>#</th>
                  <th>Setup</th>
                  <th>Fixes</th>
                  <th className="num">% resolved ↓</th>
                  <th className="num">95 % CI</th>
                  <th className="num">Δ vs baseline</th>
                  <th className="num">Rubric</th>
                  <th className="num">Cost / task</th>
                  <th className="num">Median steps</th>
                  <th className="num">Trials</th>
                  <th>Date</th>
                  <th>Run</th>
                </tr>
              </thead>
              <tbody>
                {entries.length === 0 && (
                  <tr>
                    <td colSpan={12} className="empty">
                      No setups match these filters.
                    </td>
                  </tr>
                )}
                {entries.map((e) => (
                  <tr
                    key={`${setupKey(e)}${String(e.fixes.length)}`}
                    className={e.rank === 1 ? "top" : ""}
                  >
                    <td className="mono">{e.rank}</td>
                    <td>
                      <div style={{ fontWeight: 500 }}>{e.model}</div>
                      <div className="mono small muted">
                        {e.harness} {e.harness_version}
                      </div>
                    </td>
                    <td>
                      {e.fixes.length ? (
                        <span className="chip blue" title={e.fixes.join(", ")}>
                          {e.fixes.length} fixes
                        </span>
                      ) : (
                        <span className="chip">baseline</span>
                      )}
                    </td>
                    <td className="num" style={{ fontWeight: 700, fontSize: 15 }}>
                      {e.resolved_pct.toFixed(1)}%
                    </td>
                    <td className="num muted">
                      {e.ci_low.toFixed(0)}–{e.ci_high.toFixed(0)}
                    </td>
                    <td
                      className="num"
                      style={{
                        color: e.delta_vs_baseline ? "var(--ok-ink)" : "var(--muted)",
                        fontWeight: 600,
                      }}
                    >
                      {e.delta_vs_baseline === null
                        ? "—"
                        : `${e.delta_vs_baseline >= 0 ? "+" : "−"}${Math.abs(e.delta_vs_baseline).toFixed(1)}`}
                    </td>
                    <td className="num">{e.rubric_mean.toFixed(2)}</td>
                    <td className="num">${e.cost_per_task.toFixed(2)}</td>
                    <td className="num">{e.median_steps}</td>
                    <td className="num">{e.trials}</td>
                    <td className="mono">{e.date}</td>
                    <td>
                      {e.eval_run_id ? (
                        <a href={href("evals", e.eval_run_id)}>eval run</a>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="row between small muted">
            <span>
              Resolved = the check passes. Every number traces to a bench repo commit, task digest
              and candidate revision.
            </span>
            <span>Cost is an API-price estimate.</span>
          </div>
        </>
      )}
    </div>
  );
}
