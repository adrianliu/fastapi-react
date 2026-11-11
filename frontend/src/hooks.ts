import { useCallback, useEffect, useRef, useState } from "react";
import { errorText, pollJob } from "./api/client.ts";
import type { Job, JobRef } from "./api/types.ts";

export interface Loadable<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

export function useApi<T>(fn: () => Promise<T>, deps: unknown[]): Loadable<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const fnRef = useRef(fn);
  useEffect(() => {
    fnRef.current = fn;
  });
  const key = JSON.stringify(deps);

  useEffect(() => {
    let live = true;
    fnRef
      .current()
      .then((d) => {
        if (!live) return;
        setData(d);
        setError(null);
      })
      .catch((e: unknown) => {
        if (live) setError(errorText(e));
      });
    return () => {
      live = false;
    };
  }, [key, tick]);

  const reload = useCallback(() => {
    setTick((t) => t + 1);
  }, []);
  return { data, error, loading: data === null && error === null, reload };
}

export interface JobState {
  job: Job | null;
  error: string | null;
  running: boolean;
  elapsed: number;
  start: (fn: () => Promise<JobRef>) => Promise<Job | null>;
}

export function useJob(): JobState {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const signal = useRef({ cancelled: false });

  useEffect(() => {
    // Fresh flag per mount: StrictMode unmounts and remounts once in dev, and a flag
    // left cancelled by the first unmount would stop every later poll after one check.
    const s = { cancelled: false };
    signal.current = s;
    return () => {
      s.cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => {
      setNow(Date.now());
    }, 250);
    return () => {
      clearInterval(t);
    };
  }, [running]);

  const start = useCallback(async (fn: () => Promise<JobRef>) => {
    setError(null);
    setJob(null);
    setRunning(true);
    const t0 = Date.now();
    setStartedAt(t0);
    setNow(t0);
    try {
      const ref = await fn();
      const final = await pollJob(ref.job_id, setJob, signal.current);
      if (final.status === "failed") setError(final.error ?? "job failed");
      return final;
    } catch (e) {
      setError(errorText(e));
      return null;
    } finally {
      setRunning(false);
      setNow(Date.now());
    }
  }, []);

  const elapsed = startedAt === null ? 0 : Math.floor((now - startedAt) / 1000);
  return { job, error, running, elapsed, start };
}
