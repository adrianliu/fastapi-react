import { useCallback, useEffect, useMemo, useState } from "react";
import {
  endpoints,
  useFetch,
  type Episode,
  type ReviewState,
  type SessionDetail,
  type Step,
} from "../api";
import LabelPanel from "../components/LabelPanel";
import { EpisodeView, StepView, type ViewOptions } from "../components/Timeline";
import TrajectoryMap from "../components/TrajectoryMap";
import Waterfall from "../components/Waterfall";
import { dateTime, plural, span, tokens, usd } from "../format";
import { href } from "../router";
import { evidenceIds } from "../trajectory";

export default function SessionPage({ id }: { id: string }) {
  const { data, error, loading } = useFetch(endpoints.session(id));
  if (error)
    return (
      <div className="page">
        <p className="alert">Could not load this session ({error}).</p>
      </div>
    );
  if (loading || !data)
    return (
      <div className="page">
        <p className="empty">Loading session…</p>
      </div>
    );
  return <SessionView key={data.trajectory_id} s={data} />;
}

function SessionView({ s }: { s: SessionDetail }) {
  const top = useMemo(
    () =>
      s.episodes.reduce<Episode | null>(
        (best, e) => (best === null || e.score > best.score ? e : best),
        null,
      ),
    [s],
  );
  const [selected, setSelected] = useState(top?.turn_index ?? 0);
  const [open, setOpen] = useState<Set<number>>(() => new Set(top ? [top.turn_index] : []));
  const [options, setOptions] = useState<ViewOptions>({
    reasoning: true,
    subagents: true,
    onlyErrors: false,
    system: true,
  });
  const [query, setQuery] = useState("");
  const [reviews, setReviews] = useState<Record<string, ReviewState>>({});
  const [target, setTarget] = useState<{ step: number; anchor: string } | null>(null);

  const episode = s.episodes.find((e) => e.turn_index === selected) ?? top;
  const evidence = useMemo(() => evidenceIds(episode?.label ?? null), [episode]);
  const subagents = useMemo(() => new Map(s.subagents.map((a) => [a.trajectory_id, a])), [s]);
  const byTurn = useMemo(() => {
    const m = new Map<number, Step[]>();
    for (const st of s.steps) m.set(st.turn_index, [...(m.get(st.turn_index) ?? []), st]);
    return m;
  }, [s]);

  const selectTurn = useCallback((turn: number) => {
    setSelected(turn);
    setOpen((prev) => new Set(prev).add(turn));
    setTarget({ step: -1, anchor: `turn-${String(turn)}` });
  }, []);

  const jump = useCallback(
    (stepId: number) => {
      const step = s.steps.find((st) => st.step_id === stepId);
      if (!step) return;
      // A reaction is shown inside the episode it reacts to.
      const reactionOf = s.episodes.find(
        (e) => e.reaction_step_id === stepId && e.turn_index === selected,
      );
      const turn = reactionOf ? reactionOf.turn_index : step.turn_index;
      setOpen((prev) => new Set(prev).add(turn));
      setQuery("");
      setTarget({ step: stepId, anchor: `${reactionOf ? "reaction" : "step"}-${String(stepId)}` });
    },
    [s, selected],
  );

  useEffect(() => {
    if (!target) return;
    const el = document.getElementById(target.anchor);
    if (!el) return;
    // Collapsed runs hide their steps inside <details>; open it first.
    const det = el.closest("details");
    if (det) det.open = true;
    el.scrollIntoView({ behavior: "smooth", block: target.step < 0 ? "start" : "center" });
  }, [target, open]);

  const onReviewed = useCallback((labelId: string, state: ReviewState) => {
    setReviews((prev) => ({ ...prev, [labelId]: state }));
  }, []);

  const q = query.trim().toLowerCase();
  const matches = q
    ? s.steps.filter(
        (st) =>
          st.message.toLowerCase().includes(q) ||
          (st.reasoning_content ?? "").toLowerCase().includes(q) ||
          st.tool_calls.some(
            (c) =>
              c.summary.toLowerCase().includes(q) || (c.content ?? "").toLowerCase().includes(q),
          ),
      )
    : [];

  const maxScore = Math.max(1, ...s.episodes.map((e) => e.score));
  const toggle = (key: keyof ViewOptions) => {
    setOptions((o) => ({ ...o, [key]: !o[key] }));
  };

  return (
    <>
      <section className="pagehead">
        <div className="crumbs">
          <a href={href("sessions")}>Sessions</a>
          <span aria-hidden="true">/</span>
          <span>{s.project_path}</span>
        </div>
        <div className="row between" style={{ alignItems: "flex-start", gap: 16 }}>
          <div className="grow" style={{ flexBasis: 520 }}>
            <h1>{s.title}</h1>
            <div className="row" style={{ gap: 6, marginTop: 10 }}>
              <span className="chip blue">
                {s.agent_name} {s.agent_version}
              </span>
              <span className="chip mono">{s.model_name}</span>
              <span className={s.origin === "benchmark" ? "chip sub" : "chip"}>{s.origin}</span>
              {s.git_commit && (
                <span className="chip mono">
                  {s.git_branch ?? "detached"} @ {s.git_commit}
                  {s.git_dirty ? " · dirty" : ""}
                </span>
              )}
              <span className="chip">
                {dateTime(s.started_at)} UTC · {span(s.started_at, s.ended_at)}
              </span>
              <span className="chip mono">{s.trajectory_id}</span>
            </div>
          </div>
          <div className="row">
            <label className="row" style={{ gap: 0 }}>
              <span className="sr-only">Search this session</span>
              <input
                className="input"
                type="search"
                placeholder="Search messages, calls, results"
                value={query}
                style={{ minWidth: 260, minHeight: 40 }}
                onChange={(e) => {
                  setQuery(e.target.value);
                }}
              />
            </label>
            {s.has_candidates && (
              <a className="btn primary" href={href("sessions", s.trajectory_id, "candidates")}>
                Task candidates
              </a>
            )}
          </div>
        </div>
        <div className="stats" style={{ marginTop: 8 }}>
          <div className="stat">
            <div className="small muted">Steps (tree)</div>
            <div className="v">
              {s.total_steps}{" "}
              <span className="small muted" style={{ fontWeight: 400 }}>
                · {plural(s.subagent_count, "subagent")}
              </span>
            </div>
          </div>
          <div className="stat">
            <div className="small muted">Turns · episodes</div>
            <div className="v">{s.turns}</div>
          </div>
          <div className="stat">
            <div className="small muted">Prompt / cached</div>
            <div className="v">
              {tokens(s.total_prompt_tokens)}{" "}
              <span className="small muted" style={{ fontWeight: 400 }}>
                / {tokens(s.total_cached_tokens)}
              </span>
            </div>
          </div>
          <div className="stat">
            <div className="small muted">Completion</div>
            <div className="v">{tokens(s.total_completion_tokens)}</div>
          </div>
          <div className="stat">
            <div className="small muted">Cost (API-price est.)</div>
            <div className="v">{usd(s.total_cost_usd)}</div>
          </div>
          <div className="stat">
            <div className="small muted">Tool errors</div>
            <div className="v" style={{ color: s.tool_errors ? "var(--err)" : undefined }}>
              {s.tool_errors}
            </div>
          </div>
          <div className="stat">
            <div className="small muted">Friction score</div>
            <div className="v" style={{ color: "var(--hot-score)" }}>
              {s.friction_score.toFixed(1)}
            </div>
          </div>
        </div>
      </section>

      <div className="page">
        <TrajectoryMap session={s} selectedTurn={selected} onSelectTurn={selectTurn} />
        {episode && (
          <Waterfall key={episode.turn_index} session={s} episode={episode} onSelectStep={jump} />
        )}

        <div className="cols">
          <nav className="panel turnrail" aria-label="Turns">
            <div className="caps" style={{ padding: "0 4px 8px" }}>
              Turns · friction
            </div>
            {s.episodes.map((e) => (
              <button
                key={e.turn_index}
                type="button"
                className="turn"
                aria-pressed={e.turn_index === selected}
                title={e.prompt}
                onClick={() => {
                  selectTurn(e.turn_index);
                }}
              >
                <span
                  className="mono"
                  style={{ fontWeight: e.turn_index === selected ? 600 : 400 }}
                >
                  T{e.turn_index}
                </span>
                <span className="meter">
                  <span className="track" style={{ background: "var(--line)" }}>
                    <span
                      className="fill"
                      style={{ display: "block", width: `${String((e.score / maxScore) * 100)}%` }}
                    />
                  </span>
                </span>
                <span
                  className="mono"
                  style={{
                    textAlign: "right",
                    color: e.score >= 4 ? "var(--hot-score)" : "var(--muted)",
                  }}
                >
                  {e.score.toFixed(1)}
                </span>
              </button>
            ))}
            <div
              className="stack"
              style={{ gap: 2, borderTop: "1px solid var(--line)", marginTop: 12, paddingTop: 12 }}
            >
              <div className="caps" style={{ padding: "0 4px" }}>
                Show
              </div>
              {(
                [
                  ["reasoning", "Reasoning"],
                  ["subagents", "Subagents inline"],
                  ["onlyErrors", "Only errored calls"],
                  ["system", "System steps"],
                ] as const
              ).map(([key, text]) => (
                <label key={key} className="check" style={{ padding: "0 4px" }}>
                  <input
                    type="checkbox"
                    checked={options[key]}
                    onChange={() => {
                      toggle(key);
                    }}
                  />
                  {text}
                </label>
              ))}
              <div className="row" style={{ padding: "8px 4px 0" }}>
                <button
                  type="button"
                  className="btn"
                  style={{ minHeight: 36 }}
                  onClick={() => {
                    setOpen(new Set(s.episodes.map((e) => e.turn_index)));
                  }}
                >
                  Expand all
                </button>
                <button
                  type="button"
                  className="btn"
                  style={{ minHeight: 36 }}
                  onClick={() => {
                    setOpen(new Set());
                  }}
                >
                  Collapse
                </button>
              </div>
            </div>
          </nav>

          <main className="timeline">
            {q ? (
              <section className="episode open" aria-label="Search results">
                <div className="episode-head" style={{ cursor: "default" }}>
                  <strong>
                    {plural(matches.length, "step")} match “{query}”
                  </strong>
                </div>
                {matches.length === 0 && <p className="empty">Nothing matches.</p>}
                {matches.map((st) => (
                  <div key={st.step_id} style={{ position: "relative" }}>
                    <button
                      type="button"
                      className="chip"
                      style={{ position: "absolute", right: 16, bottom: 10, zIndex: 1 }}
                      onClick={() => {
                        jump(st.step_id);
                      }}
                    >
                      T{st.turn_index} · show in context
                    </button>
                    <StepView
                      step={st}
                      evidence={evidence}
                      subagents={subagents}
                      options={options}
                      flash={false}
                    />
                  </div>
                ))}
              </section>
            ) : (
              s.episodes.map((e) => (
                <EpisodeView
                  key={e.turn_index}
                  episode={e}
                  steps={byTurn.get(e.turn_index) ?? []}
                  reaction={
                    e.turn_index === selected
                      ? s.steps.find((st) => st.step_id === e.reaction_step_id)
                      : undefined
                  }
                  open={open.has(e.turn_index)}
                  selected={e.turn_index === selected}
                  onToggle={() => {
                    setOpen((prev) => {
                      const next = new Set(prev);
                      if (next.has(e.turn_index)) next.delete(e.turn_index);
                      else next.add(e.turn_index);
                      return next;
                    });
                    setSelected(e.turn_index);
                  }}
                  evidence={e.turn_index === selected ? evidence : new Set()}
                  subagents={subagents}
                  options={options}
                  flashStep={target?.step ?? null}
                />
              ))
            )}
          </main>

          {episode && (
            <LabelPanel
              episode={episode}
              review={episode.label ? reviews[episode.label.label_id] : undefined}
              onReviewed={onReviewed}
              onJump={jump}
            />
          )}
        </div>
      </div>
    </>
  );
}
