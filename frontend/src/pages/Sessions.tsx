import { useState } from "react";
import { endpoints, useFetch } from "../api";
import { dateTime, span, usd } from "../format";
import { href } from "../router";

interface Filters {
  harness: string;
  project: string;
  origin: string;
  has_errors: boolean;
  has_friction_label: boolean;
  sort: string;
}

const INITIAL: Filters = {
  harness: "",
  project: "",
  origin: "",
  has_errors: false,
  has_friction_label: false,
  sort: "friction",
};

export default function SessionsPage() {
  const [f, setF] = useState<Filters>(INITIAL);
  const params = new URLSearchParams({ sort: f.sort });
  if (f.harness) params.set("harness", f.harness);
  if (f.project) params.set("project", f.project);
  if (f.origin) params.set("origin", f.origin);
  if (f.has_errors) params.set("has_errors", "true");
  if (f.has_friction_label) params.set("has_friction_label", "true");

  const meta = useFetch(endpoints.meta);
  const all = useFetch(endpoints.sessions());
  const { data, error, loading } = useFetch(endpoints.sessions(params));
  const projects = [...new Set((all.data ?? []).map((s) => s.project_path))].sort();
  const maxScore = Math.max(1, ...(data ?? []).map((s) => s.friction_score));

  function set<K extends keyof Filters>(key: K, value: Filters[K]) {
    setF((prev) => ({ ...prev, [key]: value }));
  }

  return (
    <div className="page narrow">
      <div className="row between" style={{ alignItems: "flex-end" }}>
        <div>
          <h1 style={{ fontSize: 24 }}>Sessions</h1>
          {meta.data && (
            <p className="muted" style={{ marginTop: 4 }}>
              {meta.data.sessions} trajectories · {Object.keys(meta.data.by_harness).length}{" "}
              harnesses · {meta.data.projects} projects ·{" "}
              {dateTime(meta.data.first_started_at).slice(0, 6)} –{" "}
              {dateTime(meta.data.last_started_at).slice(0, 6)}
            </p>
          )}
        </div>
        <div className="row small">
          {meta.data &&
            Object.entries(meta.data.by_harness).map(([h, n]) => (
              <span
                key={h}
                className="chip"
                style={{ background: "var(--panel)", border: "1px solid var(--line)" }}
              >
                {h} <span className="mono">{n}</span>
              </span>
            ))}
        </div>
      </div>

      <form
        className="panel row"
        style={{ padding: 12, gap: 10, alignItems: "flex-end" }}
        onSubmit={(e) => {
          e.preventDefault();
        }}
      >
        <label className="field">
          Harness
          <select
            value={f.harness}
            onChange={(e) => {
              set("harness", e.target.value);
            }}
          >
            <option value="">All</option>
            <option value="claude-code">claude-code</option>
            <option value="codex">codex</option>
          </select>
        </label>
        <label className="field">
          Project
          <select
            value={f.project}
            onChange={(e) => {
              set("project", e.target.value);
            }}
          >
            <option value="">All {projects.length}</option>
            {projects.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          Origin
          <select
            value={f.origin}
            onChange={(e) => {
              set("origin", e.target.value);
            }}
          >
            <option value="">All</option>
            <option value="organic">organic</option>
            <option value="benchmark">benchmark</option>
          </select>
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={f.has_errors}
            onChange={(e) => {
              set("has_errors", e.target.checked);
            }}
          />
          Has errors
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={f.has_friction_label}
            onChange={(e) => {
              set("has_friction_label", e.target.checked);
            }}
          />
          Has friction label
        </label>
        <span className="grow" />
        <label className="field">
          Sort
          <select
            value={f.sort}
            onChange={(e) => {
              set("sort", e.target.value);
            }}
          >
            <option value="friction">Friction score ↓</option>
            <option value="cost">Cost ↓</option>
            <option value="duration">Duration ↓</option>
            <option value="started">Newest</option>
          </select>
        </label>
      </form>

      {error && <p className="alert">Could not load sessions ({error}).</p>}
      <div className="panel tablewrap">
        <table className="data" style={{ minWidth: 1100 }}>
          <thead>
            <tr>
              <th>Session · labels</th>
              <th>Project</th>
              <th>Harness · model</th>
              <th>Started (UTC)</th>
              <th className="num">Duration</th>
              <th className="num">Steps</th>
              <th className="num">Cost est.</th>
              <th className="num">Errors</th>
              <th style={{ width: 180 }}>Friction</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={9} className="empty">
                  Loading…
                </td>
              </tr>
            )}
            {data?.length === 0 && (
              <tr>
                <td colSpan={9} className="empty">
                  No sessions match these filters.
                </td>
              </tr>
            )}
            {data?.map((s, i) => (
              <tr
                key={s.trajectory_id}
                className={i === 0 && f.sort === "friction" && s.friction_score >= 4 ? "hl" : ""}
              >
                <td>
                  <a
                    href={href("sessions", s.trajectory_id)}
                    style={{ fontWeight: 500, color: "var(--ink)" }}
                  >
                    {s.title}
                  </a>
                  <div className="small muted row" style={{ gap: 6, marginTop: 4 }}>
                    {s.origin === "benchmark" && <span className="chip sub">benchmark</span>}
                    {s.friction_types.length > 0
                      ? s.friction_types.join(" · ")
                      : "no friction label"}
                    {s.subagent_count > 0 && ` · ${String(s.subagent_count)} subagents`}
                  </div>
                </td>
                <td className="mono">{s.project_path}</td>
                <td>
                  <span
                    style={{
                      color: s.agent_name === "claude-code" ? "var(--blue-ink)" : "var(--ink-2)",
                    }}
                  >
                    {s.agent_name}
                  </span>
                  <div className="mono small muted">{s.model_name}</div>
                </td>
                <td className="mono">{dateTime(s.started_at)}</td>
                <td className="num">{span(s.started_at, s.ended_at)}</td>
                <td className="num">{s.total_steps}</td>
                <td className="num">{usd(s.total_cost_usd)}</td>
                <td className="num" style={{ color: s.tool_errors ? "var(--err)" : undefined }}>
                  {s.tool_errors}
                </td>
                <td>
                  <div className="meter">
                    <span className="track">
                      <span
                        className="fill"
                        style={{
                          display: "block",
                          width: `${String((s.friction_score / maxScore) * 100)}%`,
                        }}
                      />
                    </span>
                    <span
                      className="mono"
                      style={{
                        width: 36,
                        textAlign: "right",
                        fontWeight: 600,
                        color: s.friction_score >= 4 ? "var(--hot-score)" : "var(--muted)",
                      }}
                    >
                      {s.friction_score.toFixed(1)}
                    </span>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="row between small muted">
        <span>{data ? `Showing ${String(data.length)} sessions` : ""}</span>
        <span>
          Friction score = highest episode score from the rule pass (spec 4.2). Cost is an API-price
          estimate.
        </span>
      </div>
    </div>
  );
}
