import type { ReactNode } from "react";
import type { Loadable, JobState } from "./hooks.ts";

export function Status<T>({
  state,
  empty,
  isEmpty,
  children,
}: {
  state: Loadable<T>;
  empty?: string;
  isEmpty?: (d: T) => boolean;
  children: (data: T) => ReactNode;
}) {
  if (state.error !== null && state.data === null) {
    return (
      <div className="error-box">
        Could not load: {state.error}{" "}
        <button className="link" onClick={state.reload}>
          Retry
        </button>
      </div>
    );
  }
  if (state.data === null) return <div className="muted pad">Loading…</div>;
  if (isEmpty?.(state.data)) {
    return <div className="empty">{empty ?? "Nothing here yet."}</div>;
  }
  return <>{children(state.data)}</>;
}

export function JobProgress({ state, label }: { state: JobState; label: string }) {
  if (!state.running && !state.job && !state.error) return null;
  const status = state.job?.status ?? (state.running ? "queued" : "");
  return (
    <div className={"job-progress " + status}>
      {state.running && <span className="spinner" />}
      <strong>{label}</strong>
      <span className="badge">{status}</span>
      {state.running && <span className="muted">{state.elapsed}s</span>}
      {state.job?.progress && <span>{state.job.progress}</span>}
      {state.error && <span className="err">{state.error}</span>}
    </div>
  );
}

export function Bar({ value, tone }: { value: number; tone?: string }) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  return (
    <span className="bar">
      <span className={"bar-fill " + (tone ?? "")} style={{ width: String(pct) + "%" }} />
    </span>
  );
}

export function DiffView({ diff }: { diff: string }) {
  if (!diff.trim()) return <div className="empty">No diff.</div>;
  return (
    <pre className="diff">
      {diff.split("\n").map((line, i) => {
        let cls = "";
        if (line.startsWith("+++") || line.startsWith("---")) cls = "d-file";
        else if (line.startsWith("+")) cls = "d-add";
        else if (line.startsWith("-")) cls = "d-del";
        else if (line.startsWith("@@")) cls = "d-hunk";
        return (
          <div key={i} className={cls}>
            {line || " "}
          </div>
        );
      })}
    </pre>
  );
}
