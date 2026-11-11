import { useMemo } from "react";
import type { SessionDetail } from "../api";
import { tokens } from "../format";
import { buildMap } from "../trajectory";

interface Props {
  session: SessionDetail;
  selectedTurn: number;
  onSelectTurn: (turn: number) => void;
}

const LEGEND: [string, string][] = [
  ["user", "var(--blue)"],
  ["model call", "var(--k-model)"],
  ["read / search", "var(--k-read)"],
  ["edit", "var(--k-edit)"],
  ["shell", "var(--k-shell)"],
  ["subagent", "var(--sub)"],
  ["error", "var(--err)"],
];

export default function TrajectoryMap({ session, selectedTurn, onSelectTurn }: Props) {
  const map = useMemo(() => buildMap(session), [session]);
  const sel = map.turns.find((t) => t.turn === selectedTurn);

  return (
    <section className="panel pad stack" aria-label="Trajectory map">
      <div className="row between">
        <h2>
          Trajectory map{" "}
          <span className="muted small" style={{ fontWeight: 400 }}>
            · every step and tool call on one time axis · click a turn to inspect it
          </span>
        </h2>
        <div className="legend">
          {LEGEND.map(([name, color]) => (
            <span key={name}>
              <span className="swatch" style={{ background: color }} />
              {name}
            </span>
          ))}
        </div>
      </div>
      <div className="tmap">
        <div className="tmap-labels" aria-hidden="true">
          <div className="turns">Turns</div>
          {map.lanes.map((l) => (
            <div key={l.name}>{l.name}</div>
          ))}
          <div className="ctx">
            context
            <span className="mono" style={{ fontSize: 11 }}>
              0–{tokens(map.maxContext)} tok
            </span>
          </div>
          <div style={{ height: 20 }} />
        </div>
        <div className="tmap-tracks">
          {sel && (
            <div
              className="selband"
              style={{ left: `${String(sel.left)}%`, width: `${String(sel.width)}%` }}
            />
          )}
          {map.compactions.map((left) => (
            <div key={left} className="compaction" style={{ left: `${String(left)}%` }} />
          ))}
          <div className="turnband">
            {map.turns.map((t) => (
              <button
                key={t.turn}
                type="button"
                className={t.score >= 4 ? "hot" : "calm"}
                aria-pressed={t.turn === selectedTurn}
                title={`Turn ${String(t.turn)} · friction score ${String(t.score)}`}
                style={{ left: `${String(t.left)}%`, width: `calc(${String(t.width)}% - 2px)` }}
                onClick={() => {
                  onSelectTurn(t.turn);
                }}
              >
                T{t.turn}
                {t.score >= 4 ? ` · ${t.score.toFixed(1)}` : ""}
              </button>
            ))}
          </div>
          {map.lanes.map((lane) => (
            <div key={lane.name} className="lane" aria-label={`${lane.name} lane`}>
              {lane.bars.map((b) => (
                <div
                  key={b.key}
                  className={b.error ? "bar err" : "bar"}
                  title={b.title}
                  style={{
                    left: `${String(b.left)}%`,
                    width: `${String(b.width)}%`,
                    background: b.error ? undefined : b.color,
                  }}
                />
              ))}
            </div>
          ))}
          <div className="ctxlane" aria-label="Context size per model call">
            {map.context.map((c) => (
              <div
                key={c.stepId}
                className={c.turn === selectedTurn ? "col sel" : "col"}
                title={`s${String(c.stepId)} · ${tokens(c.tokens)} prompt tokens`}
                style={{ left: `${String(c.left)}%`, height: `${String(c.height)}%` }}
              />
            ))}
          </div>
          <div className={map.compactions.length ? "axis tall" : "axis"}>
            {map.ticks.map((t) => (
              <span key={t.label} style={{ left: `${String(t.left)}%` }}>
                {t.label}
              </span>
            ))}
            {map.compactions.map((left) => (
              <span
                key={left}
                className="below"
                style={{ left: `${String(left)}%`, color: "var(--warn-ink)" }}
              >
                ↑ compaction
              </span>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
