import { useSyncExternalStore } from "react";

function subscribe(onChange: () => void) {
  window.addEventListener("hashchange", onChange);
  return () => {
    window.removeEventListener("hashchange", onChange);
  };
}

function snapshot() {
  return window.location.hash;
}

/** Hash route split into path segments: "#/sessions/abc" -> ["sessions", "abc"]. */
export function useRoute(): { path: string[]; query: URLSearchParams } {
  const hash = useSyncExternalStore(subscribe, snapshot);
  const [path = "", query = ""] = hash.replace(/^#\/?/, "").split("?");
  return {
    path: path.split("/").filter(Boolean).map(decodeURIComponent),
    query: new URLSearchParams(query),
  };
}

export function href(...parts: string[]): string {
  return "#/" + parts.map(encodeURIComponent).join("/");
}
