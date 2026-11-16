import Link from "next/link";

export default function AppFrame({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <div className="ehr-app">
      <header className="ehr-topbar">
        <div className="ehr-brand" aria-label="Folium Agents">
          <span className="brand-mark">F</span>
          <span className="brand-copy">
            <strong>Folium Agents</strong>
            <small>Talk to your EHR</small>
          </span>
        </div>
        <div className="topbar-context">
          <span className="environment-tag">Training environment</span>
          <span>Talk to your EHR</span>
        </div>
        <div className="topbar-user">
          <span className="user-avatar" aria-hidden="true">
            S
          </span>
          <span>Demo workspace</span>
        </div>
      </header>
      <nav className="ehr-nav" aria-label="Workspace">
        <Link className="nav-item" href="/patients">
          Patient Search
        </Link>
        <Link className="nav-item" href="/chat">
          Chat
        </Link>
      </nav>
      <main className="page-content">{children}</main>
      <footer className="ehr-footer">
        Folium Agents demo · Synthetic data only · Not for clinical use
      </footer>
    </div>
  );
}
