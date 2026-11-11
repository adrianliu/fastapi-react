import { api } from "../api/client.ts";
import { fmtDay, fmtNum } from "../format.ts";
import { useApi, useJob } from "../hooks.ts";
import { JobProgress, Status } from "../ui.tsx";

export default function HomePage() {
  const home = useApi(() => api.home(), []);
  const job = useJob();

  const runImport = async () => {
    await job.start(() => api.importSessions());
    home.reload();
  };

  return (
    <div>
      <header className="page-head">
        <h1>Home</h1>
        <button className="primary" disabled={job.running} onClick={() => void runImport()}>
          {job.running ? "Importing…" : "Import sessions"}
        </button>
      </header>
      <JobProgress state={job} label="Import" />
      <Status
        state={home}
        isEmpty={(h) => h.sessions === 0}
        empty="No sessions imported yet. Click “Import sessions” to read ~/.claude/projects, the session-hub archive and ~/.codex/sessions."
      >
        {(h) => (
          <>
            <div className="tiles">
              <div className="tile">
                <div className="tile-num">{fmtNum(h.sessions)}</div>
                <div className="tile-label">sessions</div>
                <div className="muted small">
                  {fmtNum(h.trajectories)} trajectories · {fmtNum(h.steps)} steps
                </div>
              </div>
              <div className="tile">
                <div className="tile-num">{Object.keys(h.harnesses).length}</div>
                <div className="tile-label">harnesses</div>
                <div className="chips">
                  {Object.entries(h.harnesses).map(([k, v]) => (
                    <span key={k} className="chip">
                      {k} <b>{fmtNum(v)}</b>
                    </span>
                  ))}
                </div>
              </div>
              <div className="tile">
                <div className="tile-num">{fmtNum(h.projects)}</div>
                <div className="tile-label">projects</div>
              </div>
              <div className="tile">
                <div className="tile-num">{fmtNum(h.weeks)}</div>
                <div className="tile-label">weeks covered</div>
                <div className="muted small">
                  {fmtDay(h.first_at)} → {fmtDay(h.last_at)}
                </div>
              </div>
            </div>
            {Object.keys(h.unknown_records).length > 0 && (
              <p className="muted small">
                Unrecognised records skipped:{" "}
                {Object.entries(h.unknown_records)
                  .map(([k, v]) => k + " " + String(v))
                  .join(", ")}
              </p>
            )}
          </>
        )}
      </Status>
    </div>
  );
}
