import type {
  BenchRun,
  Comparison,
  Estimate,
  EstimateRequest,
  Fix,
  Group,
  Home,
  InstallPreview,
  InstallResult,
  Job,
  JobRef,
  RunRequest,
  SessionDetail,
  SessionList,
  Task,
  Trial,
  EvalStarted,
} from "./types.ts";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch("/api" + path, {
    ...init,
    headers: init?.body ? { "Content-Type": "application/json" } : undefined,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
      else if (body.detail !== undefined) detail = JSON.stringify(body.detail);
    } catch {
      // body was not JSON; keep statusText
    }
    throw new ApiError(res.status, String(res.status) + " " + detail);
  }
  return (await res.json()) as T;
}

const post = <T>(path: string, body: unknown): Promise<T> =>
  request<T>(path, { method: "POST", body: JSON.stringify(body) });

export interface SessionQuery {
  q?: string;
  harness?: string;
  project?: string;
  sort?: string;
  limit?: number;
  offset?: number;
}

export const api = {
  home: () => request<Home>("/home"),
  importSessions: (sinceHours = 2) => post<JobRef>("/import", { since_hours: sinceHours }),
  sessions: (query: SessionQuery) => {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(query)) {
      if (v !== undefined && v !== "") p.set(k, String(v));
    }
    return request<SessionList>("/sessions?" + p.toString());
  },
  session: (id: string) => request<SessionDetail>("/sessions/" + encodeURIComponent(id)),
  job: (id: number) => request<Job>("/jobs/" + String(id)),
  jobs: () => request<Job[]>("/jobs"),
  buildGroups: () => post<JobRef>("/groups/build", {}),
  groups: () => request<Group[]>("/groups"),
  group: (id: number) => request<Group>("/groups/" + String(id)),
  draftFix: (groupId: number, fixType: "rule" | "skill" = "rule") =>
    post<JobRef>("/fixes/draft", { group_id: groupId, fix_type: fixType }),
  evalFix: (fixId: number, repeats: number) =>
    post<EvalStarted>("/bench/eval", { fix_id: fixId, repeats }),
  fixes: () => request<Fix[]>("/fixes"),
  fix: (id: number) => request<Fix>("/fixes/" + String(id)),
  saveFix: (id: number, content: string) =>
    request<Fix>("/fixes/" + String(id), {
      method: "PUT",
      body: JSON.stringify({ content }),
    }),
  installPreview: (id: number, target: string) =>
    request<InstallPreview>(
      "/fixes/" + String(id) + "/install-preview?target=" + encodeURIComponent(target),
    ),
  install: (id: number, target: string) =>
    post<InstallResult>("/fixes/" + String(id) + "/install", {
      target,
      confirm: true,
    }),
  tasks: () => request<Task[]>("/bench/tasks"),
  estimate: (body: EstimateRequest) => post<Estimate>("/bench/estimate", body),
  run: (body: RunRequest) => post<JobRef>("/bench/run", body),
  runs: () => request<BenchRun[]>("/bench/runs"),
  comparison: (run: string) =>
    request<Comparison>("/bench/comparison?run=" + encodeURIComponent(run)),
  trial: (id: string) => request<Trial>("/bench/trials/" + encodeURIComponent(id)),
};

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/** Poll GET /api/jobs/{id} every second until done or failed. */
export async function pollJob(
  jobId: number,
  onUpdate: (job: Job) => void,
  signal?: { cancelled: boolean },
): Promise<Job> {
  for (;;) {
    const job = await api.job(jobId);
    onUpdate(job);
    if (job.status === "done" || job.status === "failed") return job;
    if (signal?.cancelled) return job;
    await sleep(1000);
  }
}

export function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}
