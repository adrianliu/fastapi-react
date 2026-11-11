export function usd(v: number, digits = 2): string {
  return "$" + v.toFixed(digits);
}

export function tokens(v: number): string {
  if (v >= 1_000_000) return (v / 1_000_000).toFixed(2) + "M";
  if (v >= 1_000) return (v / 1_000).toFixed(1) + "k";
  return String(v);
}

export function ms(v: number): string {
  if (v < 1000) return String(Math.round(v)) + " ms";
  if (v < 60_000) return (v / 1000).toFixed(1) + " s";
  const m = Math.floor(v / 60_000);
  const s = Math.round((v % 60_000) / 1000);
  if (m < 60) return `${String(m)}m ${String(s).padStart(2, "0")}s`;
  return `${String(Math.floor(m / 60))} h ${String(m % 60)} m`;
}

export function span(from: string, to: string): string {
  return ms(Date.parse(to) - Date.parse(from));
}

export function clock(iso: string): string {
  return new Date(iso).toISOString().slice(11, 19);
}

export function dateTime(iso: string): string {
  const d = new Date(iso);
  const month = d.toLocaleString("en-US", { month: "short", timeZone: "UTC" });
  return `${month} ${String(d.getUTCDate())} ${d.toISOString().slice(11, 16)}`;
}

export function stepRange(from: number, to: number): string {
  return from === to ? `s${String(from)}` : `s${String(from)}–${String(to)}`;
}

export function pct(v: number, digits = 1): string {
  return v.toFixed(digits) + "%";
}

export function signed(v: number, digits = 2): string {
  return (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(digits);
}

export function plural(n: number, word: string): string {
  return `${String(n)} ${word}${n === 1 ? "" : "s"}`;
}
