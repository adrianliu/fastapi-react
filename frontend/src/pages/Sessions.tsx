import { useState } from "react";
import { api } from "../api/client.ts";
import { fmtCost, fmtDate, fmtNum, shortPath, truncate } from "../format.ts";
import { useApi } from "../hooks.ts";
import { go } from "../router.ts";
import { Status } from "../ui.tsx";

export default function SessionsPage() {
  const [q, setQ] = useState("");
  const [harness, setHarness] = useState("");
  const [sort, setSort] = useState("started_at");
  const [offset, setOffset] = useState(0);
  const limit = 50;
  const home = useApi(() => api.home(), []);
  const list = useApi(
    () => api.sessions({ q, harness, sort, limit, offset }),
    [q, harness, sort, offset],
  );
  const harnesses = home.data ? Object.keys(home.data.harnesses) : [];

  return (
    <div>
      <header className="page-head">
        <h1>Sessions</h1>
        {list.data && <span className="muted">{fmtNum(list.data.total)} sessions</span>}
      </header>
      <div className="toolbar">
        <input
          type="search"
          placeholder="Search prompts, projects…"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setOffset(0);
          }}
        />
        <select
          value={harness}
          onChange={(e) => {
            setHarness(e.target.value);
            setOffset(0);
          }}
        >
          <option value="">All harnesses</option>
          {harnesses.map((h) => (
            <option key={h}>{h}</option>
          ))}
        </select>
        <select
          value={sort}
          onChange={(e) => {
            setSort(e.target.value);
          }}
        >
          <option value="started_at">Newest</option>
          <option value="cost">Est. cost</option>
          <option value="steps">Steps</option>
          <option value="friction">Friction</option>
        </select>
      </div>
      <Status state={list} isEmpty={(d) => d.items.length === 0} empty="No sessions match.">
        {(d) => (
          <>
            <table className="table clickable">
              <thead>
                <tr>
                  <th>Started</th>
                  <th>Harness</th>
                  <th>Project</th>
                  <th>First prompt</th>
                  <th className="num">Steps</th>
                  <th className="num">Errors</th>
                  <th className="num">Est. cost</th>
                  <th className="num">Friction</th>
                </tr>
              </thead>
              <tbody>
                {d.items.map((s) => (
                  <tr
                    key={s.trajectory_id}
                    onClick={() => {
                      go("sessions/" + s.trajectory_id);
                    }}
                  >
                    <td className="nowrap">{fmtDate(s.started_at)}</td>
                    <td>
                      <span className="chip">{s.agent_name}</span>
                    </td>
                    <td className="nowrap" title={s.project_path}>
                      {shortPath(s.project_path)}
                    </td>
                    <td>{truncate(s.first_prompt, 90)}</td>
                    <td className="num">{fmtNum(s.total_steps)}</td>
                    <td className={"num" + (s.n_errors > 0 ? " err" : "")}>{s.n_errors}</td>
                    <td className="num nowrap">{fmtCost(s.total_cost_usd)}</td>
                    <td className="num">
                      {s.friction_score === null ? "—" : s.friction_score.toFixed(1)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="pager">
              <button
                disabled={offset === 0}
                onClick={() => {
                  setOffset(Math.max(0, offset - limit));
                }}
              >
                ← Prev
              </button>
              <span className="muted">
                {offset + 1}–{Math.min(offset + limit, d.total)} of {d.total}
              </span>
              <button
                disabled={offset + limit >= d.total}
                onClick={() => {
                  setOffset(offset + limit);
                }}
              >
                Next →
              </button>
            </div>
          </>
        )}
      </Status>
    </div>
  );
}
