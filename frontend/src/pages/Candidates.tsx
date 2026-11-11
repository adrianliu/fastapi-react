import { useState } from "react";
import { endpoints, useFetch, type Readiness, type SpanRole } from "../api";
import { stepRange } from "../format";
import { href } from "../router";

const ROLE_CHIP: Record<SpanRole, string> = {
  request: "chip blue",
  requirement: "chip teal",
  attempt: "chip",
  correction: "chip hot",
  outcome: "chip ok",
  solution_hint: "chip sub",
};

const ROLE_LEGEND: [SpanRole, string][] = [
  ["request", "request → instruction"],
  ["requirement", "requirement → instruction"],
  ["attempt", "attempt"],
  ["correction", "correction"],
  ["outcome", "outcome"],
  ["solution_hint", "solution_hint · eval only"],
];

const READY_CHIP: Record<Readiness, string> = {
  ready_for_task_build: "chip ok",
  needs_review: "chip warn",
  blocked: "chip err",
};

export default function CandidatesPage({ id }: { id: string }) {
  const { data, error, loading } = useFetch(endpoints.candidates(id));
  const [selected, setSelected] = useState("C1");

  if (error)
    return (
      <div className="page">
        <p className="alert">No task candidates for this session ({error}).</p>
      </div>
    );
  if (loading || !data)
    return (
      <div className="page">
        <p className="empty">Loading candidates…</p>
      </div>
    );

  const cand = data.candidates.find((c) => c.candidate_id === selected) ?? data.candidates[0];
  const edges = data.candidates.flatMap((c) =>
    c.depends_on.map((d) => ({ from: d.candidate_id, to: c.candidate_id })),
  );
  const linked = new Set(edges.flatMap((e) => [e.from, e.to]));
  const titleOf = (cid: string) =>
    data.candidates.find((c) => c.candidate_id === cid)?.title ?? cid;

  return (
    <>
      <section className="pagehead">
        <div className="crumbs">
          <a href={href("sessions")}>Sessions</a>
          <span aria-hidden="true">/</span>
          <a href={href("sessions", data.trajectory_id)}>{data.session_title}</a>
          <span aria-hidden="true">/</span>
          <span>Task candidates</span>
        </div>
        <h1>Task candidates · {data.candidates.length} proposed</h1>
        <p className="small muted">
          Proposal set #{data.proposal_set} ·{" "}
          <span className="mono">
            {data.model} · {data.prompt_version} · condenser {data.condenser_version}
          </span>{" "}
          · read-only in this version: editing spans, merging and building tasks come later
        </p>
        <div className="row small" style={{ gap: 6 }}>
          <span className="muted">Span roles</span>
          {ROLE_LEGEND.map(([role, text]) => (
            <span key={role} className={ROLE_CHIP[role]}>
              {text}
            </span>
          ))}
        </div>
      </section>

      <div className="page">
        <div className="cols">
          <section
            className="panel"
            style={{ flex: "1 1 420px", minWidth: 0, overflow: "hidden" }}
            aria-label="Session timeline"
          >
            <div
              className="row between"
              style={{ padding: "12px 16px", borderBottom: "1px solid var(--line)" }}
            >
              <h2>Session timeline</h2>
              <span className="mono small muted">
                {data.turns.length} turns · highlighting {cand?.candidate_id}
              </span>
            </div>
            {data.turns.map((t) => {
              const spans = data.candidates.flatMap((c) =>
                c.spans
                  .filter((sp) => sp.from_step <= t.last_step_id && sp.to_step >= t.first_step_id)
                  .map((sp) => ({ ...sp, cid: c.candidate_id })),
              );
              const mine = spans.some((sp) => sp.cid === cand?.candidate_id);
              return (
                <div key={t.turn_index} className={mine ? "cand-turn sel" : "cand-turn"}>
                  <span className="mono small muted">T{t.turn_index}</span>
                  <div style={{ minWidth: 0 }}>
                    <a
                      href={href("sessions", data.trajectory_id)}
                      style={{ color: mine ? "var(--ink)" : "var(--ink-2)" }}
                    >
                      “{t.prompt}”
                    </a>
                    <div className="row" style={{ gap: 6, marginTop: 6 }}>
                      {spans.map((sp) => (
                        <button
                          key={`${sp.cid}${sp.role}${String(sp.from_step)}${sp.excerpt ?? ""}`}
                          type="button"
                          className={sp.cid === cand?.candidate_id ? ROLE_CHIP[sp.role] : "chip"}
                          style={sp.cid === cand?.candidate_id ? undefined : { opacity: 0.7 }}
                          title={sp.excerpt ?? undefined}
                          onClick={() => {
                            setSelected(sp.cid);
                          }}
                        >
                          {sp.cid} {sp.role} {stepRange(sp.from_step, sp.to_step)}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              );
            })}
          </section>

          <section
            className="stack"
            style={{ flex: "1 1 560px", minWidth: 0 }}
            aria-label="Candidates"
          >
            <div className="panel pad stack" style={{ gap: 10 }}>
              <div className="caps">Dependencies</div>
              <div className="row" style={{ gap: 10, fontSize: 13 }}>
                {edges.map((e) => (
                  <span key={`${e.from}${e.to}`} className="row" style={{ gap: 8 }}>
                    <span className="chip mono">{e.from}</span>
                    <span className="muted" aria-label="is needed by">
                      →
                    </span>
                    <span className="chip mono">{e.to}</span>
                    <span className="small muted">{titleOf(e.to)}</span>
                  </span>
                ))}
                {data.candidates
                  .filter((c) => !linked.has(c.candidate_id))
                  .map((c) => (
                    <span key={c.candidate_id} className="chip mono">
                      {c.candidate_id} · no edges
                    </span>
                  ))}
              </div>
            </div>

            {data.candidates.map((c) =>
              c.candidate_id === cand?.candidate_id ? (
                <article key={c.candidate_id} className="panel cand-card sel" aria-current="true">
                  <div className="row" style={{ gap: 10 }}>
                    <span className="mono" style={{ fontWeight: 700, fontSize: 15 }}>
                      {c.candidate_id}
                    </span>
                    <h2 className="grow" style={{ fontSize: 17, flexBasis: 260 }}>
                      {c.title}
                    </h2>
                    <span className={READY_CHIP[c.readiness]} style={{ fontWeight: 600 }}>
                      {c.readiness}
                    </span>
                    <span className="mono small muted">rev {c.revision}</span>
                  </div>
                  <div>
                    <div className="small muted">Objective</div>
                    <p>{c.objective}</p>
                  </div>
                  <div>
                    <div className="small muted" style={{ marginBottom: 6 }}>
                      Acceptance criteria
                    </div>
                    <ul style={{ margin: 0, padding: 0, listStyle: "none" }} className="stack">
                      {c.criteria.map((cr) => (
                        <li key={cr.text} className="row between" style={{ gap: 6 }}>
                          <span>{cr.text}</span>
                          <span className="mono small muted">
                            {cr.step_ids.map((i) => `s${String(i)}`).join(", ")}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div className="instruction">
                    <div className="small muted" style={{ marginBottom: 6 }}>
                      instruction.md preview · request + requirement spans only
                    </div>
                    <pre>{c.instruction}</pre>
                    {c.spans
                      .filter((sp) => sp.role === "solution_hint")
                      .map((sp) => (
                        <p
                          key={sp.from_step}
                          className="small"
                          style={{ marginTop: 8, color: "var(--sub-ink)" }}
                        >
                          “{sp.excerpt}” (s{sp.from_step}) is held back as a solution_hint.
                        </p>
                      ))}
                  </div>
                  <div className="cols" style={{ gap: 16 }}>
                    <div className="grow" style={{ flexBasis: 240 }}>
                      <div className="small muted" style={{ marginBottom: 6 }}>
                        Starting state
                      </div>
                      {c.starting_state.length === 0 && (
                        <p className="small muted">None recorded.</p>
                      )}
                      {c.starting_state.map((f) => (
                        <div key={f.fact} className="row" style={{ gap: 8, fontSize: 13 }}>
                          <span className={f.status === "known" ? "chip ok" : "chip err"}>
                            {f.status}
                          </span>
                          {f.fact}
                          {f.step_ids.length > 0 && (
                            <span className="mono small muted">
                              {f.step_ids.map((i) => `s${String(i)}`).join(", ")}
                            </span>
                          )}
                        </div>
                      ))}
                    </div>
                    <div className="grow" style={{ flexBasis: 240 }}>
                      <div className="small muted" style={{ marginBottom: 6 }}>
                        Depends on
                      </div>
                      {c.depends_on.length === 0 && <p className="small muted">Nothing.</p>}
                      {c.depends_on.map((d) => (
                        <p key={d.candidate_id} style={{ fontSize: 13 }}>
                          <span className="mono" style={{ fontWeight: 600 }}>
                            {d.candidate_id}
                          </span>{" "}
                          · {d.reason}{" "}
                          <span className="mono small muted">
                            {d.step_ids.map((i) => `s${String(i)}`).join(", ")}
                          </span>
                        </p>
                      ))}
                    </div>
                  </div>
                  {(c.blocked_reasons.length > 0 || c.open_questions.length > 0) && (
                    <ul
                      className="small"
                      style={{ margin: 0, paddingLeft: 18, color: "var(--ink-2)" }}
                    >
                      {c.blocked_reasons.map((r) => (
                        <li key={r}>{r}</li>
                      ))}
                      {c.open_questions.map((q) => (
                        <li key={q}>Open question: {q}</li>
                      ))}
                    </ul>
                  )}
                </article>
              ) : (
                <button
                  key={c.candidate_id}
                  type="button"
                  className="panel cand-card"
                  onClick={() => {
                    setSelected(c.candidate_id);
                  }}
                >
                  <span className="row" style={{ gap: 10, width: "100%" }}>
                    <span className="mono" style={{ fontWeight: 700 }}>
                      {c.candidate_id}
                    </span>
                    <span
                      className="grow"
                      style={{ fontWeight: 600, fontSize: 15, flexBasis: 240 }}
                    >
                      {c.title}
                    </span>
                    <span className={READY_CHIP[c.readiness]} style={{ fontWeight: 600 }}>
                      {c.readiness}
                    </span>
                  </span>
                  <span className="small" style={{ color: "var(--ink-2)" }}>
                    {c.blocked_reasons[0] ??
                      (c.open_questions[0]
                        ? `Open question: ${c.open_questions[0]}`
                        : `${String(c.criteria.length)} criteria · ${String(c.spans.length)} spans`)}
                  </span>
                </button>
              ),
            )}
          </section>
        </div>
      </div>
    </>
  );
}
