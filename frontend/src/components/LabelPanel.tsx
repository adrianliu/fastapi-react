import { useEffect, useState } from "react";
import { reviewLabel, type Episode, type ReviewState } from "../api";
import { usd } from "../format";

const TYPE_NUMBER: Record<string, number> = {
  environment: 1,
  instruction_ignored: 2,
  context_loss: 3,
  false_completion: 4,
  requirement_missed: 5,
  wrong_assumption: 6,
  overreach: 7,
  tool_misuse: 8,
  retry_loop: 9,
  inefficiency: 10,
};

const STATE_CHIP: Record<ReviewState, string> = {
  pending: "chip",
  confirmed: "chip ok",
  rejected: "chip err",
  edited: "chip blue",
};

interface Props {
  episode: Episode;
  review: ReviewState | undefined;
  onReviewed: (labelId: string, state: ReviewState) => void;
  onJump: (stepId: number) => void;
}

export default function LabelPanel({ episode, review, onReviewed, onJump }: Props) {
  const label = episode.label;
  const state = review ?? label?.review_state ?? "pending";
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function set(next: "pending" | "confirmed" | "rejected") {
    if (!label || saving) return;
    setSaving(true);
    setError("");
    try {
      await reviewLabel(label.label_id, next);
      onReviewed(label.label_id, next);
    } catch {
      setError("Could not save the review. Try again.");
    } finally {
      setSaving(false);
    }
  }

  useEffect(() => {
    if (!label) return;
    const id = label.label_id;
    function onKey(e: KeyboardEvent) {
      const t = e.target;
      if (
        t instanceof HTMLElement &&
        (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))
      )
        return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const key = e.key.toLowerCase();
      if (key !== "y" && key !== "n") return;
      const next = key === "y" ? "confirmed" : "rejected";
      reviewLabel(id, next)
        .then(() => {
          onReviewed(id, next);
        })
        .catch(() => {
          setError("Could not save the review. Try again.");
        });
    }
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [label, onReviewed]);

  const chip = (id: number, tone: "hot" | "plain") => (
    <button
      key={`${tone}${String(id)}`}
      type="button"
      className={tone === "hot" ? "chip outline" : "chip"}
      onClick={() => {
        onJump(id);
      }}
    >
      s{id}
    </button>
  );

  return (
    <aside className="inspector" aria-label="Episode label">
      <div className="panel pad stack" style={{ gap: 14 }}>
        <div className="row between">
          <h2>Episode T{episode.turn_index} · label</h2>
          {label && (
            <span className={STATE_CHIP[state]}>
              {state === "pending" ? "pending review" : state}
            </span>
          )}
        </div>
        {!label ? (
          <p className="muted">
            No pass-2 label. This episode scores {episode.score.toFixed(1)}; pass 2 runs on episodes
            scoring ≥ 4 or in the top 20 %.
          </p>
        ) : (
          <>
            <div>
              <div className="small muted">Intent</div>
              <div>{label.intent}</div>
            </div>
            <div className="row" style={{ gap: 16 }}>
              <div>
                <div className="small muted">Task type</div>
                <div className="mono" style={{ fontSize: 13 }}>
                  {label.task_type}
                </div>
              </div>
              <div>
                <div className="small muted">Outcome</div>
                <div
                  className="mono"
                  style={{
                    fontSize: 13,
                    color: label.outcome === "success" ? "var(--ok-ink)" : "var(--hot-ink)",
                  }}
                >
                  {label.outcome}
                </div>
              </div>
            </div>
            <p className="small muted">{label.outcome_reason}</p>
            {label.friction.map((f, i) => (
              <div key={f.type} className={i === 0 ? "friction first" : "friction"}>
                <div className="row between">
                  <span
                    className="mono"
                    style={{ fontWeight: 600, color: i === 0 ? "var(--hot-ink)" : "var(--ink-2)" }}
                  >
                    {TYPE_NUMBER[f.type] ?? "?"} · {f.type}
                  </span>
                  <span className="small" style={{ color: "var(--ink-2)" }}>
                    severity <span className="mono">{f.severity}</span> / 3
                    {f.user_corrected ? " · user corrected" : ""}
                  </span>
                </div>
                <p style={{ fontSize: 13, color: "var(--ink-2)" }}>{f.explanation}</p>
                {f.instruction_quote && (
                  <blockquote className="mono small" style={{ margin: 0, color: "var(--ink-2)" }}>
                    “{f.instruction_quote}”
                  </blockquote>
                )}
                <div className="row small">
                  {f.evidence_step_ids.length > 0 && <span className="muted">Evidence</span>}
                  {f.evidence_step_ids.map((id) => chip(id, "hot"))}
                  {f.resolution_step_ids.length > 0 && <span className="muted">Resolved</span>}
                  {f.resolution_step_ids.map((id) => chip(id, "plain"))}
                </div>
              </div>
            ))}
            <div
              style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 8 }}
            >
              <button
                type="button"
                className="btn good"
                aria-pressed={state === "confirmed"}
                disabled={saving}
                onClick={() => void set("confirmed")}
              >
                Confirm <span className="kbd">Y</span>
              </button>
              <button
                type="button"
                className="btn danger"
                aria-pressed={state === "rejected"}
                disabled={saving}
                onClick={() => void set("rejected")}
              >
                Reject <span className="kbd">N</span>
              </button>
            </div>
            {state !== "pending" && (
              <button
                type="button"
                className="btn"
                disabled={saving}
                onClick={() => void set("pending")}
              >
                Undo review
              </button>
            )}
            {error && (
              <p role="alert" className="small" style={{ color: "var(--err-ink)" }}>
                {error}
              </p>
            )}
            <div
              className="mono small muted"
              style={{ borderTop: "1px solid var(--line-soft)", paddingTop: 10, lineHeight: 1.6 }}
            >
              {label.model} · prompt {label.prompt_version} · condenser {label.condenser_version}
              <br />
              input sha {label.input_sha256.slice(0, 4)}…{label.input_sha256.slice(-2)} ·{" "}
              {(label.input_chars / 1000).toFixed(1)}k chars · {usd(label.cost_usd, 3)} (est.)
            </div>
          </>
        )}
      </div>

      <div className="panel pad stack" style={{ gap: 8 }}>
        <h2>Pass 1 signals</h2>
        {episode.signals.length === 0 ? (
          <p className="small muted">No rule signals fired for this episode.</p>
        ) : (
          <div className="kv">
            {episode.signals.map((s) => (
              <span key={s.name} style={{ display: "contents" }}>
                <span>
                  {s.name}
                  {s.count > 1 ? ` × ${String(s.count)}` : ""}
                </span>
                <span style={{ textAlign: "right" }}>{s.points.toFixed(1)}</span>
              </span>
            ))}
            <span style={{ borderTop: "1px solid var(--line)", paddingTop: 6, fontWeight: 600 }}>
              score
            </span>
            <span
              style={{
                borderTop: "1px solid var(--line)",
                paddingTop: 6,
                textAlign: "right",
                fontWeight: 600,
                color: "var(--hot-score)",
              }}
            >
              {episode.score.toFixed(1)}
            </span>
          </div>
        )}
        <p className="small muted">
          Weights from spec 4.2. Expected test failures are not yet excluded.
        </p>
      </div>
    </aside>
  );
}
