import { useState } from "react";
import { api, errorText } from "../api/client.ts";
import type { Fix, InstallPreview } from "../api/types.ts";
import { fmtDate } from "../format.ts";
import { useApi } from "../hooks.ts";
import { DiffView, Status } from "../ui.tsx";

const DEFAULT_TARGET = "~/.claude/CLAUDE.md";

function FixEditor({ initial }: { initial: Fix }) {
  const [fix, setFix] = useState(initial);
  const latest = fix.versions[fix.versions.length - 1];
  const [content, setContent] = useState(latest?.content ?? "");
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [target, setTarget] = useState(DEFAULT_TARGET);
  const [preview, setPreview] = useState<InstallPreview | null>(null);

  const lines = content.split("\n").length;

  const save = async () => {
    setBusy(true);
    setErr(null);
    setMsg(null);
    try {
      const f = await api.saveFix(fix.id, content);
      setFix(f);
      const v = f.versions[f.versions.length - 1];
      setMsg("Saved version " + String(v?.version ?? "?"));
    } catch (e) {
      setErr(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  const loadPreview = async () => {
    setBusy(true);
    setErr(null);
    setMsg(null);
    try {
      setPreview(await api.installPreview(fix.id, target));
    } catch (e) {
      setErr(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  const confirm = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await api.install(fix.id, target);
      setMsg(
        r.applied ? "Installed into " + r.target : "Not applied (already present?) " + r.target,
      );
      setPreview(null);
    } catch (e) {
      setErr(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <header className="page-head">
        <div>
          <h1>{fix.name}</h1>
          <p className="lead">{fix.summary}</p>
          <span className="chip">{fix.fix_type}</span>{" "}
          <a href={"#/groups/" + String(fix.group_id)} className="small">
            group #{fix.group_id}
          </a>
        </div>
      </header>
      {err && <div className="error-box">{err}</div>}
      {msg && <div className="ok-box">{msg}</div>}
      <div className="split">
        <div className="card">
          <div className="row">
            <h3>Rule</h3>
            <span className="spacer" />
            <span className={"small " + (lines > 15 ? "err" : "muted")}>{lines} / 15 lines</span>
          </div>
          <textarea
            className="editor"
            value={content}
            rows={14}
            onChange={(e) => {
              setContent(e.target.value);
            }}
          />
          <div className="row">
            <button
              className="primary"
              disabled={busy || content === latest?.content}
              onClick={() => void save()}
            >
              Save
            </button>
            <input
              className="target"
              value={target}
              onChange={(e) => {
                setTarget(e.target.value);
              }}
            />
            <button disabled={busy} onClick={() => void loadPreview()}>
              Install…
            </button>
          </div>
        </div>
        <div className="card">
          <h3>Rationale</h3>
          {fix.rationale.length === 0 && <div className="muted">None.</div>}
          <ol className="rationale">
            {fix.rationale.map((r, i) => (
              <li key={i}>
                {r.instruction}
                {r.correction_ids.length > 0 && (
                  <div className="muted small">
                    corrections {r.correction_ids.map(String).join(", ")}
                  </div>
                )}
              </li>
            ))}
          </ol>
          <h3>Versions</h3>
          <ul className="plain versions">
            {[...fix.versions].reverse().map((v) => (
              <li key={v.version}>
                <button
                  className="link"
                  onClick={() => {
                    setContent(v.content);
                  }}
                >
                  v{v.version}
                </button>{" "}
                <span className="muted small">
                  {v.author}
                  {v.model ? " · " + v.model : ""} · {fmtDate(v.created_at)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </div>
      {preview && (
        <div className="card">
          <div className="row">
            <h3>Install preview: {preview.target}</h3>
            <span className="spacer" />
            <button
              onClick={() => {
                setPreview(null);
              }}
            >
              Cancel
            </button>
            <button className="primary" disabled={busy} onClick={() => void confirm()}>
              Confirm install
            </button>
          </div>
          <DiffView diff={preview.diff} />
        </div>
      )}
    </>
  );
}

export function FixPage({ id }: { id: number }) {
  const state = useApi(() => api.fix(id), [id]);
  return (
    <div>
      <a href="#/fixes" className="back">
        ← Fixes
      </a>
      <Status state={state}>{(f) => <FixEditor key={f.id} initial={f} />}</Status>
    </div>
  );
}

export function FixesPage() {
  const state = useApi(() => api.fixes(), []);
  return (
    <div>
      <header className="page-head">
        <h1>Fixes</h1>
      </header>
      <Status
        state={state}
        isEmpty={(f) => f.length === 0}
        empty="No fixes yet. Open a friction group and click “Draft fix”."
      >
        {(fs) => (
          <div className="cards">
            {fs.map((f) => (
              <a key={f.id} className="card" href={"#/fixes/" + String(f.id)}>
                <h3>{f.name}</h3>
                <p>{f.summary}</p>
                <div className="muted small">
                  {f.fix_type} · {f.versions.length} versions
                </div>
              </a>
            ))}
          </div>
        )}
      </Status>
    </div>
  );
}
