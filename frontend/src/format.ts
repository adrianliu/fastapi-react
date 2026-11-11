export function fmtCost(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return "$" + (v < 1 ? v.toFixed(3) : v.toFixed(2)) + " est.";
}

export function fmtNum(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return v.toLocaleString();
}

export function fmtDate(v: string | null | undefined): string {
  if (!v) return "—";
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? v : d.toLocaleString();
}

export function fmtDay(v: string | null | undefined): string {
  if (!v) return "—";
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? v : d.toLocaleDateString();
}

export function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return (v * 100).toFixed(0) + "%";
}

export function shortPath(p: string): string {
  const parts = p.split("/").filter(Boolean);
  return parts.slice(-2).join("/") || p;
}

export function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}
