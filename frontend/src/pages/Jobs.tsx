import { api } from "../api/client.ts";
import { fmtDate } from "../format.ts";
import { useApi } from "../hooks.ts";
import { Status } from "../ui.tsx";

export default function JobsPage() {
  const state = useApi(() => api.jobs(), []);
  return (
    <div>
      <header className="page-head">
        <h1>Jobs</h1>
        <button onClick={state.reload}>Refresh</button>
      </header>
      <Status state={state} isEmpty={(j) => j.length === 0} empty="No jobs yet.">
        {(js) => (
          <table className="table">
            <thead>
              <tr>
                <th>#</th>
                <th>Kind</th>
                <th>Status</th>
                <th>Progress</th>
                <th>Created</th>
                <th>Finished</th>
              </tr>
            </thead>
            <tbody>
              {js.map((j) => (
                <tr key={j.id}>
                  <td>{j.id}</td>
                  <td>{j.kind}</td>
                  <td>
                    <span className={"badge " + j.status}>{j.status}</span>
                  </td>
                  <td>
                    {j.progress}
                    {j.error && <div className="err small">{j.error}</div>}
                  </td>
                  <td className="nowrap">{fmtDate(j.created_at)}</td>
                  <td className="nowrap">{fmtDate(j.finished_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Status>
    </div>
  );
}
