import "./styles.css";
import ComparisonPage from "./pages/Comparison.tsx";
import { FixesPage, FixPage } from "./pages/Fix.tsx";
import { GroupPage, GroupsPage } from "./pages/Groups.tsx";
import HomePage from "./pages/Home.tsx";
import JobsPage from "./pages/Jobs.tsx";
import RunPage from "./pages/Run.tsx";
import SessionPage from "./pages/Session.tsx";
import SessionsPage from "./pages/Sessions.tsx";
import TasksPage from "./pages/Tasks.tsx";
import { useRoute } from "./router.ts";

const NAV: [string, string][] = [
  ["", "Home"],
  ["sessions", "Sessions"],
  ["groups", "Friction groups"],
  ["fixes", "Fixes"],
  ["tasks", "Tasks"],
  ["run", "Run"],
  ["comparison", "Comparison"],
  ["jobs", "Jobs"],
];

function Page({ route }: { route: string[] }) {
  const [section = "", a, b] = route;
  switch (section) {
    case "":
      return <HomePage />;
    case "sessions":
      return a ? <SessionPage key={a} id={a} focusStep={b} /> : <SessionsPage />;
    case "groups":
      return a ? <GroupPage key={a} id={Number(a)} /> : <GroupsPage />;
    case "fixes":
      return a ? <FixPage key={a} id={Number(a)} /> : <FixesPage />;
    case "tasks":
      return <TasksPage />;
    case "run":
      return <RunPage />;
    case "comparison":
      return <ComparisonPage key={a ?? ""} run={a} />;
    case "jobs":
      return <JobsPage />;
    default:
      return <div className="empty">Page not found.</div>;
  }
}

export default function App() {
  const route = useRoute();
  const section = route[0] ?? "";
  return (
    <div className="shell">
      <nav className="nav">
        <a className="brand" href="#/">
          Hindcast
        </a>
        {NAV.map(([path, label]) => (
          <a key={path} href={"#/" + path} className={section === path ? "active" : ""}>
            {label}
          </a>
        ))}
        <div className="nav-foot muted small">Costs are API-price est.</div>
      </nav>
      <main className="main">
        <Page route={route} />
      </main>
    </div>
  );
}
