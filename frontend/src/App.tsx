import { endpoints, useFetch } from "./api";
import CandidatesPage from "./pages/Candidates";
import EvalPage, { EvalsList } from "./pages/Evals";
import LeaderboardPage from "./pages/Leaderboard";
import NotesPage from "./pages/Notes";
import SessionPage from "./pages/Session";
import SessionsPage from "./pages/Sessions";
import { href, useRoute } from "./router";

const NAV = [
  ["sessions", "Sessions"],
  ["evals", "Evals"],
  ["leaderboard", "Leaderboard"],
  ["notes", "Notes"],
] as const;

function Page({ path }: { path: string[] }) {
  const [section = "sessions", id, sub] = path;
  if (section === "sessions" && id && sub === "candidates") return <CandidatesPage id={id} />;
  if (section === "sessions" && id) return <SessionPage id={id} />;
  if (section === "sessions") return <SessionsPage />;
  if (section === "evals" && id) return <EvalPage id={id} />;
  if (section === "evals") return <EvalsList />;
  if (section === "leaderboard") return <LeaderboardPage />;
  if (section === "notes") return <NotesPage />;
  return (
    <div className="page">
      <p className="empty">
        Page not found. <a href={href("sessions")}>Go to sessions</a>
      </p>
    </div>
  );
}

export default function App() {
  const { path } = useRoute();
  const section = path[0] ?? "sessions";
  const meta = useFetch(endpoints.meta);

  return (
    <>
      <header className="topbar">
        <a className="brand" href={href("sessions")}>
          <svg
            width="22"
            height="22"
            viewBox="0 0 24 24"
            fill="none"
            stroke="#8FB0FF"
            strokeWidth="2"
            strokeLinecap="round"
            aria-hidden="true"
          >
            <path d="M3 12a9 9 0 1 0 3-6.7" />
            <path d="M3 4v5h5" />
            <path d="M12 7v5l3 2" />
          </svg>
          Hindcast
        </a>
        <nav className="nav" aria-label="Main">
          {NAV.map(([key, text]) => (
            <a key={key} href={href(key)} aria-current={section === key ? "page" : undefined}>
              {text}
            </a>
          ))}
        </nav>
        {meta.data?.data_source === "demo" && (
          <span
            className="demo-badge"
            title="Importers are not built yet; sessions and runs are a fixed demo dataset."
          >
            Demo data
          </span>
        )}
      </header>
      <Page key={path.join("/")} path={path} />
    </>
  );
}
