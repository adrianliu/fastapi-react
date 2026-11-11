import { useMemo, useState } from "react";
import type { Episode, SessionDetail } from "../api";
import { ms, span } from "../format";
import { buildWaterfall } from "../trajectory";

const LIMIT = 24;

interface Props {
  session: SessionDetail;
  episode: Episode;
  onSelectStep: (stepId: number) => void;
}

export default function Waterfall({ session, episode, onSelectStep }: Props) {
  const rows = useMemo(() => buildWaterfall(session, episode), [session, episode]);
  const [all, setAll] = useState(false);
  const shown = all ? rows : rows.slice(0, LIMIT);
  const first = session.steps.find((s) => s.step_id === episode.first_step_id);
  const end =
    session.steps.find((s) => s.step_id === episode.reaction_step_id) ??
    session.steps.find((s) => s.step_id === episode.last_step_id);

  return (
    <section
      className="panel pad stack"
      aria-label={`Turn ${String(episode.turn_index)} waterfall`}
    >
      <div className="row between">
        <h3>
          T{episode.turn_index} waterfall{" "}
          {first && end && (
            <span className="mono muted" style={{ fontWeight: 400 }}>
              {span(first.timestamp, end.timestamp)} · {rows.length} rows
            </span>
          )}
        </h3>
        <span className="small muted">Bar = wall time · ◆ = friction evidence · click to jump</span>
      </div>
      <div className="stack" style={{ gap: 4 }}>
        {shown.map((r) => (
          <button
            key={r.key}
            type="button"
            className="wf-row"
            style={{
              border: 0,
              background: "transparent",
              padding: 0,
              cursor: "pointer",
              textAlign: "left",
            }}
            onClick={() => {
              onSelectStep(r.stepId);
            }}
          >
            <span className="mono muted">{r.id}</span>
            <span className="mono ellipsis" style={{ color: "var(--ink-2)" }} title={r.label}>
              {r.label}
            </span>
            <span className="wf-track">
              <span
                className="bar"
                style={{
                  left: `${String(r.left)}%`,
                  width: `${String(r.width)}%`,
                  background: r.color,
                }}
              />
              {r.flag && (
                <span className="wf-flag" style={{ left: `calc(${String(r.left)}% - 14px)` }}>
                  ◆
                </span>
              )}
            </span>
            <span className="mono muted" style={{ textAlign: "right" }}>
              {r.duration ? ms(r.duration) : ""}
            </span>
          </button>
        ))}
      </div>
      {rows.length > LIMIT && (
        <button
          type="button"
          className="btn"
          style={{ alignSelf: "flex-start" }}
          onClick={() => {
            setAll(!all);
          }}
        >
          {all ? "Show fewer" : `Show all ${String(rows.length)} rows`}
        </button>
      )}
    </section>
  );
}
