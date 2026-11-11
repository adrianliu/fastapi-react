import { endpoints, useFetch, type EvalRun, type Trial, type Verdict } from "../api";
import { dateTime, ms, signed, tokens, usd } from "../format";
import { href } from "../router";

const VERDICT_TEXT: Record<Verdict, string> = {
  better: "Better",
  worse: "Worse",
  no_clear_difference: "No clear difference",
  too_few_tasks: "Too few tasks for a verdict",
};
const VERDICT_COLOR: Record<Verdict, string> = {
  better: "var(--ok-ink)",
  worse: "var(--err-ink)",
  no_clear_difference: "var(--ink-2)",
  too_few_tasks: "var(--muted)",
};

export function EvalsList() {
  const { data, error } = useFetch(endpoints.evals);
  return (
    <div className="page narrow">
      <div>
        <h1 style={{ fontSize: 24 }}>Offline evals</h1>
        <p className="muted" style={{ marginTop: 4 }}>
          Each run benchmarks a fix on tasks rebuilt from your sessions: baseline vs baseline + fix,
          repeated.
        </p>
      </div>
      {error && <p className="alert">Could not load eval runs ({error}).</p>}
      <div className="stack">
        {data?.map((r) => (
          <a
            key={r.run_id}
            href={href("evals", r.run_id)}
            className="panel pad row between"
            style={{ color: "var(--ink)" }}
          >
            <span className="stack" style={{ gap: 4 }}>
              <strong>{r.title}</strong>
              <span className="small muted mono">
                {r.dataset} · started {dateTime(r.started_at)} UTC
              </span>
            </span>
            <span className="row">
              <span className="mono small">
                {r.trials_done}/{r.trials_total} trials
              </span>
              {r.status === "running" ? (
                <span className="chip blue">running</span>
              ) : (
                r.verdict && (
                  <span
                    className="chip"
                    style={{ color: VERDICT_COLOR[r.verdict], fontWeight: 600 }}
                  >
                    {VERDICT_TEXT[r.verdict]}
                  </span>
                )
              )}
            </span>
          </a>
        ))}
      </div>
    </div>
  );
}

export default function EvalPage({ id }: { id: string }) {
  const { data: run, error, loading } = useFetch(endpoints.evalRun(id));
  if (error)
    return (
      <div className="page">
        <p className="alert">Could not load this run ({error}).</p>
      </div>
    );
  if (loading || !run)
    return (
      <div className="page">
        <p className="empty">Loading run…</p>
      </div>
    );

  const [base, cand] = [run.variants[0] ?? "", run.variants[run.variants.length - 1] ?? ""];
  const b = run.bootstrap;

  return (
    <>
      <section className="pagehead">
        <div className="crumbs">
          <a href={href("evals")}>Evals</a>
          <span aria-hidden="true">/</span>
          <span className="mono">{run.dataset}</span>
        </div>
        <h1>{run.title}</h1>
        <div className="row" style={{ gap: 6 }}>
          <span className={run.status === "finished" ? "chip ok" : "chip blue"}>{run.status}</span>
          <span className="chip">
            {run.variants.length} variants × {run.tasks.length} tasks × {run.repeats} repeats ={" "}
            {run.trials_total} trials
          </span>
          <span className="chip mono">
            {run.harness} · {run.model}
          </span>
          <span className="chip mono">
            harbor {run.harbor_version} · rewardkit {run.rewardkit_version}
          </span>
          <span className="chip mono">bench repo {run.bench_commit}</span>
          <span className="chip">
            {run.duration_s ? ms(run.duration_s * 1000) + " · " : ""}
            {usd(run.cost_usd)} est.
          </span>
        </div>
      </section>

      <div className="page">
        {run.status === "running" && (
          <Progress trials={run.trials} done={run.trials_done} total={run.trials_total} />
        )}

        {b && (
          <div className="cols" style={{ gap: 16 }}>
            <section
              className="panel pad stack"
              style={{
                flex: "1 1 380px",
                borderColor: b.verdict === "better" ? "var(--ok-line)" : undefined,
              }}
            >
              <div className="caps">Verdict</div>
              <div className="row" style={{ alignItems: "baseline", gap: 12 }}>
                <span className="verdict" style={{ color: VERDICT_COLOR[b.verdict] }}>
                  {VERDICT_TEXT[b.verdict]}
                </span>
                <span className="mono" style={{ fontSize: 15 }}>
                  {signed(b.delta)} rubric · CI [{b.ci_low.toFixed(2)}, {b.ci_high.toFixed(2)}]
                </span>
              </div>
              <p style={{ color: "var(--ink-2)" }}>
                Paired over {b.paired_tasks} tasks, {b.resamples.toLocaleString("en-US")} bootstrap
                resamples, margin {b.margin}.{" "}
                {b.verdict === "better" && "The whole interval sits above the margin."}
                {b.verdict === "no_clear_difference" && "The interval overlaps the margin."}
              </p>
              <div className="row small">
                {run.stats.map(
                  (s) =>
                    s.fix_applied !== null && (
                      <span key={s.variant} className="chip">
                        {run.fix_kind} {run.fix_kind === "skill" ? "invoked" : "present"}{" "}
                        {s.fix_applied}/{s.trials}
                      </span>
                    ),
                )}
                <span className="chip">
                  {run.tasks.filter((t) => t.control).length} control task
                </span>
              </div>
            </section>
            <section className="panel pad stack" style={{ flex: "1 1 480px", gap: 8 }}>
              <div className="row between">
                <span className="caps">Bootstrap · paired Δ rubric</span>
                <span className="mono small muted">n = {b.resamples.toLocaleString("en-US")}</span>
              </div>
              <Histogram b={b} />
            </section>
          </div>
        )}

        {run.status === "finished" && run.stats.length > 0 && (
          <section className="panel tablewrap">
            <table className="data" style={{ minWidth: 860 }}>
              <thead>
                <tr>
                  <th>Variant</th>
                  <th className="num">Check pass</th>
                  <th className="num">Rubric mean</th>
                  <th className="num">Median diff</th>
                  <th className="num">New config</th>
                  <th className="num">Tool errors</th>
                  <th className="num">Tokens</th>
                  <th className="num">Duration</th>
                  <th className="num">Cost est.</th>
                </tr>
              </thead>
              <tbody>
                {run.stats.map((s) => {
                  const isCand = s.variant === cand;
                  const better = isCand ? { color: "var(--ok-ink)", fontWeight: 600 } : undefined;
                  return (
                    <tr key={s.variant} className={isCand ? "top" : ""}>
                      <td style={{ fontWeight: isCand ? 600 : 500 }}>
                        <span
                          className="swatch"
                          style={{
                            background: isCand ? "var(--ok)" : "var(--k-web)",
                            marginRight: 8,
                          }}
                        />
                        {s.variant}
                      </td>
                      <td className="num">
                        {s.check_pass}/{s.trials}
                      </td>
                      <td className="num" style={better}>
                        {s.rubric_mean.toFixed(2)}
                      </td>
                      <td className="num" style={better}>
                        {s.median_diff_lines} lines
                      </td>
                      <td className="num" style={better}>
                        {s.new_config}/{s.item_trials}
                      </td>
                      <td className="num">{s.mean_tool_errors.toFixed(1)}</td>
                      <td className="num">{tokens(s.mean_tokens)}</td>
                      <td className="num">{ms(s.mean_duration_s * 1000)}</td>
                      <td className="num">{usd(s.mean_cost_usd)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </section>
        )}

        <div className="cols" style={{ gap: 16 }}>
          {run.items.length > 0 && (
            <section className="panel pad stack" style={{ flex: "1 1 520px", minWidth: 0 }}>
              <div className="row between">
                <h2>Rubric items · rate across {run.items[0]?.n ?? 0} trials</h2>
                <span className="small muted">
                  grey = {base} · green = {cand} · ✕ items: lower is better
                </span>
              </div>
              {run.items.map((it) => {
                const a = (it.baseline / Math.max(1, it.n)) * 100;
                const c = (it.candidate / Math.max(1, it.n)) * 100;
                return (
                  <div key={it.key} className="dumbbell">
                    <span>
                      {it.bad ? "✕" : "✓"} {it.label}
                    </span>
                    <div className="db-track" aria-hidden="true">
                      <div className="axisline" />
                      <div
                        className="link"
                        style={{
                          left: `${String(Math.min(a, c))}%`,
                          width: `${String(Math.abs(a - c))}%`,
                        }}
                      />
                      <div
                        className="pt"
                        style={{ left: `${String(a)}%`, background: "var(--k-web)" }}
                      />
                      <div
                        className="pt"
                        style={{ left: `${String(c)}%`, background: "var(--ok)" }}
                      />
                    </div>
                    <span className="mono" style={{ textAlign: "right", fontSize: 12.5 }}>
                      {it.baseline}/{it.n} → {it.candidate}/{it.n}
                    </span>
                  </div>
                );
              })}
            </section>
          )}
          <Matrix run={run} />
        </div>
      </div>
    </>
  );
}

function Histogram({ b }: { b: NonNullable<EvalRun["bootstrap"]> }) {
  const max = Math.max(1, ...b.histogram);
  const width = (b.hist_max - b.hist_min) / b.histogram.length;
  const zero = ((0 - b.hist_min) / (b.hist_max - b.hist_min)) * 100;
  return (
    <>
      <div
        className="hist"
        role="img"
        aria-label={`Bootstrap distribution, 95% interval ${b.ci_low.toFixed(2)} to ${b.ci_high.toFixed(2)}`}
      >
        <div
          style={{
            position: "absolute",
            top: 0,
            bottom: 0,
            left: `${String(zero)}%`,
            borderLeft: "1.5px dashed var(--muted)",
          }}
        />
        {b.histogram.map((n, i) => {
          const mid = b.hist_min + (i + 0.5) * width;
          return (
            <div
              key={i}
              className={mid >= b.ci_low && mid <= b.ci_high ? "b in" : "b"}
              style={{ height: `${String(n ? Math.max(2, (n / max) * 100) : 0)}%` }}
            />
          );
        })}
      </div>
      <div className="axis">
        <span style={{ left: 0 }}>{b.hist_min.toFixed(1)}</span>
        <span style={{ left: `calc(${String(zero)}% - 8px)` }}>0</span>
        <span style={{ right: 0 }}>+{b.hist_max.toFixed(1)}</span>
      </div>
    </>
  );
}

function Matrix({ run }: { run: EvalRun }) {
  const cols = run.variants.length * run.repeats;
  const find = (task: string, variant: string, repeat: number): Trial | undefined =>
    run.trials.find((t) => t.task === task && t.variant === variant && t.repeat === repeat);
  return (
    <section className="panel pad stack" style={{ flex: "1 1 520px", minWidth: 0 }}>
      <div className="row between">
        <h2>Per task · each cell is one trial</h2>
        <span className="small muted">cells with a trajectory open it</span>
      </div>
      <div className="tablewrap">
        <div
          className="matrix"
          style={{ ["--cols" as string]: String(cols), minWidth: 120 + cols * 56 }}
        >
          <span />
          {run.variants.map((v, i) => (
            <span
              key={v}
              style={{
                gridColumn: `span ${String(run.repeats)}`,
                fontWeight: 600,
                color: i ? "var(--ok-ink)" : "var(--muted)",
              }}
            >
              {v} r1–r{run.repeats}
            </span>
          ))}
          {run.tasks.map((task) => (
            <Row key={task.name} task={task} run={run} find={find} />
          ))}
        </div>
      </div>
    </section>
  );
}

function Row({
  task,
  run,
  find,
}: {
  task: EvalRun["tasks"][number];
  run: EvalRun;
  find: (task: string, variant: string, repeat: number) => Trial | undefined;
}) {
  return (
    <>
      <div className="stack" style={{ gap: 0, justifyContent: "center", minHeight: 56 }}>
        <span className="mono" style={{ fontWeight: 600, fontSize: 12.5 }}>
          {task.name}
        </span>
        <span className="muted">{task.source}</span>
      </div>
      {run.variants.flatMap((v) =>
        Array.from({ length: run.repeats }, (_, r) => {
          const t = find(task.name, v, r + 1);
          const key = `${v}-${String(r)}`;
          if (t?.score == null) {
            return (
              <div
                key={key}
                className="cell"
                style={{ background: "var(--sunk)", color: "var(--muted)" }}
              >
                {t?.status ?? "—"}
              </div>
            );
          }
          const body = (
            <>
              <strong>{t.score.toFixed(2)}</strong>
              <span style={{ fontSize: 11 }}>
                {t.note ?? (t.diff_lines !== null ? `${String(t.diff_lines)} ln` : "")}
              </span>
            </>
          );
          const cls = t.check_pass && t.score >= 0.7 ? "cell" : "cell fail";
          const title = `${task.name} · ${v} · r${String(r + 1)} · rubric ${t.score.toFixed(2)}`;
          return t.trajectory_id ? (
            <a
              key={key}
              className={cls}
              href={href("sessions", t.trajectory_id)}
              title={`${title} · open trajectory`}
            >
              {body}
            </a>
          ) : (
            <div key={key} className={cls} title={title}>
              {body}
            </div>
          );
        }),
      )}
    </>
  );
}

function Progress({ trials, done, total }: { trials: Trial[]; done: number; total: number }) {
  return (
    <section className="panel pad stack" style={{ gap: 10 }}>
      <div className="row between">
        <h2>
          Running · {done} / {total} trials
        </h2>
        <span className="small muted">Verdict appears when every trial has finished.</span>
      </div>
      <div
        className="progress"
        role="img"
        aria-label={`${String(done)} of ${String(total)} trials finished`}
      >
        {trials.map((t, i) => (
          <div
            key={i}
            className={t.status}
            title={`${t.task} · ${t.variant} · r${String(t.repeat)} · ${t.status}`}
          />
        ))}
      </div>
      <div className="legend">
        <span>
          <span className="swatch" style={{ background: "var(--ok)" }} />
          passed
        </span>
        <span>
          <span className="swatch" style={{ background: "var(--err)" }} />
          failed
        </span>
        <span>
          <span className="swatch" style={{ background: "var(--k-read)" }} />
          running
        </span>
        <span>
          <span className="swatch" style={{ background: "var(--line)" }} />
          queued
        </span>
      </div>
    </section>
  );
}
