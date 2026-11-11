import { api } from "../api/client.ts";
import type { CheckStatus } from "../api/types.ts";
import { useApi } from "../hooks.ts";
import { Status } from "../ui.tsx";

function Check({ name, status }: { name: string; status: CheckStatus }) {
  return (
    <span className={"check " + status}>
      {name}: {status}
    </span>
  );
}

export default function TasksPage() {
  const state = useApi(() => api.tasks(), []);
  return (
    <div>
      <header className="page-head">
        <h1>Tasks</h1>
        <a className="button primary" href="#/run">
          Run benchmark…
        </a>
      </header>
      <Status state={state} isEmpty={(t) => t.length === 0} empty="No bench tasks yet.">
        {(ts) => (
          <div className="task-list">
            {ts.map((t) => (
              <div key={t.name} className="card">
                <div className="row">
                  <h3>{t.name}</h3>
                  <span className="chip">{t.kind}</span>
                  <span className="muted small">{t.dataset}</span>
                  <span className="spacer" />
                  <Check name="nop" status={t.checks.nop} />
                  <Check name="oracle" status={t.checks.oracle} />
                  <Check name="install" status={t.checks.install} />
                </div>
                <pre className="instruction">{t.instruction}</pre>
                <div className="label">rubric</div>
                <ul className="rubric">
                  {t.rubric.map((r) => (
                    <li key={r.id}>
                      <span className="chip small">{r.kind}</span> {r.text}{" "}
                      <span className="muted small">×{r.weight}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}
      </Status>
    </div>
  );
}
