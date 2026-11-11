import { useState } from "react";
import { api } from "../api/client.ts";
import { fmtCost } from "../format.ts";
import { useApi, useJob } from "../hooks.ts";
import { go } from "../router.ts";
import { JobProgress } from "../ui.tsx";

export default function RunPage() {
  const fixes = useApi(() => api.fixes(), []);
  const tasks = useApi(() => api.tasks(), []);
  const [fixId, setFixId] = useState<number | null | undefined>(undefined);
  const [variants, setVariants] = useState(2);
  const [nTasks, setNTasks] = useState(3);
  const [repeats, setRepeats] = useState(1);
  const chosenFix = fixId === undefined ? (fixes.data?.[0]?.id ?? null) : fixId;
  const est = useApi(
    () => api.estimate({ fix_id: chosenFix, variants, tasks: nTasks, repeats }),
    [chosenFix, variants, nTasks, repeats],
  );
  const job = useJob();

  const start = async () => {
    const taskNames = (tasks.data ?? []).slice(0, nTasks).map((t) => t.name);
    const base = { tasks: taskNames, repeats };
    const final = await job.start(() =>
      api.run({
        baseline_config: { ...base, fix_id: null },
        candidate_config: { ...base, fix_id: chosenFix },
      }),
    );
    const run = final?.result?.run_id ?? final?.result?.run;
    if (final?.status === "done") {
      go(
        "comparison" +
          (typeof run === "number" || typeof run === "string" ? "/" + String(run) : ""),
      );
    }
  };

  return (
    <div>
      <header className="page-head">
        <h1>Run benchmark</h1>
      </header>
      <div className="card narrow">
        <label>
          Candidate fix
          <select
            value={chosenFix ?? ""}
            onChange={(e) => {
              setFixId(e.target.value ? Number(e.target.value) : null);
            }}
          >
            <option value="">(none)</option>
            {(fixes.data ?? []).map((f) => (
              <option key={f.id} value={f.id}>
                {f.name}
              </option>
            ))}
          </select>
        </label>
        <div className="grid3">
          <label>
            Variants
            <input
              type="number"
              min={1}
              value={variants}
              onChange={(e) => {
                setVariants(Number(e.target.value));
              }}
            />
          </label>
          <label>
            Tasks
            <input
              type="number"
              min={1}
              max={tasks.data?.length}
              value={nTasks}
              onChange={(e) => {
                setNTasks(Number(e.target.value));
              }}
            />
          </label>
          <label>
            Repeats
            <input
              type="number"
              min={1}
              value={repeats}
              onChange={(e) => {
                setRepeats(Number(e.target.value));
              }}
            />
          </label>
        </div>
        <div className="estimate">
          {est.error && <span className="err">Estimate unavailable: {est.error}</span>}
          {est.data && (
            <>
              <span>
                <b>{est.data.trials}</b> trials
              </span>
              <span>
                ~<b>{est.data.minutes.toFixed(0)}</b> min
              </span>
              <span>
                <b>{fmtCost(est.data.cost_usd)}</b>
              </span>
            </>
          )}
        </div>
        <button className="primary" disabled={job.running} onClick={() => void start()}>
          {job.running ? "Running…" : "Start"}
        </button>
      </div>
      <JobProgress state={job} label="Bench run" />
    </div>
  );
}
