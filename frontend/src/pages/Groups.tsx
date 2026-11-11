import { useState } from "react";
import { api } from "../api/client.ts";
import { fmtDate, shortPath } from "../format.ts";
import { useApi, useJob } from "../hooks.ts";
import { go } from "../router.ts";
import { JobProgress, Status } from "../ui.tsx";

export function GroupsPage() {
  const groups = useApi(() => api.groups(), []);
  const job = useJob();
  const rebuild = async () => {
    await job.start(() => api.buildGroups());
    groups.reload();
  };
  return (
    <div>
      <header className="page-head">
        <h1>Friction groups</h1>
        <button className="primary" disabled={job.running} onClick={() => void rebuild()}>
          {job.running ? "Rebuilding…" : "Rebuild"}
        </button>
      </header>
      <JobProgress state={job} label="Rebuild groups" />
      <Status
        state={groups}
        isEmpty={(g) => g.length === 0}
        empty="No friction groups yet. Import sessions, then click Rebuild."
      >
        {(gs) => (
          <div className="cards">
            {gs.map((g, i) => (
              <a key={g.id} className="card group-card" href={"#/groups/" + String(g.id)}>
                <div className="rank">#{i + 1}</div>
                <h3>{g.name}</h3>
                <p>{g.lesson}</p>
                <div className="muted small">
                  <b>{g.sessions}</b> sessions × <b>{g.projects}</b> projects · {g.n_items}{" "}
                  corrections
                </div>
              </a>
            ))}
          </div>
        )}
      </Status>
    </div>
  );
}

export function GroupPage({ id }: { id: number }) {
  const group = useApi(() => api.group(id), [id]);
  const job = useJob();
  const [kind, setKind] = useState<"rule" | "skill">("skill");
  const draft = async (fixType: "rule" | "skill") => {
    setKind(fixType);
    const final = await job.start(() => api.draftFix(id, fixType));
    const fixId = final?.result?.fix_id;
    if (final?.status === "done" && typeof fixId === "number") {
      go("fixes/" + String(fixId));
    }
  };
  return (
    <div>
      <a href="#/groups" className="back">
        ← Friction groups
      </a>
      <Status state={group}>
        {(g) => (
          <>
            <header className="page-head">
              <div>
                <h1>{g.name}</h1>
                <p className="lead">{g.lesson}</p>
                <div className="muted">
                  {g.sessions} sessions × {g.projects} projects · {g.n_items} corrections
                </div>
              </div>
              <div className="row">
                <button disabled={job.running} onClick={() => void draft("rule")}>
                  {job.running && kind === "rule" ? "Drafting rule…" : "Draft rule"}
                </button>
                <button
                  className="primary"
                  disabled={job.running}
                  onClick={() => void draft("skill")}
                >
                  {job.running && kind === "skill" ? "Drafting skill…" : "Draft skill"}
                </button>
              </div>
            </header>
            <JobProgress state={job} label={kind === "skill" ? "Draft skill" : "Draft rule"} />
            {g.items.length === 0 && <div className="empty">No corrections in this group.</div>}
            <div className="corrections">
              {g.items.map((c) => (
                <div key={c.id} className="card correction">
                  <div className="agent-before">
                    <div className="label">agent before</div>
                    <div className="clip">{c.agent_before || "—"}</div>
                  </div>
                  <blockquote>{c.quote}</blockquote>
                  <div className="muted small row">
                    <span title={c.project_path}>{shortPath(c.project_path)}</span>
                    <span>{fmtDate(c.timestamp)}</span>
                    <a href={"#/sessions/" + c.trajectory_id + "/" + String(c.step_id)}>
                      open step →
                    </a>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </Status>
    </div>
  );
}
